"""Reset proofs and credentials share one atomic identity boundary."""

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from calendar_sync.application.identity.errors import ResetStorageUnavailable
from calendar_sync.infrastructure.persistence.credentials import SqliteCredentialChanges
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.registration import SqlitePasswordResetLinks
from calendar_sync.infrastructure.persistence.users import SqliteSessions, SqliteUserDirectory
from tests.adapters.test_users_store import FIRST, SECOND, MovableClock, SequentialIds
from tests.contracts.persistence import CredentialPersistenceContract, CredentialPersistenceHarness
from tests.helpers import NOW
from tests.identity_fakes import (
    MemoryCredentialChanges,
    MemoryResetLinks,
    MemorySessions,
    MemoryUsers,
)


@dataclass
class ResetClock:
    moment: datetime = NOW

    def now(self) -> datetime:
        return self.moment


@pytest.fixture(params=["memory", "sqlite"])
def credentials(request: pytest.FixtureRequest, tmp_path: Path) -> CredentialPersistenceHarness:
    clock = ResetClock()
    if request.param == "sqlite":
        path = tmp_path / "reset.db"
        initialize_database(path)
        users = SqliteUserDirectory(path)
        sessions = SqliteSessions(path, clock)
        links = SqlitePasswordResetLinks(path, SequentialIds(), clock)
        changes = SqliteCredentialChanges(path, clock)
        users.add(FIRST, "old-hash")
        users.add(SECOND, "other-hash")
        return CredentialPersistenceHarness(users, sessions, links, links, changes, clock)
    memory_users = MemoryUsers()
    memory_sessions = MemorySessions(NOW, memory_users)
    memory_links = MemoryResetLinks(memory_users, memory_sessions, clock)
    memory_changes = MemoryCredentialChanges(memory_users, memory_sessions, clock)
    memory_users.add(FIRST, "old-hash")
    memory_users.add(SECOND, "other-hash")
    return CredentialPersistenceHarness(
        memory_users, memory_sessions, memory_links, memory_links, memory_changes, clock
    )


class TestCredentialStores(CredentialPersistenceContract):
    pass


def _sqlite_identity(tmp_path: Path) -> tuple[Path, ResetClock, CredentialPersistenceHarness]:
    path = tmp_path / "identity.db"
    initialize_database(path)
    clock = ResetClock()
    users = SqliteUserDirectory(path)
    users.add(FIRST, "old-hash")
    users.add(SECOND, "other-hash")
    sessions = SqliteSessions(path, clock)
    links = SqlitePasswordResetLinks(path, SequentialIds(), clock)
    changes = SqliteCredentialChanges(path, clock)
    return path, clock, CredentialPersistenceHarness(users, sessions, links, links, changes, clock)


def test_reset_checks_expiry_after_hash_and_lock_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager
    from threading import Event

    from calendar_sync.infrastructure.persistence import registration
    from calendar_sync.infrastructure.persistence.connections import transaction

    path, clock, h = _sqlite_identity(tmp_path)
    prepared = h.public.issue_for_email(SECOND.email or "")
    assert prepared is not None
    session = h.sessions.start(SECOND.id, "other-hash", SECOND.email, 0)
    assert session is not None
    waiting = Event()

    @contextmanager
    def observed_transaction(path: Path, *, timeout: float = 5.0) -> Iterator[sqlite3.Connection]:
        with transaction(path, timeout=timeout) as connection:
            connection.set_trace_callback(
                lambda statement: waiting.set() if statement == "BEGIN IMMEDIATE" else None
            )
            yield connection

    monkeypatch.setattr(registration, "transaction", observed_transaction)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction(path) as locked:
            locked.execute("BEGIN IMMEDIATE")
            future = executor.submit(h.links.reset, prepared.link.token, "forbidden")
            assert waiting.wait(timeout=1)
            clock.moment = prepared.link.expires_at
        assert future.result(timeout=1) is None
    assert h.users.password_hash(SECOND.id) == "other-hash"
    assert h.sessions.user_of(session.token) == SECOND.id
    with transaction(path) as connection:
        assert tuple(
            connection.execute("SELECT used_at, revoked_at FROM password_reset_links").fetchone()
        ) == (None, None)


