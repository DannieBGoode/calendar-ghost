"""Atomic provider identity ownership, admission and session changes."""

import secrets
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest

from calendar_sync.application.identity.provider_links import ConfirmProviderLink
from calendar_sync.application.identity.provider_sign_in_ports import (
    AdmissionCommand,
    BeginIntent,
    BrowserProof,
    InvitationIntent,
    ProviderCallback,
    ProviderSignInRefused,
)
from calendar_sync.domain.access import UserId
from calendar_sync.domain.provider_identity import ProviderClaims, ProviderIdentityKey
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.provider_admission import SqliteProviderAdmission
from calendar_sync.infrastructure.persistence.provider_flows import SqliteProviderFlows
from calendar_sync.infrastructure.security import CredentialCipher, token_hash
from tests.fakes.oidc import NOW, FixedClock


@dataclass
class AdmissionHarness:
    path: Path
    clock: FixedClock
    flows: SqliteProviderFlows
    admission: SqliteProviderAdmission

    def command(
        self,
        email: str | None = "new@example.test",
        verified: bool = True,
        invitation: InvitationIntent | None = None,
    ) -> tuple[BrowserProof, AdmissionCommand]:
        browser, state = BrowserProof(secrets.token_urlsafe(32)), secrets.token_urlsafe(32)
        self.flows.begin(BeginIntent("google", browser, invitation), state)
        flow = self.flows.consume(ProviderCallback("google", state, "code", browser))
        assert flow is not None
        claims = ProviderClaims(
            ProviderIdentityKey("https://issuer.test", "subject"), email, verified
        )
        return browser, AdmissionCommand(claims, flow, None)


@pytest.fixture
def admission(tmp_path: Path) -> AdmissionHarness:
    path = tmp_path / "admission.db"
    initialize_database(path)
    clock = FixedClock()
    flows = SqliteProviderFlows(path, CredentialCipher.generate_key(), clock, {"google": "config"})
    with transaction(path) as connection:
        connection.execute(
            "INSERT INTO users(id,email,password_hash,role,state,created_at) "
            "VALUES ('existing','existing@example.test','hash','user','active',?)",
            (NOW.isoformat(),),
        )
        connection.execute("INSERT INTO provider_sign_in_settings VALUES ('google',1)")
        connection.execute("UPDATE installation_settings SET registration_policy = 'open'")
        connection.execute(
            "UPDATE identity_email_readiness SET fingerprint='ready',tested_at=?",
            (NOW.isoformat(),),
        )
    writer = SqliteProviderAdmission(path, clock, flows, "ready")
    return AdmissionHarness(path, clock, flows, writer)


def test_existing_identity_ignores_changed_email(admission: AdmissionHarness) -> None:
    _, command = admission.command("existing@example.test")
    first = admission.admission.complete(command)
    _, changed = admission.command("changed@example.test", False)
    result = admission.admission.complete(changed)
    assert first.session is not None
    assert result.session is not None
    assert result.session.user_id == UserId("existing")
    assert result.session.token != first.session.token


@pytest.mark.parametrize("state", ["active", "disabled"])
def test_verified_email_auto_links_only_active_owner(
    admission: AdmissionHarness, state: str
) -> None:
    with transaction(admission.path) as connection:
        connection.execute("UPDATE users SET state=?", (state,))
    _, command = admission.command("existing@example.test")
    if state == "disabled":
        with pytest.raises(ProviderSignInRefused):
            admission.admission.complete(command)
    else:
        result = admission.admission.complete(command)
        assert result.session is not None
        assert result.session.user_id == UserId("existing")


@pytest.mark.parametrize("email", [None, "new@example.test", "existing@example.test"])
def test_unverified_flow_is_generic_for_unknown_and_existing_email(
    admission: AdmissionHarness, email: str | None
) -> None:
    browser, command = admission.command(email, False)
    result = admission.admission.complete(command)
    assert result.session is None
    assert result.pending is not None
    assert admission.flows.pending(browser, result.pending.token) == result.pending
    with transaction(admission.path) as connection:
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM provider_identities").fetchone()[0] == 0


