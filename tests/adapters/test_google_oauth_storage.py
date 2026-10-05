import base64
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from oauthlib.oauth2 import WebApplicationClient  # type: ignore[import-untyped]

from calendar_sync.application.errors import (
    AccountAccessCheckFailed,
    CalendarPermissionRequired,
    ConnectedAccountDisconnected,
    InvalidAuthorizationState,
)
from calendar_sync.application.ports import (
    CalendarAccess,
    ConnectedAccountState,
    DiscoveredCalendar,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.google.oauth import (
    CALENDAR_SCOPES,
    OAUTH_SCOPES,
    PROFILE_SCOPES,
    GoogleOAuthService,
    OAuthClientConfig,
    discovered_calendar,
)
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import (
    STATE_LIFETIME,
    SqliteAuthorizationStates,
)
from calendar_sync.infrastructure.persistence.sqlite import initialize_database
from calendar_sync.infrastructure.security import CredentialCipher, InvalidMasterKey

DEFAULT_REDIRECT_URI = "http://localhost:8000/api/v1/oauth/google/callback"
UNCONFIGURED_CLIENT = OAuthClientConfig("", "", DEFAULT_REDIRECT_URI)


def _oauth(
    database: Path,
    store: SqliteConnectedAccountStore,
    client: OAuthClientConfig = UNCONFIGURED_CLIENT,
    *,
    master_key: str = "",
) -> GoogleOAuthService:
    return GoogleOAuthService(client, store, SqliteAuthorizationStates(database), master_key)


def test_credential_cipher_round_trip_is_not_plaintext() -> None:
    cipher = CredentialCipher(CredentialCipher.generate_key())
    plaintext = '{"refresh_token":"synthetic-secret"}'

    encrypted = cipher.encrypt(plaintext)

    assert plaintext.encode() not in encrypted
    assert cipher.decrypt(encrypted) == plaintext


def test_invalid_master_key_is_rejected() -> None:
    with pytest.raises(InvalidMasterKey):
        CredentialCipher("not-a-32-byte-key")


def test_connected_account_upsert_preserves_identity(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))

    first = store.save(
        "Personal", "person@example.test", '{"token":"one"}', provider=ProviderKind.GOOGLE
    )
    updated = store.save(
        "Renamed", "person@example.test", '{"token":"two"}', provider=ProviderKind.GOOGLE
    )

    assert updated.id == first.id
    assert updated.display_name == "Renamed"
    assert len(store.list()) == 1


def test_connected_account_avatar_round_trips_and_follows_reauthorization(
    tmp_path: Path,
) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    photo = "https://lh3.googleusercontent.com/a/synthetic=s96-c"

    saved = store.save(
        "Person", "person@example.test", "{}", avatar_url=photo, provider=ProviderKind.GOOGLE
    )
    listed = store.list()
    reauthorized = store.save("Person", "person@example.test", "{}", provider=ProviderKind.GOOGLE)

    assert saved.avatar_url == photo
    assert listed[0].avatar_url == photo
    assert reauthorized.avatar_url is None


def test_avatar_migration_upgrades_an_existing_installation(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initial = (
        files("calendar_sync.infrastructure.persistence").joinpath("0001_initial.sql").read_text()
    )
    with sqlite3.connect(database) as connection:
        connection.executescript(initial)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (1, '2026-01-01')"
        )
        connection.execute(
            """
            INSERT INTO connected_accounts (
                id, provider, display_name, email, encrypted_credentials,
                state, created_at, updated_at
            ) VALUES ('existing', 'google', 'Person', 'person@example.test', x'00',
                'connected', '2026-01-01', '2026-01-01')
            """
        )

    initialize_database(database)
    initialize_database(database)

    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    with sqlite3.connect(database) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
    assert versions == list(range(1, 21))
    assert [(account.id.value, account.avatar_url) for account in store.list()] == [
        ("existing", None)
    ]


