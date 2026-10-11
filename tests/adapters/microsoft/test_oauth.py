"""Connecting a Microsoft account: the authorization code flow with PKCE, bound to the User who
began it, least-privilege scopes, and rotating refresh tokens (ADR 0032)."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from calendar_sync.application.causes import Cause
from calendar_sync.application.errors import (
    AccountAccessCheckFailed,
    AuthorizationFailed,
    AuthorizationNotConfigured,
    CalendarPermissionRequired,
    InvalidAuthorizationState,
    ProviderFailureKind,
)
from calendar_sync.application.ports import CalendarAccess, DiscoveredCalendar
from calendar_sync.application.providers import ProviderKind
from calendar_sync.infrastructure.microsoft.oauth import (
    SCOPES,
    MicrosoftClient,
    MicrosoftOAuthService,
)
from calendar_sync.infrastructure.oauth import OAuthClientConfig, pkce_challenge
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import (
    SqliteAuthorizationStates,
)
from calendar_sync.infrastructure.persistence.sqlite import initialize_database
from calendar_sync.infrastructure.provider_calls import ContextProviderCallStats
from calendar_sync.infrastructure.security import CredentialCipher
from tests.fake_microsoft_graph_api import (
    FakeCalendar,
    FakeMicrosoftGraph,
    graph_error,
    token_error,
)
from tests.users import OTHER_USER, USER, add_user

NOW = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)
REDIRECT = "http://localhost:8000/api/v1/oauth/microsoft/callback"
KEY = CredentialCipher.generate_key()
ADDRESS = "person@example.test"


@dataclass
class Clock:
    moment: datetime = NOW

    def now(self) -> datetime:
        return self.moment


@dataclass
class Installation:
    graph: FakeMicrosoftGraph
    oauth: MicrosoftOAuthService
    store: SqliteConnectedAccountStore
    database: Path
    clock: Clock


@pytest.fixture
def installation(tmp_path: Path) -> Installation:
    database = tmp_path / "test.db"
    initialize_database(database)
    add_user(database)
    add_user(database, OTHER_USER, role="user")
    graph = FakeMicrosoftGraph()
    graph.mailbox(ADDRESS, display_name="Person", mail=ADDRESS)
    store = SqliteConnectedAccountStore(database, CredentialCipher(KEY))
    clock = Clock()
    client = MicrosoftClient(OAuthClientConfig(graph.client_id, graph.client_secret, REDIRECT))
    oauth = MicrosoftOAuthService(
        client, store, SqliteAuthorizationStates(database, clock), KEY, graph.client(), clock
    )
    return Installation(graph, oauth, store, database, clock)


def _query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


def _connect(installation: Installation, address: str = ADDRESS) -> str:
    """Begin the flow as USER, consent as `address`, and complete it; the account's id."""
    url = installation.oauth.authorization_url(USER)
    code = installation.graph.consent(url, address)
    authorized = installation.oauth.complete(_query(url)["state"], code, USER)
    return authorized.account.id.value


def test_consent_asks_any_account_for_least_privilege_scopes_with_pkce(
    installation: Installation,
) -> None:
    url = installation.oauth.authorization_url(USER, login_hint=ADDRESS)

    parsed, query = urlparse(url), _query(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    )
    assert query["scope"].split() == list(SCOPES)
    assert set(SCOPES) == {"openid", "email", "offline_access", "User.Read", "Calendars.ReadWrite"}
    assert (query["response_type"], query["response_mode"]) == ("code", "query")
    assert (query["client_id"], query["redirect_uri"]) == ("synthetic-client", REDIRECT)
    assert query["code_challenge_method"] == "S256"
    assert query["code_challenge"] == pkce_challenge(
        installation.oauth.code_verifier(query["state"])
    )
    assert query["login_hint"] == ADDRESS


def test_a_tenant_limits_which_accounts_may_sign_in(installation: Installation) -> None:
    graph = installation.graph
    client = MicrosoftClient(
        OAuthClientConfig(graph.client_id, graph.client_secret, REDIRECT), tenant="organizations"
    )
    oauth = MicrosoftOAuthService(
        client,
        installation.store,
        SqliteAuthorizationStates(installation.database),
        KEY,
        graph.client(),
        installation.clock,
    )

    assert urlparse(oauth.authorization_url(USER)).path == "/organizations/oauth2/v2.0/authorize"


def test_an_unconfigured_application_cannot_begin_a_flow(installation: Installation) -> None:
    oauth = MicrosoftOAuthService(
        MicrosoftClient(OAuthClientConfig("", "", REDIRECT)),
        installation.store,
        SqliteAuthorizationStates(installation.database),
        KEY,
        installation.graph.client(),
        installation.clock,
    )

    with pytest.raises(AuthorizationNotConfigured):
        oauth.authorization_url(USER)


