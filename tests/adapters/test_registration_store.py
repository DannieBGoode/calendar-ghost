"""Verified admission commits proof, policy and User checks under one short lock."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest

from calendar_sync.application.identity.registration_ports import (
    InvitationVerificationRequired,
    RegistrationStorageUnavailable,
    RegistrationUnavailable,
)
from calendar_sync.domain.access import RegistrationPolicy, Role, User, UserState
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.registration import (
    SqliteInvitations,
    SqliteRegistrationSettings,
)
from calendar_sync.infrastructure.persistence.registration_proofs import SqliteRegistrationProofs
from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
from calendar_sync.infrastructure.security import token_hash
from tests.adapters.test_users_store import FIRST, NOW, SECOND, MovableClock


class RandomIds:
    def new(self) -> str:
        return str(uuid4())


def registration(
    tmp_path: Path,
) -> tuple[
    Path, MovableClock, SqliteUserDirectory, SqliteRegistrationSettings, SqliteRegistrationProofs
]:
    database = tmp_path / "registration.db"
    initialize_database(database)
    users = SqliteUserDirectory(database)
    users.add(FIRST, "existing-hash")
    clock = MovableClock(NOW)
    settings = SqliteRegistrationSettings(database, clock)
    with transaction(database) as connection:
        connection.execute(
            "UPDATE identity_email_readiness SET fingerprint = 'current', tested_at = ?",
            (NOW.isoformat(),),
        )
    settings.set_policy(RegistrationPolicy.OPEN, actor=FIRST.id, fingerprint="current")
    return database, clock, users, settings, SqliteRegistrationProofs(database, RandomIds(), clock)


def unchanged(database: Path) -> tuple[int, int]:
    with transaction(database) as connection:
        users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        sessions = connection.execute("SELECT COUNT(*) FROM user_sessions").fetchone()[0]
        return users, sessions


def test_hash_only_proofs_do_not_reserve_email(tmp_path: Path) -> None:
    database, _, users, _, proofs = registration(tmp_path)
    first = proofs.issue(" New@Example.test ", None, "current")
    second = proofs.issue("new@example.test", None, "current")
    assert first
    assert second
    assert first.link.token != second.link.token
    assert first.link.token not in repr(first)
    assert first.recipient not in repr(first)
    with transaction(database) as connection:
        rows = connection.execute("SELECT * FROM registration_proofs").fetchall()
        assert len(rows) == 2
        assert rows[0]["token_hash"] == token_hash(first.link.token)
        assert first.link.token not in repr([tuple(row) for row in rows])
    users.add(replace(SECOND, email=first.recipient), "chosen-elsewhere")
    assert proofs.check(first.link.token, "current") is None
    assert proofs.complete(second.link.token, "new-hash", "current") is None
    assert unchanged(database) == (2, 0)


def test_sibling_completion_race_creates_one_user(tmp_path: Path) -> None:
    database, _, users, _, proofs = registration(tmp_path)
    siblings = [proofs.issue("new@example.test", None, "current") for _ in range(2)]
    assert all(siblings)
    with ThreadPoolExecutor(max_workers=2) as pool:
        joined = list(
            pool.map(
                lambda proof: proofs.complete(proof.link.token, "new-hash", "current"), siblings
            )
        )
    admitted = [user for user in joined if user]
    assert len(admitted) == 1
    user = admitted[0]
    assert (user.role, user.state, user.plan) == (Role.USER, UserState.ACTIVE, None)
    assert users.password_hash(user.id) == "new-hash"
    with transaction(database) as connection:
        assert (
            connection.execute(
                "SELECT email_verified FROM users WHERE id=?", (user.id.value,)
            ).fetchone()[0]
            == 1
        )
    with transaction(database) as connection:
        assert (
            connection.execute(
                "SELECT credential_revision FROM users WHERE id = ?", (user.id.value,)
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM registration_proofs WHERE used_at IS NOT NULL"
            ).fetchone()[0]
            == 2
        )
    assert unchanged(database) == (2, 0)


def test_existing_disabled_and_raced_email_unchanged(tmp_path: Path) -> None:
    database, _, users, _, proofs = registration(tmp_path)
    users.add(replace(SECOND, state=UserState.DISABLED), "disabled-hash")
    assert proofs.issue(SECOND.email or "", None, "current") is None
    pending = proofs.issue("new@example.test", None, "current")
    assert pending
    users.set_email(SECOND.id, pending.recipient)
    assert proofs.complete(pending.link.token, "replacement", "current") is None
    assert users.password_hash(SECOND.id) == "disabled-hash"
    assert unchanged(database) == (2, 0)


def test_invitation_not_consumed_until_completion(tmp_path: Path) -> None:
    database, clock, _, settings, proofs = registration(tmp_path)
    invitations = SqliteInvitations(database, RandomIds(), clock)
    invitation = invitations.issue(FIRST.id, NOW)
    assert invitation
    pending = proofs.issue("new@example.test", invitation.token, "current")
    assert pending
    assert invitations.usable(invitation.token, NOW)
    settings.set_policy(RegistrationPolicy.INVITATION_ONLY, actor=FIRST.id, fingerprint=None)
    assert proofs.check(pending.link.token, None)
    user = proofs.complete(pending.link.token, "hash", None)
    assert user
    assert not invitations.usable(invitation.token, NOW)
    assert proofs.complete(pending.link.token, "other", None) is None
    assert unchanged(database) == (2, 0)


@pytest.mark.parametrize("refusal", ["revoked", "expired", "direct", "deleted"])
def test_invitation_revocation_expiry_and_competing_acceptance(
    tmp_path: Path, refusal: str
) -> None:
    database, clock, _, settings, proofs = registration(tmp_path)
    invitations = SqliteInvitations(database, RandomIds(), clock)
    invitation = invitations.issue(FIRST.id, NOW)
    assert invitation
    clock.moment = NOW + timedelta(days=6, hours=23)
    pending = proofs.issue("new@example.test", invitation.token, "current")
    assert pending
    assert pending.link.expires_at == invitation.expires_at
    if refusal == "revoked":
        assert invitations.revoke(invitation.id, clock.now())
    elif refusal == "expired":
        clock.moment = invitation.expires_at
    elif refusal == "deleted":
        with transaction(database) as connection:
            connection.execute("DELETE FROM invitations WHERE id = ?", (invitation.id,))
            assert connection.execute("SELECT COUNT(*) FROM registration_proofs").fetchone()[0] == 0
    else:
        settings.set_policy(RegistrationPolicy.INVITATION_ONLY, actor=FIRST.id, fingerprint=None)
        assert invitations.accept(invitation.token, "other@example.test", "direct-hash")
    assert proofs.check(pending.link.token, "current") is None
    assert proofs.complete(pending.link.token, "hash", "current") is None
    assert unchanged(database) == (2 if refusal == "direct" else 1, 0)


def test_policy_closure_reopen_and_return_to_setup(tmp_path: Path) -> None:
    database, clock, _, settings, proofs = registration(tmp_path)
    invitations = SqliteInvitations(database, RandomIds(), clock)
    invitation = invitations.issue(FIRST.id, NOW)
    assert invitation
    public = proofs.issue("public@example.test", None, "current")
    bound = proofs.issue("bound@example.test", invitation.token, "current")
    assert public
    assert bound
    settings.set_policy(RegistrationPolicy.INVITATION_ONLY, actor=FIRST.id, fingerprint=None)
    assert proofs.check(public.link.token, "current") is None
    assert proofs.check(bound.link.token, None)
    settings.set_policy(RegistrationPolicy.OPEN, actor=FIRST.id, fingerprint="current")
    assert proofs.check(public.link.token, "current") is None
    settings.set_policy(RegistrationPolicy.ONLY_ME, actor=FIRST.id, fingerprint=None)
    settings.set_policy(RegistrationPolicy.OPEN, actor=FIRST.id, fingerprint="current")
    assert proofs.complete(bound.link.token, "hash", "current") is None
    fresh = proofs.issue("fresh@example.test", None, "current")
    assert fresh
    settings.return_to_setup(NOW)
    assert proofs.complete(fresh.link.token, "hash", "current") is None
    with transaction(database) as connection:
        assert tuple(
            connection.execute(
                "SELECT fingerprint, tested_at, generation FROM identity_email_readiness"
            ).fetchone()
        ) == (None, None, 1)
    assert unchanged(database) == (1, 0)


@pytest.mark.parametrize("change", ["expiry", "readiness", "closure"])
def test_expiry_and_readiness_rechecked_after_hashing_and_lock_wait(
    tmp_path: Path, change: str
) -> None:
    database, clock, _, settings, proofs = registration(tmp_path)
    pending = proofs.issue("new@example.test", None, "current")
    assert pending
    assert proofs.check(pending.link.token, "current")
    # These changes represent another request landing while the caller hashes its password.
    if change == "expiry":
        clock.moment = pending.link.expires_at
    elif change == "readiness":
        with transaction(database) as connection:
            connection.execute("UPDATE identity_email_readiness SET fingerprint = 'changed'")
        with pytest.raises(RegistrationUnavailable):
            proofs.check(pending.link.token, "current")
        with pytest.raises(RegistrationUnavailable):
            proofs.complete(pending.link.token, "hashed-outside-lock", "current")
        with transaction(database) as connection:
            connection.execute("UPDATE identity_email_readiness SET fingerprint = 'current'")
        assert proofs.check(pending.link.token, "current")
        assert unchanged(database) == (1, 0)
        return
    else:
        settings.set_policy(RegistrationPolicy.INVITATION_ONLY, actor=FIRST.id, fingerprint=None)
    assert proofs.complete(pending.link.token, "hashed-outside-lock", "current") is None
    assert unchanged(database) == (1, 0)


def test_direct_invitation_under_open_requires_verification(tmp_path: Path) -> None:
    database, clock, _, _, _ = registration(tmp_path)
    invitations = SqliteInvitations(database, RandomIds(), clock)
    invitation = invitations.issue(FIRST.id, NOW)
    assert invitation
    with pytest.raises(InvitationVerificationRequired):
        invitations.accept(invitation.token, "new@example.test", "hash")
    assert unchanged(database) == (1, 0)


def test_completion_reads_fresh_time_after_the_write_lock(tmp_path: Path) -> None:
    database, clock, _, _, proofs = registration(tmp_path)
    pending = proofs.issue("new@example.test", None, "current")
    assert pending
    started = Event()

    def finishing() -> User | None:
        started.set()
        return proofs.complete(pending.link.token, "hash", "current")

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction(database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            future = pool.submit(finishing)
            assert started.wait(1)
            clock.moment = pending.link.expires_at
        assert future.result() is None
    assert unchanged(database) == (1, 0)


def test_checks_do_not_purge_and_cleanup_is_bounded(tmp_path: Path) -> None:
    database, clock, _, _, proofs = registration(tmp_path)
    pending = proofs.issue("new@example.test", None, "current")
    sibling = proofs.issue("new@example.test", None, "current")
    assert pending
    assert sibling
    clock.moment = pending.link.expires_at
    assert proofs.check(pending.link.token, "current") is None
    with transaction(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM registration_proofs").fetchone()[0] == 2
    assert proofs.purge(clock.now(), 1) == 1
    assert proofs.purge(clock.now(), 5000) == 1
    assert proofs.purge(clock.now(), 0) == 0


def test_storage_contention_fails_closed_without_mutation(tmp_path: Path) -> None:
    database, _, _, _, proofs = registration(tmp_path)
    pending = proofs.issue("new@example.test", None, "current")
    assert pending
    with transaction(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(RegistrationStorageUnavailable):
            proofs.complete(pending.link.token, "hash", "current")
    assert proofs.check(pending.link.token, "current")
    assert unchanged(database) == (1, 0)


def test_cross_purpose_and_empty_installation_never_admit(tmp_path: Path) -> None:
    database, clock, users, _, proofs = registration(tmp_path)
    invitations = SqliteInvitations(database, RandomIds(), clock)
    invitation = invitations.issue(FIRST.id, NOW)
    assert invitation
    assert proofs.check(invitation.token, "current") is None
    assert proofs.complete(invitation.token, "hash", "current") is None
    pending = proofs.issue("new@example.test", None, "current")
    assert pending
    users.delete(FIRST.id)
    assert proofs.check(pending.link.token, "current") is None
    assert proofs.complete(pending.link.token, "hash", "current") is None
    assert proofs.issue("another@example.test", None, "current") is None
    assert unchanged(database) == (0, 0)


@pytest.mark.parametrize("fingerprint", ["current", "stale"])
def test_queued_invitation_request_cannot_issue_after_open_closes(
    tmp_path: Path, fingerprint: str
) -> None:
    database, clock, _, settings, proofs = registration(tmp_path)
    invitations = SqliteInvitations(database, RandomIds(), clock)
    invitation = invitations.issue(FIRST.id, NOW)
    assert invitation
    # The worker receives this queued request only after the administrator closes Open.
    queued_email, queued_invitation = "new@example.test", invitation.token
    settings.set_policy(RegistrationPolicy.INVITATION_ONLY, actor=FIRST.id, fingerprint=None)
    with transaction(database) as connection:
        before = {
            table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
            for table in ("registration_proofs", "invitations", "users", "user_sessions")
        }
    assert proofs.issue(queued_email, queued_invitation, fingerprint) is None
    with transaction(database) as connection:
        after = {
            table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
            for table in before
        }
    assert after == before
