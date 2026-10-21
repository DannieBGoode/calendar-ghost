"""Actual registration response connections are bounded; ordinary identity stays unchanged."""

import sqlite3
from collections import defaultdict
from contextlib import AbstractContextManager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from calendar_sync.application.identity.ports import Session
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.persistence import connections
from calendar_sync.infrastructure.persistence.registration import SqliteInvitations
from calendar_sync.infrastructure.persistence.sqlite import unit_of_work
from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
from calendar_sync.interfaces.api.app import create_app
from tests.adapters.test_registration_api import COMPLETE, EMAIL, proof, ready
from tests.adapters.test_registration_store import RandomIds
from tests.users import ADMIN_PASSWORD


def test_response_reads_use_bounded_connections_and_plans_still_fail_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "test.db"
    _, container = ready(path)
    token = proof(container)
    timeouts: dict[str, set[float]] = defaultdict(set)
    original = connections.open_connection

    def tracked(database: Path, *, timeout: float = 5.0) -> sqlite3.Connection:
        connection = original(database, timeout=timeout)

        def read(
            action: int,
            table: str | None,
            _column: str | None,
            _db: str | None,
            _source: str | None,
        ) -> int:
            if action == sqlite3.SQLITE_READ and table:
                timeouts[table].add(timeout)
                if table == "plans":
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(read)
        return connection

    # Isolate precisely the response tail after account, proof, and session have committed.
    start = container.registrations.complete.sessions.start

    def started(
        user: UserId, password_hash: str, email: str | None, revision: int
    ) -> Session | None:
        session = start(user, password_hash, email, revision)
        monkeypatch.setattr(connections, "open_connection", tracked)
        monkeypatch.setattr(unit_of_work, "open_connection", tracked)
        return session

    monkeypatch.setattr(container.registrations.complete.sessions, "start", started)
    public = TestClient(create_app(container))
    response = public.post(COMPLETE, json={"token": token, "password": ADMIN_PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json()["user"]["email"] == EMAIL
    assert "set-cookie" in response.headers
    assert timeouts["users"] == {0.1}
    assert timeouts["calendar_watches"] == {0.1}
    assert timeouts["installation_settings"] == {0.1}
    assert timeouts["plans"] == {0.1}
    answers = container.registrations.answers
    answers.status.evidence.evidence("https://calendar.example.test")
    assert answers.status.sources.provider_of(ConnectedAccountId("missing")) is None
    assert timeouts["delivery_evidence"] == {0.1}
    assert timeouts["connected_accounts"] == {0.1}
    timeouts.clear()
    ordinary = SqliteUserDirectory(path).by_email(EMAIL)
    assert ordinary
    assert timeouts["users"] == {5.0}
    timeouts.clear()
    container.instant_sync_status.availability(ordinary.id)
    assert timeouts["calendar_watches"] == {5.0}
    assert timeouts["users"] == {5.0}
    assert timeouts["installation_settings"] == {5.0}


def test_direct_invitation_storage_keeps_ordinary_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from calendar_sync.infrastructure.persistence import registration

    path = tmp_path / "test.db"
    _, container = ready(path)
    timeouts: list[float] = []
    original = connections.transaction

    def tracked(
        database: Path, *, timeout: float = 5.0
    ) -> AbstractContextManager[sqlite3.Connection]:
        timeouts.append(timeout)
        return original(database, timeout=timeout)

    monkeypatch.setattr(registration, "transaction", tracked)
    container.administration.show_registration.settings.policy()
    invitations = SqliteInvitations(path, RandomIds(), container.registrations.complete.clock)
    assert not invitations.usable("invalid", container.registrations.complete.clock.now())
    assert invitations.accept("invalid", EMAIL, "synthetic-hash") is None
    assert timeouts == [5.0, 5.0, 5.0]


def test_invite_write_storage_fault_is_mapped(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    client, _ = ready(path)
    with connections.transaction(path) as connection:
        connection.execute("DROP TABLE invitations")
    result = client.post("/api/v1/invitations")
    assert (result.status_code, result.json()["code"]) == (503, "registration_unavailable")
