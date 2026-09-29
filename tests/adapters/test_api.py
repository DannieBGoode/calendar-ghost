import sqlite3
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Thread
from typing import cast
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import calendar_sync.interfaces.api.app as api_module
from calendar_sync.application.errors import ProviderFailure, ProviderFailureKind
from calendar_sync.application.ports import (
    AuditEntry,
    CalendarProvider,
    RecordedEvent,
    RuleRunOutcome,
    RunKind,
)
from calendar_sync.application.preview import PreviewSyncRule
from calendar_sync.application.reconciliation import ReconcileSyncRule
from calendar_sync.application.removal import RemoveSyncRule
from calendar_sync.application.synchronization import ExecuteSyncRule, SyncRunResult
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Container, build_container
from calendar_sync.domain.model import (
    CalendarEvent,
    ConnectedAccountId,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    EventStatus,
    ProjectionFingerprint,
    Recurrence,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TimedInterval,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
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
from tests.fake_calendar import FakeCalendars, FixedClock
from tests.helpers import all_day_event, endpoint, event, occurrence, rule, series, week_start


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
            "disconnected_accounts": 0,
            "sync_rules": 0,
            "enabled_rules": 0,
            "stopped_rules": 0,
            "open_incidents": 0,
            "last_synced_at": None,
            "blocked_events": 0,
            "blocked_entry_id": None,
            "blocked_rule_id": None,
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
        assert activity[0]["event"] is None
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
    assert dashboard.json()["disconnected_accounts"] == 1
    # rule-1, validated-rule, and destination-rule degrade; the paused rule stays paused.
    assert dashboard.json()["stopped_rules"] == 3
    assert dashboard.json()["health"] == "attention"
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
    assert detached.json() == {"deleted": 0, "detached": 0, "conflicts": 0}
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


def test_reconcile_now_counts_as_the_daily_check_for_blocked_events(tmp_path: Path) -> None:
    container = build_container(
        Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())
    )
    with container.unit_of_work() as uow:
        uow.rules.add(rule(state=SyncRuleState.ENABLED))
        uow.commit()
    _append_audit(container, _audit("conflict", "destination_occurrence_missing", run_id="run-1"))

    def full_pass(rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
        assert full
        # The pass decides the blocked event again and finds it still blocked.
        _append_audit(
            container, _audit("conflict", "destination_occurrence_missing", run_id="run-2")
        )
        return SyncRunResult(rule_id, conflicts=1, run_id="run-2", listed_in_full=True)

    container = replace(
        container,
        scheduler=None,
        execute_sync_rule=cast(ExecuteSyncRule, Mock(execute=full_pass)),
        reconcile_sync_rule=cast(
            ReconcileSyncRule,
            Mock(execute=Mock(return_value=Mock(is_consistent=True, checked_mappings=0, drift=[]))),
        ),
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        assert client.post("/api/v1/rules/rule-1/reconcile").status_code == 200
        incidents = client.get("/api/v1/incidents").json()

    assert [(item["rule_id"], item["state"]) for item in incidents] == [("rule-1", "open")]
    assert incidents[0]["summary"].startswith("1 event could not be synced")


@pytest.mark.parametrize("failing", ["audit_floor", "record_full_pass"])
def test_reconcile_now_is_not_aborted_by_block_health_bookkeeping(
    tmp_path: Path, failing: str
) -> None:
    container = build_container(
        Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())
    )
    with container.unit_of_work() as uow:
        uow.rules.add(rule(state=SyncRuleState.ENABLED))
        uow.commit()
    execute = Mock(return_value=SyncRunResult(SyncRuleId("rule-1"), run_id="run-1"))
    reconcile = Mock(return_value=Mock(is_consistent=True, checked_mappings=0, drift=[]))
    health = Mock(audit_floor=Mock(return_value=0), record_full_pass=Mock())
    getattr(health, failing).side_effect = sqlite3.OperationalError("database is locked")
    container = replace(
        container,
        scheduler=None,
        execute_sync_rule=cast(ExecuteSyncRule, Mock(execute=execute)),
        reconcile_sync_rule=cast(ReconcileSyncRule, Mock(execute=reconcile)),
        rule_health=health,
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        response = client.post("/api/v1/rules/rule-1/reconcile")

    # Incident bookkeeping is best-effort; the requested sync and reconciliation still run.
    assert response.status_code == 200
    assert execute.call_count == 1
    assert reconcile.call_count == 1


def test_reconcile_now_records_the_full_pass_even_when_reconciliation_fails(
    tmp_path: Path,
) -> None:
    container = build_container(
        Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())
    )
    with container.unit_of_work() as uow:
        uow.rules.add(rule(state=SyncRuleState.ENABLED))
        uow.commit()
    _append_audit(container, _audit("conflict", "destination_occurrence_missing", run_id="run-1"))

    def full_pass(rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
        _append_audit(
            container, _audit("conflict", "destination_occurrence_missing", run_id="run-2")
        )
        return SyncRunResult(rule_id, conflicts=1, run_id="run-2", listed_in_full=True)

    failure = ProviderFailure(ProviderFailureKind.TEMPORARY, "synthetic outage")
    container = replace(
        container,
        scheduler=None,
        execute_sync_rule=cast(ExecuteSyncRule, Mock(execute=full_pass)),
        reconcile_sync_rule=cast(ReconcileSyncRule, Mock(execute=Mock(side_effect=failure))),
    )

    with TestClient(create_app(container), raise_server_exceptions=False) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        assert client.post("/api/v1/rules/rule-1/reconcile").status_code >= 500
        incidents = client.get("/api/v1/incidents").json()

    assert [(item["rule_id"], item["state"]) for item in incidents] == [("rule-1", "open")]


def test_dashboard_and_rule_list_report_the_latest_successful_sync(tmp_path: Path) -> None:
    container = replace(build_container(Settings(tmp_path / "test.db")), scheduler=None)
    with container.unit_of_work() as uow:
        uow.rules.add(rule(state=SyncRuleState.ENABLED))
        uow.rules.add(
            SyncRule(
                id=SyncRuleId("rule-2"),
                source=endpoint("personal-account", "second-calendar"),
                destination=endpoint("work-account", "second-destination"),
                state=SyncRuleState.ENABLED,
            )
        )
        uow.run_outcomes.record(
            RuleRunOutcome(
                SyncRuleId("rule-1"),
                RunKind.SYNC,
                datetime(2026, 9, 28, 9, 0, tzinfo=UTC),
                succeeded=True,
                created=2,
            )
        )
        uow.run_outcomes.record(
            RuleRunOutcome(
                SyncRuleId("rule-2"),
                RunKind.SYNC,
                datetime(2026, 9, 28, 10, 0, tzinfo=UTC),
                succeeded=False,
                failure_kind="rate_limit",
            )
        )
        uow.commit()

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        dashboard = client.get("/api/v1/dashboard").json()
        rules = {item["id"]: item for item in client.get("/api/v1/rules").json()}

    # A failed run is not evidence that calendars are current.
    assert dashboard["last_synced_at"] == "2026-09-28T09:00:00+00:00"
    assert rules["rule-1"]["last_sync"]["last_succeeded_at"] == "2026-09-28T09:00:00+00:00"
    assert rules["rule-2"]["last_sync"]["last_succeeded_at"] is None
    assert dashboard["enabled_rules"] == 2
    assert dashboard["health"] == "healthy"
    assert rules["rule-1"]["last_sync"]["created"] == 2
    assert rules["rule-2"]["last_sync"]["failure_kind"] == "rate_limit"


def test_last_successful_sync_survives_a_later_failure(tmp_path: Path) -> None:
    container = replace(build_container(Settings(tmp_path / "test.db")), scheduler=None)
    with container.unit_of_work() as uow:
        uow.rules.add(rule(state=SyncRuleState.ENABLED))
        succeeded = RuleRunOutcome(
            SyncRuleId("rule-1"), RunKind.SYNC, datetime(2026, 9, 28, 9, 0, tzinfo=UTC), True
        )
        uow.run_outcomes.record(succeeded)
        uow.run_outcomes.record(
            replace(
                succeeded,
                completed_at=datetime(2026, 9, 28, 10, 0, tzinfo=UTC),
                succeeded=False,
                failure_kind="rate_limit",
            )
        )
        uow.commit()

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        dashboard = client.get("/api/v1/dashboard").json()
        (listed,) = client.get("/api/v1/rules").json()

    assert dashboard["last_synced_at"] == "2026-09-28T09:00:00+00:00"
    assert listed["last_sync"]["succeeded"] is False
    assert listed["last_sync"]["last_succeeded_at"] == "2026-09-28T09:00:00+00:00"


def test_recent_changes_list_each_written_event_newest_first(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    dentist = RecordedEvent.of(event(title="Dentist"))
    _append_audit(
        container,
        _audit("create", "source_created", run_id="run-1", event=dentist),
        _audit("ignore", "projection_current", run_id="run-2", event=dentist),
        _audit("update", "source_changed", run_id="run-3", source_event_id="b"),
        _audit("conflict", "mapping_inconsistent", run_id="run-4", source_event_id="c"),
        _audit("delete", "source_cancelled", run_id="run-5", source_event_id="d"),
    )

    with TestClient(create_app(container)) as client:
        assert client.get("/api/v1/recent-changes").status_code == 401
        client.post("/api/v1/setup/admin", json=PASSWORD)
        changes = client.get("/api/v1/recent-changes").json()
        limited = client.get("/api/v1/recent-changes", params={"limit": 1}).json()

    # No-change checks are quiet and blocks belong to the health strip, so neither is listed.
    assert [change["entry"]["reason"] for change in changes] == [
        "source_cancelled",
        "source_changed",
        "source_created",
    ]
    assert changes[2]["entry"]["event"]["title"] == "Dentist"
    assert [(change["repeats"], change["first_occurred_at"]) for change in changes] == [
        (1, "2026-09-28T15:18:00+00:00")
    ] * 3
    assert [change["entry"]["reason"] for change in limited] == ["source_cancelled"]


def test_recent_changes_collapse_an_identical_repeated_write(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    weekly = RecordedEvent.of(
        replace(event(title="Stand-up"), recurrence=Recurrence(("RRULE:FREQ=WEEKLY",)))
    )
    moved = event(title="Stand-up")
    assert isinstance(moved.time, TimedInterval)
    moved = replace(
        moved,
        time=TimedInterval(
            moved.time.starts_at + timedelta(hours=1), moved.time.ends_at + timedelta(hours=1)
        ),
    )
    _append_audit(
        container,
        *(
            _audit("create", "projection_missing", run_id=f"loop-{index}", event=weekly)
            for index in range(3)
        ),
        _audit("update", "source_changed", run_id="edit-1", source_event_id="other"),
        # Two edits of the same event are changes of their own, even when their summaries match.
        _audit("update", "source_changed", run_id="edit-0", source_event_id="other"),
        _audit(
            "update",
            "source_changed",
            run_id="edit-2",
            source_event_id="other",
            event=RecordedEvent.of(moved),
        ),
    )
    with sqlite3.connect(container.settings.database_path) as connection:
        connection.execute(
            "UPDATE audit_entries SET occurred_at = '2026-09-29T14:00:00+00:00' WHERE id = 1"
        )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        changes = client.get("/api/v1/recent-changes").json()

    assert [
        (change["entry"]["id"], change["repeats"], change["first_occurred_at"])
        for change in changes
    ] == [
        (6, 1, "2026-09-28T15:18:00+00:00"),
        (5, 1, "2026-09-28T15:18:00+00:00"),
        (4, 1, "2026-09-28T15:18:00+00:00"),
        (3, 3, "2026-09-29T14:00:00+00:00"),
    ]


def test_recent_changes_look_past_a_long_repeated_repair(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    _append_audit(
        container,
        _audit("create", "source_created", run_id="older", source_event_id="dentist"),
        *(_audit("create", "projection_missing", run_id=f"loop-{index}") for index in range(1200)),
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        changes = client.get("/api/v1/recent-changes").json()

    assert [(change["entry"]["reason"], change["repeats"]) for change in changes] == [
        ("projection_missing", 1200),
        ("source_created", 1),
    ]


def test_dashboard_reports_events_whose_latest_decision_was_blocked(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    with container.unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()
    _append_audit(
        container,
        _audit("conflict", "destination_occurrence_missing", run_id="run-1", source_event_id="a"),
        _audit("conflict", "mapping_inconsistent", run_id="run-1", source_event_id="b"),
        _audit("update", "source_changed", run_id="run-2", source_event_id="b"),
        # Blocks of a removed rule and old recurring exclusions are not open blocks.
        _audit("conflict", "mapping_inconsistent", rule_id="removed", source_event_id="c"),
        _audit("conflict", "recurring_unsupported", source_event_id="d"),
        _audit("removal_conflict", None, source_event_id="e"),
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        dashboard = client.get("/api/v1/dashboard").json()

    assert (dashboard["blocked_events"], dashboard["blocked_entry_id"]) == (1, 1)
    assert dashboard["blocked_rule_id"] == "rule-1"


def test_dashboard_names_no_rule_when_blocks_span_rules(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    with container.unit_of_work() as uow:
        uow.rules.add(rule())
        uow.rules.add(
            replace(rule(), id=SyncRuleId("rule-2"), source=endpoint("other", "calendar"))
        )
        uow.commit()
    _append_audit(
        container,
        _audit("conflict", "mapping_inconsistent", source_event_id="a"),
        _audit("conflict", "mapping_inconsistent", rule_id="rule-2", source_event_id="b"),
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        dashboard = client.get("/api/v1/dashboard").json()

    assert (dashboard["blocked_events"], dashboard["blocked_entry_id"]) == (2, 2)
    assert dashboard["blocked_rule_id"] is None
    # A block alone is reported, not an incident: the health stays healthy until it persists.
    assert dashboard["health"] == "healthy"


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
    source_event_id: str | None = "source-event",
    destination_event_id: str | None = None,
    event: RecordedEvent | None = None,
) -> AuditEntry:
    return AuditEntry(
        occurred_at=datetime(2026, 9, 28, 15, 18, tzinfo=UTC),
        rule_id=SyncRuleId(rule_id),
        action=action,
        outcome={"ignore": "skipped", "conflict": "blocked"}.get(action, "completed"),
        source_event_id=source_event_id,
        destination_event_id=destination_event_id,
        reason=reason,
        run_id=run_id,
        event=event,
    )


def test_removal_conflicts_are_blocked_activity_scoped_by_rule(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    _append_audit(
        container,
        _audit("remove_projection", None, run_id=None),
        _audit("removal_conflict", None, run_id=None),
        _audit("removal_conflict", None, rule_id="rule-2", run_id=None),
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        everything = client.get("/api/v1/audit-entries").json()
        blocked = client.get(
            "/api/v1/audit-entries", params={"category": "blocked", "rule_id": "rule-1"}
        ).json()

    assert [entry["category"] for entry in everything] == ["blocked", "blocked", "changed"]
    assert [(entry["action"], entry["rule_id"]) for entry in blocked] == [
        ("removal_conflict", "rule-1")
    ]


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


def test_no_change_runs_count_whole_runs_that_a_page_boundary_splits(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    _append_audit(
        container,
        _audit("ignore", "projection_current", run_id="run-1"),
        _audit("ignore", "projection_current", run_id="run-1"),
        # The oldest entry on the loaded page; the run's checks above sit below the boundary.
        _audit("create", "source_created", run_id="run-1"),
        _audit("update", "source_changed", run_id="run-2"),
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        runs = client.get("/api/v1/audit-entries/no-change-runs", params={"after": 2}).json()

    assert [(item["run_id"], item["count"]) for item in runs] == [("run-1", 2)]


def test_no_change_runs_find_recent_runs_by_entry_range_not_by_run_index(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    build_container(Settings(database))

    with sqlite3.connect(database) as connection:
        plans = [
            " ".join(str(row[3]) for row in connection.execute(f"EXPLAIN QUERY PLAN {sql}", args))
            for sql, args in (
                (api_module._recent_runs_sql(with_rule=False), (0, 500)),
                (api_module._recent_runs_sql(with_rule=True), ("rule-1", 0, 500)),
            )
        ]

    assert "INTEGER PRIMARY KEY (rowid>?)" in plans[0]
    assert "audit_entries_rule_id (rule_id=? AND id>?)" in plans[1]
    assert all("audit_entries_run_id" not in plan for plan in plans)


def test_activity_lists_runs_with_no_change_checks_including_quiet_runs(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    _append_audit(
        container,
        _audit("ignore", "projection_current", run_id="run-1"),
        _audit("ignore", "occurrence_current", run_id="run-1"),
        _audit("create", "source_created", run_id="run-1"),
        # A run that only confirmed events were up to date has no other entries to show.
        _audit("ignore", "projection_current", run_id="run-2"),
        _audit("ignore", "all_day_excluded", run_id="run-3"),
        _audit("ignore", "projection_current", rule_id="rule-2", run_id="run-4"),
    )

    with TestClient(create_app(container)) as client:
        assert client.get("/api/v1/audit-entries/no-change-runs").status_code == 401
        client.post("/api/v1/setup/admin", json=PASSWORD)
        everything = client.get("/api/v1/audit-entries/no-change-runs").json()
        one_rule = client.get(
            "/api/v1/audit-entries/no-change-runs", params={"rule_id": "rule-1"}
        ).json()
        newer = client.get("/api/v1/audit-entries/no-change-runs", params={"after": 3}).json()
        one_run = client.get(
            "/api/v1/audit-entries", params={"run_id": "run-1", "category": "unchanged"}
        )

    assert [(item["run_id"], item["count"], item["newest_id"]) for item in everything] == [
        ("run-4", 1, 6),
        ("run-2", 1, 4),
        ("run-1", 2, 2),
    ]
    assert everything[0]["rule_id"] == "rule-2"
    assert [item["run_id"] for item in one_rule] == ["run-2", "run-1"]
    assert [item["run_id"] for item in newer] == ["run-4", "run-2"]
    assert [entry["reason"] for entry in one_run.json()] == [
        "occurrence_current",
        "projection_current",
    ]


def test_activity_filters_combine_several_categories(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    _append_audit(
        container,
        _audit("create", "source_created"),
        _audit("ignore", "projection_current"),
        _audit("ignore", "all_day_excluded"),
        _audit("conflict", "mapping_inconsistent"),
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        response = client.get(
            "/api/v1/audit-entries",
            params=[("category", "changed"), ("category", "skipped"), ("category", "blocked")],
        )

    assert response.status_code == 200
    assert [entry["reason"] for entry in response.json()] == [
        "mapping_inconsistent",
        "all_day_excluded",
        "source_created",
    ]


def test_occurrences_that_already_match_are_listed_as_no_change(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    _append_audit(
        container,
        _audit("ignore", "occurrence_current"),
        _audit("ignore", "occurrence_already_cancelled"),
        _audit("ignore", "series_not_synchronized"),
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        everything = client.get("/api/v1/audit-entries").json()
        unchanged = client.get("/api/v1/audit-entries", params={"category": "unchanged"}).json()
        skipped = client.get("/api/v1/audit-entries", params={"category": "skipped"}).json()

    assert [entry["category"] for entry in everything] == ["skipped", "unchanged", "unchanged"]
    assert [entry["reason"] for entry in unchanged] == [
        "occurrence_already_cancelled",
        "occurrence_current",
    ]
    assert [entry["reason"] for entry in skipped] == ["series_not_synchronized"]


def test_single_activity_entry_can_be_opened_directly(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    _append_audit(container, _audit("create", "source_created", destination_event_id="copy-1"))

    with TestClient(create_app(container)) as client:
        assert client.get("/api/v1/audit-entries/1").status_code == 401
        client.post("/api/v1/setup/admin", json=PASSWORD)
        response = client.get("/api/v1/audit-entries/1")
        missing = client.get("/api/v1/audit-entries/99")

    assert response.status_code == 200
    assert response.json()["reason"] == "source_created"
    assert response.json()["category"] == "changed"
    assert response.json()["destination_event_id"] == "copy-1"
    assert missing.status_code == 404


def test_activity_names_each_event_as_its_run_recorded_it(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    # No provider is configured: Activity names events without asking Google.
    container = build_container(Settings(database))
    with container.unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()
    renamed = event(title="Dentist (moved)")
    _append_audit(
        container,
        _audit("create", "source_created", event=RecordedEvent.of(event(title="Dentist"))),
        _audit("ignore", "projection_current", event=RecordedEvent.of(event(title="Dentist"))),
        _audit("update", "source_changed", event=RecordedEvent.of(renamed)),
        # Google reports a deleted event without its title or time.
        _audit("delete", "source_cancelled", event=RecordedEvent(title="", cancelled=True)),
        # Removing a rule reads no event at all.
        _audit("remove_projection", None, run_id=None),
        _audit("create", "source_created", source_event_id="recorded-before-upgrade"),
        _audit("create", "source_created", source_event_id="all-day", event=_day_off()),
        _audit("policy_changed", None, source_event_id=None),
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        entries = {
            entry["id"]: entry["event"] for entry in client.get("/api/v1/audit-entries").json()
        }
        opened = client.get("/api/v1/audit-entries/4").json()["event"]

    dentist = {
        "title": "Dentist",
        "all_day": False,
        "starts": "2026-08-30T10:00:00+00:00",
        "ends": "2026-08-30T11:00:00+00:00",
        "recurring": False,
        "cancelled": False,
        "renamed_from": None,
        "moved_from": None,
    }
    assert entries[1] == entries[2] == dentist
    assert entries[3] == dentist | {"title": "Dentist (moved)", "renamed_from": "Dentist"}
    assert entries[4] == opened == dentist | {"title": "Dentist (moved)", "cancelled": True}
    assert entries[5] == dentist | {"title": "Dentist (moved)"}
    assert entries[6] is None
    assert entries[7] == {
        "title": "Day off",
        "all_day": True,
        "starts": "2026-08-30",
        "ends": "2026-08-31",
        "recurring": False,
        "cancelled": False,
        "renamed_from": None,
        "moved_from": None,
    }
    assert entries[8] is None
    with sqlite3.connect(database) as connection:
        dump = "\n".join(connection.iterdump())
    assert "Sensitive" not in dump


def test_activity_shows_the_time_an_event_moved_from(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    dentist = event(title="Dentist")
    assert isinstance(dentist.time, TimedInterval)
    moved_time = TimedInterval(
        dentist.time.starts_at + timedelta(hours=1), dentist.time.ends_at + timedelta(hours=1)
    )
    later = replace(dentist, time=moved_time)
    _append_audit(
        container,
        _audit("create", "source_created", event=RecordedEvent.of(dentist)),
        _audit("update", "source_changed", event=RecordedEvent.of(later)),
        _audit("update", "destination_drift_repaired", event=RecordedEvent.of(later)),
        # Only the end changed: a longer event, not a moved one.
        _audit(
            "update",
            "source_changed",
            event=RecordedEvent.of(
                replace(
                    later,
                    time=TimedInterval(
                        moved_time.starts_at, moved_time.ends_at + timedelta(hours=1)
                    ),
                )
            ),
        ),
        # Google reports a deleted event without its time; it did not move.
        _audit("delete", "source_cancelled", event=RecordedEvent(title="", cancelled=True)),
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        moved = {
            entry["id"]: entry["event"]["moved_from"]
            for entry in client.get("/api/v1/audit-entries").json()
        }

    assert moved == {
        1: None,
        2: {
            "all_day": False,
            "starts": "2026-08-30T10:00:00+00:00",
            "ends": "2026-08-30T11:00:00+00:00",
        },
        3: None,
        4: None,
        5: None,
    }


def test_activity_marks_a_write_that_repeats_the_previous_run(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    _append_audit(
        container,
        _audit("create", "projection_missing", run_id="run-1"),
        _audit("create", "projection_missing", run_id="run-2"),
        _audit("ignore", "projection_current", run_id="run-3"),
        _audit("ignore", "projection_current", run_id="run-4"),
        _audit("update", "source_changed", run_id="run-5"),
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        repeated = {
            entry["id"]: entry["repeated"]
            for entry in client.get(
                "/api/v1/audit-entries", params={"category": ["changed", "unchanged"]}
            ).json()
        }

    # Checks repeat by design; only a write that redoes the previous run's write is marked.
    assert repeated == {1: False, 2: True, 3: False, 4: False, 5: False}


def test_activity_never_calls_a_source_change_a_repeat(tmp_path: Path) -> None:
    # A Details Projection's location can change while its recorded title and time stay the same,
    # so matching summaries do not prove a source change repeated the previous one.
    container = build_container(Settings(tmp_path / "test.db"))
    _append_audit(
        container,
        _audit(
            "update", "source_changed", run_id="run-1", event=RecordedEvent.of(event(title="A"))
        ),
        _audit(
            "update", "source_changed", run_id="run-2", event=RecordedEvent.of(event(title="B"))
        ),
        _audit(
            "update", "source_changed", run_id="run-3", event=RecordedEvent.of(event(title="B"))
        ),
        # The same title and time, but the event became a series: a change of its own.
        _audit(
            "update",
            "source_changed",
            run_id="run-4",
            event=replace(RecordedEvent.of(event(title="B")), recurring=True),
        ),
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        repeated = {
            entry["id"]: entry["repeated"] for entry in client.get("/api/v1/audit-entries").json()
        }

    assert repeated == {1: False, 2: False, 3: False, 4: False}


def test_activity_keeps_an_observed_empty_title_but_names_untitled_cancellations(
    tmp_path: Path,
) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    offsite = RecordedEvent.of(replace(event(title="Offsite"), recurrence=None))
    _append_audit(
        container,
        _audit("create", "source_created", event=RecordedEvent.of(event(title="Dentist"))),
        _audit("update", "source_changed", event=RecordedEvent.of(event(title=""))),
        _audit("ignore", "projection_current", event=RecordedEvent.of(event(title=""))),
        _audit("delete", "source_cancelled", event=RecordedEvent(title="", cancelled=True)),
        _audit("update", "source_changed", event=RecordedEvent.of(event(title="Dentist"))),
        _audit("update", "occurrence_changed", source_event_id="occurrence", event=offsite),
        _audit(
            "delete",
            "occurrence_removed_from_series",
            source_event_id="occurrence",
            event=RecordedEvent(title="", recurring=True, cancelled=True),
        ),
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        entries = {
            entry["id"]: entry["event"] for entry in client.get("/api/v1/audit-entries").json()
        }

    names = {
        entry_id: (event["title"], event["renamed_from"], event["cancelled"])
        for entry_id, event in entries.items()
    }
    assert names == {
        1: ("Dentist", None, False),
        2: ("", "Dentist", False),
        3: ("", None, False),
        4: ("", None, True),
        5: ("Dentist", "", False),
        6: ("Offsite", None, False),
        7: ("Offsite", None, True),
    }
    assert entries[7]["starts"] == entries[6]["starts"]


def test_activity_shows_the_recurrence_each_entry_saw(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    weekly = RecordedEvent.of(replace(event(), recurrence=Recurrence(("RRULE:FREQ=WEEKLY",))))
    _append_audit(
        container,
        _audit("create", "source_created", event=weekly),
        # The series became a single event under the same identifier.
        _audit("update", "source_changed", event=RecordedEvent.of(event())),
        _audit("create", "source_created", source_event_id="series", event=weekly),
        _audit("delete", "source_cancelled", source_event_id="series", event=_untitled_stub()),
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        recurring = {
            entry["id"]: entry["event"]["recurring"]
            for entry in client.get("/api/v1/audit-entries").json()
        }

    assert recurring == {1: True, 2: False, 3: True, 4: True}


def _untitled_stub() -> RecordedEvent:
    return RecordedEvent(title="", cancelled=True)


def test_activity_does_not_carry_names_across_rules(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    _append_audit(
        container,
        _audit("create", "source_created", event=RecordedEvent.of(event(title="Dentist"))),
        _audit("remove_projection", None, rule_id="rule-2"),
    )

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        entries = client.get("/api/v1/audit-entries").json()

    assert [entry["event"] and entry["event"]["title"] for entry in entries] == [None, "Dentist"]


def _day_off() -> RecordedEvent:
    return RecordedEvent.of(all_day_event())


def test_cancelled_source_events_keep_their_title_for_display(tmp_path: Path) -> None:
    cancelled = replace(event(title="Dentist"), status=EventStatus.CANCELLED)
    provider = FakeInspectionProvider({"source-event": cancelled})
    container = replace(
        build_container(Settings(tmp_path / "test.db")),
        calendar_provider=cast(CalendarProvider, provider),
    )
    with container.unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()
    _append_audit(container, _audit("delete", "source_cancelled"))

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        response = client.get("/api/v1/audit-entries/1/event")

    assert response.json()["source"]["cancelled"] is True
    assert response.json()["source"]["title"] == "Dentist"


def test_sync_reconciliation_and_removal_share_one_rule_lock(tmp_path: Path) -> None:
    container = build_container(
        Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())
    )

    assert container.execute_sync_rule is not None
    assert container.reconcile_sync_rule is not None
    assert container.execute_sync_rule.locks is container.rule_locks
    assert container.reconcile_sync_rule.locks is container.rule_locks
    assert container.remove_sync_rule.locks is container.rule_locks


def test_pause_waits_for_an_in_flight_provider_write(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    with container.unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()
    responses: list[int] = []

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        writing = container.rule_locks.for_writes(rule().id)
        writing.acquire()
        worker = Thread(
            target=lambda: responses.append(client.post("/api/v1/rules/rule-1/pause").status_code)
        )
        worker.start()
        worker.join(0.2)
        blocked_while_writing = worker.is_alive()
        writing.release()
        worker.join(2)

    assert blocked_while_writing
    assert responses == [200]


def test_activity_event_of_a_removed_rule_reports_gone_without_provider_reads(
    tmp_path: Path,
) -> None:
    provider = FakeInspectionProvider({"source-event": event()})
    container = build_container(Settings(tmp_path / "test.db"))
    _append_audit(container, _audit("detach_projection", None, run_id=None))

    for candidate in (
        container,
        replace(container, calendar_provider=cast(CalendarProvider, provider)),
    ):
        with TestClient(create_app(candidate)) as client:
            client.post("/api/v1/setup/admin", json=PASSWORD)
            client.post("/api/v1/session", json=PASSWORD)
            response = client.get("/api/v1/audit-entries/1/event")
            assert response.status_code == 410
            assert "removed" in response.json()["detail"]
    assert provider.requested == []


def _waits_for_rule_writes(container: Container, request: Callable[[TestClient], int]) -> int:
    responses: list[int] = []
    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        writing = container.rule_locks.for_writes(rule().id)
        writing.acquire()
        worker = Thread(target=lambda: responses.append(request(client)))
        worker.start()
        worker.join(0.2)
        blocked = worker.is_alive()
        writing.release()
        worker.join(2)
    assert blocked
    return responses[0]


def test_enable_waits_for_a_concurrent_rule_change(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    with container.unit_of_work() as uow:
        uow.rules.add(rule(state=SyncRuleState.DRY_RUN_VALIDATED))
        uow.commit()

    status_code = _waits_for_rule_writes(
        container, lambda client: client.post("/api/v1/rules/rule-1/enable").status_code
    )

    assert status_code == 200


def test_disconnect_waits_for_a_concurrent_rule_change(tmp_path: Path) -> None:
    container = replace(
        build_container(Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())),
        scheduler=None,
    )
    assert container.connected_accounts is not None
    account = container.connected_accounts.save(
        "Work", "work@example.test", '{"refresh_token":"synthetic-secret"}'
    )
    with container.unit_of_work() as uow:
        uow.rules.add(
            SyncRule(
                rule().id,
                endpoint("personal", "personal-calendar"),
                endpoint(account.id.value, "work-calendar"),
                state=SyncRuleState.ENABLED,
            )
        )
        uow.commit()

    status_code = _waits_for_rule_writes(
        container,
        lambda client: client.post(f"/api/v1/accounts/{account.id.value}/disconnect").status_code,
    )

    assert status_code == 200
    with container.unit_of_work() as uow:
        degraded = uow.rules.get(rule().id)
    assert degraded is not None
    assert degraded.state is SyncRuleState.DEGRADED


def test_preview_reports_recurring_series_and_planned_actions(tmp_path: Path) -> None:
    container = build_container(Settings(tmp_path / "test.db"))
    with container.unit_of_work() as uow:
        uow.rules.add(rule(state=SyncRuleState.DRAFT))
        uow.commit()
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=(week_start(0), week_start(1)))
    calendars.put(occurrence(master, 1, status=EventStatus.CANCELLED))
    fingerprinter = ProjectionFingerprinter()
    preview = PreviewSyncRule(
        container.unit_of_work,
        calendars,
        EventProjector(),
        FixedClock(),
        SyncDecisionService(EventProjector(), fingerprinter),
    )

    with TestClient(create_app(replace(container, preview_sync_rule=preview))) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        body = client.post("/api/v1/rules/rule-1/preview").json()

    assert body["eligible_events"] == 1
    assert body["excluded_events"] == 0
    assert body["recurring_series"] == 1
    assert body["occurrence_changes"] == 1
    assert [(item["kind"], item["planned_action"]) for item in body["sample"]] == [
        ("series", "create"),
        ("occurrence", "delete"),
    ]


class _ConnectedAccounts:
    def is_connected(self, account_id: ConnectedAccountId) -> bool:
        return True


def test_delete_removal_reports_events_left_because_ownership_was_not_proven(
    tmp_path: Path,
) -> None:
    calendars = FakeCalendars()
    calendars.put(event("native", calendar=rule().destination))
    container = build_container(Settings(tmp_path / "test.db"))
    container = replace(
        container,
        remove_sync_rule=RemoveSyncRule(
            container.unit_of_work,
            calendars,
            _ConnectedAccounts(),
            FixedClock(),
            container.rule_locks,
        ),
    )
    with container.unit_of_work() as uow:
        uow.rules.add(rule())
        uow.mappings.save(
            EventMapping(
                EventMappingId("mapping-1"),
                rule().id,
                event("source-event").reference,
                EventRef(rule().destination, EventId("native")),
                "revision-1",
                ProjectionFingerprint("fingerprint"),
            )
        )
        uow.commit()

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        removed = client.delete("/api/v1/rules/rule-1?projections=delete")
        after = client.get("/api/v1/rules/rule-1")

    assert removed.status_code == 200
    assert removed.json() == {"deleted": 0, "detached": 0, "conflicts": 1}
    assert after.status_code == 404
    assert calendars.writes == []