def test_reset_atomic_failure_preserves_credential_proofs_and_sessions(tmp_path: Path) -> None:
    from calendar_sync.infrastructure.persistence.connections import transaction

    path, _, h = _sqlite_identity(tmp_path)
    prepared = h.public.issue_for_email(SECOND.email or "")
    assert prepared is not None
    session = h.sessions.start(SECOND.id, "other-hash", SECOND.email, 0)
    assert session is not None
    expected = h.changes.current(SECOND.id)
    with transaction(path) as connection:
        connection.execute(
            "CREATE TRIGGER refuse_session_delete BEFORE DELETE ON user_sessions "
            "BEGIN SELECT RAISE(ABORT, 'private-exception-marker'); END"
        )
    with pytest.raises(ResetStorageUnavailable, match="Password reset is temporarily unavailable"):
        h.links.reset(prepared.link.token, "forbidden")
    assert h.changes.current(SECOND.id) == expected
    assert h.sessions.user_of(session.token) == SECOND.id
    assert h.links.owner(prepared.link.token, NOW) == SECOND.id


def test_reset_tokens_are_hashed_and_secret_values_never_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from calendar_sync.application.identity.administration import ResetPassword
    from calendar_sync.application.identity.reset_admission import ResetAdmission
    from calendar_sync.infrastructure.identity_front_gate import MemoryIdentityFrontGate
    from calendar_sync.infrastructure.persistence.connections import transaction
    from calendar_sync.infrastructure.security import ScryptPasswords, token_hash

    path, clock, h = _sqlite_identity(tmp_path)
    prepared = h.public.issue_for_email(SECOND.email or "")
    assert prepared is not None
    address = SECOND.email
    assert address is not None
    secret = "a private synthetic reset password"
    reset = ResetPassword(
        h.links,
        ScryptPasswords(),
        clock,
        ResetAdmission(MemoryIdentityFrontGate(clock), None, clock),
    )
    with caplog.at_level("DEBUG"):
        reset.execute(prepared.link.token, secret, "synthetic-client")
    snapshot = h.changes.current(SECOND.id)
    assert snapshot is not None
    assert snapshot.password_hash is not None
    assert ScryptPasswords().verify(secret, snapshot.password_hash)
    for value in (
        prepared.link.token,
        address,
        secret,
        snapshot.password_hash,
        "private-exception-marker",
    ):
        assert value not in caplog.text
    assert prepared.link.token not in repr(prepared)
    assert address not in repr(prepared)
    assert prepared.link.token not in repr(prepared.link)
    assert snapshot.password_hash not in repr(snapshot)
    with transaction(path) as connection:
        proof = dict(connection.execute("SELECT * FROM password_reset_links").fetchone())
        assert proof["token_hash"] == token_hash(prepared.link.token)
        assert proof["created_by"] is None
        assert prepared.link.token not in str(proof)
        assert address not in str(proof)
        assert secret not in "\n".join(connection.iterdump())


def test_invitation_tokens_never_reset_credentials(tmp_path: Path) -> None:
    from calendar_sync.domain.access import RegistrationPolicy
    from calendar_sync.infrastructure.persistence.registration import (
        SqliteInvitations,
        SqliteRegistrationSettings,
    )

    path, clock, h = _sqlite_identity(tmp_path)
    SqliteRegistrationSettings(path, MovableClock(NOW)).set_policy(
        RegistrationPolicy.INVITATION_ONLY, actor=FIRST.id, fingerprint=None
    )
    invitation = SqliteInvitations(path, SequentialIds(), MovableClock(NOW)).issue(FIRST.id, NOW)
    assert invitation is not None
    before = h.changes.current(FIRST.id)
    assert h.links.owner(invitation.token, clock.now()) is None
    assert h.links.reset(invitation.token, "forbidden") is None
    assert h.changes.current(FIRST.id) == before


