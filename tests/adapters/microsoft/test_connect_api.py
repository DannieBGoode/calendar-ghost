"""Connecting a Microsoft account through the Web API, as a browser does, against the fake."""

from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from calendar_sync.application.provider_descriptors import ProviderDirectory
from calendar_sync.application.providers import ProviderKind
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters, compose
from calendar_sync.infrastructure.microsoft.descriptor import microsoft_provider
from calendar_sync.infrastructure.microsoft.oauth import MicrosoftClient
from calendar_sync.infrastructure.oauth import OAuthClientConfig
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import (
    SqliteAuthorizationStates,
)
from calendar_sync.infrastructure.providers.routing import RoutingAccountCalendars
from calendar_sync.infrastructure.scheduling import SystemClock
from calendar_sync.infrastructure.security import CredentialCipher
from calendar_sync.interfaces.api.app import create_app
from tests.fake_microsoft_graph_api import CLIENT_ID, CLIENT_SECRET, FakeMicrosoftGraph
from tests.users import sign_in

REDIRECT = "http://localhost:8000/api/v1/oauth/microsoft/callback"


def _app(tmp_path: Path, graph: FakeMicrosoftGraph) -> TestClient:
    key = CredentialCipher.generate_key()
    settings = Settings(
        tmp_path / "test.db",
        master_key=key,
        microsoft_client_id=CLIENT_ID,
        microsoft_client_secret=CLIENT_SECRET,
    )
    adapters = build_adapters(settings)
    store = SqliteConnectedAccountStore(settings.database_path, CredentialCipher(key))
    # The descriptor bootstrap composes, reaching the fake instead of Microsoft.
    microsoft = microsoft_provider(
        MicrosoftClient(OAuthClientConfig(CLIENT_ID, CLIENT_SECRET, REDIRECT)),
        store,
        SqliteAuthorizationStates(settings.database_path),
        key,
        SystemClock(),
        graph.client(),
    )
    providers = ProviderDirectory(
        tuple(
            microsoft if descriptor.kind is ProviderKind.OUTLOOK else descriptor
            for descriptor in adapters.providers.descriptors
        )
    )
    adapters = replace(
        adapters,
        providers=providers,
        account_calendars=RoutingAccountCalendars.of(store, providers),
    )
    return TestClient(create_app(replace(compose(settings, adapters), scheduler=None)))


def test_a_configured_microsoft_provider_is_listed_with_how_to_connect(tmp_path: Path) -> None:
    with _app(tmp_path, FakeMicrosoftGraph()) as client:
        sign_in(client)
        providers = client.get("/api/v1/providers").json()

    (microsoft,) = [provider for provider in providers if provider["kind"] == "outlook"]
    assert microsoft["display_name"] == "Microsoft"
    assert microsoft["connect_url"] == "/api/v1/oauth/microsoft/start"
    assert microsoft["redirect_uri"] == REDIRECT
    assert "api_disabled" not in microsoft["cause_anchors"]


def test_a_browser_connects_a_microsoft_account_and_returns_to_connections(
    tmp_path: Path,
) -> None:
    graph = FakeMicrosoftGraph()
    graph.mailbox("person@example.test", display_name="Person", mail="person@example.test")

    with _app(tmp_path, graph) as client:
        sign_in(client)
        start = client.get("/api/v1/oauth/microsoft/start", follow_redirects=False)
        consent = start.headers["location"]
        code = graph.consent(consent, "person@example.test")
        state = parse_qs(urlparse(consent).query)["state"][0]
        returned = client.get(
            f"/api/v1/oauth/microsoft/callback?state={state}&code={code}", follow_redirects=False
        )
        accounts = client.get("/api/v1/accounts").json()

    assert start.status_code == 302
    assert consent.startswith("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?")
    assert returned.status_code == 303
    assert returned.headers["location"].startswith(
        "/settings/connections?oauth=connected&provider=outlook&account="
    )
    assert [(a["email"], a["provider"], a["state"]) for a in accounts] == [
        ("person@example.test", "outlook", "connected")
    ]


def test_a_google_state_returned_to_microsofts_callback_connects_nothing(
    tmp_path: Path,
) -> None:
    graph = FakeMicrosoftGraph()
    graph.mailbox("person@example.test")

    with _app(tmp_path, graph) as client:
        sign_in(client)
        returned = client.get(
            "/api/v1/oauth/microsoft/callback?state=a-state-of-another-flow&code=c",
            follow_redirects=False,
        )
        accounts = client.get("/api/v1/accounts").json()

    assert (returned.status_code, returned.json()["code"]) == (400, "invalid_authorization_state")
    assert accounts == []


def test_declining_consent_returns_to_connections_and_uses_the_state_up(tmp_path: Path) -> None:
    graph = FakeMicrosoftGraph()

    with _app(tmp_path, graph) as client:
        sign_in(client)
        start = client.get("/api/v1/oauth/microsoft/start", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        # Microsoft returns `consent_required` when a work account's organization must approve.
        declined = client.get(
            f"/api/v1/oauth/microsoft/callback?state={state}&error=consent_required",
            follow_redirects=False,
        )
        again = client.get(
            f"/api/v1/oauth/microsoft/callback?state={state}&error=access_denied",
            follow_redirects=False,
        )

    assert declined.headers["location"] == (
        "/settings/connections?oauth=calendar_permission_required&provider=outlook"
    )
    assert again.status_code == 400
