"""Every SQLite connection opens through one module, with the installation's settings."""

import sqlite3
from pathlib import Path

import pytest

from calendar_sync.infrastructure.persistence.connections import open_connection, transaction
from calendar_sync.infrastructure.persistence.sqlite import initialize_database


def _database(tmp_path: Path) -> Path:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
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


def test_a_transaction_commits_and_closes(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with transaction(database) as connection:
        connection.execute(
            "INSERT INTO oauth_states(state_hash, created_at, expires_at) VALUES ('h', 'a', 'b')"
        )

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    with transaction(database) as reader:
        assert reader.execute("SELECT COUNT(*) FROM oauth_states").fetchone()[0] == 1


def _write_then_fail(database: Path, opened: list[sqlite3.Connection]) -> None:
    with transaction(database) as connection:
        opened.append(connection)
        connection.execute(
            "INSERT INTO oauth_states(state_hash, created_at, expires_at) VALUES ('h', 'a', 'b')"
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
