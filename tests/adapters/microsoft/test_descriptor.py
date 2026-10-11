"""The Microsoft package as bootstrap composes it: one descriptor (ADR 0022, ADR 0032)."""

from pathlib import Path

from calendar_sync.application.providers import ProviderKind
from calendar_sync.infrastructure.microsoft.descriptor import microsoft_provider
from calendar_sync.infrastructure.microsoft.oauth import MicrosoftClient, MicrosoftOAuthService
from calendar_sync.infrastructure.microsoft.provider import OutlookCalendarProvider
from calendar_sync.infrastructure.oauth import OAuthClientConfig
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import (
    SqliteAuthorizationStates,
)
from calendar_sync.infrastructure.persistence.sqlite import initialize_database
from calendar_sync.infrastructure.scheduling import SystemClock
from calendar_sync.infrastructure.security import CredentialCipher

REDIRECT = "http://localhost:8000/api/v1/oauth/microsoft/callback"
CONFIGURED = MicrosoftClient(OAuthClientConfig("client", "secret", REDIRECT))


def _store(tmp_path: Path) -> tuple[SqliteConnectedAccountStore, SqliteAuthorizationStates, str]:
    database = tmp_path / "test.db"
    initialize_database(database)
    key = CredentialCipher.generate_key()
    return (
        SqliteConnectedAccountStore(database, CredentialCipher(key)),
        SqliteAuthorizationStates(database),
        key,
    )


def test_a_configured_installation_gets_every_microsoft_role(tmp_path: Path) -> None:
    store, states, key = _store(tmp_path)

    descriptor = microsoft_provider(CONFIGURED, store, states, key, SystemClock())

    assert descriptor.kind is ProviderKind.OUTLOOK
    assert descriptor.connectable
    assert descriptor.connection is not None
    assert descriptor.connection.redirect_uri == REDIRECT
    assert isinstance(descriptor.calendars, MicrosoftOAuthService)
    assert isinstance(descriptor.provider, OutlookCalendarProvider)


def test_without_its_application_or_the_master_key_microsoft_offers_nothing(
    tmp_path: Path,
) -> None:
    store, states, key = _store(tmp_path)
    unregistered = MicrosoftClient(OAuthClientConfig("", "", REDIRECT))

    for descriptor in (
        microsoft_provider(unregistered, store, states, key, SystemClock()),
        microsoft_provider(CONFIGURED, None, states, "", SystemClock()),
    ):
        assert (descriptor.connection, descriptor.calendars, descriptor.provider) == (
            None,
            None,
            None,
        )
    assert not microsoft_provider(unregistered, store, states, key, SystemClock()).configured
