from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]

from calendar_sync.bootstrap.config import Settings
from calendar_sync.domain.model import ConnectedAccountId

CALENDAR_SCOPES = (
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
)
# Basic profile identifies each Connected Account by name and photo. It is optional: a grant
# without it still connects, and the account falls back to initials.
PROFILE_SCOPES = ("openid", "https://www.googleapis.com/auth/userinfo.profile")
OAUTH_SCOPES = CALENDAR_SCOPES + PROFILE_SCOPES


class GoogleOAuthNotConfigured(RuntimeError):
    pass


class GoogleOAuthCompletionFailed(RuntimeError):
    pass


class GoogleCalendarPermissionRequired(GoogleOAuthCompletionFailed):
    pass


class InvalidOAuthState(ValueError):
    pass


class InvalidMasterKey(ValueError):
    pass


class ConnectedGoogleAccountNotFound(LookupError):
    pass


class ConnectedGoogleAccountDisconnected(RuntimeError):
    pass


class ConnectedGoogleAccountMustBeDisconnected(RuntimeError):
    pass


class GoogleAccountAccessCheckFailed(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ConnectedGoogleAccount:
    id: ConnectedAccountId
    display_name: str
    email: str
    state: str
    avatar_url: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveredCalendar:
    id: str
    summary: str
    access_role: str
    primary: bool


@dataclass(frozen=True, slots=True)
class GoogleAccountAccess:
    calendars_visible: int
    writable_calendars: int


class CredentialCipher:
    def __init__(self, encoded_key: str) -> None:
        try:
            key = base64.urlsafe_b64decode(encoded_key.encode())
        except Exception as error:
            raise InvalidMasterKey("master key must be URL-safe base64") from error
        if len(key) != 32:
            raise InvalidMasterKey("master key must decode to exactly 32 bytes")
        self._cipher = AESGCM(key)

    def encrypt(self, plaintext: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._cipher.encrypt(nonce, plaintext.encode(), None)

    def decrypt(self, ciphertext: bytes) -> str:
        nonce, encrypted = ciphertext[:12], ciphertext[12:]
        return self._cipher.decrypt(nonce, encrypted, None).decode()

    @staticmethod
    def generate_key() -> str:
        return base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode()


class SqliteConnectedAccountStore:
    def __init__(self, database_path: Path, cipher: CredentialCipher) -> None:
        self._database_path = database_path
        self._cipher = cipher

    def list(self) -> tuple[ConnectedGoogleAccount, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, display_name, email, state, avatar_url
                FROM connected_accounts ORDER BY email
                """
            ).fetchall()
        return tuple(_account_from_row(row) for row in rows)

    def save(
        self,
        display_name: str,
        email: str,
        credential_json: str,
        *,
        avatar_url: str | None = None,
    ) -> ConnectedGoogleAccount:
        now = datetime.now(UTC).isoformat()
        account_id = str(uuid.uuid4())
        encrypted = self._cipher.encrypt(credential_json)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO connected_accounts (
                    id, provider, display_name, email, avatar_url, encrypted_credentials,
                    state, created_at, updated_at
                ) VALUES (?, 'google', ?, ?, ?, ?, 'connected', ?, ?)
                ON CONFLICT(provider, email) DO UPDATE SET
                    display_name = excluded.display_name,
                    avatar_url = excluded.avatar_url,
                    encrypted_credentials = excluded.encrypted_credentials,
                    state = 'connected',
                    updated_at = excluded.updated_at
                """,
                (account_id, display_name, email, avatar_url, encrypted, now, now),
            )
            row = connection.execute(
                """
                SELECT id, display_name, email, state, avatar_url
                FROM connected_accounts WHERE email = ?
                """,
                (email,),
            ).fetchone()
        assert row is not None
        return _account_from_row(row)

    def credentials(self, account_id: ConnectedAccountId) -> Credentials:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT encrypted_credentials, state FROM connected_accounts WHERE id = ?",
                (account_id.value,),
            ).fetchone()
        if row is None:
            raise ConnectedGoogleAccountNotFound(
                f"connected account {account_id.value} does not exist"
            )
        if str(row["state"]) != "connected":
            raise ConnectedGoogleAccountDisconnected(
                "this Google account is disconnected; reauthorize it from Settings"
            )
        payload = json.loads(self._cipher.decrypt(bytes(row["encrypted_credentials"])))
        credentials = Credentials.from_authorized_user_info(  # type: ignore[no-untyped-call]
            payload, scopes=CALENDAR_SCOPES
        )
        return cast(Credentials, credentials)

    def disconnect(self, account_id: ConnectedAccountId) -> ConnectedGoogleAccount:
        now = datetime.now(UTC).isoformat()
        cleared_credentials = self._cipher.encrypt("{}")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, display_name, email, avatar_url FROM connected_accounts WHERE id = ?",
                (account_id.value,),
            ).fetchone()
            if row is None:
                raise ConnectedGoogleAccountNotFound(
                    f"connected account {account_id.value} does not exist"
                )
            connection.execute(
                """
                UPDATE connected_accounts
                SET encrypted_credentials = ?, state = 'disconnected', updated_at = ?
                WHERE id = ?
                """,
                (cleared_credentials, now, account_id.value),
            )
        return ConnectedGoogleAccount(
            ConnectedAccountId(str(row["id"])),
            str(row["display_name"]),
            str(row["email"]),
            "disconnected",
            _optional_text(row["avatar_url"]),
        )

    def delete(self, account_id: ConnectedAccountId) -> int:
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            row = connection.execute(
                "SELECT state FROM connected_accounts WHERE id = ?",
                (account_id.value,),
            ).fetchone()
            if row is None:
                raise ConnectedGoogleAccountNotFound(
                    f"connected account {account_id.value} does not exist"
                )
            if str(row["state"]) != "disconnected":
                raise ConnectedGoogleAccountMustBeDisconnected(
                    "disconnect this Google account before deleting it permanently"
                )
            rule_ids = tuple(
                str(rule["id"])
                for rule in connection.execute(
                    """
                    SELECT id FROM sync_rules
                    WHERE source_account_id = ? OR destination_account_id = ?
                    """,
                    (account_id.value, account_id.value),
                ).fetchall()
            )
            if rule_ids:
                placeholders = ", ".join("?" for _ in rule_ids)
                connection.execute(
                    f"DELETE FROM audit_entries WHERE rule_id IN ({placeholders})", rule_ids
                )
                connection.execute(
                    f"DELETE FROM incidents WHERE rule_id IN ({placeholders})", rule_ids
                )
                connection.execute(f"DELETE FROM sync_rules WHERE id IN ({placeholders})", rule_ids)
            connection.execute(
                "DELETE FROM connected_accounts WHERE id = ?",
                (account_id.value,),
            )
        return len(rule_ids)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection


