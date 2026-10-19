from __future__ import annotations

import logging
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, cast

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Adapters, Container, build_adapters, compose
from calendar_sync.domain.access import Role
from calendar_sync.domain.audit import AuditAction, AuditEntry, AuditOutcome, RecordedEvent
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarId,
    ConnectedAccountId,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.domain.plans import Plan, PlanKey, PlanLimits, SyncInterval
from calendar_sync.interfaces.access import StatusAccess, StatusPrincipal
from calendar_sync.interfaces.api import dependencies
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import (
    SESSION_COOKIE,
    StatusReaderServices,
    status_reader,
)
from tests.helpers import endpoint, rule
from tests.plans import FREE, plans_on
from tests.users import (
    OTHER_USER,
    add_account,
    add_user,
    administrator,
    limited_user,
    session_for,
    sign_in,
)

PASSWORD = {"password": "correct horse battery staple"}
SECRETS = {
    "account": "acct-secret-7f3a",
    "email": "secret.person@example.test",
    "calendar": "c_secret9b1e@group.calendar.example.test",
    "title": "Secret dentist visit",
}
ONE_TOKEN = Plan(PlanKey("one-token"), "One token", PlanLimits(None, None, 1, SyncInterval.INSTANT))


def _installation(tmp_path: Path) -> tuple[Container, Adapters]:
    """An installation with its first User, so records can be seeded for them."""
    settings = Settings(tmp_path / "test.db")
    adapters = build_adapters(settings)
    administrator(adapters)
    return replace(compose(settings, adapters), scheduler=None), adapters


def _signed_in(client: TestClient) -> None:
    sign_in(client)


def _issue(client: TestClient, name: str = "Uptime Kuma") -> str:
    response = client.post("/api/v1/integration-tokens", json={"name": name})
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    token: str = response.json()["token"]
    return token


def test_tokens_are_managed_only_with_an_administrator_session(tmp_path: Path) -> None:
    container, _ = _installation(tmp_path)
    with TestClient(create_app(container)) as client:
        assert client.get("/api/v1/integration-tokens").status_code == 401
        _signed_in(client)
        token = _issue(client)
        listed = client.get("/api/v1/integration-tokens").json()

        assert listed[0]["name"] == "Uptime Kuma"
        assert "token" not in listed[0]
        invalid = client.post("/api/v1/integration-tokens", json={"name": "a\nb"})
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "invalid_integration_token_name"

        client.cookies.clear()
        bearer = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/integration-tokens", headers=bearer).status_code == 401
        assert (
            client.post(
                "/api/v1/integration-tokens", json={"name": "x"}, headers=bearer
            ).status_code
            == 401
        )


def test_a_member_at_their_plans_token_limit_is_refused_with_the_limit(tmp_path: Path) -> None:
    container, adapters = _installation(tmp_path)
    database = tmp_path / "test.db"
    member = limited_user(database)
    plans_on(adapters.plan_catalog, ONE_TOKEN)
    with TestClient(create_app(container)) as client:
        client.cookies.set(SESSION_COOKIE, session_for(database, member))
        _issue(client)
        refused = client.post("/api/v1/integration-tokens", json={"name": "Homepage"})
        listed = client.get("/api/v1/integration-tokens").json()

    assert (refused.status_code, refused.json()["code"], refused.json()["params"]) == (
        409,
        "plan_limit_reached",
        {"reason": "integration_tokens", "limit": 1, "count": 1},
    )
    assert [token["name"] for token in listed] == ["Uptime Kuma"]


def test_a_demoted_administrator_keeps_their_tokens_but_issues_none_past_the_limit(
    tmp_path: Path,
) -> None:
    container, adapters = _installation(tmp_path)
    database = tmp_path / "test.db"
    other = add_user(database, OTHER_USER)
    plans_on(adapters.plan_catalog, FREE)
    with TestClient(create_app(container)) as client:
        client.cookies.set(SESSION_COOKIE, session_for(database, other))
        kept = _issue(client)
        adapters.users.set_role(other, Role.USER)
        refused = client.post("/api/v1/integration-tokens", json={"name": "Homepage"})
        health = client.post(
            "/api/v1/integration-tokens",
            json={"name": "Health monitor", "scopes": ["status:read", "installation:read"]},
        )
        still_reads = client.get("/api/v1/status", headers={"Authorization": f"Bearer {kept}"})
        adapters.users.set_role(other, Role.INSTALLATION_ADMINISTRATOR)
        promoted = client.post("/api/v1/integration-tokens", json={"name": "Homepage"})

    assert (refused.status_code, refused.json()["code"], refused.json()["params"]) == (
        409,
        "plan_limit_reached",
        {"reason": "integration_tokens", "limit": 0, "count": 0},
    )
    assert (health.status_code, health.json()["code"]) == (403, "administrator_required")
    assert still_reads.status_code == 200
    assert promoted.status_code == 201