def test_completing_connects_the_account_with_its_address_and_name(
    installation: Installation,
) -> None:
    account_id = _connect(installation)

    (account,) = installation.store.for_user(USER).list()
    assert account.id.value == account_id
    assert (account.email, account.display_name) == (ADDRESS, "Person")
    assert account.provider is ProviderKind.OUTLOOK
    # The code was exchanged with the verifier its challenge was made from.
    (exchange,) = installation.graph.token_requests
    assert exchange["grant_type"] == "authorization_code"
    assert exchange["code_verifier"]


def test_a_personal_account_without_mail_is_named_by_its_sign_in_address(
    installation: Installation,
) -> None:
    installation.graph.mailbox("person@outlook.example", display_name="Person", mail=None)

    _connect(installation, "person@outlook.example")

    assert [account.email for account in installation.store.for_user(USER).list()] == [
        "person@outlook.example"
    ]


def test_the_stored_credentials_are_encrypted_and_never_hold_the_secret(
    installation: Installation,
) -> None:
    _connect(installation)

    with sqlite3.connect(installation.database) as connection:
        (stored,) = connection.execute(
            "SELECT encrypted_credentials FROM connected_accounts"
        ).fetchone()
    assert b"refresh_token" not in stored
    (account,) = installation.store.for_user(USER).list()
    credentials = json.loads(installation.store.credential_json(account.id))
    assert set(credentials) >= {"access_token", "refresh_token", "expires_at"}
    assert "synthetic-secret" not in json.dumps(credentials)


def test_a_consent_link_another_user_opens_connects_nothing(installation: Installation) -> None:
    url = installation.oauth.authorization_url(USER)
    code = installation.graph.consent(url, ADDRESS)

    with pytest.raises(AuthorizationFailed):
        installation.oauth.complete(_query(url)["state"], code, OTHER_USER)

    # The state is used up and the code was never exchanged.
    assert installation.graph.token_requests == []
    with pytest.raises(InvalidAuthorizationState):
        installation.oauth.complete(_query(url)["state"], code, USER)
    assert installation.store.for_user(OTHER_USER).list() == ()
    assert installation.store.for_user(USER).list() == ()


def test_a_user_disabled_during_the_flow_connects_nothing(installation: Installation) -> None:
    url = installation.oauth.authorization_url(USER)
    code = installation.graph.consent(url, ADDRESS)
    with sqlite3.connect(installation.database) as connection:
        connection.execute("UPDATE users SET state = 'disabled' WHERE id = ?", (USER.value,))

    with pytest.raises(InvalidAuthorizationState):
        installation.oauth.complete(_query(url)["state"], code, USER)
    assert installation.store.for_user(USER).list() == ()


def test_a_user_disabled_while_microsoft_answers_connects_nothing(
    installation: Installation,
) -> None:
    url = installation.oauth.authorization_url(USER)
    code = installation.graph.consent(url, ADDRESS)
    answer = installation.graph.handle

    def disable_then_answer(request: object) -> object:
        with sqlite3.connect(installation.database) as connection:
            connection.execute("UPDATE users SET state = 'disabled' WHERE id = ?", (USER.value,))
        return answer(request)  # type: ignore[arg-type]

    installation.graph.handle = disable_then_answer  # type: ignore[method-assign,assignment]

    with pytest.raises(AuthorizationFailed):
        installation.oauth.complete(_query(url)["state"], code, USER)
    assert installation.store.for_user(USER).list() == ()


def test_a_grant_without_calendar_access_connects_nothing(installation: Installation) -> None:
    url = installation.oauth.authorization_url(USER)
    code = installation.graph.consent(url, ADDRESS, scope="openid email offline_access User.Read")

    with pytest.raises(CalendarPermissionRequired):
        installation.oauth.complete(_query(url)["state"], code, USER)
    assert installation.store.for_user(USER).list() == ()


def test_a_refused_code_exchange_connects_nothing(installation: Installation) -> None:
    url = installation.oauth.authorization_url(USER)
    installation.graph.consent(url, ADDRESS)

    with pytest.raises(AuthorizationFailed):
        installation.oauth.complete(_query(url)["state"], "a-code-microsoft-never-issued", USER)
    assert installation.store.for_user(USER).list() == ()


def test_cancelling_uses_the_state_up(installation: Installation) -> None:
    state = _query(installation.oauth.authorization_url(USER))["state"]

    installation.oauth.cancel(state)

    with pytest.raises(InvalidAuthorizationState):
        installation.oauth.cancel(state)


