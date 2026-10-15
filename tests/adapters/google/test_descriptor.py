"""The Google package as bootstrap composes it: one descriptor (ADR 0022, ADR 0036)."""

from pathlib import Path

from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.google.descriptor import google_provider
from calendar_sync.infrastructure.google.watches import GoogleCalendarWatcher, GoogleNoticeReader
from calendar_sync.infrastructure.oauth import OAuthClientConfig
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import (
    SqliteAuthorizationStates,
)
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.security import CredentialCipher

CLIENT = OAuthClientConfig("client", "secret", "http://localhost:8000/api/v1/oauth/google/callback")


def test_google_watches_its_calendars_and_reads_their_notices(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    key = CredentialCipher.generate_key()
    store = SqliteConnectedAccountStore(database, CredentialCipher(key))

    descriptor = google_provider(
        CLIENT, store, SqliteAuthorizationStates(database), key, SystemClock()
    )

    assert descriptor.kind is ProviderKind.GOOGLE
    assert isinstance(descriptor.watcher, GoogleCalendarWatcher)
    assert isinstance(descriptor.notice_reader, GoogleNoticeReader)


def test_without_the_master_key_google_watches_nothing(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)

    descriptor = google_provider(
        CLIENT, None, SqliteAuthorizationStates(database), "", SystemClock()
    )

    assert (descriptor.watcher, descriptor.notice_reader) == (None, None)