@pytest.mark.parametrize("policy", ["only_me", "invitation_only", "open"])
@pytest.mark.parametrize("invitation", ["none", "matching", "wrong-email", "expired", "revoked"])
@pytest.mark.parametrize("ready", [False, True])
def test_invitation_email_and_policy_table(
    admission: AdmissionHarness, policy: str, invitation: str, ready: bool
) -> None:
    bound = None
    with transaction(admission.path) as connection:
        connection.execute("UPDATE installation_settings SET registration_policy=?", (policy,))
        if not ready:
            connection.execute(
                "UPDATE identity_email_readiness SET tested_at=NULL,fingerprint=NULL"
            )
        if invitation != "none":
            expiry = NOW + timedelta(days=-1 if invitation == "expired" else 1)
            connection.execute(
                "INSERT INTO "
                "invitations(id,token_hash,created_by,created_at,expires_at,revoked_at) "
                "VALUES ('invite',?,'existing',?,?,?)",
                (
                    token_hash("invitation"),
                    NOW.isoformat(),
                    expiry.isoformat(),
                    NOW.isoformat() if invitation == "revoked" else None,
                ),
            )
            bound = InvitationIntent(
                "invitation",
                "wrong@example.test" if invitation == "wrong-email" else "new@example.test",
            )
    _, command = admission.command(invitation=bound)
    allowed = (ready if policy == "open" else invitation == "matching") and invitation in {
        "none",
        "matching",
    }
    if not allowed:
        with pytest.raises(ProviderSignInRefused):
            admission.admission.complete(command)
        return
    result = admission.admission.complete(command)
    assert result.session is not None
    with transaction(admission.path) as connection:
        row = connection.execute(
            "SELECT role,password_hash,plan_key FROM users WHERE id=?",
            (result.session.user_id.value,),
        ).fetchone()
        assert tuple(row) == ("user", None, None)
        if bound:
            assert (
                connection.execute("SELECT accepted_by FROM invitations").fetchone()[0]
                == result.session.user_id.value
            )


def test_provider_sign_in_rotates_session(admission: AdmissionHarness) -> None:
    browser, command = admission.command()
    result = admission.admission.complete(command)
    assert result.session is not None
    assert result.session.token != browser.value
    assert result.session.expires_at == NOW + timedelta(days=7)
    with pytest.raises(ProviderSignInRefused):
        admission.admission.complete(command)


@pytest.mark.parametrize(
    "mutation", ["disabled", "provider", "configuration", "expired", "cancelled"]
)
def test_admission_rechecks_current_facts(admission: AdmissionHarness, mutation: str) -> None:
    browser, command = admission.command("existing@example.test")
    if mutation == "configuration":
        admission.flows.fingerprints["google"] = "changed"
    elif mutation == "expired":
        admission.clock.value += timedelta(minutes=10)
    elif mutation == "cancelled":
        admission.flows.cancel(browser)
    else:
        with transaction(admission.path) as connection:
            if mutation == "disabled":
                connection.execute("UPDATE users SET state='disabled'")
            else:
                connection.execute("UPDATE provider_sign_in_settings SET enabled=0")
    with pytest.raises(ProviderSignInRefused):
        admission.admission.complete(command)
    with transaction(admission.path) as connection:
        assert connection.execute("SELECT count(*) FROM provider_identities").fetchone()[0] == 0


def test_admission_races(admission: AdmissionHarness) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    _, first = admission.command()
    _, second = admission.command()
    barrier = Barrier(2)

    def complete(command: AdmissionCommand) -> bool:
        barrier.wait(timeout=2)
        try:
            return admission.admission.complete(command).session is not None
        except ProviderSignInRefused:
            return False

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(complete, (first, second)))
    assert any(results)
    with transaction(admission.path) as connection:
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM provider_identities").fetchone()[0] == 1


def test_setup_revokes_flows(admission: AdmissionHarness) -> None:
    from calendar_sync.infrastructure.persistence.registration import SqliteRegistrationSettings

    _, command = admission.command()
    SqliteRegistrationSettings(admission.path, admission.clock).return_to_setup(NOW)
    with pytest.raises(ProviderSignInRefused):
        admission.admission.complete(command)
    with transaction(admission.path) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM provider_sign_in_settings WHERE enabled=1"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT count(*) FROM provider_flows").fetchone()[0] == 0


