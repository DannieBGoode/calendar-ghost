"""Every SQLite connection opens through one module, with the installation's settings."""

import sqlite3
from contextlib import closing
from datetime import timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest

from calendar_sync.application.errors import ProviderFailureKind
from calendar_sync.infrastructure.persistence import sqlite as sqlite_persistence
from calendar_sync.infrastructure.persistence.authorization_states import SqliteAuthorizationStates
from calendar_sync.infrastructure.persistence.connections import open_connection, transaction
from calendar_sync.infrastructure.persistence.health import SqliteRuleHealthRecords
from calendar_sync.infrastructure.persistence.sqlite import (
    initialize_database,
)
from tests.helpers import NOW, rule
from tests.users import USER, add_user, sqlite_units


def _database(tmp_path: Path) -> Path:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    add_user(database)
    return database


def test_a_connection_enforces_foreign_keys_and_names_columns(tmp_path: Path) -> None:
    connection = open_connection(_database(tmp_path))
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        row = connection.execute("SELECT 1 AS answer").fetchone()
        assert row["answer"] == 1
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO sync_cursors(rule_id, cursor) VALUES ('missing-rule', 'c')"
            )
    finally:
        connection.close()


def test_a_writer_commits_while_a_reader_holds_its_snapshot(tmp_path: Path) -> None:
    # In SQLite's default rollback journal, an open read keeps any writer from committing, so a
    # Web UI request could fail a Sync Run's write; write-ahead logging lets both proceed.
    database = _database(tmp_path)
    with (
        closing(open_connection(database, isolation_level=None)) as reader,
        closing(open_connection(database, timeout=0)) as writer,
    ):
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM oauth_states").fetchone()
        with writer:
            writer.execute(
                "INSERT INTO oauth_states(state_hash, user_id, created_at, expires_at) "
                "VALUES ('h', 'user-1', 'a', 'b')"
            )
        # The reader still sees the database as it was when its read began.
        assert reader.execute("SELECT COUNT(*) FROM oauth_states").fetchone()[0] == 0
        reader.execute("COMMIT")
        assert reader.execute("SELECT COUNT(*) FROM oauth_states").fetchone()[0] == 1


def test_a_transaction_commits_and_closes(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with transaction(database) as connection:
        connection.execute(
            "INSERT INTO oauth_states(state_hash, user_id, created_at, expires_at) "
            "VALUES ('h', 'user-1', 'a', 'b')"
        )

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    with transaction(database) as reader:
        assert reader.execute("SELECT COUNT(*) FROM oauth_states").fetchone()[0] == 1


def _write_then_fail(database: Path, opened: list[sqlite3.Connection]) -> None:
    with transaction(database) as connection:
        opened.append(connection)
        connection.execute(
            "INSERT INTO oauth_states(state_hash, user_id, created_at, expires_at) "
            "VALUES ('h', 'user-1', 'a', 'b')"
        )
        raise RuntimeError("stop")


def test_a_failed_transaction_rolls_back_and_closes(tmp_path: Path) -> None:
    database = _database(tmp_path)
    opened: list[sqlite3.Connection] = []

    with pytest.raises(RuntimeError):
        _write_then_fail(database, opened)

    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("SELECT 1")
    with transaction(database) as reader:
        assert reader.execute("SELECT COUNT(*) FROM oauth_states").fetchone()[0] == 0


def _orphan_at_commit(database: Path, opened: list[sqlite3.Connection]) -> None:
    with transaction(database) as connection:
        opened.append(connection)
        # Deferred, the foreign key is checked at commit, so the commit itself fails.
        connection.execute("PRAGMA defer_foreign_keys = ON")
        connection.execute("INSERT INTO sync_cursors(rule_id, cursor) VALUES ('missing', 'c')")


def test_a_transaction_whose_commit_fails_closes(tmp_path: Path) -> None:
    database = _database(tmp_path)
    opened: list[sqlite3.Connection] = []

    with pytest.raises(sqlite3.IntegrityError):
        _orphan_at_commit(database, opened)

    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("SELECT 1")


class _UnconfigurableConnection:
    """Stands in for a connection that opens but rejects its settings."""

    row_factory: object = None
    closed = False

    def execute(self, sql: str) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    def close(self) -> None:
        self.closed = True


def test_a_connection_that_cannot_be_configured_is_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unconfigurable = _UnconfigurableConnection()
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: unconfigurable)

    with pytest.raises(sqlite3.OperationalError):
        open_connection(tmp_path / "calendar-sync.db")

    assert unconfigurable.closed


SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "calendar_sync"


