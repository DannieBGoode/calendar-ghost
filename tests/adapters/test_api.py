import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from calendar_sync.application.errors import ProviderFailure, ProviderFailureKind
from calendar_sync.application.ports import AuditEntry, CalendarProvider
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Container, build_container
from calendar_sync.domain.model import (
    CalendarEvent,
    ConnectedAccountId,
    EventId,
    EventRef,
    Recurrence,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.infrastructure.google.oauth import (
    ConnectedGoogleAccountNotFound,
    CredentialCipher,
    GoogleAccountAccess,
    GoogleAccountAccessCheckFailed,
    GoogleCalendarPermissionRequired,
    GoogleOAuthCompletionFailed,
)
from calendar_sync.interfaces.api.app import create_app
from tests.helpers import endpoint, event, rule


def test_first_run_admin_and_protected_dashboard(tmp_path: Path) -> None:
    app = create_app(build_container(Settings(tmp_path / "test.db")))

    with TestClient(app) as client:
        assert client.get("/api/v1/setup").json() == {"administrator_configured": False}
        assert client.get("/api/v1/dashboard").status_code == 401

        response = client.post(
            "/api/v1/setup/admin", json={"password": "correct horse battery staple"}
        )

        assert response.status_code == 200
        assert response.json() == {"authenticated": True}
        dashboard = client.get("/api/v1/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json() == {
            "health": "healthy",
            "connected_accounts": 0,
            "sync_rules": 0,
            "open_incidents": 0,
        }


def test_create_cross_account_rule_through_api(tmp_path: Path) -> None:
    app = create_app(build_container(Settings(tmp_path / "test.db")))

    with TestClient(app) as client:
        client.post("/api/v1/setup/admin", json={"password": "correct horse battery staple"})
        payload = {
            "source": {
                "connected_account_id": "personal",
                "calendar_id": "personal-calendar",
            },
            "destination": {
                "connected_account_id": "work",
                "calendar_id": "work-calendar",
            },
            "privacy_policy": "busy_only",
            "sync_all_day_events": False,
        }

        response = client.post("/api/v1/rules", json=payload)

        assert response.status_code == 201
        assert response.json()["source"]["connected_account_id"] == "personal"
        assert response.json()["destination"]["connected_account_id"] == "work"
        assert response.json()["sync_all_day_events"] is False


def test_activity_and_incidents_require_admin_and_return_operational_data(
    tmp_path: Path,
) -> None:
    database = tmp_path / "test.db"
    container = build_container(Settings(database))
    with container.unit_of_work() as uow:
        uow.audit.append(
            AuditEntry(
                occurred_at=datetime(2026, 8, 30, tzinfo=UTC),
                rule_id=SyncRuleId("rule-1"),
                action="create",
                outcome="completed",
                detail="source has no managed projection",
            )
        )
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO incidents (
                id, deduplication_key, rule_id, category, state,
                summary, opened_at, updated_at
            ) VALUES (?, ?, ?, ?, 'open', ?, ?, ?)
            """,
            (
                "incident-1",
                "provider:rule-1",
                "rule-1",
                "authentication",
                "Google authorization expired",
                "2026-08-30T10:00:00+00:00",
                "2026-08-30T10:00:00+00:00",
            ),
        )

    app = create_app(container)
    with TestClient(app) as client:
        assert client.get("/api/v1/audit-entries").status_code == 401
        client.post("/api/v1/setup/admin", json={"password": "correct horse battery staple"})

        activity = client.get("/api/v1/audit-entries").json()
        incidents = client.get("/api/v1/incidents").json()

        assert activity[0]["action"] == "create"
        assert "event" not in activity[0]
        assert incidents[0]["summary"] == "Google authorization expired"


def test_logout_revokes_session_and_wrong_password_cannot_restore_it(tmp_path: Path) -> None:
    app = create_app(build_container(Settings(tmp_path / "test.db")))

    with TestClient(app) as client:
        client.post("/api/v1/setup/admin", json={"password": "correct horse battery staple"})
        assert client.get("/api/v1/dashboard").status_code == 200

        assert client.delete("/api/v1/session").status_code == 204
        assert client.get("/api/v1/dashboard").status_code == 401
        assert (
            client.post("/api/v1/session", json={"password": "this password is wrong"}).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/session", json={"password": "correct horse battery staple"}
            ).status_code
            == 200
        )
        assert client.get("/api/v1/dashboard").status_code == 200


def test_admin_setup_is_single_use_and_secure_cookie_setting_is_honored(tmp_path: Path) -> None:
    app = create_app(build_container(Settings(tmp_path / "test.db", secure_cookies=True)))

    with TestClient(app) as client:
        first = client.post(
            "/api/v1/setup/admin", json={"password": "correct horse battery staple"}
        )
        second = client.post(
            "/api/v1/setup/admin", json={"password": "another correct battery staple"}
        )

        assert "Secure" in first.headers["set-cookie"]
        assert "HttpOnly" in first.headers["set-cookie"]
        assert "SameSite=lax" in first.headers["set-cookie"]
        assert second.status_code == 409


def test_rule_validation_rejects_unknown_policy_same_endpoint_and_duplicate(
    tmp_path: Path,
) -> None:
    app = create_app(build_container(Settings(tmp_path / "test.db")))
    base_payload = {
        "source": {"connected_account_id": "personal", "calendar_id": "calendar"},
        "destination": {"connected_account_id": "work", "calendar_id": "calendar"},
        "privacy_policy": "busy_only",
        "sync_all_day_events": True,
    }

    with TestClient(app) as client:
        client.post("/api/v1/setup/admin", json={"password": "correct horse battery staple"})
        unknown = client.post("/api/v1/rules", json={**base_payload, "privacy_policy": "unknown"})
        same_endpoint = client.post(
            "/api/v1/rules",
            json={
                **base_payload,
                "destination": {
                    "connected_account_id": "personal",
                    "calendar_id": "calendar",
                },
            },
        )
        first = client.post("/api/v1/rules", json=base_payload)
        duplicate = client.post("/api/v1/rules", json=base_payload)

        assert unknown.status_code == 422
        assert same_endpoint.status_code == 422
        assert first.status_code == 201
        assert duplicate.status_code == 409


def test_google_routes_report_unconfigured_installation(tmp_path: Path) -> None:
    app = create_app(build_container(Settings(tmp_path / "test.db")))

    with TestClient(app) as client:
        client.post("/api/v1/setup/admin", json={"password": "correct horse battery staple"})

        assert client.get("/api/v1/google/configuration").json() == {
            "configured": False,
            "redirect_uri": None,
        }
        assert client.get("/api/v1/oauth/google/start").status_code == 503
        assert client.get("/api/v1/accounts").json() == []
        assert client.post("/api/v1/rules/missing/preview").status_code == 503


def test_google_configuration_reports_redirect_uri_to_administrators(tmp_path: Path) -> None:
    settings = Settings(
        tmp_path / "test.db",
        master_key=CredentialCipher.generate_key(),
        google_client_id="synthetic-client",
        google_client_secret="synthetic-secret",
        google_redirect_uri="http://localhost:18000/api/v1/oauth/google/callback",
    )
    app = create_app(build_container(settings))

    with TestClient(app) as client:
        anonymous = client.get("/api/v1/google/configuration")
        client.post("/api/v1/setup/admin", json={"password": "correct horse battery staple"})
        configuration = client.get("/api/v1/google/configuration")

    assert anonymous.status_code == 401
    assert configuration.json() == {
        "configured": True,
        "redirect_uri": "http://localhost:18000/api/v1/oauth/google/callback",
    }


def test_connected_accounts_can_be_listed_and_disconnected(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    container = replace(
        build_container(Settings(database, master_key=CredentialCipher.generate_key())),
        scheduler=None,
    )
    assert container.connected_accounts is not None
    account = container.connected_accounts.save(
        "Personal",
        "person@example.test",
        '{"refresh_token":"synthetic-secret"}',
        avatar_url="https://lh3.googleusercontent.com/a/synthetic=s96-c",
    )
    with container.unit_of_work() as uow:
        uow.rules.add(rule())
        uow.rules.add(
            SyncRule(
                id=SyncRuleId("paused-rule"),
                source=endpoint(account.id.value, "paused-calendar"),
                destination=endpoint("work-account", "paused-destination"),
                state=SyncRuleState.PAUSED,
            )
        )
        uow.rules.add(
            SyncRule(
                id=SyncRuleId("validated-rule"),
                source=endpoint(account.id.value, "validated-calendar"),
                destination=endpoint("work-account", "validated-destination"),
                state=SyncRuleState.DRY_RUN_VALIDATED,
            )
        )
        uow.rules.add(
            SyncRule(
                id=SyncRuleId("unrelated-rule"),
                source=endpoint("other-account", "other-calendar"),
                destination=endpoint("work-account", "other-destination"),
                state=SyncRuleState.ENABLED,
            )
        )
        uow.rules.add(
            SyncRule(
                id=SyncRuleId("destination-rule"),
                source=endpoint("other-account", "destination-source"),
                destination=endpoint(account.id.value, "destination-calendar"),
                state=SyncRuleState.ENABLED,
            )
        )
        uow.cursors.save(SyncRuleId("rule-1"), "preserved-cursor")
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE sync_rules SET source_account_id = ? WHERE id = 'rule-1'",
            (account.id.value,),
        )
    app = create_app(container)

    with TestClient(app) as client:
        assert client.post(f"/api/v1/accounts/{account.id.value}/disconnect").status_code == 401
        assert client.delete(f"/api/v1/accounts/{account.id.value}").status_code == 401
        client.post("/api/v1/setup/admin", json={"password": "correct horse battery staple"})

        listed = client.get("/api/v1/accounts")
        disconnected = client.post(f"/api/v1/accounts/{account.id.value}/disconnect")
        disconnected_calendars = client.get(f"/api/v1/accounts/{account.id.value}/calendars")
        disconnected_verification = client.post(f"/api/v1/accounts/{account.id.value}/verify")
        repeated = client.post(f"/api/v1/accounts/{account.id.value}/disconnect")
        missing = client.post("/api/v1/accounts/missing/disconnect")
        dashboard = client.get("/api/v1/dashboard")

    assert listed.status_code == 200
    assert listed.json() == [
        {
            "id": account.id.value,
            "display_name": "Personal",
            "email": "person@example.test",
            "avatar_url": "https://lh3.googleusercontent.com/a/synthetic=s96-c",
            "state": "connected",
            "rule_count": 4,
        }
    ]
    assert disconnected.status_code == 200
    assert disconnected.json()["state"] == "disconnected"
    assert disconnected.json()["rule_count"] == 4
    assert disconnected_calendars.status_code == 409
    assert "reauthorize" in disconnected_calendars.json()["detail"]
    assert disconnected_verification.status_code == 409
    assert repeated.status_code == 200
    assert missing.status_code == 404
    assert dashboard.json()["connected_accounts"] == 0
    with container.unit_of_work() as uow:
        disconnected_rule = uow.rules.get(SyncRuleId("rule-1"))
    assert disconnected_rule is not None
    assert disconnected_rule.state is SyncRuleState.DEGRADED
    with container.unit_of_work() as uow:
        paused_rule = uow.rules.get(SyncRuleId("paused-rule"))
        validated_rule = uow.rules.get(SyncRuleId("validated-rule"))
        unrelated_rule = uow.rules.get(SyncRuleId("unrelated-rule"))
        destination_rule = uow.rules.get(SyncRuleId("destination-rule"))
        cursor = uow.cursors.get(SyncRuleId("rule-1"))
    assert paused_rule is not None
    assert paused_rule.state is SyncRuleState.PAUSED
    assert validated_rule is not None
    assert validated_rule.state is SyncRuleState.DEGRADED
    assert unrelated_rule is not None
    assert unrelated_rule.state is SyncRuleState.ENABLED
    assert destination_rule is not None
    assert destination_rule.state is SyncRuleState.DEGRADED
    assert cursor == "preserved-cursor"


def test_disconnected_account_can_be_permanently_deleted_with_affected_rules(
    tmp_path: Path,
) -> None:
    database = tmp_path / "test.db"
    container = replace(
        build_container(Settings(database, master_key=CredentialCipher.generate_key())),
        scheduler=None,
    )
    assert container.connected_accounts is not None
    account = container.connected_accounts.save(
        "Personal", "person@example.test", '{"refresh_token":"synthetic-secret"}'
    )
    unrelated_account = container.connected_accounts.save(
        "Work", "work@example.test", '{"refresh_token":"synthetic-secret"}'
    )
    affected_rule = SyncRule(
        id=SyncRuleId("delete-rule"),
        source=endpoint(account.id.value, "personal-calendar"),
        destination=endpoint(unrelated_account.id.value, "work-calendar"),
        state=SyncRuleState.ENABLED,
    )
    destination_affected_rule = SyncRule(
        id=SyncRuleId("delete-destination-rule"),
        source=endpoint("third-account", "third-calendar"),
        destination=endpoint(account.id.value, "personal-destination"),
        state=SyncRuleState.PAUSED,
    )
    unrelated_rule = SyncRule(
        id=SyncRuleId("keep-rule"),
        source=endpoint(unrelated_account.id.value, "work-calendar"),
        destination=endpoint("third-account", "third-calendar"),
        state=SyncRuleState.PAUSED,
    )
    with container.unit_of_work() as uow:
        uow.rules.add(affected_rule)
        uow.rules.add(destination_affected_rule)
        uow.rules.add(unrelated_rule)
        uow.cursors.save(affected_rule.id, "source-cursor")
        uow.destination_cursors.save(affected_rule.id, "destination-cursor")
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO event_mappings (
                id, rule_id, source_account_id, source_calendar_id, source_event_id,
                destination_account_id, destination_calendar_id, destination_event_id,
                source_revision, projection_fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "mapping-1",
                affected_rule.id.value,
                account.id.value,
                "personal-calendar",
                "source-event",
                unrelated_account.id.value,
                "work-calendar",
                "destination-event",
                "revision-1",
                "fingerprint-1",
            ),
        )
        connection.execute(
            """
            INSERT INTO audit_entries (occurred_at, rule_id, action, outcome, detail)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "2026-08-31T12:00:00+00:00",
                affected_rule.id.value,
                "create",
                "completed",
                "synthetic operational detail",
            ),
        )
        connection.execute(
            """
            INSERT INTO incidents (
                id, deduplication_key, rule_id, category, state,
                summary, opened_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "incident-1",
                "authentication:delete-rule",
                affected_rule.id.value,
                "authentication",
                "open",
                "Synthetic authorization incident",
                "2026-08-31T12:00:00+00:00",
                "2026-08-31T12:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO rule_failures (rule_id, consecutive_failures, last_category, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (affected_rule.id.value, 2, "authentication", "2026-08-31T12:00:00+00:00"),
        )
    app = create_app(container)

    with TestClient(app) as client:
        client.post("/api/v1/setup/admin", json={"password": "correct horse battery staple"})
        connected_delete = client.delete(f"/api/v1/accounts/{account.id.value}")
        disconnected = client.post(f"/api/v1/accounts/{account.id.value}/disconnect")
        deleted = client.delete(f"/api/v1/accounts/{account.id.value}")
        repeated = client.delete(f"/api/v1/accounts/{account.id.value}")

    assert connected_delete.status_code == 409
    assert "disconnect" in connected_delete.json()["detail"]
    assert disconnected.status_code == 200
    assert deleted.status_code == 204
    assert repeated.status_code == 404
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM connected_accounts WHERE id = ?", (account.id.value,)
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM connected_accounts WHERE id = ?",
                (unrelated_account.id.value,),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sync_rules WHERE id = ?", (affected_rule.id.value,)
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sync_rules WHERE id = ?",
                (destination_affected_rule.id.value,),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sync_rules WHERE id = ?", (unrelated_rule.id.value,)
            ).fetchone()[0]
            == 1
        )
        for table in (
            "event_mappings",
            "sync_cursors",
            "destination_sync_cursors",
            "audit_entries",
            "incidents",
            "rule_failures",
        ):
            assert (
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE rule_id = ?", (affected_rule.id.value,)
                ).fetchone()[0]
                == 0
            )


def test_disconnected_account_without_rules_can_be_permanently_deleted(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    container = replace(
        build_container(Settings(database, master_key=CredentialCipher.generate_key())),
        scheduler=None,
    )
    assert container.connected_accounts is not None
    account = container.connected_accounts.save(
        "Unused", "unused@example.test", '{"refresh_token":"synthetic-secret"}'
    )
    container.connected_accounts.disconnect(account.id)
    app = create_app(container)

    with TestClient(app) as client:
        client.post("/api/v1/setup/admin", json={"password": "correct horse battery staple"})
        deleted = client.delete(f"/api/v1/accounts/{account.id.value}")

    assert deleted.status_code == 204
    assert container.connected_accounts.list() == ()


def test_connected_account_access_can_be_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = replace(
        build_container(Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())),
        scheduler=None,
    )
    assert container.google_oauth is not None
    verify_access = Mock(return_value=GoogleAccountAccess(3, 2))
    monkeypatch.setattr(container.google_oauth, "verify_access", verify_access)
    app = create_app(container)

    with TestClient(app) as client:
        assert client.post("/api/v1/accounts/account-1/verify").status_code == 401
        client.post("/api/v1/setup/admin", json={"password": "correct horse battery staple"})
        response = client.post("/api/v1/accounts/account-1/verify")

    assert response.status_code == 200
    assert response.json() == {
        "calendar_api": True,
        "calendar_list_access": True,
        "event_access": True,
        "calendars_visible": 3,
        "writable_calendars": 2,
    }
    verify_access.assert_called_once_with(ConnectedAccountId("account-1"))


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [
        (ConnectedGoogleAccountNotFound("missing account"), 404),
        (GoogleAccountAccessCheckFailed("provider unavailable"), 424),
    ],
)
def test_connected_account_access_failures_are_mapped_to_recovery_statuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected_status: int,
) -> None:
    container = replace(
        build_container(Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())),
        scheduler=None,
    )
    assert container.google_oauth is not None
    monkeypatch.setattr(container.google_oauth, "verify_access", Mock(side_effect=failure))
    app = create_app(container)

    with TestClient(app) as client:
        client.post("/api/v1/setup/admin", json={"password": "correct horse battery staple"})
        response = client.post("/api/v1/accounts/account-1/verify")

    assert response.status_code == expected_status
    assert response.json()["detail"] == str(failure)


def test_google_oauth_callback_exchanges_code_without_forwarding_http_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = build_container(
        Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())
    )
    assert container.google_oauth is not None
    complete = Mock()
    monkeypatch.setattr(container.google_oauth, "complete", complete)
    app = create_app(container)

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/oauth/google/callback?state=synthetic-state&code=synthetic-code",
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/settings?google=connected"
    complete.assert_called_once_with("synthetic-state", "synthetic-code")


def test_google_oauth_denial_returns_to_settings_and_consumes_state(tmp_path: Path) -> None:
    container = build_container(
        Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())
    )
    assert container.google_oauth is not None
    container.google_oauth._store_state("synthetic-state")
    app = create_app(container)

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/oauth/google/callback?state=synthetic-state&error=access_denied",
            follow_redirects=False,
        )
        repeated = client.get(
            "/api/v1/oauth/google/callback?state=synthetic-state&error=access_denied",
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/settings?google=calendar_permission_required"
    assert repeated.status_code == 400


def test_google_oauth_non_permission_error_returns_to_settings(tmp_path: Path) -> None:
    container = build_container(
        Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())
    )
    assert container.google_oauth is not None
    container.google_oauth._store_state("synthetic-state")
    app = create_app(container)

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/oauth/google/callback?state=synthetic-state&error=temporarily_unavailable",
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/settings?google=authorization_failed"


def test_google_oauth_callback_requires_an_authorization_result(tmp_path: Path) -> None:
    container = build_container(
        Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())
    )
    app = create_app(container)

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/oauth/google/callback?state=synthetic-state",
            follow_redirects=False,
        )

    assert response.status_code == 400
    assert "authorization result" in response.json()["detail"]


def test_google_oauth_missing_calendar_permission_returns_to_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = build_container(
        Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())
    )
    assert container.google_oauth is not None
    complete = Mock(side_effect=GoogleCalendarPermissionRequired("permission required"))
    monkeypatch.setattr(container.google_oauth, "complete", complete)
    app = create_app(container)

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/oauth/google/callback?state=synthetic-state&code=synthetic-code",
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/settings?google=calendar_permission_required"
    complete.assert_called_once_with("synthetic-state", "synthetic-code")


def test_google_oauth_completion_failure_returns_to_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = build_container(
        Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())
    )
    assert container.google_oauth is not None
    complete = Mock(side_effect=GoogleOAuthCompletionFailed("token exchange failed"))
    monkeypatch.setattr(container.google_oauth, "complete", complete)
    app = create_app(container)

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/oauth/google/callback?state=synthetic-state&code=synthetic-code",
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/settings?google=authorization_failed"
    complete.assert_called_once_with("synthetic-state", "synthetic-code")


def test_frontend_fallback_cannot_serve_files_outside_static_root(tmp_path: Path) -> None:
    app = create_app(build_container(Settings(tmp_path / "test.db")))

    with TestClient(app) as client:
        response = client.get("/%2e%2e/app.py")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Calendar Sync" in response.text
    assert "from __future__ import annotations" not in response.text


@pytest.mark.parametrize("path", ["/overview", "/rules", "/rules/rule-1", "/activity", "/settings"])
def test_frontend_fallback_serves_each_application_section(tmp_path: Path, path: str) -> None:
    app = create_app(build_container(Settings(tmp_path / "test.db")))

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Calendar Sync" in response.text


def test_enabled_rule_can_be_paused_through_api(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    with container.unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()
    app = create_app(container)

    with TestClient(app) as client:
        client.post("/api/v1/setup/admin", json={"password": "correct horse battery staple"})
        paused = client.post("/api/v1/rules/rule-1/pause")
        repeated = client.post("/api/v1/rules/rule-1/pause")

    assert paused.status_code == 200
    assert paused.json()["state"] == "paused"
    assert repeated.status_code == 409


PASSWORD = {"password": "correct horse battery staple"}


def _client_with_rule(tmp_path: Path, state: SyncRuleState = SyncRuleState.ENABLED) -> TestClient:
    container = build_container(Settings(tmp_path / "test.db"))
    with container.unit_of_work() as uow:
        uow.rules.add(rule(state=state))
        uow.commit()
    return TestClient(create_app(container))


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/rules/rule-1"),
        ("PATCH", "/api/v1/rules/rule-1"),
        ("DELETE", "/api/v1/rules/rule-1?projections=detach"),
        ("POST", "/api/v1/rules/rule-1/replace"),
    ],
)
def test_rule_management_routes_require_an_administrator(
    tmp_path: Path, method: str, path: str
) -> None:
    with _client_with_rule(tmp_path) as client:
        assert client.request(method, path, json={}).status_code == 401
        assert client.get("/api/v1/rules").status_code == 401


def test_rule_details_include_policy_state_mapping_count_and_outcomes(tmp_path: Path) -> None:
    with _client_with_rule(tmp_path) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        details = client.get("/api/v1/rules/rule-1")
        missing = client.get("/api/v1/rules/missing")

    assert details.status_code == 200
    assert details.json()["initial_lookback_days"] == 30
    assert details.json()["mapping_count"] == 0
    assert details.json()["reprojection_required"] is False
    assert details.json()["last_sync"] is None
    assert details.json()["last_reconciliation"] is None
    assert missing.status_code == 404


def test_policy_edit_pauses_rule_and_blocks_enable_until_previewed(tmp_path: Path) -> None:
    with _client_with_rule(tmp_path) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        edited = client.patch(
            "/api/v1/rules/rule-1",
            json={"privacy_policy": "copy_details", "sync_all_day_events": True},
        )
        enable = client.post("/api/v1/rules/rule-1/enable")
        unknown = client.patch(
            "/api/v1/rules/rule-1",
            json={"privacy_policy": "everything", "sync_all_day_events": True},
        )
        missing = client.patch(
            "/api/v1/rules/missing",
            json={"privacy_policy": "busy_only", "sync_all_day_events": True},
        )

    assert edited.status_code == 200
    assert edited.json()["state"] == "paused"
    assert edited.json()["privacy_policy"] == "copy_details"
    assert edited.json()["reprojection_required"] is True
    assert enable.status_code == 409
    assert unknown.status_code == 422
    assert missing.status_code == 404


def test_policy_edit_is_rejected_while_removal_is_incomplete(tmp_path: Path) -> None:
    with _client_with_rule(tmp_path, SyncRuleState.DISABLED) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        response = client.patch(
            "/api/v1/rules/rule-1",
            json={"privacy_policy": "copy_details", "sync_all_day_events": True},
        )

    assert response.status_code == 409


def test_rule_removal_requires_an_explicit_choice_and_detach_removes_the_rule(
    tmp_path: Path,
) -> None:
    with _client_with_rule(tmp_path) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        unspecified = client.delete("/api/v1/rules/rule-1")
        invalid = client.delete("/api/v1/rules/rule-1?projections=everything")
        delete_without_google = client.delete("/api/v1/rules/rule-1?projections=delete")
        detached = client.delete("/api/v1/rules/rule-1?projections=detach")
        after = client.get("/api/v1/rules/rule-1")
        missing = client.delete("/api/v1/rules/rule-1?projections=detach")

    assert unspecified.status_code == 422
    assert invalid.status_code == 422
    assert delete_without_google.status_code == 503
    assert detached.status_code == 200
    assert detached.json() == {"deleted": 0, "detached": 0}
    assert after.status_code == 404
    assert missing.status_code == 404


def test_delete_removal_is_blocked_for_a_disconnected_destination(tmp_path: Path) -> None:
    container = replace(
        build_container(Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())),
        scheduler=None,
    )
    assert container.connected_accounts is not None
    account = container.connected_accounts.save(
        "Work", "work@example.test", '{"refresh_token":"synthetic-secret"}'
    )
    container.connected_accounts.disconnect(account.id)
    with container.unit_of_work() as uow:
        uow.rules.add(
            SyncRule(
                SyncRuleId("rule-1"),
                endpoint("personal", "personal-calendar"),
                endpoint(account.id.value, "work-calendar"),
                state=SyncRuleState.PAUSED,
            )
        )
        uow.commit()

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        blocked = client.delete("/api/v1/rules/rule-1?projections=delete")
        state = client.get("/api/v1/rules/rule-1").json()["state"]

    assert blocked.status_code == 409
    assert state == "paused"


def test_replacement_creates_a_new_draft_and_rejects_invalid_calendars(tmp_path: Path) -> None:
    unchanged = {
        "source": {"connected_account_id": "personal-account", "calendar_id": "personal-calendar"},
        "destination": {"connected_account_id": "work-account", "calendar_id": "work-calendar"},
        "projections": "detach",
    }
    same_endpoint = {**unchanged, "destination": unchanged["source"]}
    changed = {
        **unchanged,
        "destination": {"connected_account_id": "work-account", "calendar_id": "team-calendar"},
    }
    with _client_with_rule(tmp_path) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        rejected = client.post("/api/v1/rules/rule-1/replace", json=unchanged)
        invalid = client.post("/api/v1/rules/rule-1/replace", json=same_endpoint)
        replaced = client.post("/api/v1/rules/rule-1/replace", json=changed)
        rules = client.get("/api/v1/rules").json()

    assert rejected.status_code == 422
    assert invalid.status_code == 422
    assert replaced.status_code == 201
    assert replaced.json()["rule"]["state"] == "draft"
    assert replaced.json()["rule"]["destination"]["calendar_id"] == "team-calendar"
    assert replaced.json()["detached"] == 0
    assert [item["id"] for item in rules] == [replaced.json()["rule"]["id"]]


def test_sync_and_reconcile_now_report_a_rule_that_is_not_enabled(tmp_path: Path) -> None:
    container = replace(
        build_container(Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())),
        scheduler=None,
    )
    with container.unit_of_work() as uow:
        uow.rules.add(rule(state=SyncRuleState.PAUSED))
        uow.commit()

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        synced = client.post("/api/v1/rules/rule-1/sync")
        reconciled = client.post("/api/v1/rules/rule-1/reconcile")

    assert synced.status_code == 409
    assert reconciled.status_code == 409


def _append_audit(container: Container, *entries: AuditEntry) -> None:
    with container.unit_of_work() as uow:
        for entry in entries:
            uow.audit.append(entry)
        uow.commit()


def _audit(
    action: str,
    reason: str | None,
    *,
    rule_id: str = "rule-1",
    run_id: str | None = "run-1",
    destination_event_id: str | None = None,
) -> AuditEntry:
    return AuditEntry(
        occurred_at=datetime(2026, 9, 28, 15, 18, tzinfo=UTC),
        rule_id=SyncRuleId(rule_id),
        action=action,
        outcome={"ignore": "skipped", "conflict": "blocked"}.get(action, "completed"),
        source_event_id="source-event",
        destination_event_id=destination_event_id,
        reason=reason,
        run_id=run_id,
    )


def test_activity_exposes_reasons_categories_and_filters(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    _append_audit(
        container,
        _audit("create", "source_created", destination_event_id="copy-1"),
        _audit("ignore", "projection_current"),
        _audit("ignore", "recurring_unsupported"),
        # Recorded before recurring exclusions became skips.
        _audit("conflict", "recurring_unsupported", run_id=None),
        _audit("conflict", "mapping_inconsistent"),
        _audit("update", "source_changed", rule_id="rule-2", run_id="run-2"),
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json={"password": "correct horse battery staple"})

        everything = client.get("/api/v1/audit-entries").json()

        def categories(**params: str | int) -> list[str | None]:
            response = client.get("/api/v1/audit-entries", params=params)
            assert response.status_code == 200
            return [entry["reason"] for entry in response.json()]

        assert [entry["category"] for entry in everything] == [
            "changed",
            "blocked",
            "skipped",
            "skipped",
            "unchanged",
            "changed",
        ]
        assert everything[-1]["run_id"] == "run-1"
        assert everything[-1]["source_event_id"] == "source-event"
        assert everything[-1]["destination_event_id"] == "copy-1"
        assert categories(category="skipped") == ["recurring_unsupported"] * 2
        assert categories(category="blocked") == ["mapping_inconsistent"]
        assert categories(category="unchanged") == ["projection_current"]
        assert categories(rule_id="rule-2") == ["source_changed"]
        assert categories(before=everything[1]["id"], limit=2) == [
            "recurring_unsupported",
            "recurring_unsupported",
        ]
        assert client.get("/api/v1/audit-entries", params={"category": "other"}).status_code == 422
        assert client.get("/api/v1/audit-entries", params={"limit": 500}).status_code == 422


class FakeInspectionProvider:
    def __init__(self, events: dict[str, CalendarEvent], failure: Exception | None = None) -> None:
        self.events = events
        self.failure = failure
        self.requested: list[EventRef] = []

    def get_event(self, reference: EventRef) -> CalendarEvent | None:
        self.requested.append(reference)
        if self.failure is not None:
            raise self.failure
        return self.events.get(reference.event_id.value)


def test_activity_event_is_read_live_without_persisting_content(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    source = replace(
        event(title="Dentist"),
        recurrence=Recurrence(("RRULE:FREQ=WEEKLY",)),
        web_link="https://calendar.google.com/event?eid=synthetic",
    )
    provider = FakeInspectionProvider({"source-event": source})
    container = replace(
        build_container(Settings(database)), calendar_provider=cast(CalendarProvider, provider)
    )
    with container.unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()
    _append_audit(container, _audit("delete", "source_cancelled", destination_event_id="gone"))

    with TestClient(create_app(container)) as client:
        assert client.get("/api/v1/audit-entries/1/event").status_code == 401
        client.post("/api/v1/setup/admin", json={"password": "correct horse battery staple"})

        response = client.get("/api/v1/audit-entries/1/event")

        assert response.status_code == 200
        assert response.json() == {
            "source": {
                "found": True,
                "cancelled": False,
                "title": "Dentist",
                "all_day": False,
                "starts": "2026-08-30T10:00:00+00:00",
                "ends": "2026-08-30T11:00:00+00:00",
                "recurring": True,
                "web_link": "https://calendar.google.com/event?eid=synthetic",
            },
            "destination": {
                "found": False,
                "cancelled": False,
                "title": "",
                "all_day": False,
                "starts": None,
                "ends": None,
                "recurring": False,
                "web_link": None,
            },
        }
        assert provider.requested == [
            EventRef(rule().source, EventId("source-event")),
            EventRef(rule().destination, EventId("gone")),
        ]
        assert client.get("/api/v1/audit-entries/99/event").status_code == 404
    with sqlite3.connect(database) as connection:
        dump = "\n".join(connection.iterdump())
    assert "Dentist" not in dump


def test_activity_event_reports_unavailable_provider(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    failing = FakeInspectionProvider(
        {}, ProviderFailure(ProviderFailureKind.AUTHENTICATION, "token expired")
    )
    container = build_container(Settings(database))
    with container.unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()
    _append_audit(container, _audit("create", "source_created"))

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json={"password": "correct horse battery staple"})
        assert client.get("/api/v1/audit-entries/1/event").status_code == 503

    with TestClient(
        create_app(replace(container, calendar_provider=cast(CalendarProvider, failing)))
    ) as client:
        client.post("/api/v1/session", json={"password": "correct horse battery staple"})
        response = client.get("/api/v1/audit-entries/1/event")
        assert response.status_code == 424
        assert "authentication" in response.json()["detail"]


def test_rule_management_entries_are_listed_as_changes(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    _append_audit(
        container,
        _audit("policy_changed", None, run_id=None),
        _audit("remove_projection", None, run_id=None),
        _audit("detach_projection", None, run_id=None),
        _audit("rule_removed", None, run_id=None),
        _audit("ignore", "projection_current"),
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        changed = client.get("/api/v1/audit-entries", params={"category": "changed"}).json()

    assert [entry["action"] for entry in changed] == [
        "rule_removed",
        "detach_projection",
        "remove_projection",
        "policy_changed",
    ]
    assert {entry["category"] for entry in changed} == {"changed"}