def test_disconnect_discards_credentials_and_reauthorization_preserves_identity(
    tmp_path: Path,
) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    cipher = CredentialCipher(CredentialCipher.generate_key())
    store = SqliteConnectedAccountStore(database, cipher)
    account = store.save(
        "Personal",
        "person@example.test",
        '{"refresh_token":"synthetic-secret"}',
        provider=ProviderKind.GOOGLE,
    )
    disconnected = store.disconnect(account.id)

    assert disconnected.state == "disconnected"
    with pytest.raises(ConnectedAccountDisconnected, match="reauthorize"):
        store.credential_json(account.id)
    with sqlite3.connect(database) as connection:
        cleared = bytes(
            connection.execute(
                "SELECT encrypted_credentials FROM connected_accounts WHERE id = ?",
                (account.id.value,),
            ).fetchone()[0]
        )
    assert cipher.decrypt(cleared) == "{}"
    assert b"synthetic-secret" not in cleared

    reauthorized = store.save(
        "Personal",
        "person@example.test",
        '{"refresh_token":"replacement-secret"}',
        provider=ProviderKind.GOOGLE,
    )
    assert reauthorized.id == account.id
    assert reauthorized.state == "connected"


class SteppingClock:
    def __init__(self, *moments: datetime) -> None:
        self._moments = list(moments)

    def now(self) -> datetime:
        return self._moments.pop(0)


def test_authorized_at_follows_connection_and_reauthorization_only(tmp_path: Path) -> None:
    # Activity offers rule recovery only once access was renewed after the incident.
    database = tmp_path / "test.db"
    initialize_database(database)
    connected_at, disconnected_at, reauthorized_at = (
        datetime(2026, 9, 29, hour, tzinfo=UTC) for hour in (9, 10, 11)
    )
    store = SqliteConnectedAccountStore(
        database,
        CredentialCipher(CredentialCipher.generate_key()),
        SteppingClock(connected_at, disconnected_at, reauthorized_at),
    )

    account = store.save("Personal", "person@example.test", "{}", provider=ProviderKind.GOOGLE)
    disconnected = store.disconnect(account.id)
    listed_disconnected = store.list()
    reauthorized = store.save("Personal", "person@example.test", "{}", provider=ProviderKind.GOOGLE)

    assert account.authorized_at == connected_at.isoformat()
    assert disconnected.authorized_at is None
    assert [item.authorized_at for item in listed_disconnected] == [None]
    assert reauthorized.authorized_at == reauthorized_at.isoformat()
    fetched = store.get(account.id)
    assert fetched is not None
    assert fetched.authorized_at == reauthorized_at.isoformat()


def test_oauth_state_is_single_use(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    oauth = _oauth(database, store)

    oauth._store_state("synthetic-state")
    oauth._consume_state("synthetic-state")

    with pytest.raises(InvalidAuthorizationState, match="already used"):
        oauth._consume_state("synthetic-state")


def test_expired_oauth_state_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    oauth = _oauth(database, store)
    oauth._store_state("expired-state")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE oauth_states SET expires_at = ?",
            ("2000-01-01T00:00:00+00:00",),
        )

    with pytest.raises(InvalidAuthorizationState, match="expired"):
        oauth._consume_state("expired-state")


STORED = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


@dataclass
class MovableClock:
    moment: datetime

    def now(self) -> datetime:
        return self.moment


def _states(tmp_path: Path) -> tuple[SqliteAuthorizationStates, MovableClock]:
    database = tmp_path / "test.db"
    initialize_database(database)
    clock = MovableClock(STORED)
    return SqliteAuthorizationStates(database, clock), clock


def test_an_oauth_state_is_consumed_once_within_its_lifetime(tmp_path: Path) -> None:
    states, clock = _states(tmp_path)
    states.store("synthetic-state")

    clock.moment = STORED + STATE_LIFETIME - timedelta(seconds=1)
    assert states.consume("synthetic-state") is True
    assert states.consume("synthetic-state") is False


def test_an_oauth_state_is_rejected_once_its_lifetime_ends(tmp_path: Path) -> None:
    states, clock = _states(tmp_path)
    states.store("synthetic-state")

    clock.moment = STORED + STATE_LIFETIME
    assert states.consume("synthetic-state") is False


