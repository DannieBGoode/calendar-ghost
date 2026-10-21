"""Email ownership changes remain atomic with credential and session changes."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from calendar_sync.application.identity.credentials import CredentialSnapshot
from calendar_sync.application.identity.email_changes import EmailChangeUnavailable
from calendar_sync.application.identity.ports import Session
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.email_changes import SqliteEmailChangeProofs
from calendar_sync.infrastructure.security import CredentialCipher, token_hash
from tests.adapters.test_password_reset_store import ResetClock, _sqlite_identity
from tests.adapters.test_users_store import FIRST, SECOND, SequentialIds
from tests.contracts.persistence import CredentialPersistenceHarness


def setup(
    tmp_path: Path,
) -> tuple[
    Path,
    ResetClock,
    CredentialPersistenceHarness,
    SqliteEmailChangeProofs,
    CredentialSnapshot,
    Session,
]:
    path, clock, h = _sqlite_identity(tmp_path)
    store = SqliteEmailChangeProofs(
        path, SequentialIds(), clock, master_key=CredentialCipher.generate_key()
    )
    expected = h.changes.current(SECOND.id)
    assert expected
    session = h.sessions.start(SECOND.id, expected.password_hash, expected.email, expected.revision)
    assert session
    return path, clock, h, store, expected, session


def test_email_change_lifecycle(tmp_path: Path) -> None:
    path, clock, h, store, expected, session = setup(tmp_path)
    request = store.request(expected, "new@example.test", session.token)
    assert h.users.get(SECOND.id) == SECOND
    assert store.pending(SECOND.id) == request
    prepared = store.prepare(request.id)
    assert prepared
    assert prepared.recipient == "new@example.test"
    assert request.expires_at == clock.now() + timedelta(hours=24)
    assert store.prepare(request.id) is None
    assert prepared.token not in repr(prepared)
    with transaction(path) as connection:
        row = connection.execute("SELECT token_hash FROM email_change_proofs").fetchone()
        assert row[0] == token_hash(prepared.token)
    assert store.check(SECOND.id, prepared.token)
    assert store.check(SECOND.id, prepared.token)
    replacement = store.request(expected, "replacement@example.test", session.token)
    store.cancel(SECOND.id, request.id)
    assert store.pending(SECOND.id) == replacement
    assert not store.check(SECOND.id, prepared.token)
    store.cancel(FIRST.id, replacement.id)
    assert store.pending(SECOND.id) == replacement
    store.cancel(SECOND.id, replacement.id)
    assert store.prepare(replacement.id) is None
    assert store.pending(SECOND.id) is None


def test_delayed_preparation_starts_a_full_day_without_repeat_extension(tmp_path: Path) -> None:
    path, clock, h, store, expected, session = setup(tmp_path)
    requested_at = clock.now()
    request = store.request(expected, "new@example.test", session.token)
    clock.moment = requested_at + timedelta(hours=23)
    prepared = store.prepare(request.id)
    assert prepared is not None
    issued_expiry = requested_at + timedelta(hours=47)
    pending = store.pending(SECOND.id)
    assert pending is not None
    assert pending.expires_at == issued_expiry
    with transaction(path) as connection:
        row = connection.execute(
            "SELECT token_hash, expires_at FROM email_change_proofs WHERE id = ?", (request.id,)
        ).fetchone()
        assert row["token_hash"] == token_hash(prepared.token)
        assert row["expires_at"] == issued_expiry.isoformat()

    clock.moment = requested_at + timedelta(hours=25)
    assert store.check(SECOND.id, prepared.token)
    assert store.prepare(request.id) is None
    assert store.pending(SECOND.id) == pending
    clock.moment = issued_expiry
    assert not store.check(SECOND.id, prepared.token)
    assert store.pending(SECOND.id) is None
    assert store.confirm(expected, prepared.token, session.token) is None
    assert h.changes.current(SECOND.id) == expected


@pytest.mark.parametrize("elapsed_hours", [24, 25])
def test_expired_unprepared_request_cannot_gain_an_issued_lifetime(
    tmp_path: Path, elapsed_hours: int
) -> None:
    path, clock, _h, store, expected, session = setup(tmp_path)
    requested_at = clock.now()
    request = store.request(expected, "new@example.test", session.token)
    clock.moment = requested_at + timedelta(hours=elapsed_hours)
    assert store.prepare(request.id) is None
    assert store.pending(SECOND.id) is None
    with transaction(path) as connection:
        row = connection.execute(
            "SELECT token_hash, expires_at FROM email_change_proofs WHERE id = ?", (request.id,)
        ).fetchone()
        assert row["token_hash"] is None
        assert row["expires_at"] == request.expires_at.isoformat()


@pytest.mark.parametrize(
    "refusal",
    [
        "foreign",
        "ended",
        "expired",
        "password",
        "revision",
        "email",
        "disabled",
        "deleted",
        "cancelled",
        "deadline",
        "reset-token",
    ],
)
def test_confirmation_checks_ownership_and_live_session_atomically(
    tmp_path: Path, refusal: str
) -> None:
    path, clock, h, store, expected, session = setup(tmp_path)
    request = store.request(expected, "new@example.test", session.token)
    prepared = store.prepare(request.id)
    assert prepared
    token = prepared.token
    if refusal == "foreign":
        other_expected = h.changes.current(FIRST.id)
        assert other_expected is not None
        expected = other_expected
    elif refusal == "ended":
        h.sessions.end(session.token)
    elif refusal == "expired":
        with transaction(path) as connection:
            connection.execute(
                "UPDATE user_sessions SET expires_at = ?", (clock.now().isoformat(),)
            )
    elif refusal in ("password", "revision", "email"):
        expected = {
            "password": replace(expected, password_hash="wrong"),
            "revision": replace(expected, revision=99),
            "email": replace(expected, email="wrong@example.test"),
        }[refusal]
    elif refusal == "disabled":
        from calendar_sync.domain.access import UserState

        h.users.set_state(SECOND.id, UserState.DISABLED)
    elif refusal == "deleted":
        h.users.delete(SECOND.id)
    elif refusal == "cancelled":
        store.cancel(SECOND.id, request.id)
    elif refusal == "deadline":
        clock.moment = request.expires_at
    else:
        token = h.links.issue(SECOND.id, FIRST.id, clock.now()).token
    before = h.users.get(SECOND.id)
    assert expected
    assert store.confirm(expected, token, session.token) is None
    assert h.users.get(SECOND.id) == before


def test_confirmation_keeps_only_confirming_session_and_revokes_resets(tmp_path: Path) -> None:
    _path, clock, h, store, expected, session = setup(tmp_path)
    other = h.sessions.start(SECOND.id, expected.password_hash, expected.email, 0)
    reset = h.links.issue(SECOND.id, FIRST.id, clock.now())
    request = store.request(expected, "new@example.test", session.token)
    prepared = store.prepare(request.id)
    assert prepared
    assert other
    result = store.confirm(expected, prepared.token, session.token)
    assert result
    assert result.previous_email == SECOND.email
    changed = h.users.get(SECOND.id)
    credential = h.changes.current(SECOND.id)
    assert changed is not None
    assert credential is not None
    assert changed.email == "new@example.test"
    assert credential.revision == 1
    assert h.sessions.user_of(session.token) == SECOND.id
    assert h.sessions.user_of(other.token) is None
    assert h.links.owner(reset.token, clock.now()) is None
    assert store.confirm(expected, prepared.token, session.token) is None


def test_direct_change_requires_pending_cancel(tmp_path: Path) -> None:
    _path, _clock, h, store, expected, session = setup(tmp_path)
    request = store.request(expected, "new@example.test", session.token)
    with pytest.raises(EmailChangeUnavailable):
        h.changes.change_email(expected, "direct@example.test")
    store.cancel(SECOND.id, request.id)
    assert h.changes.change_email(expected, "direct@example.test")


@pytest.mark.parametrize("first", ["reset", "confirm", "password", "email-aba", "disable-aba"])
def test_email_change_reset_password_and_disable_races(tmp_path: Path, first: str) -> None:
    from calendar_sync.domain.access import UserState

    _path, clock, h, store, expected, session = setup(tmp_path)
    request = store.request(expected, "new@example.test", session.token)
    prepared = store.prepare(request.id)
    assert prepared
    reset = h.links.issue(SECOND.id, FIRST.id, clock.now())
    if first == "confirm":
        assert store.confirm(expected, prepared.token, session.token)
        assert h.links.reset(reset.token, "reset-hash") is None
        return
    if first == "reset":
        assert h.links.reset(reset.token, "reset-hash") == SECOND.id
    elif first == "password":
        assert h.changes.change_password(expected, "new-hash", session.token)
    elif first == "email-aba":
        h.users.set_email(SECOND.id, "away@example.test")
        h.users.set_email(SECOND.id, SECOND.email or "")
    else:
        h.users.set_state(SECOND.id, UserState.DISABLED)
        h.users.set_state(SECOND.id, UserState.ACTIVE)
    assert store.pending(SECOND.id) is None
    assert not store.check(SECOND.id, prepared.token)
    assert store.confirm(expected, prepared.token, session.token) is None


def test_email_change_uniqueness_race_is_neutral(tmp_path: Path) -> None:
    _path, clock, h, store, expected, session = setup(tmp_path)
    request = store.request(expected, "shared@example.test", session.token)
    proof = store.prepare(request.id)
    other = h.changes.current(FIRST.id)
    assert other
    other_session = h.sessions.start(other.user_id, other.password_hash, other.email, 0)
    assert other_session
    clock.moment += timedelta(minutes=1)
    other_request = store.request(other, "shared@example.test", other_session.token)
    other_proof = store.prepare(other_request.id)
    assert proof
    assert other_proof
    assert store.confirm(expected, proof.token, session.token)
    with pytest.raises(EmailChangeUnavailable):
        store.confirm(other, other_proof.token, other_session.token)
    assert h.changes.current(FIRST.id) == other
    assert h.sessions.user_of(other_session.token) == FIRST.id
    assert store.check(FIRST.id, other_proof.token)
    clock.moment += timedelta(minutes=1)
    assert store.request(other, "shared@example.test", other_session.token)


def test_confirmation_failure_rolls_back_proof_credential_and_sessions(tmp_path: Path) -> None:
    from calendar_sync.application.identity.email_change_admission import (
        EmailChangeStorageUnavailable,
    )

    path, _clock, h, store, expected, session = setup(tmp_path)
    request = store.request(expected, "new@example.test", session.token)
    prepared = store.prepare(request.id)
    assert prepared
    other = h.sessions.start(expected.user_id, expected.password_hash, expected.email, 0)
    assert other
    with transaction(path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_session_deletion BEFORE DELETE ON user_sessions "
            "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"
        )
    with pytest.raises(EmailChangeStorageUnavailable):
        store.confirm(expected, prepared.token, session.token)
    assert h.changes.current(SECOND.id) == expected
    assert store.check(SECOND.id, prepared.token)
    assert h.sessions.user_of(other.token) == SECOND.id


def test_email_change_expiry_is_read_after_lock_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3
    from collections.abc import Iterator
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager
    from threading import Event

    from calendar_sync.infrastructure.persistence import email_change_records

    path, clock, h, store, expected, session = setup(tmp_path)
    request = store.request(expected, "new@example.test", session.token)
    prepared = store.prepare(request.id)
    assert prepared
    waiting = Event()

    @contextmanager
    def observed(path: Path, *, timeout: float = 5.0) -> Iterator[sqlite3.Connection]:
        with transaction(path, timeout=timeout) as connection:
            connection.set_trace_callback(
                lambda sql: waiting.set() if sql == "BEGIN IMMEDIATE" else None
            )
            yield connection

    monkeypatch.setattr(email_change_records, "transaction", observed)
    with ThreadPoolExecutor() as pool:
        with transaction(path) as locked:
            locked.execute("BEGIN IMMEDIATE")
            future = pool.submit(store.confirm, expected, prepared.token, session.token)
            assert waiting.wait(1)
            clock.moment = request.expires_at
        assert future.result(1) is None
    assert h.changes.current(SECOND.id) == expected


def test_proofs_keyless_completion_purge_and_user_cascade(tmp_path: Path) -> None:
    from calendar_sync.application.identity.email_change_admission import (
        EmailChangeStorageUnavailable,
    )

    path, clock, h, store, expected, session = setup(tmp_path)
    request = store.request(expected, "new@example.test", session.token)
    prepared = store.prepare(request.id)
    assert prepared
    keyless = SqliteEmailChangeProofs(path, SequentialIds(), clock)
    with pytest.raises(EmailChangeStorageUnavailable):
        keyless.request(expected, "blocked@example.test", session.token)
    assert keyless.check(SECOND.id, prepared.token)
    assert keyless.purge(clock.now() + timedelta(days=10), 500) == 0
    assert keyless.confirm(expected, prepared.token, session.token)
    # Completion opportunistically removes consumed proof history.
    assert keyless.purge(clock.now(), 1) == 0
    current = h.changes.current(SECOND.id)
    assert current
    live = store.request(current, "another@example.test", session.token)
    assert store.pending(SECOND.id) == live
    h.users.delete(SECOND.id)
    with transaction(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM email_change_attempts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM email_change_proofs").fetchone()[0] == 0


@pytest.mark.parametrize("version", [0, 36])
def test_email_change_migration_upgrade_restart_and_preservation(
    tmp_path: Path, version: int
) -> None:
    from calendar_sync.infrastructure.persistence.migrations import initialize_database
    from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
    from tests.adapters.test_user_migration import database_at_version

    path = tmp_path / "upgrade.db"
    if version:
        database_at_version(path, version)
        SqliteUserDirectory(path).add(FIRST, "preserved-hash")
    initialize_database(path)
    initialize_database(path)
    with transaction(path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 38
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        assert not connection.execute("SELECT * FROM email_change_proofs").fetchall()
    if version:
        assert SqliteUserDirectory(path).get(FIRST.id) == FIRST
        assert SqliteUserDirectory(path).password_hash(FIRST.id) == "preserved-hash"


def test_email_change_migration_failure_rolls_back_all_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    from calendar_sync.infrastructure.persistence import migrations
    from tests.adapters.test_user_migration import database_at_version

    path = tmp_path / "rollback.db"
    database_at_version(path, 36)
    with transaction(path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_migration BEFORE INSERT ON schema_migrations "
            "WHEN NEW.version = 37 BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        migrations.initialize_database(path)
    with transaction(path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 36
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'email_change%'"
        ).fetchall()
        connection.execute("DROP TRIGGER fail_migration")
    migrations.initialize_database(path)


def test_proof_lock_failure_changes_nothing(tmp_path: Path) -> None:
    import time

    from calendar_sync.application.identity.email_change_admission import (
        EmailChangeStorageUnavailable,
    )

    path, _clock, _h, store, expected, session = setup(tmp_path)
    with transaction(path) as locked:
        locked.execute("BEGIN IMMEDIATE")
        start = time.monotonic()
        with pytest.raises(EmailChangeStorageUnavailable):
            store.request(expected, "new@example.test", session.token)
        assert time.monotonic() - start < 0.5
    assert store.pending(expected.user_id) is None
    with transaction(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM email_change_attempts").fetchone()[0] == 0


def test_proof_purge_batch_preserves_live_request(tmp_path: Path) -> None:
    path, clock, _h, store, expected, session = setup(tmp_path)
    pending = store.request(expected, "live@example.test", session.token)
    with transaction(path) as connection:
        connection.executemany(
            "INSERT INTO email_change_proofs(id, user_id, proposed_email, "
            "credential_revision, created_at, expires_at) VALUES (?, ?, ?, 0, ?, ?)",
            [
                (
                    f"expired-{i}",
                    SECOND.id.value,
                    "old@example.test",
                    clock.now().isoformat(),
                    clock.now().isoformat(),
                )
                for i in range(600)
            ],
        )
    assert store.purge(clock.now(), 900) == 500
    assert store.purge(clock.now(), 500) == 100
    assert store.pending(SECOND.id) == pending


def test_request_rollback_keeps_previous_proof_and_allowance(tmp_path: Path) -> None:
    from calendar_sync.application.identity.email_change_admission import (
        EmailChangeStorageUnavailable,
    )

    path, _clock, _h, store, expected, session = setup(tmp_path)
    pending = store.request(expected, "first@example.test", session.token)
    with transaction(path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_new_proof BEFORE INSERT ON email_change_proofs "
            "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"
        )
    with pytest.raises(EmailChangeStorageUnavailable):
        store.request(expected, "second@example.test", session.token)
    assert store.pending(SECOND.id) == pending
    with transaction(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM email_change_attempts").fetchone()[0] == 1


def test_proof_cleanup_failure_preserves_committed_request_and_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from calendar_sync.application.identity.email_change_admission import (
        EmailChangeStorageUnavailable,
    )

    _path, _clock, h, store, expected, session = setup(tmp_path)

    def failed(*args: object) -> int:
        raise EmailChangeStorageUnavailable

    monkeypatch.setattr(store, "purge", failed)
    request = store.request(expected, "new@example.test", session.token)
    assert store.pending(SECOND.id) == request
    prepared = store.prepare(request.id)
    assert prepared
    assert store.confirm(expected, prepared.token, session.token)
    assert not store.check(SECOND.id, prepared.token)
    current = h.changes.current(SECOND.id)
    assert current
    assert current.email == "new@example.test"


@pytest.mark.parametrize("change", ["session", "revision", "disabled", "deadline"])
def test_preparation_and_requests_refuse_stale_facts(tmp_path: Path, change: str) -> None:
    from calendar_sync.domain.access import UserState

    _path, clock, h, store, expected, session = setup(tmp_path)
    request = store.request(expected, "new@example.test", session.token)
    if change == "session":
        h.sessions.end(session.token)
        with pytest.raises(EmailChangeUnavailable):
            store.request(expected, "second@example.test", session.token)
        return
    if change == "revision":
        h.users.set_password_hash(SECOND.id, "changed-hash")
    elif change == "disabled":
        h.users.set_state(SECOND.id, UserState.DISABLED)
    else:
        clock.moment = request.expires_at
    assert store.pending(SECOND.id) is None
    assert store.prepare(request.id) is None
    if change != "deadline":
        with pytest.raises(EmailChangeUnavailable):
            store.request(expected, "second@example.test", session.token)
