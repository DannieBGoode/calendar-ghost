"""Existing session and credential writes tolerate ordinary short SQLite contention."""

import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from functools import partial
from pathlib import Path
from threading import Event, Timer

import pytest
from fastapi.testclient import TestClient

from calendar_sync.application.identity.errors import SignInStorageUnavailable
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_container
from calendar_sync.infrastructure.persistence import credentials, users
from calendar_sync.infrastructure.persistence.connections import BUSY_TIMEOUT_SECONDS, transaction
from calendar_sync.interfaces.api.app import create_app
from calendar_sync.interfaces.api.dependencies import SESSION_COOKIE
from tests.adapters.test_password_reset_store import _sqlite_identity
from tests.adapters.test_users_store import SECOND
from tests.users import ADMIN_EMAIL, ADMIN_PASSWORD, sign_in


@contextmanager
def _brief_write_contention(database: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    locked, attempted, release = Event(), Event(), Event()
    timer = Timer(0.3, release.set)

    def hold_lock() -> None:
        with transaction(database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            locked.set()
            assert release.wait(timeout=3)

    def observe(statement: str) -> None:
        if (
            statement.lstrip().startswith(("BEGIN IMMEDIATE", "INSERT ", "UPDATE ", "DELETE "))
            and not attempted.is_set()
        ):
            attempted.set()
            timer.start()

    @contextmanager
    def observed_transaction(
        path: Path, *, timeout: float = BUSY_TIMEOUT_SECONDS
    ) -> Iterator[sqlite3.Connection]:
        with transaction(path, timeout=timeout) as connection:
            connection.set_trace_callback(observe)
            yield connection

    with ThreadPoolExecutor(max_workers=1) as pool:
        holding = pool.submit(hold_lock)
        try:
            assert locked.wait(timeout=2)
            with monkeypatch.context() as patch:
                patch.setattr(users, "transaction", observed_transaction)
                patch.setattr(credentials, "transaction", observed_transaction)
                yield
                assert attempted.is_set()
        finally:
            release.set()
            timer.cancel()
            holding.result(timeout=2)


@pytest.mark.parametrize("operation", ["start", "end", "record_sign_in", "change_password"])
def test_existing_identity_writes_wait_for_brief_contention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    path, clock, h = _sqlite_identity(tmp_path)
    expected = h.changes.current(SECOND.id)
    assert expected is not None
    session = h.sessions.start(SECOND.id, expected.password_hash, expected.email, expected.revision)
    assert session is not None
    signed_in_at = clock.now() + timedelta(hours=1)
    with _brief_write_contention(path, monkeypatch):
        if operation == "start":
            started = h.sessions.start(
                SECOND.id, expected.password_hash, expected.email, expected.revision
            )
            assert started is not None
            assert h.sessions.user_of(started.token) == SECOND.id
        elif operation == "end":
            h.sessions.end(session.token)
            assert h.sessions.user_of(session.token) is None
        elif operation == "record_sign_in":
            h.users.record_sign_in(SECOND.id, signed_in_at)
            current = h.users.get(SECOND.id)
            assert current is not None
            assert current.last_sign_in_at == signed_in_at
        else:
            assert h.changes.change_password(expected, "changed-hash", session.token)
            assert h.users.password_hash(SECOND.id) == "changed-hash"
            assert h.sessions.user_of(session.token) == SECOND.id


@pytest.mark.parametrize("operation", ["sign_in", "sign_out"])
def test_session_api_succeeds_after_brief_write_contention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    path = tmp_path / "identity.db"
    container = build_container(Settings(path))
    client = TestClient(create_app(container))
    sign_in(client)
    original_token = client.cookies.get(SESSION_COOKIE)
    assert original_token is not None
    if operation == "sign_in":
        assert client.delete("/api/v1/session").status_code == 204
    with _brief_write_contention(path, monkeypatch):
        if operation == "sign_in":
            response = client.post(
                "/api/v1/session", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
            )
            assert response.status_code == 200
            assert response.json()["authenticated"] is True
            assert response.json()["user"]["email"] == ADMIN_EMAIL
        else:
            assert client.delete("/api/v1/session").status_code == 204
            assert container.identity.sessions.user_of(original_token) is None
    assert client.get("/api/v1/session").json()["authenticated"] is (operation == "sign_in")


@pytest.mark.parametrize("operation", ["start", "record_sign_in"])
def test_composed_registration_writes_refuse_brief_contention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    path = tmp_path / "identity.db"
    container = build_container(Settings(path))
    client = TestClient(create_app(container))
    sign_in(client)
    expected = container.identity.users.sign_in_credentials(ADMIN_EMAIL)
    assert expected
    completion = container.registrations.complete
    write = (
        partial(
            completion.sessions.start,
            expected.user.id,
            expected.credential.password_hash,
            expected.credential.email,
            expected.credential.revision,
        )
        if operation == "start"
        else partial(
            completion.users.record_sign_in,
            expected.user.id,
            completion.clock.now() + timedelta(hours=1),
        )
    )
    with _brief_write_contention(path, monkeypatch), pytest.raises(SignInStorageUnavailable):
        write()
    assert container.identity.users.get(expected.user.id) == expected.user
    with transaction(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM user_sessions").fetchone()[0] == 1
