"""Each Connected Account belongs to one provider, recorded when it connects (ADR 0022)."""

import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest

from calendar_sync.application.ports import CalendarAccess, DiscoveredCalendar
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.persistence import sqlite as sqlite_module
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from calendar_sync.infrastructure.security import CredentialCipher
from tests.helpers import endpoint

# Timestamps a version-16 installation would have written: distinct per account, so a copy/paste
# mistake between the two rows would show up as a wrong value rather than a coincidental match.
_PERSONAL_CREATED_AT = "2026-01-01T00:00:00+00:00"
_PERSONAL_UPDATED_AT = "2026-01-02T00:00:00+00:00"
_DISCONNECTED_CREATED_AT = "2026-02-01T00:00:00+00:00"
_DISCONNECTED_UPDATED_AT = "2026-02-03T00:00:00+00:00"


def _populate_version_16_database(connection: sqlite3.Connection) -> None:
    """Writes rows the shape version-16 code produced, directly through SQL.

    Covers a connected account with an avatar, a disconnected account with synthetic credential
    bytes, each account's remembered calendar names, a rule using both accounts, an event mapping
    for that rule, and the rule's sync cursor -- every table a version-16 installation could have
    populated before migration 17 existed.
    """
    connection.execute(
        """
        INSERT INTO connected_accounts (
            id, provider, display_name, email, encrypted_credentials, state,
            created_at, updated_at, avatar_url
        ) VALUES (?, 'google', ?, ?, ?, 'connected', ?, ?, ?)
        """,
        (
            "personal",
            "Personal",
            "person@example.test",
            b"synthetic-credential-bytes-personal",
            _PERSONAL_CREATED_AT,
            _PERSONAL_UPDATED_AT,
            "https://example.test/avatar.png",
        ),
    )
    connection.execute(
        """
        INSERT INTO connected_accounts (
            id, provider, display_name, email, encrypted_credentials, state,
            created_at, updated_at, avatar_url
        ) VALUES (?, 'google', ?, ?, ?, 'disconnected', ?, ?, NULL)
        """,
        (
            "disconnected",
            "Old Work",
            "old-work@example.test",
            b"synthetic-credential-bytes-disconnected",
            _DISCONNECTED_CREATED_AT,
            _DISCONNECTED_UPDATED_AT,
        ),
    )
    connection.execute(
        """
        INSERT INTO calendar_names (connected_account_id, calendar_id, name, updated_at)
        VALUES ('personal', 'family', 'Family', ?)
        """,
        (_PERSONAL_UPDATED_AT,),
    )
    connection.execute(
        """
        INSERT INTO calendar_names (connected_account_id, calendar_id, name, updated_at)
        VALUES ('disconnected', 'old-work-cal', 'Old Work Calendar', ?)
        """,
        (_DISCONNECTED_UPDATED_AT,),
    )
    connection.execute(
        """
        INSERT INTO sync_rules (
            id, source_account_id, source_calendar_id,
            destination_account_id, destination_calendar_id,
            privacy_policy, all_day_policy, busy_title,
            initial_lookback_days, state, reprojection_required,
            tentative_policy, unanswered_policy
        ) VALUES (
            'rule-1', 'personal', 'family', 'disconnected', 'old-work-cal',
            'busy_only', 'include', 'Busy', 30, 'enabled', 0, 'mark', 'as_tentative'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO event_mappings (
            id, rule_id, source_account_id, source_calendar_id, source_event_id,
            destination_account_id, destination_calendar_id, destination_event_id,
            source_revision, projection_fingerprint
        ) VALUES (
            'mapping-1', 'rule-1', 'personal', 'family', 'event-1',
            'disconnected', 'old-work-cal', 'projected-event-1', 'revision-1', 'fingerprint-1'
        )
        """
    )
    connection.execute("INSERT INTO sync_cursors (rule_id, cursor) VALUES ('rule-1', 'cursor-1')")
    connection.commit()