class _RefusingSessions:
    def user_of(self, token: str | None) -> None:
        return None


class _RefusingIdentity:
    sessions = _RefusingSessions()


class _RefusingTokens:
    def authenticate(self, token: str) -> None:
        return None


class _RefusingServices:
    identity = _RefusingIdentity()
    token_authentication = _RefusingTokens()


def _traceback_depth(traceback: TracebackType | None) -> int:
    depth = 0
    while traceback is not None:
        depth += 1
        traceback = traceback.tb_next
    return depth


def _refuse(services: StatusReaderServices) -> HTTPException:
    try:
        status_reader(services, authorization=None, session=None)
    except HTTPException as error:
        return error
    raise AssertionError("expected status_reader to raise")


def test_status_reader_raises_an_independent_exception_each_refusal() -> None:
    """A shared exception object would append frames to one `__traceback__` on every refusal and
    keep each refused call's locals alive; a fresh exception per call does neither."""
    services = cast(StatusReaderServices, _RefusingServices())

    first = _refuse(services)
    second = _refuse(services)
    third = _refuse(services)

    assert first is not second
    assert second is not third
    depths = [_traceback_depth(error.__traceback__) for error in (first, second, third)]
    assert depths[0] == depths[1] == depths[2]
    assert first.__traceback__ is not second.__traceback__
    assert first.status_code == second.status_code == 401
    assert first.detail == second.detail == "valid credentials required"


def test_status_accepts_a_token_or_a_session(tmp_path: Path) -> None:
    container, _ = _installation(tmp_path)
    with TestClient(create_app(container)) as client:
        _signed_in(client)
        token = _issue(client)
        by_session = client.get("/api/v1/status")
        client.cookies.clear()
        by_token = client.get("/api/v1/status", headers={"Authorization": f"Bearer {token}"})

    assert by_session.status_code == by_token.status_code == 200
    assert by_token.headers["cache-control"] == "no-store"
    body = by_token.json()
    assert body["status"] == "setup"
    assert body["needs_attention"] is False
    assert body["problems"] == []
    assert set(body) >= {"summary", "version", "checked_at", "scheduler", "counts", "rules"}


@pytest.mark.parametrize(
    "header",
    [None, "Bearer cgs_" + "A" * 43, "Bearer not-a-token", "Basic abc", "Bearer "],
)
def test_status_refuses_missing_and_invalid_credentials_alike(
    tmp_path: Path, header: str | None
) -> None:
    container, _ = _installation(tmp_path)
    headers = {"Authorization": header} if header is not None else {}
    with TestClient(create_app(container)) as client:
        response = client.get("/api/v1/status", headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "detail": "valid credentials required",
        "code": "credentials_required",
        "params": {},
    }


def test_a_token_without_the_status_scope_is_forbidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every token issued today has the status scope, so the refusal is forced at the decision.
    monkeypatch.setattr(
        dependencies, "status_access", lambda *_: StatusPrincipal(StatusAccess.FORBIDDEN)
    )
    container, _ = _installation(tmp_path)
    with TestClient(create_app(container)) as client:
        response = client.get("/api/v1/status", headers={"Authorization": "Bearer cgs_token"})

    assert response.status_code == 403
    assert response.json() == {
        "detail": "token lacks the required scope",
        "code": "insufficient_scope",
        "params": {},
    }


def test_an_invalid_bearer_header_is_refused_beside_a_valid_session(tmp_path: Path) -> None:
    container, _ = _installation(tmp_path)
    with TestClient(create_app(container)) as client:
        _signed_in(client)
        response = client.get("/api/v1/status", headers={"Authorization": "Bearer cgs_" + "B" * 43})
    assert response.status_code == 401


