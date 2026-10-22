"""SQLite flow ownership, single use, capacity, and sealed pending-password context."""

import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from calendar_sync.application.identity.provider_sign_in_ports import (
    BeginIntent,
    BoundInvitation,
    BrowserProof,
    InvitationIntent,
    LinkOwner,
    ProviderCallback,
    ProviderSignInRefused,
)
from calendar_sync.domain.access import UserId
from calendar_sync.domain.provider_identity import ProviderClaims, ProviderIdentityKey
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.provider_flows import SqliteProviderFlows
from calendar_sync.infrastructure.security import CredentialCipher, token_hash
from tests.fakes.oidc import NOW, FixedClock


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "flows.db"
    initialize_database(path)
    with transaction(path) as connection:
        connection.execute("INSERT INTO provider_sign_in_settings VALUES ('google',1)")
        for name in ("one", "two"):
            connection.execute(
                "INSERT INTO users(id, email, password_hash, role, state, created_at) "
                "VALUES (?, ?, 'hash', 'user', 'active', ?)",
                (name, f"{name}@example.test", NOW.isoformat()),
            )
            connection.execute(
                "INSERT INTO user_sessions(token_hash, user_id, created_at, "
                "expires_at) VALUES (?, ?, ?, ?)",
                (token_hash(name), name, NOW.isoformat(), (NOW + timedelta(days=1)).isoformat()),
            )
    return path


def flows(database: Path, clock: FixedClock | None = None) -> SqliteProviderFlows:
    return SqliteProviderFlows(
        database,
        CredentialCipher.generate_key(),
        clock or FixedClock(),
        {"google": "config", "microsoft": "other-config"},
    )


def owner(name: str = "one") -> LinkOwner:
    return LinkOwner(UserId(name), token_hash(name), 0)


@pytest.mark.parametrize(
    "change",
    [
        "valid",
        "browser",
        "provider",
        "purpose",
        "owner",
        "session",
        "revision",
        "expired",
        "cancelled",
        "config",
    ],
)
def test_flow_binding_table(database: Path, change: str) -> None:
    clock = FixedClock()
    service = flows(database, clock)
    browser, state = BrowserProof(secrets.token_urlsafe(32)), secrets.token_urlsafe(32)
    flow = service.begin(BeginIntent("google", browser, owner=owner()), state)
    callback = ProviderCallback("google", state, "code", browser, owner())
    if change == "browser":
        callback = replace(callback, browser=BrowserProof(secrets.token_urlsafe(32)))
    if change == "provider":
        callback = replace(callback, provider="microsoft")
    if change == "purpose":
        callback = replace(callback, owner=None)
    if change == "owner":
        callback = replace(callback, owner=owner("two"))
    if change == "session":
        callback = replace(callback, owner=replace(owner(), session_hash=token_hash("other")))
    if change == "revision":
        with transaction(database) as connection:
            connection.execute("UPDATE users SET credential_revision = 1 WHERE id = 'one'")
    if change == "expired":
        clock.value += timedelta(minutes=10)
    if change == "cancelled":
        service.cancel(browser)
    if change == "config":
        service.fingerprints["google"] = "changed"
    assert service.consume(callback) == (flow if change == "valid" else None)
    assert service.consume(callback) is None


def test_anonymous_callback_cannot_switch_into_a_session(database: Path) -> None:
    service = flows(database)
    browser, state = BrowserProof(secrets.token_urlsafe(32)), secrets.token_urlsafe(32)
    service.begin(BeginIntent("google", browser), state)
    assert service.consume(ProviderCallback("google", state, "code", browser, owner())) is None


def test_parallel_callbacks_have_one_winner(database: Path) -> None:
    service = flows(database)
    browser, state = BrowserProof(secrets.token_urlsafe(32)), secrets.token_urlsafe(32)
    service.begin(BeginIntent("google", browser), state)
    callback = ProviderCallback("google", state, "code", browser)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(service.consume, [callback, callback]))
    assert sum(result is not None for result in results) == 1


def test_pending_rotation_binding_expiry_and_sealing(database: Path) -> None:
    service = flows(database)
    browser, state = BrowserProof(secrets.token_urlsafe(32)), secrets.token_urlsafe(32)
    intent = BeginIntent(
        "google", browser, InvitationIntent("invite-secret", "private@example.test")
    )
    service.begin(intent, state)
    flow = service.consume(ProviderCallback("google", state, "code", browser))
    assert flow is not None
    assert flow.context.invitation == BoundInvitation(
        token_hash("invite-secret"), "private@example.test"
    )
    claims = ProviderClaims(
        ProviderIdentityKey("https://issuer.example.test", "private-subject"),
        "private@example.test",
        False,
    )
    first = service.defer(flow, claims)
    state = secrets.token_urlsafe(32)
    flow = service.begin(intent, state)
    assert service.consume(ProviderCallback("google", state, "code", browser)) == flow
    second = service.defer(
        flow, replace(claims, key=ProviderIdentityKey(claims.key.issuer, "new-subject"))
    )
    assert service.pending(browser, first.token) is None
    assert service.load_pending(browser, first.token) is None
    assert service.pending(browser, second.token) == second
    assert service.pending(BrowserProof(secrets.token_urlsafe(32)), second.token) is None
    raw = database.read_bytes()
    for secret in (
        state,
        browser.value,
        first.token,
        second.token,
        "invite-secret",
        "private-subject",
        "private@example.test",
    ):
        assert secret.encode() not in raw
    pending = service.load_pending(browser, second.token)
    assert pending is not None
    assert pending.claims.key.subject == "new-subject"
    assert service.load_pending(browser, second.token) == pending