def test_final_failure_rolls_back_user_identity_and_invitation(admission: AdmissionHarness) -> None:
    from calendar_sync.application.identity.provider_sign_in_ports import ProviderSignInUnavailable

    with transaction(admission.path) as connection:
        connection.execute(
            "CREATE TRIGGER refuse_new_session BEFORE INSERT ON "
            "user_sessions BEGIN SELECT RAISE(ABORT,'synthetic'); END"
        )
        connection.execute(
            "INSERT INTO invitations(id,token_hash,created_by,created_at,expires_at) "
            "VALUES ('invite',?,'existing',?,?)",
            (token_hash("invitation"), NOW.isoformat(), (NOW + timedelta(days=1)).isoformat()),
        )
    _, command = admission.command(invitation=InvitationIntent("invitation", "new@example.test"))
    with pytest.raises(ProviderSignInUnavailable):
        admission.admission.complete(command)
    with transaction(admission.path) as connection:
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM provider_identities").fetchone()[0] == 0

        assert connection.execute("SELECT accepted_at FROM invitations").fetchone()[0] is None


def confirmation(admission: AdmissionHarness) -> ConfirmProviderLink:
    from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory

    passwords, throttle = Mock(), Mock()
    passwords.hash.return_value = "decoy"
    passwords.verify.side_effect = lambda password, hashed: (
        password == "correct" and hashed == "hash"
    )
    throttle.wait.return_value = 0
    return ConfirmProviderLink(
        SqliteUserDirectory(admission.path, sign_in_timeout=0.1),
        passwords,
        throttle,
        admission.flows,
        admission.admission,
    )


def test_wrong_password_keeps_pending_link_usable(admission: AdmissionHarness) -> None:
    browser, command = admission.command("irrelevant@example.test", False)
    pending = admission.admission.complete(command).pending
    assert pending is not None
    confirm = confirmation(admission)
    with pytest.raises(ProviderSignInRefused):
        confirm.execute(browser, pending.token, "existing@example.test", "wrong", "client")
    assert admission.flows.pending(browser, pending.token) == pending
    session = confirm.execute(browser, pending.token, "existing@example.test", "correct", "client")
    assert session.user_id == UserId("existing")
    assert admission.flows.pending(browser, pending.token) is None


@pytest.mark.parametrize(
    "mutation", ["revision", "disabled", "email", "deleted", "cancelled", "provider"]
)
def test_password_confirmation_revision_race(admission: AdmissionHarness, mutation: str) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    browser, command = admission.command("untrusted@example.test", False)
    pending = admission.admission.complete(command).pending
    assert pending is not None
    confirm = confirmation(admission)
    barrier = Barrier(2)

    def verify(password: str, hashed: str) -> bool:
        barrier.wait(timeout=2)
        barrier.wait(timeout=2)
        return True

    cast(Mock, confirm.passwords).verify.side_effect = verify
    with ThreadPoolExecutor(1) as pool:
        task = pool.submit(
            confirm.execute, browser, pending.token, "existing@example.test", "correct", "client"
        )
        barrier.wait(timeout=2)
        # A separate connection acquires the write lock while password work is suspended.
        with transaction(admission.path, timeout=0.1) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if mutation == "revision":
                connection.execute(
                    "UPDATE users SET credential_revision=credential_revision+1,"
                    "password_hash='reset'"
                )
            elif mutation == "disabled":
                connection.execute("UPDATE users SET state='disabled'")
            elif mutation == "email":
                connection.execute("UPDATE users SET email='changed@example.test'")
            elif mutation == "deleted":
                connection.execute("DELETE FROM users")
            elif mutation == "provider":
                connection.execute("UPDATE provider_sign_in_settings SET enabled=0")
            else:
                connection.execute("DELETE FROM provider_pending_links")
        barrier.wait(timeout=2)
        with pytest.raises(ProviderSignInRefused):
            task.result(timeout=2)
    with transaction(admission.path) as connection:
        assert connection.execute("SELECT count(*) FROM provider_identities").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM user_sessions").fetchone()[0] == 0


@pytest.mark.parametrize("kind", ["unknown", "disabled", "wrong", "no-password"])
def test_confirmation_failures_share_neutral_error(admission: AdmissionHarness, kind: str) -> None:
    browser, command = admission.command(None, False)
    pending = admission.admission.complete(command).pending
    assert pending is not None
    if kind in {"disabled", "no-password"}:
        with transaction(admission.path) as connection:
            if kind == "disabled":
                connection.execute("UPDATE users SET state='disabled'")
            else:
                connection.execute("UPDATE users SET password_hash=NULL")
    confirm = confirmation(admission)
    with pytest.raises(ProviderSignInRefused, match="Provider sign-in could not be completed"):
        confirm.execute(
            browser,
            pending.token,
            "unknown@example.test" if kind == "unknown" else "existing@example.test",
            "wrong" if kind == "wrong" else "correct",
            "client",
        )
    cast(Mock, confirm.passwords).verify.assert_called_once()
    assert admission.flows.pending(browser, pending.token) == pending


