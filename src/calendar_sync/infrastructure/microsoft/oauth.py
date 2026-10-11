"""Microsoft's OAuth flow, Microsoft account credentials, and Outlook calendar discovery.

The authorization code flow with PKCE runs against the identity platform's v2.0 endpoints, for the
tenant the installation chose (`common` admits personal and work or school accounts), on the
neutral OAuth mechanics: a single-use state bound to the signed-in, active User and to this
provider. Scopes are least-privilege and need no administrator's consent. Microsoft rotates the
refresh token on every use, so each refresh keeps the new one (ADR 0032).
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from calendar_sync.application.causes import Cause
from calendar_sync.application.errors import (
    AccountAccessCheckFailed,
    AuthorizationFailed,
    AuthorizationNotConfigured,
    CalendarPermissionRequired,
    ConnectedAccountDisconnected,
    ConnectedAccountNotFound,
    ProviderFailureKind,
)
from calendar_sync.application.ports import (
    AccountAccess,
    AuthorizedAccount,
    CalendarAccess,
    Clock,
    DiscoveredCalendar,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.microsoft.graph import (
    LOGIN,
    TIMEOUT_SECONDS,
    GraphHttp,
    GraphRefusal,
    Json,
    TokenRefusal,
    token_refusal,
)
from calendar_sync.infrastructure.oauth import (
    OAuthClientConfig,
    OAuthStates,
    RefreshLocks,
    connect_account,
    pkce_challenge,
    pkce_verifier,
)
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import (
    SqliteAuthorizationStates,
)
from calendar_sync.infrastructure.provider_calls import record_token_refresh

CALENDAR_SCOPE = "Calendars.ReadWrite"
SCOPES = ("openid", "email", "offline_access", "User.Read", CALENDAR_SCOPE)
"""Least-privilege delegated scopes: sign-in, the account's address and refresh tokens, its
profile, and its own calendars. None needs an administrator's consent."""
# What each flow's PKCE verifier is derived for, so it is never Google's.
PKCE_PURPOSE = b"calendar-ghost/microsoft-oauth-pkce/v1"
# An access token this close to expiring is renewed before a request uses it.
REFRESH_MARGIN = timedelta(minutes=5)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MicrosoftClient:
    """The installation's Microsoft Entra application, and which accounts may sign in to it."""

    oauth: OAuthClientConfig
    tenant: str = "common"
    """`common` admits personal and work or school accounts; `organizations`, `consumers`, or a
    tenant ID admit fewer."""