class GoogleOAuthService:
    def __init__(
        self,
        settings: Settings,
        accounts: SqliteConnectedAccountStore,
    ) -> None:
        self._settings = settings
        self._accounts = accounts

    def authorization_url(self) -> str:
        self._require_client_configuration()
        state = secrets.token_urlsafe(32)
        self._store_state(state)
        flow = self._flow(state)
        url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return str(url)

    def complete(self, state: str, code: str) -> ConnectedGoogleAccount:
        self._consume_state(state)
        flow = self._flow(state)
        try:
            flow.fetch_token(code=code)
        except Exception as error:
            raise GoogleOAuthCompletionFailed(
                "Google authorization could not be completed"
            ) from error
        credentials = flow.credentials
        granted_scopes = set(getattr(credentials, "granted_scopes", None) or ())
        if granted_scopes and not set(CALENDAR_SCOPES).issubset(granted_scopes):
            raise GoogleCalendarPermissionRequired(
                "Google Calendar permission is required to connect this account"
            )
        try:
            service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
            calendars = self._calendar_items(service)
        except Exception as error:
            if _google_status_code(error) in {401, 403}:
                raise GoogleCalendarPermissionRequired(
                    "Google Calendar permission is required to connect this account"
                ) from error
            raise GoogleOAuthCompletionFailed(
                "Google Calendar authorization could not be verified"
            ) from error
        primary = next((calendar for calendar in calendars if calendar.get("primary")), None)
        if primary is None:
            raise GoogleOAuthCompletionFailed("Google account did not expose a primary calendar")
        email = str(primary.get("id") or "")
        if not email:
            raise GoogleOAuthCompletionFailed("Google primary calendar did not expose an identity")
        profile = _profile_claims(getattr(credentials, "id_token", None))
        display_name = _optional_text(profile.get("name")) or str(primary.get("summary") or email)
        return self._accounts.save(
            display_name,
            email,
            credentials.to_json(),
            avatar_url=_https_url(profile.get("picture")),
        )

    def cancel(self, state: str) -> None:
        self._consume_state(state)

    def calendars(self, account_id: ConnectedAccountId) -> tuple[DiscoveredCalendar, ...]:
        credentials = self._accounts.credentials(account_id)
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        return tuple(
            DiscoveredCalendar(
                id=str(item["id"]),
                summary=str(item.get("summary") or item["id"]),
                access_role=str(item.get("accessRole") or "reader"),
                primary=bool(item.get("primary")),
            )
            for item in self._calendar_items(service)
            if isinstance(item.get("id"), str)
        )

    def verify_access(self, account_id: ConnectedAccountId) -> GoogleAccountAccess:
        credentials = self._accounts.credentials(account_id)
        try:
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
                raise GoogleAccountAccessCheckFailed(
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
        except GoogleAccountAccessCheckFailed:
            raise
        except Exception as error:
            status_code = _google_status_code(error)
            if status_code == 401:
                detail = "Google authorization has expired; reauthorize this account"
            elif status_code == 403:
                detail = (
                    "Google Calendar access was denied; confirm the Calendar API is enabled "
                    "and reauthorize this account"
                )
            else:
                detail = "Google Calendar access could not be verified; try again"
            raise GoogleAccountAccessCheckFailed(detail) from error
        return GoogleAccountAccess(
            calendars_visible=len(calendars),
            writable_calendars=sum(
                1 for item in calendars if item.get("accessRole") in {"owner", "writer"}
            ),
        )

    def service_for(self, account_id: ConnectedAccountId) -> Any:
        credentials = self._accounts.credentials(account_id)
        return build("calendar", "v3", credentials=credentials, cache_discovery=False)

    def _flow(self, state: str) -> Flow:
        client_config = {
            "web": {
                "client_id": self._settings.google_client_id,
                "client_secret": self._settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [self._settings.google_redirect_uri],
            }
        }
        return Flow.from_client_config(
            client_config,
            scopes=OAUTH_SCOPES,
            state=state,
            redirect_uri=self._settings.google_redirect_uri,
            code_verifier=self._code_verifier(state),
            autogenerate_code_verifier=False,
        )

    def _code_verifier(self, state: str) -> str:
        # Derivation keeps the verifier recoverable after a restart without persisting
        # another OAuth secret alongside the hashed state.
        digest = hmac.new(
            self._settings.master_key.encode(),
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
        if not (
            self._settings.google_client_id
            and self._settings.google_client_secret
            and self._settings.google_redirect_uri
        ):
            raise GoogleOAuthNotConfigured(
                "configure the Google OAuth client ID, secret, and redirect URI"
            )

    def _store_state(self, state: str) -> None:
        now = datetime.now(UTC)
        with sqlite3.connect(self._settings.database_path) as connection:
            connection.execute(
                "INSERT INTO oauth_states(state_hash, created_at, expires_at) VALUES (?, ?, ?)",
                (
                    _state_hash(state),
                    now.isoformat(),
                    (now + timedelta(minutes=10)).isoformat(),
                ),
            )

    def _consume_state(self, state: str) -> None:
        now = datetime.now(UTC)
        with sqlite3.connect(self._settings.database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE oauth_states SET consumed_at = ?
                WHERE state_hash = ? AND consumed_at IS NULL AND expires_at > ?
                """,
                (now.isoformat(), _state_hash(state), now.isoformat()),
            )
        if cursor.rowcount != 1:
            raise InvalidOAuthState("OAuth state is missing, expired, or already used")


def _account_from_row(row: sqlite3.Row) -> ConnectedGoogleAccount:
    return ConnectedGoogleAccount(
        ConnectedAccountId(str(row["id"])),
        str(row["display_name"]),
        str(row["email"]),
        str(row["state"]),
        _optional_text(row["avatar_url"]),
    )


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


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def _google_status_code(error: Exception) -> int | None:
    response = getattr(error, "resp", None)
    status_code = getattr(response, "status", None)
    return int(status_code) if isinstance(status_code, int) else None