def test_only_the_connection_module_opens_sqlite() -> None:
    # The shipped package only; scripts/dev_preview.py seeds a throwaway preview database.
    opening = sorted(
        str(path.relative_to(SOURCE_ROOT))
        for path in SOURCE_ROOT.rglob("*.py")
        if "sqlite3.connect(" in path.read_text()
    )
    assert opening == ["infrastructure/persistence/connections.py"]


def test_consecutive_failures_of_an_existing_rule_are_counted(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with sqlite_units(database)() as uow:
        uow.rules.add(rule())
        uow.commit()
    records = SqliteRuleHealthRecords(database, add_user(database))
    later = NOW + timedelta(minutes=5)

    assert records.record_failure(rule().id, ProviderFailureKind.TEMPORARY, NOW) == 1
    assert records.record_failure(rule().id, ProviderFailureKind.RATE_LIMIT, later) == 2

    with transaction(database) as connection:
        row = connection.execute("SELECT * FROM rule_failures").fetchone()
    assert (row["consecutive_failures"], row["last_category"], row["updated_at"]) == (
        2,
        "rate_limit",
        later.isoformat(),
    )


def test_a_failure_for_a_removed_rule_is_counted_without_a_record(tmp_path: Path) -> None:
    database = _database(tmp_path)
    records = SqliteRuleHealthRecords(database, add_user(database))

    assert records.record_failure(rule().id, ProviderFailureKind.TEMPORARY, NOW) == 1
    assert records.record_failure(rule().id, ProviderFailureKind.TEMPORARY, NOW) == 1
    with transaction(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM rule_failures").fetchone()[0] == 0


def test_an_orphaned_failure_count_from_an_earlier_release_is_left_alone(tmp_path: Path) -> None:
    database = _database(tmp_path)
    # Earlier releases wrote failures without enforcing foreign keys, so a row may outlive its rule.
    with closing(sqlite3.connect(database)) as legacy, legacy:
        legacy.execute(
            "INSERT INTO rule_failures(rule_id, user_id, consecutive_failures, last_category, "
            "updated_at) VALUES (?, 'user-1', 2, 'temporary', ?)",
            (rule().id.value, NOW.isoformat()),
        )

    records = SqliteRuleHealthRecords(database, add_user(database))
    later = NOW + timedelta(minutes=5)

    assert records.record_failure(rule().id, ProviderFailureKind.RATE_LIMIT, later) == 1
    assert records.record_failure(rule().id, ProviderFailureKind.RATE_LIMIT, later) == 1
    with transaction(database) as connection:
        row = connection.execute("SELECT * FROM rule_failures").fetchone()
    assert (row["consecutive_failures"], row["last_category"], row["updated_at"]) == (
        2,
        "temporary",
        NOW.isoformat(),
    )


def test_an_adapter_write_that_fails_releases_the_database(tmp_path: Path) -> None:
    database = _database(tmp_path)
    states = SqliteAuthorizationStates(database)
    states.store("state-1", USER)

    with pytest.raises(sqlite3.IntegrityError) as failure:
        states.store("state-1", USER)

    # The traceback keeps the failed call's frames alive, so a connection it left open, with its
    # write lock, would still be held here; a writer that does not wait proves it was released.
    assert failure.value is not None
    with closing(open_connection(database, timeout=0)) as writer, writer:
        writer.execute("DELETE FROM oauth_states")
    states.store("state-2", USER)
    assert states.consume("state-2")


class _Text:
    def __init__(self, text: str) -> None:
        self._text = text

    def read_text(self) -> str:
        return self._text


class _MigrationsWithAFailure:
    """The shipped migrations, plus one that creates a table and then fails."""

    NAME = "9999_fails_halfway.sql"

    def __init__(self, shipped: Any) -> None:
        self._shipped = shipped

    def joinpath(self, name: str) -> Any:
        if name == self.NAME:
            return _Text("CREATE TABLE half_done (id INTEGER);\nINSERT INTO missing VALUES (1);")
        return self._shipped.joinpath(name)


def test_a_migration_that_fails_leaves_no_partial_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(tmp_path)
    with closing(open_connection(database)) as connection:
        applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
    monkeypatch.setattr(
        sqlite_persistence,
        "_FORWARD_MIGRATIONS",
        (*sqlite_persistence._FORWARD_MIGRATIONS, (9999, _MigrationsWithAFailure.NAME)),
    )
    monkeypatch.setattr(
        sqlite_persistence, "files", lambda package: _MigrationsWithAFailure(files(package))
    )

    with pytest.raises(sqlite3.OperationalError):
        initialize_database(database)

    with closing(open_connection(database, timeout=0)) as connection, connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
        versions = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
        # The database is not left locked by the failed upgrade.
        connection.execute("DELETE FROM oauth_states")
    assert "half_done" not in tables
    assert versions == applied