class MicrosoftOAuthService:
    """Connects and reauthorizes Microsoft accounts, renews their access, and lists calendars."""

    def __init__(
        self,
        client: MicrosoftClient,
        accounts: SqliteConnectedAccountStore,
        states: SqliteAuthorizationStates,
        verifier_key: str,
        http: httpx.Client,
        clock: Clock,
    ) -> None:
        self._client = client
        self._accounts = accounts
        self._states = OAuthStates(states, ProviderKind.OUTLOOK)
        # The Installation Master Key, from which each state's PKCE verifier is derived.
        self._verifier_key = verifier_key
        self._http = http
        self._graph = GraphHttp(http)
        self._clock = clock
        self._refresh_locks = RefreshLocks()

    @property
    def graph(self) -> GraphHttp:
        return self._graph

    def authorization_url(self, owner: UserId, login_hint: str | None = None) -> str:
        if not self._client.oauth.complete:
            raise AuthorizationNotConfigured(
                "configure the Microsoft client ID, secret, and redirect URI"
            )
        state = self._states.begin(owner)
        query = {
            "client_id": self._client.oauth.client_id,
            "response_type": "code",
            "redirect_uri": self._client.oauth.redirect_uri,
            "response_mode": "query",
            "scope": " ".join(SCOPES),
            "state": state,
            "code_challenge": pkce_challenge(self.code_verifier(state)),
            "code_challenge_method": "S256",
            # Lets a person who is signed in to several accounts choose which one to connect.
            "prompt": "select_account",
        }
        if login_hint:
            query["login_hint"] = login_hint
        return f"{self._authority}/authorize?{urlencode(query)}"

    def code_verifier(self, state: str) -> str:
        """The flow's PKCE verifier, derived again from its state after a restart."""
        return pkce_verifier(self._verifier_key, PKCE_PURPOSE, state)

    def complete(self, state: str, code: str, user: UserId) -> AuthorizedAccount:
        # Someone else's consent link uses the state up before the code is ever exchanged.
        owner = self._states.claim(state, user)
        try:
            tokens = self._token_request(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._client.oauth.redirect_uri,
                    "code_verifier": self.code_verifier(state),
                    "scope": " ".join(SCOPES),
                }
            )
        except TokenRefusal as error:
            raise AuthorizationFailed("Microsoft authorization could not be completed") from error
        if not _grants_calendars(tokens.get("scope")):
            raise CalendarPermissionRequired(
                "Outlook calendar permission is required to connect this account"
            )
        access = str(tokens.get("access_token") or "")
        try:
            me = self._graph.request("me.get", "GET", "/me", access)
            self._calendar_items(access)
        except GraphRefusal as error:
            if error.status in {401, 403}:
                raise CalendarPermissionRequired(
                    "Outlook calendar permission is required to connect this account"
                ) from error
            raise AuthorizationFailed("Outlook calendar access could not be verified") from error
        email = _account_address(me, tokens.get("id_token"))
        if not email:
            raise AuthorizationFailed("the Microsoft account did not expose an address")
        return connect_account(
            self._accounts,
            owner,
            display_name=_text(me.get("displayName")) or email,
            email=email,
            credentials=json.dumps(self._credentials(tokens)),
            provider=ProviderKind.OUTLOOK,
        )

    def cancel(self, state: str) -> None:
        self._states.cancel(state)

    def calendars(self, account_id: ConnectedAccountId) -> tuple[DiscoveredCalendar, ...]:
        return tuple(
            discovered_calendar(item)
            for item in self._calendar_items(self.access_token(account_id))
            if isinstance(item.get("id"), str)
        )

    def verify_access(self, account_id: ConnectedAccountId) -> AccountAccess:
        try:
            # Inside the check: an expired token is refreshed here, and a refused refresh is the
            # most common reason access fails.
            token = self.access_token(account_id)
            calendars = [
                item for item in self._calendar_items(token) if isinstance(item.get("id"), str)
            ]
            if not calendars:
                raise AccountAccessCheckFailed(
                    "Outlook did not expose a calendar for permission verification"
                )
            calendar = next((c for c in calendars if c.get("isDefaultCalendar")), calendars[0])
            self._graph.request(
                "events.list",
                "GET",
                f"/me/calendars/{calendar['id']}/events",
                token,
                params={"$top": "1", "$select": "id"},
            )
        except (AccountAccessCheckFailed, ConnectedAccountDisconnected, ConnectedAccountNotFound):
            raise
        except TokenRefusal as error:
            raise _refused_check(_token_failure_kind(error)) from error
        except GraphRefusal as error:
            raise _refused_check(_graph_failure_kind(error)) from error
        return AccountAccess(
            calendars_visible=len(calendars),
            writable_calendars=sum(discovered_calendar(item).writable for item in calendars),
        )

    def access_token(self, account_id: ConnectedAccountId) -> str:
        """A usable access token, refreshing an expiring one once and keeping the rotated refresh
        token Microsoft returns; raises TokenRefusal when Microsoft refuses."""
        with self._refresh_locks.of(account_id):
            stored = self._accounts.credential_json(account_id)
            credentials = json.loads(stored)
            expires_at = _instant(credentials.get("expires_at"))
            if expires_at is not None and expires_at - self._clock.now() > REFRESH_MARGIN:
                return str(credentials["access_token"])
            tokens = self._token_request(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": str(credentials.get("refresh_token") or ""),
                    "scope": " ".join(SCOPES),
                }
            )
            record_token_refresh()
            # Microsoft returns a new refresh token with each refresh and expects the old one to
            # be discarded; keep the old one only if none came back.
            renewed = self._credentials(
                {"refresh_token": credentials.get("refresh_token"), **tokens}
            )
            kept = self._accounts.replace_credentials(account_id, stored, json.dumps(renewed))
            logger.info(
                "refreshed access token account=%s kept=%s",
                account_id.value,
                "yes" if kept else "no",
            )
            return str(renewed["access_token"])

    @property
    def _authority(self) -> str:
        return f"{LOGIN}/{self._client.tenant}/oauth2/v2.0"

    def _token_request(self, form: Mapping[str, str]) -> Json:
        try:
            response = self._http.post(
                f"{self._authority}/token",
                data={
                    "client_id": self._client.oauth.client_id,
                    "client_secret": self._client.oauth.client_secret,
                    **form,
                },
                timeout=TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as error:
            raise TokenRefusal(None) from error
        if response.status_code != 200:
            raise token_refusal(response)
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("access_token"), str):
            raise TokenRefusal(response.status_code)
        return body

    def _credentials(self, tokens: Mapping[str, Any]) -> Json:
        lifetime = tokens.get("expires_in")
        seconds = lifetime if isinstance(lifetime, int) else 0
        return {
            "access_token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "expires_at": (self._clock.now() + timedelta(seconds=seconds)).isoformat(),
            "scope": tokens.get("scope"),
        }

    def _calendar_items(self, token: str) -> list[Json]:
        items: list[Json] = []
        for page in self._graph.pages(
            "calendars.list",
            "/me/calendars",
            token,
            params={"$select": "id,name,canEdit,isDefaultCalendar"},
        ):
            values = page.get("value")
            if isinstance(values, list):
                items.extend(item for item in values if isinstance(item, dict))
        return items