def test_a_revoked_token_and_a_token_in_the_query_string_are_refused(tmp_path: Path) -> None:
    container, _ = _installation(tmp_path)
    with TestClient(create_app(container)) as client:
        _signed_in(client)
        token = _issue(client)
        token_id = client.get("/api/v1/integration-tokens").json()[0]["id"]
        assert client.delete(f"/api/v1/integration-tokens/{token_id}").status_code == 204
        missing = client.delete(f"/api/v1/integration-tokens/{token_id}")
        assert missing.status_code == 404
        assert missing.json()["code"] == "integration_token_not_found"
        live = _issue(client, "Homepage")
        client.cookies.clear()

        revoked = client.get("/api/v1/status", headers={"Authorization": f"Bearer {token}"})
        in_query = client.get(f"/api/v1/status?token={live}")
        in_access_token = client.get(f"/api/v1/status?access_token={live}")
        in_header = client.get("/api/v1/status", headers={"Authorization": f"Bearer {live}"})

    assert (revoked.status_code, in_query.status_code, in_access_token.status_code) == (
        401,
        401,
        401,
    )
    assert in_header.status_code == 200


def test_status_never_contains_identifiers_emails_or_event_content(tmp_path: Path) -> None:
    container, adapters = _installation(tmp_path)
    database = tmp_path / "test.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO connected_accounts (
                id, provider, display_name, email, encrypted_credentials,
                state, created_at, updated_at, user_id
            ) VALUES (
                ?, 'google', 'Secret Person', ?, x'00', 'connected', '2026-09-01', '2026-09-01',
                    (SELECT id FROM users ORDER BY rowid LIMIT 1)
            )
            """,
            (SECRETS["account"], SECRETS["email"]),
        )
    add_account(database, "work-account", administrator(adapters))
    seeded = SyncRule(
        id=SyncRuleId("rule-1"),
        source=CalendarEndpoint(
            ConnectedAccountId(SECRETS["account"]), CalendarId(SECRETS["calendar"])
        ),
        destination=endpoint("work-account", "work-calendar"),
        state=SyncRuleState.DEGRADED,
    )
    with adapters.unit_of_work(administrator(adapters))() as uow:
        uow.rules.add(seeded)
        uow.audit.append(
            AuditEntry(
                occurred_at=datetime(2026, 10, 3, 8, 0, tzinfo=UTC),
                rule_id=seeded.id,
                action=AuditAction.CREATE,
                outcome=AuditOutcome.COMPLETED,
                source_event_id="source-event-1",
                event=RecordedEvent(title=SECRETS["title"]),
            )
        )
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO incidents (
                id, deduplication_key, rule_id, category, state, summary, opened_at, updated_at,
                account_id, user_id
            ) VALUES ('incident-1', 'provider:rule-1', 'rule-1', 'authentication', 'open',
                'Calendar provider authorization expired', '2026-10-03T08:00:00+00:00',
                '2026-10-03T08:00:00+00:00', ?, (SELECT id FROM users ORDER BY rowid LIMIT 1))
            """,
            (SECRETS["account"],),
        )
    with sqlite3.connect(database) as connection:
        # Google stores `summary or id` as a calendar's name: a primary calendar's summary is the
        # account email by default (source), and an unlisted or unnamed calendar's name is its own
        # id (destination). Both must stay out of the status response.
        connection.execute(
            """
            INSERT INTO calendar_names (
                connected_account_id, calendar_id, name, updated_at, user_id
            ) VALUES (?, ?, ?, '2026-10-03T08:00:00+00:00', (SELECT id FROM users))
            """,
            (SECRETS["account"], SECRETS["calendar"], SECRETS["calendar"]),
        )
        connection.execute(
            """
            INSERT INTO calendar_names (
                connected_account_id, calendar_id, name, updated_at, user_id
            ) VALUES ('work-account', 'work-calendar', ?, '2026-10-03T08:00:00+00:00',
                (SELECT id FROM users))
            """,
            (SECRETS["email"],),
        )
    with TestClient(create_app(container)) as client:
        _signed_in(client)
        token = _issue(client)
        client.cookies.clear()
        response = client.get("/api/v1/status", headers={"Authorization": f"Bearer {token}"})

    assert response.json()["status"] == "stopped"
    for value in [*SECRETS.values(), token, "Secret Person"]:
        assert value not in response.text