def test_pkce_verifier_survives_oauth_flow_reconstruction(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    master_key = CredentialCipher.generate_key()
    store = SqliteConnectedAccountStore(database, CredentialCipher(master_key))
    oauth = _oauth(
        database,
        store,
        OAuthClientConfig(
            "synthetic.apps.googleusercontent.com", "synthetic-secret", DEFAULT_REDIRECT_URI
        ),
        master_key=master_key,
    )
    state = "synthetic-state"

    start_flow = oauth._flow(state)
    authorization_url, _ = start_flow.authorization_url()
    callback_flow = oauth._flow(state)

    verifier = callback_flow.code_verifier
    assert verifier is not None
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    query = parse_qs(urlparse(authorization_url).query)
    assert start_flow.code_verifier == verifier
    assert verifier != state
    assert query["code_challenge"] == [expected_challenge]
    assert query["code_challenge_method"] == ["S256"]


def test_oauth_completion_exchanges_explicit_code_without_parsing_callback_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StubCredentials:
        granted_scopes = CALENDAR_SCOPES

        def to_json(self) -> str:
            return '{"token":"synthetic-token"}'

    class StubFlow:
        def __init__(self) -> None:
            self.credentials = StubCredentials()
            self.fetch_token_calls: list[dict[str, Any]] = []

        def fetch_token(self, **kwargs: Any) -> None:
            self.fetch_token_calls.append(kwargs)

    class StubCalendarRequest:
        def execute(self) -> dict[str, Any]:
            return {
                "items": [
                    {
                        "id": "person@example.test",
                        "summary": "Personal",
                        "primary": True,
                    }
                ]
            }

    class StubCalendarList:
        def list(self, *, pageToken: str | None = None) -> StubCalendarRequest:
            assert pageToken is None
            return StubCalendarRequest()

    class StubCalendarService:
        def calendarList(self) -> StubCalendarList:
            return StubCalendarList()

    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    oauth = _oauth(database, store)
    oauth._store_state("synthetic-state")
    flow = StubFlow()

    def fake_flow(state: str) -> StubFlow:
        assert state == "synthetic-state"
        return flow

    def fake_build(*args: Any, **kwargs: Any) -> StubCalendarService:
        assert args == ("calendar", "v3")
        assert kwargs["credentials"] is flow.credentials
        assert kwargs["cache_discovery"] is False
        return StubCalendarService()

    monkeypatch.setattr(oauth, "_flow", fake_flow)
    monkeypatch.setattr("calendar_sync.infrastructure.google.oauth.build", fake_build)

    account = oauth.complete("synthetic-state", "synthetic-code")

    assert flow.fetch_token_calls == [{"code": "synthetic-code"}]
    assert account.email == "person@example.test"


def _synthetic_id_token(claims: dict[str, Any]) -> str:
    def segment(value: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    return f"{segment({'alg': 'RS256', 'typ': 'JWT'})}.{segment(claims)}.c2lnbmF0dXJl"


def _complete_with_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    id_token: str | None,
    granted_scopes: tuple[str, ...],
) -> Any:
    class StubCredentials:
        def __init__(self) -> None:
            self.id_token = id_token
            self.granted_scopes = granted_scopes

        def to_json(self) -> str:
            return '{"token":"synthetic-token"}'

    class StubFlow:
        credentials = StubCredentials()

        def fetch_token(self, **kwargs: Any) -> None:
            assert kwargs == {"code": "synthetic-code"}

    class StubCalendarRequest:
        def execute(self) -> dict[str, Any]:
            return {
                "items": [{"id": "person@example.test", "summary": "Personal", "primary": True}]
            }

    class StubCalendarService:
        def calendarList(self) -> Any:
            return SimpleNamespace(list=lambda pageToken=None: StubCalendarRequest())

    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    oauth = _oauth(database, store)
    oauth._store_state("synthetic-state")
    monkeypatch.setattr(oauth, "_flow", lambda _: StubFlow())
    monkeypatch.setattr(
        "calendar_sync.infrastructure.google.oauth.build",
        lambda *args, **kwargs: StubCalendarService(),
    )
    return oauth.complete("synthetic-state", "synthetic-code")


def test_oauth_requests_calendar_and_basic_profile_scopes_only() -> None:
    assert OAUTH_SCOPES == CALENDAR_SCOPES + PROFILE_SCOPES
    assert PROFILE_SCOPES == ("openid", "https://www.googleapis.com/auth/userinfo.profile")


def test_oauth_token_exchange_accepts_a_grant_without_optional_profile_scopes() -> None:
    client = WebApplicationClient("synthetic.apps.googleusercontent.com")

    token = client.parse_request_body_response(
        json.dumps(
            {
                "access_token": "synthetic-token",
                "token_type": "Bearer",
                "scope": " ".join(CALENDAR_SCOPES),
            }
        ),
        scope=list(OAUTH_SCOPES),
    )

    assert set(token["scope"]) == set(CALENDAR_SCOPES)


def test_oauth_completion_records_google_profile_photo_and_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = _complete_with_identity(
        tmp_path,
        monkeypatch,
        id_token=_synthetic_id_token(
            {
                "name": "Person Example",
                "picture": "https://lh3.googleusercontent.com/a/synthetic=s96-c",
            }
        ),
        granted_scopes=OAUTH_SCOPES,
    )

    assert account.display_name == "Person Example"
    assert account.avatar_url == "https://lh3.googleusercontent.com/a/synthetic=s96-c"


def test_oauth_completion_connects_without_profile_consent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = _complete_with_identity(
        tmp_path, monkeypatch, id_token=None, granted_scopes=CALENDAR_SCOPES
    )

    assert account.display_name == "Personal"
    assert account.avatar_url is None


@pytest.mark.parametrize(
    "id_token",
    [
        "not-a-jwt",
        _synthetic_id_token({"picture": "http://example.test/photo.png"}),
        _synthetic_id_token({"picture": "javascript:alert(1)"}),
        _synthetic_id_token({"picture": 42, "name": ["not", "text"]}),
    ],
)
def test_oauth_completion_ignores_unusable_profile_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, id_token: str
) -> None:
    account = _complete_with_identity(
        tmp_path, monkeypatch, id_token=id_token, granted_scopes=OAUTH_SCOPES
    )

    assert account.display_name == "Personal"
    assert account.avatar_url is None