@pytest.mark.parametrize("version", [0, 35])
def test_reset_migration_fresh_upgrade_restart_and_legacy_revocation(
    tmp_path: Path, version: int
) -> None:
    from calendar_sync.infrastructure.persistence.connections import transaction
    from tests.adapters.test_user_migration import database_at_version

    path = tmp_path / "migration.db"
    session = None
    if version:
        database_at_version(path, version)
        users = SqliteUserDirectory(path)
        users.add(FIRST, "preserved-hash")
        from tests.users import add_account

        add_account(path, "preserved-account", FIRST.id)
        from calendar_sync.application.identity.ports import Session
        from tests.users import session_for

        session = Session(session_for(path, FIRST.id), NOW + timedelta(days=7), FIRST.id)
        assert session is not None
        with transaction(path) as connection:
            connection.execute(
                "INSERT INTO password_reset_links "
                "(id, token_hash, user_id, created_at, expires_at) "
                "VALUES ('legacy', 'legacy-proof-hash', ?, ?, ?)",
                (FIRST.id.value, NOW.isoformat(), (NOW + timedelta(days=7)).isoformat()),
            )
            before_settings = tuple(
                connection.execute("SELECT * FROM installation_settings").fetchone()
            )
            before_accounts = tuple(
                connection.execute("SELECT * FROM connected_accounts").fetchone()
            )
    initialize_database(path)
    initialize_database(path)
    with transaction(path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 39
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        if version:
            assert connection.execute("SELECT credential_revision FROM users").fetchone()[0] == 0
            proof = connection.execute(
                "SELECT credential_revision, revoked_at FROM password_reset_links"
            ).fetchone()
            assert proof[0] is None
            assert proof[1] is not None
            assert (
                tuple(connection.execute("SELECT * FROM installation_settings").fetchone())
                == before_settings
            )
            assert (
                tuple(connection.execute("SELECT * FROM connected_accounts").fetchone())
                == before_accounts
            )
    if version:
        assert SqliteUserDirectory(path).password_hash(FIRST.id) == "preserved-hash"
        assert session is not None
        assert SqliteSessions(path, ResetClock()).user_of(session.token) == FIRST.id


def test_reset_migration_rolls_back_on_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from importlib.resources import files

    from calendar_sync.infrastructure.persistence import migrations
    from calendar_sync.infrastructure.persistence.connections import transaction
    from tests.adapters.test_user_migration import database_at_version

    path = tmp_path / "migration.db"
    database_at_version(path, 35)
    resources = files("calendar_sync.infrastructure.persistence")

    class BrokenMigration:
        def joinpath(self, name: str) -> object:
            resource = resources.joinpath(name)
            if name == "0036_self_service_reset.sql":

                class BrokenScript:
                    def read_text(self) -> str:
                        return resource.read_text() + "\nINSERT INTO nonexistent VALUES (1);"

                return BrokenScript()
            return resource

    monkeypatch.setattr(migrations, "files", lambda _: BrokenMigration())
    with pytest.raises(sqlite3.OperationalError):
        initialize_database(path)
    with transaction(path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 35
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        assert "credential_revision" not in columns
    monkeypatch.undo()
    initialize_database(path)


def test_reset_proofs_cascade_with_the_user(tmp_path: Path) -> None:
    from calendar_sync.infrastructure.persistence.connections import transaction

    path, _, h = _sqlite_identity(tmp_path)
    assert h.public.issue_for_email(SECOND.email or "") is not None
    h.users.delete(SECOND.id)
    with transaction(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM password_reset_links").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("operation", ["password", "email"])
def test_own_credential_change_rolls_back_every_write_on_fault(
    tmp_path: Path, operation: str
) -> None:
    from calendar_sync.infrastructure.persistence.connections import transaction

    path, _, h = _sqlite_identity(tmp_path)
    prepared = h.public.issue_for_email(SECOND.email or "")
    assert prepared is not None
    session = h.sessions.start(SECOND.id, "other-hash", SECOND.email, 0)
    expected = h.changes.current(SECOND.id)
    assert session is not None
    assert expected is not None
    with transaction(path) as connection:
        connection.execute(
            "CREATE TRIGGER refuse_proof_revocation BEFORE UPDATE ON password_reset_links "
            "BEGIN SELECT RAISE(ABORT, 'synthetic-write-fault'); END"
        )

    def change() -> None:
        if operation == "password":
            h.changes.change_password(expected, "forbidden", session.token)
        else:
            h.changes.change_email(expected, "forbidden@example.test")

    with pytest.raises(sqlite3.IntegrityError, match="synthetic-write-fault"):
        change()
    assert h.changes.current(SECOND.id) == expected
    assert h.users.get(SECOND.id) == SECOND
    assert h.links.owner(prepared.link.token, NOW) == SECOND.id
    assert h.sessions.user_of(session.token) == SECOND.id


def test_own_password_change_refuses_expired_kept_session(tmp_path: Path) -> None:
    path, clock, h = _sqlite_identity(tmp_path)
    expected = h.changes.current(SECOND.id)
    session = h.sessions.start(SECOND.id, "other-hash", SECOND.email, 0)
    assert expected is not None
    assert session is not None
    clock.moment = session.expires_at
    assert not h.changes.change_password(expected, "forbidden", session.token)
    assert SqliteUserDirectory(path).password_hash(SECOND.id) == "other-hash"


def test_reset_and_sign_in_serialize_concurrent_session_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager
    from threading import Event

    from calendar_sync.infrastructure.persistence import registration, users
    from calendar_sync.infrastructure.persistence.connections import transaction

    _path, _, h = _sqlite_identity(tmp_path)
    prepared = h.public.issue_for_email(SECOND.email or "")
    assert prepared is not None
    changing = Event()
    starting = Event()
    proceed = Event()

    def trace_reset(statement: str) -> None:
        if statement.startswith("UPDATE users SET password_hash"):
            changing.set()
            assert proceed.wait(timeout=2)

    @contextmanager
    def reset_transaction(path: Path, *, timeout: float = 5.0) -> Iterator[sqlite3.Connection]:
        with transaction(path, timeout=timeout) as connection:
            connection.set_trace_callback(trace_reset)
            yield connection

    @contextmanager
    def session_transaction(path: Path, *, timeout: float = 5.0) -> Iterator[sqlite3.Connection]:
        with transaction(path, timeout=timeout) as connection:
            connection.set_trace_callback(
                lambda statement: starting.set() if statement == "BEGIN IMMEDIATE" else None
            )
            yield connection

    monkeypatch.setattr(registration, "transaction", reset_transaction)
    monkeypatch.setattr(users, "transaction", session_transaction)
    with ThreadPoolExecutor(max_workers=2) as executor:
        resetting = executor.submit(h.links.reset, prepared.link.token, "reset-hash")
        assert changing.wait(timeout=1)
        stale = executor.submit(h.sessions.start, SECOND.id, "other-hash", SECOND.email, 0)
        assert starting.wait(timeout=1)
        proceed.set()
        assert resetting.result(timeout=1) == SECOND.id
        assert stale.result(timeout=1) is None
    new = h.sessions.start(SECOND.id, "reset-hash", SECOND.email, 1)
    assert new is not None
    assert h.sessions.user_of(new.token) == SECOND.id


def test_reset_owner_read_obeys_short_anonymous_lock_timeout(tmp_path: Path) -> None:
    import time

    from calendar_sync.infrastructure.persistence.connections import transaction

    path, clock, h = _sqlite_identity(tmp_path)
    prepared = h.public.issue_for_email(SECOND.email or "")
    assert prepared is not None
    # A rollback-journal exclusive lock forces readers to wait too.
    with transaction(path) as connection:
        connection.execute("PRAGMA journal_mode = DELETE")
    with transaction(path) as locked:
        locked.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        with pytest.raises(ResetStorageUnavailable):
            h.links.owner(prepared.link.token, clock.now())
        elapsed = time.monotonic() - started
    assert 0.08 <= elapsed < 0.5
