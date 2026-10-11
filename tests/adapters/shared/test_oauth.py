"""OAuth mechanics every provider's connection flow shares: single-use states bound to the User
who began the flow, PKCE, one token refresh per account at a time, and connecting for an active
User only."""

import base64
import hashlib
import sqlite3
from pathlib import Path

import pytest

from calendar_sync.application.errors import AuthorizationFailed, InvalidAuthorizationState
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.oauth import (
    OAuthClientConfig,
    OAuthStates,
    RefreshLocks,
    connect_account,
    pkce_challenge,
    pkce_verifier,
)
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import SqliteAuthorizationStates
from calendar_sync.infrastructure.persistence.sqlite import initialize_database
from calendar_sync.infrastructure.security import CredentialCipher
from tests.users import OTHER_USER, USER, add_user

KEY = CredentialCipher.generate_key()


def _states(tmp_path: Path) -> tuple[OAuthStates, Path]:
    database = tmp_path / "test.db"
    initialize_database(database)
    add_user(database)
    add_user(database, OTHER_USER, role="user")
    return OAuthStates(SqliteAuthorizationStates(database), ProviderKind.GOOGLE), database


def test_a_state_is_claimed_once_by_the_user_who_began_the_flow(tmp_path: Path) -> None:
    states, _ = _states(tmp_path)
    state = states.begin(USER)

    assert states.claim(state, USER) == USER
    with pytest.raises(InvalidAuthorizationState, match="already used"):
        states.claim(state, USER)


def test_another_user_claiming_a_state_uses_it_up_and_connects_nothing(tmp_path: Path) -> None:
    states, _ = _states(tmp_path)
    state = states.begin(USER)

    with pytest.raises(AuthorizationFailed):
        states.claim(state, OTHER_USER)
    # Nobody can try it again, not even the User who began it.
    with pytest.raises(InvalidAuthorizationState):
        states.claim(state, USER)


def test_a_state_of_a_user_disabled_meanwhile_cannot_be_claimed(tmp_path: Path) -> None:
    states, database = _states(tmp_path)
    state = states.begin(USER)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE users SET state = 'disabled' WHERE id = ?", (USER.value,))

    with pytest.raises(InvalidAuthorizationState):
        states.claim(state, USER)


def test_cancelling_uses_a_state_up(tmp_path: Path) -> None:
    states, _ = _states(tmp_path)
    state = states.begin(USER)

    states.cancel(state)

    with pytest.raises(InvalidAuthorizationState):
        states.cancel(state)


def test_states_are_long_random_and_never_repeat(tmp_path: Path) -> None:
    states, _ = _states(tmp_path)

    first, second = states.begin(USER), states.begin(USER)

    assert first != second
    assert len(first) >= 43


def test_a_pkce_verifier_is_derived_again_from_its_state_and_purpose() -> None:
    verifier = pkce_verifier(KEY, b"example/oauth-pkce/v1", "synthetic-state")

    # The callback derives it again after a restart, without storing another secret.
    assert pkce_verifier(KEY, b"example/oauth-pkce/v1", "synthetic-state") == verifier
    assert pkce_verifier(KEY, b"other/oauth-pkce/v1", "synthetic-state") != verifier
    assert pkce_verifier(KEY, b"example/oauth-pkce/v1", "another-state") != verifier
    assert 43 <= len(verifier) <= 128


def test_a_pkce_challenge_is_the_verifiers_s256_digest() -> None:
    verifier = pkce_verifier(KEY, b"example/oauth-pkce/v1", "synthetic-state")
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")

    assert pkce_challenge(verifier) == expected.decode()


def test_refresh_locks_are_one_per_account() -> None:
    locks = RefreshLocks()
    personal, work = ConnectedAccountId("personal"), ConnectedAccountId("work")

    assert locks.of(personal) is locks.of(personal)
    assert locks.of(personal) is not locks.of(work)


def test_an_account_connects_for_its_owner(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    add_user(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(KEY))

    authorized = connect_account(
        store,
        USER,
        display_name="Person",
        email="person@example.test",
        credentials='{"token":"synthetic"}',
        provider=ProviderKind.GOOGLE,
    )

    assert authorized.owner == USER
    assert [account.email for account in store.for_user(USER).list()] == ["person@example.test"]
    assert store.credential_json(authorized.account.id) == '{"token":"synthetic"}'


def test_a_user_disabled_before_the_account_is_saved_connects_nothing(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    add_user(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(KEY))
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE users SET state = 'disabled' WHERE id = ?", (USER.value,))

    with pytest.raises(AuthorizationFailed):
        connect_account(
            store,
            USER,
            display_name="Person",
            email="person@example.test",
            credentials="{}",
            provider=ProviderKind.GOOGLE,
        )
    assert store.for_user(USER).list() == ()


def test_a_client_is_complete_only_with_an_id_a_secret_and_a_redirect() -> None:
    assert OAuthClientConfig("id", "secret", "https://example.test/callback").complete
    assert not OAuthClientConfig("", "secret", "https://example.test/callback").complete
    assert not OAuthClientConfig("id", "", "https://example.test/callback").complete
