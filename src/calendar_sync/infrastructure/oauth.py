"""OAuth mechanics every provider's connection flow shares, whichever provider it connects.

A flow begins for the signed-in User with a single-use state, stored only as a hash, and
completes only for that same User while they are still active: a consent link opened by anyone
else uses the state up and connects nothing (ADR 0030). Each state's PKCE verifier is derived
from the Installation Master Key, so the callback derives it again after a restart without
storing another secret. A provider's own package builds its consent and token requests on these.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from threading import Lock

from calendar_sync.application.errors import (
    AuthorizationFailed,
    InvalidAuthorizationState,
    UserDisabled,
)
from calendar_sync.application.ports import AuthorizedAccount
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import (
    SqliteAuthorizationStates,
)


@dataclass(frozen=True, slots=True)
class OAuthClientConfig:
    """The installation's OAuth client, as registered with the provider."""

    client_id: str
    client_secret: str
    redirect_uri: str

    @property
    def complete(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)


class OAuthStates:
    """One provider's single-use states, each bound to the User who began its flow."""

    def __init__(self, states: SqliteAuthorizationStates, provider: ProviderKind) -> None:
        self._states = states
        self._provider = provider

    def begin(self, owner: UserId) -> str:
        """A new state for a flow `owner` begins; the callback connects for them alone."""
        state = secrets.token_urlsafe(32)
        self._states.store(state, owner)
        return state

    def claim(self, state: str, user: UserId) -> UserId:
        """Use the state up for `user`, the User signed in where the flow returned.

        Raises InvalidAuthorizationState for a state missing, expired, used, or whose User was
        disabled since, and AuthorizationFailed when another User began the flow: its state is
        then used up too, so nobody can connect an account into another User's records.
        """
        owner = self._consume(state)
        if owner != user:
            raise AuthorizationFailed("the authorization was begun by another User")
        return owner

    def cancel(self, state: str) -> None:
        """Use up the state of a flow the provider says did not complete."""
        self._consume(state)

    def _consume(self, state: str) -> UserId:
        owner = self._states.consume(state)
        if owner is None:
            raise InvalidAuthorizationState("OAuth state is missing, expired, or already used")
        return owner


def pkce_verifier(master_key: str, purpose: bytes, state: str) -> str:
    """The PKCE verifier of the flow `state` names (RFC 7636), derived for one provider's
    `purpose` so that no two providers' flows share one."""
    digest = hmac.new(master_key.encode(), purpose + b"\0" + state.encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode()


def pkce_challenge(verifier: str) -> str:
    """The S256 code challenge of a verifier (RFC 7636 section 4.2)."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class RefreshLocks:
    """One token refresh per account at a time, so concurrent requests reuse its new token."""

    def __init__(self) -> None:
        self._locks: dict[ConnectedAccountId, Lock] = {}
        self._guard = Lock()

    def of(self, account_id: ConnectedAccountId) -> Lock:
        with self._guard:
            return self._locks.setdefault(account_id, Lock())


def connect_account(
    accounts: SqliteConnectedAccountStore,
    owner: UserId,
    *,
    display_name: str,
    email: str,
    credentials: str,
    provider: ProviderKind,
    avatar_url: str | None = None,
) -> AuthorizedAccount:
    """Connect, or reauthorize, `owner`'s account; nothing when they were disabled meanwhile."""
    try:
        account = accounts.for_user(owner).save(
            display_name, email, credentials, provider=provider, avatar_url=avatar_url
        )
    except UserDisabled as error:
        raise AuthorizationFailed("the User was disabled during authorization") from error
    return AuthorizedAccount(owner, account)