def test_two_tabs_cannot_switch_users(admission: AdmissionHarness) -> None:
    browser, first = admission.command("existing@example.test")
    state = secrets.token_urlsafe(32)
    admission.flows.begin(BeginIntent("google", browser), state)
    flow = admission.flows.consume(ProviderCallback("google", state, "code", browser))
    assert flow is not None
    second = AdmissionCommand(
        ProviderClaims(
            ProviderIdentityKey("https://issuer.test", "other-subject"), "other@example.test", True
        ),
        flow,
        None,
    )
    assert admission.admission.complete(first).session is not None
    with pytest.raises(ProviderSignInRefused):
        admission.admission.complete(second)
    with transaction(admission.path) as connection:
        assert connection.execute("SELECT count(*) FROM user_sessions").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 1


@pytest.mark.parametrize("mutation", ["none", "session", "revision", "identity"])
def test_owned_link_never_switches_user(admission: AdmissionHarness, mutation: str) -> None:
    from calendar_sync.application.identity.provider_sign_in_ports import LinkOwner

    with transaction(admission.path) as connection:
        for token in ("current", "other"):
            connection.execute(
                "INSERT INTO user_sessions(token_hash,user_id,created_at,expires_at) "
                "VALUES (?,'existing',?,?)",
                (token_hash(token), NOW.isoformat(), (NOW + timedelta(days=1)).isoformat()),
            )
    owner = LinkOwner(UserId("existing"), token_hash("current"), 0)
    browser, state = BrowserProof(secrets.token_urlsafe(32)), secrets.token_urlsafe(32)
    admission.flows.begin(BeginIntent("google", browser, owner=owner), state)
    flow = admission.flows.consume(ProviderCallback("google", state, "code", browser, owner))
    assert flow is not None
    claims = ProviderClaims(
        ProviderIdentityKey("https://issuer.test", "subject"), "different@example.test", False
    )
    with transaction(admission.path) as connection:
        if mutation == "session":
            connection.execute(
                "DELETE FROM user_sessions WHERE token_hash=?", (owner.session_hash,)
            )
        elif mutation == "revision":
            connection.execute("UPDATE users SET credential_revision=1")
        elif mutation == "identity":
            connection.execute(
                "INSERT INTO users(id,email,role,state,created_at) "
                "VALUES ('foreign','foreign@example.test','user','active',?)",
                (NOW.isoformat(),),
            )
            connection.execute(
                "INSERT INTO provider_identities "
                "VALUES ('foreign','foreign','google','https://issuer.test','subject',?)",
                (NOW.isoformat(),),
            )
    command = AdmissionCommand(claims, flow, None)
    if mutation != "none":
        with pytest.raises(ProviderSignInRefused):
            admission.admission.complete(command)
        return
    result = admission.admission.complete(command)
    assert result.session is None
    assert result.pending is None
    with transaction(admission.path) as connection:
        assert (
            connection.execute("SELECT token_hash FROM user_sessions").fetchall()[0][0]
            == owner.session_hash
        )
        assert connection.execute("SELECT count(*) FROM user_sessions").fetchone()[0] == 1
        assert (
            connection.execute("SELECT user_id FROM provider_identities").fetchone()[0]
            == "existing"
        )
        assert connection.execute("SELECT credential_revision FROM users").fetchone()[0] == 1


