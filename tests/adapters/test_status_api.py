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

from calendar_sync.application.ports import AuditAction, AuditEntry, AuditOutcome, RecordedEvent
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import Adapters, Container, build_adapters, compose
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarId,
    ConnectedAccountId,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import StatusReaderServices, require_status_reader
from tests.helpers import endpoint

PASSWORD = {"password": "correct horse battery staple"}
SECRETS = {
    "account": "acct-secret-7f3a",
    "email": "secret.person@example.test",
    "calendar": "c_secret9b1e@group.calendar.example.test",
    "title": "Secret dentist visit",
}


def _installation(tmp_path: Path) -> tuple[Container, Adapters]:
    settings = Settings(tmp_path / "test.db")
    adapters = build_adapters(settings)
    return replace(compose(settings, adapters), scheduler=None), adapters


def _signed_in(client: TestClient) -> None:
    client.post("/api/v1/setup/admin", json=PASSWORD)


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
        assert client.post("/api/v1/integration-tokens", json={"name": "a\nb"}).status_code == 422

        client.cookies.clear()
        bearer = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/integration-tokens", headers=bearer).status_code == 401
        assert (
            client.post(
                "/api/v1/integration-tokens", json={"name": "x"}, headers=bearer
            ).status_code
            == 401
        )


class _RefusingAdministrator:
    def session_is_valid(self, token: str | None) -> bool:
        return False


class _RefusingTokens:
    def authenticate(self, token: str) -> None:
        return None


class _RefusingServices:
    administrator = _RefusingAdministrator()
    integration_tokens = _RefusingTokens()


def _traceback_depth(traceback: TracebackType | None) -> int:
    depth = 0
    while traceback is not None:
        depth += 1
        traceback = traceback.tb_next
    return depth


def _refuse(services: StatusReaderServices) -> HTTPException:
    try:
        require_status_reader(services, authorization=None, session=None)
    except HTTPException as error:
        return error
    raise AssertionError("expected require_status_reader to raise")


def test_require_status_reader_raises_an_independent_exception_each_refusal() -> None:
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
    assert response.json() == {"detail": "valid credentials required"}


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
        assert client.delete(f"/api/v1/integration-tokens/{token_id}").status_code == 404
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
                state, created_at, updated_at
            ) VALUES (
                ?, 'google', 'Secret Person', ?, x'00', 'connected', '2026-09-01', '2026-09-01'
            )
            """,
            (SECRETS["account"], SECRETS["email"]),
        )
    seeded = SyncRule(
        id=SyncRuleId("rule-1"),
        source=CalendarEndpoint(
            ConnectedAccountId(SECRETS["account"]), CalendarId(SECRETS["calendar"])
        ),
        destination=endpoint("work-account", "work-calendar"),
        state=SyncRuleState.DEGRADED,
    )
    with adapters.unit_of_work() as uow:
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
                account_id
            ) VALUES ('incident-1', 'provider:rule-1', 'rule-1', 'authentication', 'open',
                'Calendar provider authorization expired', '2026-10-03T08:00:00+00:00',
                '2026-10-03T08:00:00+00:00', ?)
            """,
            (SECRETS["account"],),
        )
    with sqlite3.connect(database) as connection:
        # Google stores `summary or id` as a calendar's name: a primary calendar's summary is the
        # account email by default (source), and an unlisted or unnamed calendar's name is its own
        # id (destination). Both must stay out of the status response.
        connection.execute(
            """
            INSERT INTO calendar_names (connected_account_id, calendar_id, name, updated_at)
            VALUES (?, ?, ?, '2026-10-03T08:00:00+00:00')
            """,
            (SECRETS["account"], SECRETS["calendar"], SECRETS["calendar"]),
        )
        connection.execute(
            """
            INSERT INTO calendar_names (connected_account_id, calendar_id, name, updated_at)
            VALUES ('work-account', 'work-calendar', ?, '2026-10-03T08:00:00+00:00')
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