def discovered_calendar(item: Mapping[str, Any]) -> DiscoveredCalendar:
    """One Outlook calendar, as rules may use it. A calendar the account may not edit is a
    source only, as Graph's `canEdit` says."""
    name = _text(item.get("name"))
    return DiscoveredCalendar(
        id=str(item["id"]),
        summary=name or str(item["id"]),
        access=CalendarAccess.WRITER if item.get("canEdit") is True else CalendarAccess.READER,
        primary=item.get("isDefaultCalendar") is True,
        named=name is not None,
    )


def _grants_calendars(scope: object) -> bool:
    """Whether the token response's granted scopes include calendar read and write; Microsoft
    names Graph's scopes in full, such as `https://graph.microsoft.com/Calendars.ReadWrite`."""
    if not isinstance(scope, str):
        return False
    return any(granted.rsplit("/", 1)[-1] == CALENDAR_SCOPE for granted in scope.split())


def _account_address(me: Mapping[str, Any], id_token: object) -> str | None:
    """The account's address: Graph's `mail`, else its sign-in name, else the ID token's.
    Microsoft documents these as display values that may change (ADR 0032)."""
    claims = _claims(id_token)
    for candidate in (
        me.get("mail"),
        me.get("userPrincipalName"),
        claims.get("email"),
        claims.get("preferred_username"),
    ):
        if (text := _text(candidate)) and "@" in text:
            return text.lower()
    return None


def _claims(id_token: object) -> Mapping[str, Any]:
    # The ID token arrives straight from the token endpoint over TLS, which OpenID Connect accepts
    # in place of signature validation; its claims only name the account, never authorize it.
    if not isinstance(id_token, str):
        return {}
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}
    return claims if isinstance(claims, dict) else {}


def _token_failure_kind(error: TokenRefusal) -> ProviderFailureKind:
    """A refresh Microsoft could not answer is temporary; any refusal needs reauthorization."""
    if error.status is None or error.status >= 500 or error.error == "temporarily_unavailable":
        return ProviderFailureKind.TEMPORARY
    return ProviderFailureKind.AUTHENTICATION


def _graph_failure_kind(error: GraphRefusal) -> ProviderFailureKind:
    if error.status == 401:
        return ProviderFailureKind.AUTHENTICATION
    if error.status == 403:
        return ProviderFailureKind.AUTHORIZATION
    return ProviderFailureKind.TEMPORARY


_CHECK_DETAILS = {
    ProviderFailureKind.AUTHENTICATION: "Microsoft no longer accepts this account; reauthorize it",
    ProviderFailureKind.AUTHORIZATION: (
        "Outlook calendar access was denied; reauthorize this account"
    ),
    ProviderFailureKind.TEMPORARY: "Outlook calendar access could not be verified; try again",
}


def _refused_check(kind: ProviderFailureKind) -> AccountAccessCheckFailed:
    return AccountAccessCheckFailed(_CHECK_DETAILS[kind], kind, Cause.UNKNOWN)


def _instant(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None