def test_the_token_never_reaches_the_logs(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    container, _ = _installation(tmp_path)
    with TestClient(create_app(container)) as client:
        _signed_in(client)
        token = _issue(client)
        client.cookies.clear()
        with caplog.at_level(logging.DEBUG):
            client.get("/api/v1/status", headers={"Authorization": f"Bearer {token}"})
            client.get("/api/v1/status", headers={"Authorization": f"Bearer {token[:-1]}x"})
    assert token not in caplog.text
    assert token[:-1] not in caplog.text


def test_the_dashboard_carries_the_server_verdict(tmp_path: Path) -> None:
    container, _ = _installation(tmp_path)
    with TestClient(create_app(container)) as client:
        _signed_in(client)
        body: dict[str, Any] = client.get("/api/v1/dashboard").json()
    assert body["status"] == "setup"
    assert body["needs_attention"] is False
    assert body["problems"] == []
    assert "health" not in body
    # Without a scheduler there is no next pass to wait for.
    assert body["next_pass_at"] is None


def test_counts_never_call_a_stopped_rule_running(tmp_path: Path) -> None:
    container, adapters = _installation(tmp_path)
    with sqlite3.connect(tmp_path / "test.db") as connection:
        connection.executemany(
            """
            INSERT INTO connected_accounts (
                id, provider, display_name, email, encrypted_credentials,
                state, created_at, updated_at, user_id
            ) VALUES (?, 'google', ?, ?, x'00', ?, '2026-09-01', '2026-09-01',
                (SELECT id FROM users ORDER BY rowid LIMIT 1))
            """,
            [
                ("personal-account", "Personal", "personal@example.test", "connected"),
                ("work-account", "Work", "work@example.test", "disconnected"),
            ],
        )
    with adapters.unit_of_work(administrator(adapters))() as uow:
        uow.rules.add(rule())
        uow.commit()
    with TestClient(create_app(container)) as client:
        _signed_in(client)
        body: dict[str, Any] = client.get("/api/v1/status").json()
        dashboard: dict[str, Any] = client.get("/api/v1/dashboard").json()

    assert body["counts"]["rules"] == 1
    assert (body["counts"]["running"], body["counts"]["stopped"]) == (0, 1)
    # The Overview counts the rule the same way, though it is still enabled.
    assert (dashboard["running_rules"], dashboard["stopped_rules"]) == (0, 1)
    assert dashboard["enabled_rules"] == 1


def test_the_scheduler_block_says_whether_a_scheduler_is_configured(tmp_path: Path) -> None:
    container, _ = _installation(tmp_path)
    with TestClient(create_app(container)) as client:
        _signed_in(client)
        scheduler: dict[str, Any] = client.get("/api/v1/status").json()["scheduler"]

    # Without a master key there is no scheduler; this installation cannot synchronize.
    assert scheduler == {
        "configured": False,
        "last_pass_completed_at": None,
        "current_pass_started_at": None,
        "next_pass_at": None,
    }


def test_a_problem_from_an_incident_carries_its_message(tmp_path: Path) -> None:
    container, adapters = _installation(tmp_path)
    with sqlite3.connect(tmp_path / "test.db") as connection:
        connection.executemany(
            """
            INSERT INTO connected_accounts (
                id, provider, display_name, email, encrypted_credentials,
                state, created_at, updated_at, user_id
            ) VALUES (?, 'google', ?, ?, x'00', 'connected', '2026-09-01', '2026-09-01',
                (SELECT id FROM users ORDER BY rowid LIMIT 1))
            """,
            [
                ("personal-account", "Personal", "personal@example.test"),
                ("work-account", "Work", "work@example.test"),
            ],
        )
    with adapters.unit_of_work(administrator(adapters))() as uow:
        uow.rules.add(rule(state=SyncRuleState.DEGRADED))
        uow.commit()
    with sqlite3.connect(tmp_path / "test.db") as connection:
        connection.execute(
            """
            INSERT INTO incidents (
                id, deduplication_key, rule_id, category, state, summary, opened_at, updated_at,
                message_code, message_params, user_id
            ) VALUES ('incident-1', 'provider:rule-1', 'rule-1', 'authentication', 'open',
                'Authorization for Google Calendar expired', '2026-10-03T08:00:00+00:00',
                '2026-10-03T08:00:00+00:00', 'provider_failure',
                '{"kind": "authentication", "provider": "google"}',
                    (SELECT id FROM users ORDER BY rowid LIMIT 1))
            """
        )
    with TestClient(create_app(container)) as client:
        _signed_in(client)
        status: dict[str, Any] = client.get("/api/v1/status").json()
        dashboard: dict[str, Any] = client.get("/api/v1/dashboard").json()

    message = {
        "code": "provider_failure",
        "params": {"kind": "authentication", "provider": "google"},
    }
    assert status["problems"][0]["kind"] == "stopped"
    assert status["problems"][0]["message"] == message
    assert status["rules"][0]["problem"]["message"] == message
    assert dashboard["problems"][0]["message"] == message