@pytest.mark.parametrize("granted_scopes", [(CALENDAR_SCOPES[0], *PROFILE_SCOPES), ()])
def test_oauth_completion_rejects_a_grant_without_all_calendar_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, granted_scopes: tuple[str, ...]
) -> None:
    class StubCredentials:
        pass

    StubCredentials.granted_scopes = granted_scopes  # type: ignore[attr-defined]

    class StubFlow:
        credentials = StubCredentials()

        def fetch_token(self, **kwargs: Any) -> None:
            assert kwargs == {"code": "synthetic-code"}

    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    oauth = _oauth(database, store)
    oauth._store_state("synthetic-state")
    monkeypatch.setattr(oauth, "_flow", lambda _: StubFlow())

    with pytest.raises(CalendarPermissionRequired, match="Calendar permission"):
        oauth.complete("synthetic-state", "synthetic-code")

    assert store.list() == ()


def test_access_check_verifies_calendar_list_and_event_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StubCalendarRequest:
        def execute(self) -> dict[str, Any]:
            return {
                "items": [
                    {"id": "primary@example.test", "primary": True, "accessRole": "owner"},
                    {"id": "shared@example.test", "accessRole": "reader"},
                ]
            }

    class StubCalendarList:
        def list(self, *, pageToken: str | None = None) -> StubCalendarRequest:
            assert pageToken is None
            return StubCalendarRequest()

    class StubEventRequest:
        def execute(self) -> dict[str, Any]:
            return {"items": [{"id": "synthetic-event-id"}]}

    class StubEvents:
        def list(self, **parameters: Any) -> StubEventRequest:
            assert parameters == {
                "calendarId": "primary@example.test",
                "maxResults": 1,
                "showDeleted": False,
                "singleEvents": False,
                "fields": "items(id)",
            }
            return StubEventRequest()

    class StubCalendarService:
        def calendarList(self) -> StubCalendarList:
            return StubCalendarList()

        def events(self) -> StubEvents:
            return StubEvents()

    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    oauth = _oauth(database, store)
    monkeypatch.setattr(oauth, "_credentials", lambda _: object())
    monkeypatch.setattr(
        "calendar_sync.infrastructure.google.oauth.build",
        lambda *args, **kwargs: StubCalendarService(),
    )

    access = oauth.verify_access(ConnectedAccountId("account-1"))

    assert access.calendars_visible == 2
    assert access.writable_calendars == 1


