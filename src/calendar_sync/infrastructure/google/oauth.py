from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from threading import Lock
from typing import Any, cast
from urllib.parse import urlparse

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]

from calendar_sync.application.errors import (
    AccountAccessCheckFailed,
    AuthorizationFailed,
    AuthorizationNotConfigured,
    CalendarPermissionRequired,
    ConnectedAccountDisconnected,
    ConnectedAccountNotFound,
    InvalidAuthorizationState,
    ProviderFailureKind,
)
from calendar_sync.application.ports import (
    AccountAccess,
    AuthorizedAccount,
    CalendarAccess,
    DiscoveredCalendar,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import (
    SqliteAuthorizationStates,
)
from calendar_sync.infrastructure.provider_calls import record_token_refresh

CALENDAR_SCOPES = (
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
)
# Basic profile identifies each Connected Account by name and photo. It is optional: a grant
# without it still connects, and the account falls back to initials.
PROFILE_SCOPES = ("openid", "https://www.googleapis.com/auth/userinfo.profile")
OAUTH_SCOPES = CALENDAR_SCOPES + PROFILE_SCOPES
GOOGLE_ACCESS_ROLES: Mapping[str, CalendarAccess] = {
    "owner": CalendarAccess.OWNER,
    "writer": CalendarAccess.WRITER,
    "reader": CalendarAccess.READER,
    "freeBusyReader": CalendarAccess.FREE_BUSY,
}
"""Google's `accessRole` values, translated to provider-neutral access.

A missing or unknown role maps to `READER`: conservative, because it is never writable.
"""
# Google may grant fewer scopes than requested (a declined profile) or more (previously granted
# scopes). oauthlib rejects any difference unless relaxed; complete() enforces Calendar scopes.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OAuthClientConfig:
    """The installation's Google OAuth client, as registered in Google Cloud."""

    client_id: str
    client_secret: str
    redirect_uri: str

    @property
    def complete(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)


class GoogleOAuthService:
    """Google's state-protected OAuth flow, with PKCE, for least-privilege Calendar scopes."""

    def __init__(
        self,
        client: OAuthClientConfig,
        accounts: SqliteConnectedAccountStore,
        states: SqliteAuthorizationStates,
        verifier_key: str,
    ) -> None:
        self._client = client
        self._accounts = accounts
        self._states = states
        # The Installation Master Key, from which each state's PKCE verifier is derived.
        self._verifier_key = verifier_key
        self._refresh_locks: dict[ConnectedAccountId, Lock] = {}
        self._refresh_guard = Lock()

    def authorization_url(self, owner: UserId, login_hint: str | None = None) -> str:
        self._require_client_configuration()
        state = secrets.token_urlsafe(32)
        self._states.store(state, owner)
        flow = self._flow(state)
        hint = {"login_hint": login_hint} if login_hint else {}
        url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            **hint,
        )
        return str(url)

    def complete(self, state: str, code: str, user: UserId) -> AuthorizedAccount:
        owner = self._consume_state(state)
        if owner != user:
            # Someone else's consent link: the state is used up and the code never exchanged,
            # so nobody can connect a Google account into another User's installation.
            raise AuthorizationFailed("Google authorization was begun by another User")
        flow = self._flow(state)
        try:
            flow.fetch_token(code=code)
        except Exception as error:
            raise AuthorizationFailed("Google authorization could not be completed") from error
        credentials = flow.credentials
        granted_scopes = set(getattr(credentials, "granted_scopes", None) or ())
        if not set(CALENDAR_SCOPES).issubset(granted_scopes):
            raise CalendarPermissionRequired(
                "Google Calendar permission is required to connect this account"
            )
        try:
            service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
            calendars = self._calendar_items(service)
        except Exception as error:
            if _google_status_code(error) in {401, 403}:
                raise CalendarPermissionRequired(
                    "Google Calendar permission is required to connect this account"
                ) from error
            raise AuthorizationFailed(
                "Google Calendar authorization could not be verified"
            ) from error
        primary = next((calendar for calendar in calendars if calendar.get("primary")), None)
        if primary is None:
            raise AuthorizationFailed("Google account did not expose a primary calendar")
        email = str(primary.get("id") or "")
        if not email:
            raise AuthorizationFailed("Google primary calendar did not expose an identity")
        profile = _profile_claims(getattr(credentials, "id_token", None))
        display_name = _optional_text(profile.get("name")) or str(primary.get("summary") or email)
        account = self._accounts.for_user(owner).save(
            display_name,
            email,
            credentials.to_json(),
            provider=ProviderKind.GOOGLE,
            avatar_url=_https_url(profile.get("picture")),
        )
        return AuthorizedAccount(owner, account)

    def cancel(self, state: str) -> None:
        self._consume_state(state)

    def calendars(self, account_id: ConnectedAccountId) -> tuple[DiscoveredCalendar, ...]:
        credentials = self._credentials(account_id)
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        return tuple(
            discovered_calendar(item)
            for item in self._calendar_items(service)
            if isinstance(item.get("id"), str)
        )

    def verify_access(self, account_id: ConnectedAccountId) -> AccountAccess:
        try:
            # Inside the check: an expired token is refreshed here, and a rejected refresh is the
            # most common reason access fails.
            credentials = self._credentials(account_id)
            service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
            calendars = self._calendar_items(service)
            calendar_id = next(
                (
                    str(item["id"])
                    for item in calendars
                    if item.get("primary") and isinstance(item.get("id"), str)
                ),
                next(
                    (str(item["id"]) for item in calendars if isinstance(item.get("id"), str)),
                    None,
                ),
            )
            if calendar_id is None:
                raise AccountAccessCheckFailed(
                    "Google Calendar did not expose a calendar for permission verification"
                )
            (
                service.events()
                .list(
                    calendarId=calendar_id,
                    maxResults=1,
                    showDeleted=False,
                    singleEvents=False,
                    fields="items(id)",
                )
                .execute()
            )
        except (AccountAccessCheckFailed, ConnectedAccountDisconnected, ConnectedAccountNotFound):
            raise
        except Exception as error:
            status_code = _google_status_code(error)
            # A refresh Google rejected carries no status; one it could not answer is retryable.
            revoked = isinstance(error, RefreshError) and not error.retryable
            if status_code == 401 or revoked:
                raise AccountAccessCheckFailed(
                    "Google authorization has expired; reauthorize this account",
                    ProviderFailureKind.AUTHENTICATION,
                ) from error
            if status_code == 403:
                raise AccountAccessCheckFailed(
                    "Google Calendar access was denied; confirm the Calendar API is enabled "
                    "and reauthorize this account",
                    ProviderFailureKind.AUTHORIZATION,
                ) from error
            raise AccountAccessCheckFailed(
                "Google Calendar access could not be verified; try again",
                ProviderFailureKind.TEMPORARY,
            ) from error
        return AccountAccess(
            calendars_visible=len(calendars),
            writable_calendars=sum(
                1 for item in calendars if _google_access(item.get("accessRole")).writable
            ),
        )

    def service_for(self, account_id: ConnectedAccountId) -> Any:
        credentials = self._credentials(account_id)
        return build("calendar", "v3", credentials=credentials, cache_discovery=False)

    def _credentials(self, account_id: ConnectedAccountId) -> Credentials:
        """Usable credentials, refreshing an expired access token once and keeping the new one.

        Without keeping it, every request after the first hour would refresh again first.
        """
        with self._refresh_lock(account_id):
            stored = self._accounts.credential_json(account_id)
            credentials = cast(
                Credentials,
                Credentials.from_authorized_user_info(  # type: ignore[no-untyped-call]
                    json.loads(stored), scopes=CALENDAR_SCOPES
                ),
            )
            if not credentials.valid:
                credentials.refresh(Request())  # type: ignore[no-untyped-call]
                record_token_refresh()
                refreshed = credentials.to_json()  # type: ignore[no-untyped-call]
                kept = self._accounts.replace_credentials(account_id, stored, refreshed)
                logger.info(
                    "refreshed access token account=%s kept=%s",
                    account_id.value,
                    "yes" if kept else "no",
                )
            return credentials

    def _refresh_lock(self, account_id: ConnectedAccountId) -> Lock:
        # One refresh per account at a time, so concurrent requests reuse its new token.
        with self._refresh_guard:
            return self._refresh_locks.setdefault(account_id, Lock())

    def _flow(self, state: str) -> Flow:
        client_config = {
            "web": {
                "client_id": self._client.client_id,
                "client_secret": self._client.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [self._client.redirect_uri],
            }
        }
        return Flow.from_client_config(
            client_config,
            scopes=OAUTH_SCOPES,
            state=state,
            redirect_uri=self._client.redirect_uri,
            code_verifier=self._code_verifier(state),
            autogenerate_code_verifier=False,
        )

    def _code_verifier(self, state: str) -> str:
        # Derivation keeps the verifier recoverable after a restart without persisting
        # another OAuth secret alongside the hashed state.
        digest = hmac.new(
            self._verifier_key.encode(),
            b"google-calendar-sync/oauth-pkce/v1\0" + state.encode(),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    @staticmethod
    def _calendar_items(service: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            response = service.calendarList().list(pageToken=page_token).execute()
            items.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return items

    def _require_client_configuration(self) -> None:
        if not self._client.complete:
            raise AuthorizationNotConfigured(
                "configure the Google OAuth client ID, secret, and redirect URI"
            )

    def _consume_state(self, state: str) -> UserId:
        owner = self._states.consume(state)
        if owner is None:
            raise InvalidAuthorizationState("OAuth state is missing, expired, or already used")
        return owner


def discovered_calendar(item: Mapping[str, Any]) -> DiscoveredCalendar:
    """One Google calendar list entry, without Google's access-role vocabulary."""
    return DiscoveredCalendar(
        id=str(item["id"]),
        summary=str(item.get("summary") or item["id"]),
        access=_google_access(item.get("accessRole")),
        primary=bool(item.get("primary")),
    )


def _google_access(role: object) -> CalendarAccess:
    """`role`'s provider-neutral access; a missing or unknown role is never writable."""
    if isinstance(role, str):
        return GOOGLE_ACCESS_ROLES.get(role, CalendarAccess.READER)
    return CalendarAccess.READER


def _profile_claims(id_token: object) -> dict[str, Any]:
    # The ID token arrives directly from Google's token endpoint over TLS, which OpenID Connect
    # accepts in place of signature validation. Its claims only label the account in the UI and
    # never authorize access.
    if not isinstance(id_token, str):
        return {}
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}
    return claims if isinstance(claims, dict) else {}


def _optional_text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _https_url(value: object) -> str | None:
    url = _optional_text(value)
    if url is None or len(url) > 2048:
        return None
    parsed = urlparse(url)
    return url if parsed.scheme == "https" and parsed.netloc else None


def _google_status_code(error: Exception) -> int | None:
    response = getattr(error, "resp", None)
    status_code = getattr(response, "status", None)
    return int(status_code) if isinstance(status_code, int) else None