def test_exchange_race_has_no_write_lock_and_cannot_resurrect_cancelled_flow(
    admission: AdmissionHarness,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from calendar_sync.application.identity.provider_sign_in import CompleteProviderSignIn

    browser, state = BrowserProof(secrets.token_urlsafe(32)), secrets.token_urlsafe(32)
    admission.flows.begin(BeginIntent("google", browser), state)
    barrier = Barrier(2)
    provider = Mock()

    def exchange(*args: str) -> ProviderClaims:
        barrier.wait(timeout=2)
        barrier.wait(timeout=2)
        return ProviderClaims(
            ProviderIdentityKey("https://issuer.test", "subject"), "new@example.test", True
        )

    provider.exchange.side_effect = exchange
    complete = CompleteProviderSignIn(
        {"google": provider}, admission.flows, Mock(), admission.admission
    )
    callback = ProviderCallback("google", state, "code", browser)
    with ThreadPoolExecutor(1) as pool:
        task = pool.submit(complete.execute, callback)
        barrier.wait(timeout=2)
        with transaction(admission.path, timeout=0.1) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM provider_flows")
        barrier.wait(timeout=2)
        with pytest.raises(ProviderSignInRefused):
            task.result(timeout=2)
    with transaction(admission.path) as connection:
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 1


def test_admission_consumes_email_siblings_and_invitation_atomically(
    admission: AdmissionHarness,
) -> None:
    browser, unverified = admission.command("new@example.test", False)
    pending = admission.admission.complete(unverified).pending
    assert pending is not None
    with transaction(admission.path) as connection:
        connection.execute(
            "INSERT INTO invitations(id,token_hash,created_by,created_at,expires_at) "
            "VALUES ('invite',?,'existing',?,?)",
            (token_hash("invitation"), NOW.isoformat(), (NOW + timedelta(days=1)).isoformat()),
        )
        connection.execute(
            "INSERT INTO registration_proofs(token_hash,email,created_at,expires_at) "
            "VALUES (?,'new@example.test',?,?)",
            (token_hash("registration"), NOW.isoformat(), (NOW + timedelta(days=1)).isoformat()),
        )
    _, verified = admission.command(invitation=InvitationIntent("invitation", "new@example.test"))
    assert admission.admission.complete(verified).session is not None
    assert admission.flows.pending(browser, pending.token) is None
    with transaction(admission.path) as connection:
        assert connection.execute("SELECT revoked_at FROM registration_proofs").fetchone()[0]
        assert connection.execute("SELECT accepted_at FROM invitations").fetchone()[0]


def test_pending_failure_restores_proof_with_identity_rollback(admission: AdmissionHarness) -> None:
    from calendar_sync.application.identity.provider_sign_in_ports import ProviderSignInUnavailable

    browser, command = admission.command(None, False)
    pending = admission.admission.complete(command).pending
    assert pending is not None
    confirm = confirmation(admission)
    with transaction(admission.path) as connection:
        connection.execute(
            "CREATE TRIGGER refuse_session BEFORE INSERT ON user_sessions "
            "BEGIN SELECT RAISE(ABORT,'synthetic'); END"
        )
    with pytest.raises(ProviderSignInUnavailable):
        confirm.execute(browser, pending.token, "existing@example.test", "correct", "client")
    assert admission.flows.pending(browser, pending.token) is not None
    with transaction(admission.path) as connection:
        assert connection.execute("SELECT count(*) FROM provider_identities").fetchone()[0] == 0


def test_admission_hashing_is_outside_write_lock(
    admission: AdmissionHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import calendar_sync.infrastructure.persistence.provider_admission as module

    _, command = admission.command()
    calls = []

    def checked_hash(value: str) -> str:
        with transaction(admission.path, timeout=0.1) as connection:
            connection.execute("BEGIN IMMEDIATE")
        calls.append(True)
        return token_hash(value)

    monkeypatch.setattr(module, "token_hash", checked_hash)
    assert admission.admission.complete(command).session is not None
    assert calls


def test_admission_waits_are_bounded(admission: AdmissionHarness) -> None:
    import time

    from calendar_sync.application.identity.provider_sign_in_ports import ProviderSignInUnavailable

    _, command = admission.command()
    with transaction(admission.path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        start = time.monotonic()
        with pytest.raises(ProviderSignInUnavailable):
            admission.admission.complete(command)
        assert time.monotonic() - start < 1


def test_parallel_confirmations_have_one_session_winner(admission: AdmissionHarness) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    browser, command = admission.command(None, False)
    pending = admission.admission.complete(command).pending
    assert pending is not None
    barrier = Barrier(2)
    confirm = confirmation(admission)

    def verify(password: str, hashed: str) -> bool:
        barrier.wait(timeout=2)
        return True

    cast(Mock, confirm.passwords).verify.side_effect = verify

    def attempt() -> bool:
        try:
            confirm.execute(browser, pending.token, "existing@example.test", "correct", "client")
        except ProviderSignInRefused:
            return False
        return True

    with ThreadPoolExecutor(2) as pool:
        first, second = pool.submit(attempt), pool.submit(attempt)
        assert sorted([first.result(timeout=2), second.result(timeout=2)]) == [False, True]
    with transaction(admission.path) as connection:
        assert connection.execute("SELECT count(*) FROM user_sessions").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM provider_identities").fetchone()[0] == 1