def test_flow_capacity_and_batched_purge(database: Path) -> None:
    clock = FixedClock()
    service = flows(database, clock)
    for _ in range(1000):
        service.begin(
            BeginIntent("google", BrowserProof(secrets.token_urlsafe(32))),
            secrets.token_urlsafe(32),
        )
    with pytest.raises(ProviderSignInRefused):
        service.begin(
            BeginIntent("google", BrowserProof(secrets.token_urlsafe(32))),
            secrets.token_urlsafe(32),
        )
    clock.value += timedelta(minutes=10)
    assert service.purge(clock.now(), 1000) == 250


def test_owned_session_reference_enforces_user(database: Path) -> None:
    import sqlite3

    service = flows(database)
    browser, state = BrowserProof(secrets.token_urlsafe(32)), secrets.token_urlsafe(32)
    service.begin(BeginIntent("google", browser, owner=owner()), state)
    with pytest.raises(sqlite3.IntegrityError), transaction(database) as connection:
        connection.execute("UPDATE provider_link_flows SET user_id = 'two'")
    with transaction(database) as connection:
        connection.execute("DELETE FROM user_sessions WHERE user_id = 'one'")
        assert connection.execute("SELECT COUNT(*) FROM provider_link_flows").fetchone()[0] == 0


def test_state_secrets_are_purpose_separated() -> None:
    from calendar_sync.infrastructure.security import ProviderSignInSecrets

    key = CredentialCipher.generate_key()
    first, restarted = ProviderSignInSecrets(key), ProviderSignInSecrets(key)
    state = secrets.token_urlsafe(32)
    assert first.nonce(state, "google") == restarted.nonce(state, "google")
    assert (
        len(
            {
                first.nonce(state, "google"),
                first.nonce(state, "microsoft"),
                first.verifier(state, "google"),
                first.digest("admission:begin", state),
            }
        )
        == 4
    )


@pytest.mark.parametrize("change", ["expiry", "cancellation", "config", "key"])
def test_pending_refuses_stale_context(database: Path, change: str) -> None:
    clock = FixedClock()
    service = flows(database, clock)
    browser, state = BrowserProof(secrets.token_urlsafe(32)), secrets.token_urlsafe(32)
    flow = service.begin(BeginIntent("google", browser), state)
    assert service.consume(ProviderCallback("google", state, "code", browser)) == flow
    claims = ProviderClaims(ProviderIdentityKey("https://issuer.test", "subject"), None, False)
    pending = service.defer(flow, claims)
    if change == "expiry":
        clock.value += timedelta(minutes=10)
    if change == "cancellation":
        service.cancel(browser)
    if change == "config":
        service.fingerprints["google"] = "changed"
    if change == "key":
        service = flows(database, clock)
    assert service.pending(browser, pending.token) is None
    assert service.load_pending(browser, pending.token) is None


def test_flow_waits_are_bounded(database: Path) -> None:
    import time

    from calendar_sync.application.identity.provider_sign_in_ports import ProviderSignInUnavailable

    service = flows(database)
    with transaction(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        start = time.monotonic()
        with pytest.raises(ProviderSignInUnavailable):
            service.begin(
                BeginIntent("google", BrowserProof(secrets.token_urlsafe(32))),
                secrets.token_urlsafe(32),
            )
        assert time.monotonic() - start < 1


def test_pending_claim_shares_final_transaction(database: Path) -> None:
    from calendar_sync.infrastructure.persistence.provider_flow_records import claim_pending

    service = flows(database)
    browser, state = BrowserProof(secrets.token_urlsafe(32)), secrets.token_urlsafe(32)
    flow = service.begin(BeginIntent("google", browser), state)
    assert service.consume(ProviderCallback("google", state, "code", browser)) == flow
    claims = ProviderClaims(ProviderIdentityKey("https://issuer.test", "subject"), None, False)
    first = service.defer(flow, claims)
    assert service.load_pending(browser, first.token) is not None
    state = secrets.token_urlsafe(32)
    flow = service.begin(BeginIntent("google", browser), state)
    assert service.consume(ProviderCallback("google", state, "code", browser)) == flow
    second = service.defer(flow, claims)
    with transaction(database) as connection:
        assert not claim_pending(connection, token_hash(first.token), flow.browser_hash, NOW)

    def rolled_back_confirmation() -> None:
        with transaction(database) as connection:
            assert claim_pending(connection, token_hash(second.token), flow.browser_hash, NOW)
            raise RuntimeError("synthetic rollback")

    with pytest.raises(RuntimeError, match="synthetic rollback"):
        rolled_back_confirmation()
    assert service.pending(browser, second.token) == second
    with transaction(database) as connection:
        assert claim_pending(connection, token_hash(second.token), flow.browser_hash, NOW)
        assert not claim_pending(connection, token_hash(second.token), flow.browser_hash, NOW)
    assert service.pending(browser, second.token) is None
