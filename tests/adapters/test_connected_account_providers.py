"""Each Connected Account belongs to one provider, recorded when it connects (ADR 0022)."""

import sqlite3
from pathlib import Path

from calendar_sync.application.ports import DiscoveredCalendar
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from calendar_sync.infrastructure.security import CredentialCipher
from tests.helpers import endpoint

ANOTHER_PROVIDERS_ACCOUNT = """
    INSERT INTO connected_accounts (
        id, provider, display_name, email, encrypted_credentials, state, created_at, updated_at
    ) VALUES (
        'elsewhere', 'another-provider', 'Elsewhere', 'person@example.test', x'00',
        'connected', '2026-10-01', '2026-10-01'
    )
"""


def _store(database: Path) -> SqliteConnectedAccountStore:
    initialize_database(database)
    return SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))


def test_a_connected_account_records_its_provider(tmp_path: Path) -> None:
    store = _store(tmp_path / "test.db")

    account = store.save("Personal", "person@example.test", "{}", provider=ProviderKind.GOOGLE)

    assert account.provider is ProviderKind.GOOGLE
    assert store.get(account.id) == account
    assert store.provider_of(account.id) is ProviderKind.GOOGLE


def test_an_account_that_does_not_exist_has_no_provider(tmp_path: Path) -> None:
    assert _store(tmp_path / "test.db").provider_of(ConnectedAccountId("missing")) is None


def test_reauthorization_finds_the_account_by_provider_and_email(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    store = _store(database)
    with sqlite3.connect(database) as connection:
        connection.execute(ANOTHER_PROVIDERS_ACCOUNT)

    google = store.save("Personal", "person@example.test", "{}", provider=ProviderKind.GOOGLE)
    again = store.save("Renamed", "person@example.test", "{}", provider=ProviderKind.GOOGLE)

    assert google.id.value != "elsewhere"
    assert (again.id, again.display_name) == (google.id, "Renamed")
    with sqlite3.connect(database) as connection:
        untouched = connection.execute(
            "SELECT display_name FROM connected_accounts WHERE id = 'elsewhere'"
        ).fetchone()
    assert untouched == ("Elsewhere",)


def test_migration_17_keeps_accounts_and_their_calendar_names(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    store = _store(database)
    account = store.save(
        "Personal",
        "person@example.test",
        '{"token":"one"}',
        provider=ProviderKind.GOOGLE,
        avatar_url="https://example.test/avatar.png",
    )
    family = endpoint(account.id.value, "family")
    with SqliteUnitOfWorkFactory(database)() as uow:
        uow.calendar_names.remember(
            account.id, [DiscoveredCalendar("family", "Family", writable=True, primary=False)]
        )
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 17")

    initialize_database(database)

    assert store.get(account.id) == account
    assert store.credential_json(account.id) == '{"token":"one"}'
    with SqliteUnitOfWorkFactory(database)() as uow:
        assert uow.calendar_names.names([family]) == {family: "Family"}


def test_any_provider_kind_can_be_stored(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    _store(database)

    with sqlite3.connect(database) as connection:
        connection.execute(ANOTHER_PROVIDERS_ACCOUNT)
        stored = connection.execute("SELECT provider FROM connected_accounts").fetchall()

    assert stored == [("another-provider",)]