def _table_names(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "AND name != 'schema_migrations' ORDER BY name"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _snapshot(connection: sqlite3.Connection) -> dict[str, list[tuple[object, ...]]]:
    """Every row of every table but schema_migrations, order-independent, exact values kept."""
    return {
        table: sorted(
            (tuple(row) for row in connection.execute(f"SELECT * FROM {table}")), key=repr
        )
        for table in _table_names(connection)
    }


def _table_sql(connection: sqlite3.Connection, table: str) -> str | None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return str(row[0]) if row else None


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
            account.id,
            [DiscoveredCalendar("family", "Family", access=CalendarAccess.OWNER, primary=False)],
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


def test_migration_17_upgrades_a_genuine_version_16_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Migration 17 (ADR 0022) runs against a database that never knew it would exist.

    The regression this guards: a prior test only re-ran migration 17 on top of a database the
    current code had already fully migrated, so it could not prove migration 17 works against the
    rows and schema a real version-16 installation actually had. This test builds that database
    with raw SQL, confirms the superseded CHECK constraint is genuinely there, then migrates for
    real and confirms every row, and the schema's foreign-key integrity, survive unchanged.
    """
    database = tmp_path / "test.db"
    original_migrations = sqlite_module._FORWARD_MIGRATIONS
    monkeypatch.setattr(sqlite_module, "_FORWARD_MIGRATIONS", original_migrations[:-1])

    initialize_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        version_16_check = _table_sql(connection, "connected_accounts")
        assert version_16_check is not None
        assert "CHECK (provider = 'google')" in version_16_check

        _populate_version_16_database(connection)
        before = _snapshot(connection)

    monkeypatch.setattr(sqlite_module, "_FORWARD_MIGRATIONS", original_migrations)

    initialize_database(database)

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        applied = {
            int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")
        }
        after = _snapshot(connection)
        after_check = _table_sql(connection, "connected_accounts")
        fk_problems = connection.execute("PRAGMA foreign_key_check").fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        leftover_tables = set(_table_names(connection)) & {
            "calendar_names_kept",
            "connected_accounts_rebuilt",
        }

        assert 17 in applied
        assert after == before
        assert after_check is not None
        assert "CHECK" not in after_check
        assert fk_problems == []
        assert integrity == "ok"
        assert leftover_tables == set()

        # The source rows for calendar_names' ON DELETE CASCADE: deleting the disconnected
        # account's row removes only its own calendar names, not the connected account's.
        cursor = connection.execute(
            "DELETE FROM connected_accounts WHERE id = 'disconnected' AND state = 'disconnected'"
        )
        assert cursor.rowcount == 1
        connection.commit()
        remaining_names = connection.execute(
            "SELECT connected_account_id, calendar_id FROM calendar_names"
        ).fetchall()

    assert remaining_names == [("personal", "family")]


def test_an_injected_failure_during_migration_17_rolls_back_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A migration 17 that fails partway must leave the version-16 database untouched.

    Migration 17 rebuilds connected_accounts and calendar_names, so a failure partway through
    (a disk error, an unexpected row, anything) must not leave the database with the old table
    dropped and the new one missing or half-populated. `initialize_database` wraps each migration
    in an explicit transaction for exactly this reason; this test injects a failing statement at
    the end of migration 17's real SQL and confirms the whole migration rolls back.
    """
    database = tmp_path / "test.db"
    original_migrations = sqlite_module._FORWARD_MIGRATIONS
    monkeypatch.setattr(sqlite_module, "_FORWARD_MIGRATIONS", original_migrations[:-1])

    initialize_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        _populate_version_16_database(connection)
        before = _snapshot(connection)
        before_check = _table_sql(connection, "connected_accounts")
    assert before_check is not None
    assert "CHECK (provider = 'google')" in before_check

    monkeypatch.setattr(sqlite_module, "_FORWARD_MIGRATIONS", original_migrations)

    real_migrations = files("calendar_sync.infrastructure.persistence")
    good_sql = real_migrations.joinpath("0017_provider_kinds.sql").read_text()
    broken_sql = f"{good_sql}\nSELECT * FROM table_that_does_not_exist;\n"

    class _BrokenFile:
        def __init__(self, text: str) -> None:
            self._text = text

        def read_text(self) -> str:
            return self._text

    class _BrokenMigrations:
        def joinpath(self, name: str) -> object:
            if name == "0017_provider_kinds.sql":
                return _BrokenFile(broken_sql)
            return real_migrations.joinpath(name)

    monkeypatch.setattr(sqlite_module, "files", lambda _package: _BrokenMigrations())

    with pytest.raises(sqlite3.Error):
        initialize_database(database)

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        after_check = _table_sql(connection, "connected_accounts")
        after = _snapshot(connection)

    assert version == 16
    assert after_check == before_check
    assert after == before