def test_access_check_explains_calendar_api_permission_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PermissionDenied(Exception):
        resp = SimpleNamespace(status=403)

    class StubCalendarRequest:
        def execute(self) -> dict[str, Any]:
            raise PermissionDenied

    class StubCalendarList:
        def list(self, *, pageToken: str | None = None) -> StubCalendarRequest:
            return StubCalendarRequest()

    class StubCalendarService:
        def calendarList(self) -> StubCalendarList:
            return StubCalendarList()

    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    oauth = _oauth(database, store)
    monkeypatch.setattr(oauth, "_credentials", lambda _: object())
    monkeypatch.setattr(
        "calendar_sync.infrastructure.google.oauth.build",
        lambda *args, **kwargs: StubCalendarService(),
    )

    with pytest.raises(AccountAccessCheckFailed, match="Calendar API is enabled"):
        oauth.verify_access(ConnectedAccountId("account-1"))


@pytest.mark.parametrize(
    ("status_code", "expected_detail"),
    [
        (401, "authorization has expired"),
        (None, "could not be verified; try again"),
    ],
)
def test_access_check_classifies_expired_and_unexpected_provider_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int | None,
    expected_detail: str,
) -> None:
    class ProviderFailure(Exception):
        resp = SimpleNamespace(status=status_code)

    class StubCalendarRequest:
        def execute(self) -> dict[str, Any]:
            raise ProviderFailure

    class StubCalendarList:
        def list(self, *, pageToken: str | None = None) -> StubCalendarRequest:
            assert pageToken is None
            return StubCalendarRequest()

    class StubCalendarService:
        def calendarList(self) -> StubCalendarList:
            return StubCalendarList()

    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    oauth = _oauth(database, store)
    monkeypatch.setattr(oauth, "_credentials", lambda _: object())
    monkeypatch.setattr(
        "calendar_sync.infrastructure.google.oauth.build",
        lambda *args, **kwargs: StubCalendarService(),
    )

    with pytest.raises(AccountAccessCheckFailed, match=expected_detail):
        oauth.verify_access(ConnectedAccountId("account-1"))


def test_access_check_rejects_an_account_without_visible_calendars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StubCalendarRequest:
        def execute(self) -> dict[str, Any]:
            return {"items": []}

    class StubCalendarList:
        def list(self, *, pageToken: str | None = None) -> StubCalendarRequest:
            assert pageToken is None
            return StubCalendarRequest()

    class StubCalendarService:
        def calendarList(self) -> StubCalendarList:
            return StubCalendarList()

    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    oauth = _oauth(database, store)
    monkeypatch.setattr(oauth, "_credentials", lambda _: object())
    monkeypatch.setattr(
        "calendar_sync.infrastructure.google.oauth.build",
        lambda *args, **kwargs: StubCalendarService(),
    )

    with pytest.raises(AccountAccessCheckFailed, match="did not expose a calendar"):
        oauth.verify_access(ConnectedAccountId("account-1"))


def test_connected_account_authorization_reflects_disconnection(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    account = store.save(
        "Work", "work@example.test", '{"refresh_token":"synthetic"}', provider=ProviderKind.GOOGLE
    )

    assert store.is_connected(account.id) is True
    store.disconnect(account.id)
    assert store.is_connected(account.id) is False
    assert store.is_connected(ConnectedAccountId("missing")) is False


def test_account_state_is_stored_under_its_existing_values(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    account = store.save("Work", "work@example.test", "{}", provider=ProviderKind.GOOGLE)
    store.disconnect(account.id)

    with sqlite3.connect(database) as connection:
        stored = connection.execute("SELECT state FROM connected_accounts").fetchone()[0]
    assert stored == "disconnected"
    assert store.get(account.id) == store.list()[0]
    assert store.list()[0].state is ConnectedAccountState.DISCONNECTED
    assert store.get(ConnectedAccountId("missing")) is None


@pytest.mark.parametrize(
    ("role", "access", "writable"),
    [
        ("owner", CalendarAccess.OWNER, True),
        ("writer", CalendarAccess.WRITER, True),
        ("reader", CalendarAccess.READER, False),
        ("freeBusyReader", CalendarAccess.FREE_BUSY, False),
        (None, CalendarAccess.READER, False),
        ("mysteryRole", CalendarAccess.READER, False),
    ],
)
def test_google_access_roles_translate_to_provider_neutral_access(
    role: str | None, access: CalendarAccess, writable: bool
) -> None:
    item = {"id": "family", "summary": "Family", "accessRole": role}

    calendar = discovered_calendar(item)

    assert calendar == DiscoveredCalendar("family", "Family", access=access, primary=False)
    assert calendar.writable is writable
