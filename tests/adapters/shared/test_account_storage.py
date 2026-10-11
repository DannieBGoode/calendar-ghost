"""Connected Accounts and their encrypted credentials, stored alike for every provider."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path

import pytest

from calendar_sync.application.errors import (
    ConnectedAccountDisconnected,
)
from calendar_sync.application.ports import (
    ConnectedAccountState,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.authorization_states import (
    STATE_LIFETIME,
    SqliteAuthorizationStates,
)
from calendar_sync.infrastructure.persistence.sqlite import initialize_database
from calendar_sync.infrastructure.security import CredentialCipher, InvalidMasterKey
from tests.adapters.test_user_migration import LATEST_VERSION
from tests.users import USER, add_user


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
    add_user(database)

    first = store.for_user(USER).save(
        "Personal", "person@example.test", '{"token":"one"}', provider=ProviderKind.GOOGLE
    )
    updated = store.for_user(USER).save(
        "Renamed", "person@example.test", '{"token":"two"}', provider=ProviderKind.GOOGLE
    )

    assert updated.id == first.id
    assert updated.display_name == "Renamed"
    assert len(store.for_user(USER).list()) == 1


def test_connected_account_avatar_round_trips_and_follows_reauthorization(
    tmp_path: Path,
) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    add_user(database)
    photo = "https://lh3.googleusercontent.com/a/synthetic=s96-c"

    saved = store.for_user(USER).save(
        "Person", "person@example.test", "{}", avatar_url=photo, provider=ProviderKind.GOOGLE
    )
    listed = store.for_user(USER).list()
    reauthorized = store.for_user(USER).save(
        "Person", "person@example.test", "{}", provider=ProviderKind.GOOGLE
    )

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
        connection.execute(
            "INSERT INTO installation_admin VALUES (1, 'scrypt$synthetic', '2026-01-01')"
        )

    initialize_database(database)
    initialize_database(database)

    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    with sqlite3.connect(database) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
        owner = UserId(str(connection.execute("SELECT id FROM users").fetchone()[0]))
    assert versions == list(range(1, LATEST_VERSION + 1))
    assert [(account.id.value, account.avatar_url) for account in store.for_user(owner).list()] == [
        ("existing", None)
    ]


def test_disconnect_discards_credentials_and_reauthorization_preserves_identity(
    tmp_path: Path,
) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    cipher = CredentialCipher(CredentialCipher.generate_key())
    store = SqliteConnectedAccountStore(database, cipher)
    add_user(database)
    account = store.for_user(USER).save(
        "Personal",
        "person@example.test",
        '{"refresh_token":"synthetic-secret"}',
        provider=ProviderKind.GOOGLE,
    )
    disconnected = store.for_user(USER).disconnect(account.id)

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

    reauthorized = store.for_user(USER).save(
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
    add_user(database)

    account = store.for_user(USER).save(
        "Personal", "person@example.test", "{}", provider=ProviderKind.GOOGLE
    )
    disconnected = store.for_user(USER).disconnect(account.id)
    listed_disconnected = store.for_user(USER).list()
    reauthorized = store.for_user(USER).save(
        "Personal", "person@example.test", "{}", provider=ProviderKind.GOOGLE
    )

    assert account.authorized_at == connected_at.isoformat()
    assert disconnected.authorized_at is None
    assert [item.authorized_at for item in listed_disconnected] == [None]
    assert reauthorized.authorized_at == reauthorized_at.isoformat()
    fetched = store.for_user(USER).get(account.id)
    assert fetched is not None
    assert fetched.authorized_at == reauthorized_at.isoformat()


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
    add_user(database)
    return SqliteAuthorizationStates(database, clock), clock


def test_an_oauth_state_is_consumed_once_within_its_lifetime(tmp_path: Path) -> None:
    states, clock = _states(tmp_path)
    states.store("synthetic-state", USER)

    clock.moment = STORED + STATE_LIFETIME - timedelta(seconds=1)
    assert states.consume("synthetic-state") == USER
    assert states.consume("synthetic-state") is None


def test_an_oauth_state_is_rejected_once_its_lifetime_ends(tmp_path: Path) -> None:
    states, clock = _states(tmp_path)
    states.store("synthetic-state", USER)

    clock.moment = STORED + STATE_LIFETIME
    assert states.consume("synthetic-state") is None


def test_an_oauth_state_of_a_disabled_user_cannot_be_used(tmp_path: Path) -> None:
    states, _ = _states(tmp_path)
    states.store("synthetic-state", USER)
    with sqlite3.connect(tmp_path / "test.db") as connection:
        connection.execute("UPDATE users SET state = 'disabled' WHERE id = ?", (USER.value,))

    assert states.consume("synthetic-state") is None


def test_connected_account_authorization_reflects_disconnection(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    add_user(database)
    account = store.for_user(USER).save(
        "Work", "work@example.test", '{"refresh_token":"synthetic"}', provider=ProviderKind.GOOGLE
    )

    assert store.for_user(USER).is_connected(account.id) is True
    store.for_user(USER).disconnect(account.id)
    assert store.for_user(USER).is_connected(account.id) is False
    assert store.for_user(USER).is_connected(ConnectedAccountId("missing")) is False


def test_account_state_is_stored_under_its_existing_values(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    add_user(database)
    account = store.for_user(USER).save(
        "Work", "work@example.test", "{}", provider=ProviderKind.GOOGLE
    )
    store.for_user(USER).disconnect(account.id)

    with sqlite3.connect(database) as connection:
        stored = connection.execute("SELECT state FROM connected_accounts").fetchone()[0]
    assert stored == "disconnected"
    assert store.for_user(USER).get(account.id) == store.for_user(USER).list()[0]
    assert store.for_user(USER).list()[0].state is ConnectedAccountState.DISCONNECTED
    assert store.for_user(USER).get(ConnectedAccountId("missing")) is None
