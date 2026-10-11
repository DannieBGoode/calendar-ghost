import base64
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from oauthlib.oauth2 import WebApplicationClient  # type: ignore[import-untyped]

from calendar_sync.application.errors import (
    AccountAccessCheckFailed,
    AuthorizationFailed,
    CalendarPermissionRequired,
)
from calendar_sync.application.ports import (
    CalendarAccess,
    DiscoveredCalendar,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.google.oauth import (
    CALENDAR_SCOPES,
    OAUTH_SCOPES,
    PROFILE_SCOPES,
    GoogleOAuthService,
    discovered_calendar,
)
from calendar_sync.infrastructure.oauth import OAuthClientConfig
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import (
    SqliteAuthorizationStates,
)
from calendar_sync.infrastructure.persistence.sqlite import initialize_database
from calendar_sync.infrastructure.security import CredentialCipher
from tests.users import OTHER_USER, USER, add_user

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


def test_oauth_completion_refuses_a_user_who_did_not_begin_the_flow(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    add_user(database)
    add_user(database, OTHER_USER, role="user")
    oauth = _oauth(database, store)
    SqliteAuthorizationStates(database).store("synthetic-state", USER, ProviderKind.GOOGLE)

    def no_exchange(state: str) -> None:
        raise AssertionError("the code must not be exchanged")

    oauth._flow = no_exchange  # type: ignore[method-assign]

    with pytest.raises(AuthorizationFailed):
        oauth.complete("synthetic-state", "synthetic-code", OTHER_USER)
    # The state is used up, so it cannot be tried again by anyone.
    assert (
        SqliteAuthorizationStates(database).consume("synthetic-state", ProviderKind.GOOGLE) is None
    )
    assert store.for_user(OTHER_USER).list() == ()
    assert store.for_user(USER).list() == ()


def test_pkce_verifier_survives_oauth_flow_reconstruction(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    master_key = CredentialCipher.generate_key()
    store = SqliteConnectedAccountStore(database, CredentialCipher(master_key))
    add_user(database)
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
    add_user(database)
    oauth = _oauth(database, store)
    SqliteAuthorizationStates(database).store("synthetic-state", USER, ProviderKind.GOOGLE)
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

    authorized = oauth.complete("synthetic-state", "synthetic-code", USER)

    assert flow.fetch_token_calls == [{"code": "synthetic-code"}]
    assert authorized.owner == USER
    assert authorized.account.email == "person@example.test"


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
    add_user(database)
    oauth = _oauth(database, store)
    SqliteAuthorizationStates(database).store("synthetic-state", USER, ProviderKind.GOOGLE)
    monkeypatch.setattr(oauth, "_flow", lambda _: StubFlow())
    monkeypatch.setattr(
        "calendar_sync.infrastructure.google.oauth.build",
        lambda *args, **kwargs: StubCalendarService(),
    )
    return oauth.complete("synthetic-state", "synthetic-code", USER).account


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
    add_user(database)
    oauth = _oauth(database, store)
    SqliteAuthorizationStates(database).store("synthetic-state", USER, ProviderKind.GOOGLE)
    monkeypatch.setattr(oauth, "_flow", lambda _: StubFlow())

    with pytest.raises(CalendarPermissionRequired, match="Calendar permission"):
        oauth.complete("synthetic-state", "synthetic-code", USER)

    assert store.for_user(USER).list() == ()


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
    add_user(database)
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
    add_user(database)
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
    add_user(database)
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
    add_user(database)
    oauth = _oauth(database, store)
    monkeypatch.setattr(oauth, "_credentials", lambda _: object())
    monkeypatch.setattr(
        "calendar_sync.infrastructure.google.oauth.build",
        lambda *args, **kwargs: StubCalendarService(),
    )

    with pytest.raises(AccountAccessCheckFailed, match="did not expose a calendar"):
        oauth.verify_access(ConnectedAccountId("account-1"))


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


def test_a_google_calendar_without_a_summary_is_labelled_by_its_id_but_unnamed() -> None:
    calendar = discovered_calendar({"id": "family@group.calendar.example.test", "summary": ""})

    assert calendar.summary == "family@group.calendar.example.test"
    assert not calendar.named


def test_a_user_disabled_during_the_token_exchange_connects_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    add_user(database)
    oauth = _oauth(database, store)
    SqliteAuthorizationStates(database).store("synthetic-state", USER, ProviderKind.GOOGLE)

    class StubCredentials:
        id_token = None
        granted_scopes = OAUTH_SCOPES

        def to_json(self) -> str:
            return '{"token":"synthetic-token"}'

    class StubFlow:
        credentials = StubCredentials()

        def fetch_token(self, **kwargs: Any) -> None:
            # An Installation Administrator disables the User while Google answers.
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE users SET state = 'disabled' WHERE id = ?", (USER.value,)
                )

    class StubCalendarRequest:
        def execute(self) -> dict[str, Any]:
            return {
                "items": [{"id": "person@example.test", "summary": "Personal", "primary": True}]
            }

    monkeypatch.setattr(oauth, "_flow", lambda _: StubFlow())
    monkeypatch.setattr(
        "calendar_sync.infrastructure.google.oauth.build",
        lambda *args, **kwargs: SimpleNamespace(
            calendarList=lambda: SimpleNamespace(list=lambda pageToken=None: StubCalendarRequest())
        ),
    )

    with pytest.raises(AuthorizationFailed):
        oauth.complete("synthetic-state", "synthetic-code", USER)
    assert store.for_user(USER).list() == ()