def test_calendars_are_listed_with_what_the_account_may_do_with_them(
    installation: Installation,
) -> None:
    box = installation.graph.mailboxes[ADDRESS]
    box.calendars = [
        FakeCalendar("calendar-default", "Calendar", default=True),
        FakeCalendar("calendar-shared", "Family", can_edit=False),
        FakeCalendar("calendar-unnamed", None),
    ]
    account_id = _connect(installation)

    calendars = installation.oauth.calendars(installation.store.for_user(USER).list()[0].id)

    assert account_id
    assert calendars == (
        DiscoveredCalendar("calendar-default", "Calendar", CalendarAccess.WRITER, primary=True),
        DiscoveredCalendar("calendar-shared", "Family", CalendarAccess.READER, primary=False),
        DiscoveredCalendar(
            "calendar-unnamed",
            "calendar-unnamed",
            CalendarAccess.WRITER,
            primary=False,
            named=False,
        ),
    )


def test_an_expired_access_token_is_refreshed_once_and_the_rotated_one_kept(
    installation: Installation,
) -> None:
    _connect(installation)
    (account,) = installation.store.for_user(USER).list()
    before = json.loads(installation.store.credential_json(account.id))
    installation.clock.moment = NOW + timedelta(hours=2)

    with ContextProviderCallStats().measure() as tally:
        installation.oauth.calendars(account.id)
        installation.oauth.calendars(account.id)

    after = json.loads(installation.store.credential_json(account.id))
    refreshes = [r for r in installation.graph.token_requests if r["grant_type"] == "refresh_token"]
    assert len(refreshes) == 1
    assert refreshes[0]["refresh_token"] == before["refresh_token"]
    # Microsoft rotates the refresh token on every use; the new one is what works next.
    assert after["refresh_token"] != before["refresh_token"]
    assert after["access_token"] != before["access_token"]
    assert tally.token_refreshes == 1


def test_an_access_check_counts_calendars_and_writable_ones(installation: Installation) -> None:
    installation.graph.mailboxes[ADDRESS].calendars = [
        FakeCalendar("calendar-default", "Calendar", default=True),
        FakeCalendar("calendar-shared", "Family", can_edit=False),
    ]
    _connect(installation)
    (account,) = installation.store.for_user(USER).list()

    access = installation.oauth.verify_access(account.id)

    assert (access.calendars_visible, access.writable_calendars) == (2, 1)


@pytest.mark.parametrize(
    ("refusal", "kind"),
    [
        (token_error("invalid_grant", 70008), ProviderFailureKind.AUTHENTICATION),
        (token_error("interaction_required", 50076), ProviderFailureKind.AUTHENTICATION),
        (token_error("invalid_client", 7000222, status=401), ProviderFailureKind.AUTHENTICATION),
        (token_error("temporarily_unavailable", 0, status=503), ProviderFailureKind.TEMPORARY),
    ],
)
def test_an_access_check_whose_refresh_is_refused_says_how(
    installation: Installation, refusal: object, kind: ProviderFailureKind
) -> None:
    _connect(installation)
    (account,) = installation.store.for_user(USER).list()
    installation.clock.moment = NOW + timedelta(hours=2)
    installation.graph.refuse(refusal)  # type: ignore[arg-type]

    with pytest.raises(AccountAccessCheckFailed) as failed:
        installation.oauth.verify_access(account.id)

    assert failed.value.kind is kind
    assert "private-marker" not in str(failed.value)


def test_an_access_check_microsoft_refuses_records_why(installation: Installation) -> None:
    _connect(installation)
    (account,) = installation.store.for_user(USER).list()
    installation.clock.moment = NOW + timedelta(hours=2)
    installation.graph.refuse(token_error("invalid_client", 7000222, status=401))

    with pytest.raises(AccountAccessCheckFailed) as failed:
        installation.oauth.verify_access(account.id)

    assert failed.value.cause is Cause.OAUTH_CLIENT_INVALID


@pytest.mark.parametrize(
    ("status", "code", "kind"),
    [
        (401, "InvalidAuthenticationToken", ProviderFailureKind.AUTHENTICATION),
        (403, "ErrorAccessDenied", ProviderFailureKind.AUTHORIZATION),
        (503, "ServiceNotAvailable", ProviderFailureKind.TEMPORARY),
    ],
)
def test_an_access_check_graph_refuses_says_how(
    installation: Installation, status: int, code: str, kind: ProviderFailureKind
) -> None:
    _connect(installation)
    (account,) = installation.store.for_user(USER).list()
    installation.graph.refuse(graph_error(status, code))

    with pytest.raises(AccountAccessCheckFailed) as failed:
        installation.oauth.verify_access(account.id)

    assert failed.value.kind is kind
    assert "private-marker" not in str(failed.value)
