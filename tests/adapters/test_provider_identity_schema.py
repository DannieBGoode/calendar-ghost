"""Migration 39 preserves populated Users and enforces provider identity ownership."""

import sqlite3
from pathlib import Path

import pytest

from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.users import SqliteUserDirectory
from tests.adapters.test_user_migration import database_at_version
from tests.adapters.test_users_store import FIRST, SECOND
from tests.users import add_account


def test_upgrade_from_38_preserves_every_user_field_and_references(tmp_path: Path) -> None:
    path = tmp_path / "upgrade.db"
    database_at_version(path, 38)
    users = SqliteUserDirectory(path)
    users.add(FIRST, "existing-hash")
    users.add(SECOND, "other-hash")
    add_account(path, "calendar-account", SECOND.id)
    with transaction(path) as connection:
        connection.execute(
            "INSERT INTO plans VALUES "
            "('family', 'Family', 3, 2, 1, 'instant', 'created', 'updated')"
        )
        connection.execute(
            "UPDATE users SET language = 'en', notify_by_email = 0, instant_sync = 0, "
            "last_sign_in_at = 'last', plan_key = 'family', plan_assigned_by = 'administrator', "
            "plan_assigner_id = ?, plan_assigned_at = 'assigned', plan_holds_at = 'held', "
            "plan_grace_limit = 3, plan_grace_admissions = 2, plan_admissions = 5, "
            "credential_revision = 7 WHERE id = ?",
            (FIRST.id.value, SECOND.id.value),
        )
        connection.execute(
            "INSERT INTO user_sessions VALUES ('session', ?, 'start', 'end')", (SECOND.id.value,)
        )
        before_users = [dict(row) for row in connection.execute("SELECT * FROM users ORDER BY id")]
        before_schema = [
            tuple(row)
            for row in connection.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE tbl_name = 'users' AND type != 'table' ORDER BY name"
            )
        ]
        before_fks = [tuple(row) for row in connection.execute("PRAGMA foreign_key_list(users)")]
    initialize_database(path)
    initialize_database(path)
    with transaction(path) as connection:
        assert [
            dict(row) for row in connection.execute("SELECT * FROM users ORDER BY id")
        ] == before_users
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE tbl_name = 'users' AND type != 'table' ORDER BY name"
            )
        ] == before_schema
        assert [
            tuple(row) for row in connection.execute("PRAGMA foreign_key_list(users)")
        ] == before_fks
        assert (
            connection.execute("SELECT user_id FROM user_sessions").fetchone()[0] == SECOND.id.value
        )
        assert (
            connection.execute("SELECT user_id FROM connected_accounts").fetchone()[0]
            == SECOND.id.value
        )
        assert connection.execute("SELECT key FROM plans").fetchone()[0] == "family"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT * FROM provider_sign_in_settings").fetchall() == []
        connection.execute("UPDATE users SET password_hash = NULL WHERE id = ?", (SECOND.id.value,))
    assert users.password_hash(SECOND.id) is None


def test_provider_identity_uniqueness_and_cascade(tmp_path: Path) -> None:
    path = tmp_path / "schema.db"
    initialize_database(path)
    users = SqliteUserDirectory(path)
    users.add(FIRST, "hash")
    users.add(SECOND, "hash")
    with transaction(path) as connection:
        connection.execute(
            "INSERT INTO provider_identities VALUES "
            "('one', ?, 'alpha', 'issuer', 'subject', 'now')",
            (FIRST.id.value,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO provider_identities VALUES "
                "('two', ?, 'beta', 'issuer', 'subject', 'now')",
                (SECOND.id.value,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO provider_identities VALUES "
                "('three', 'missing', 'alpha', 'issuer', 'other', 'now')"
            )
        connection.execute("DELETE FROM users WHERE id = ?", (FIRST.id.value,))
        assert connection.execute("SELECT * FROM provider_identities").fetchall() == []
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_failure_rolls_back_users_and_ledger(tmp_path: Path) -> None:
    from calendar_sync.infrastructure.persistence.migrations import MigrationFailed

    path = tmp_path / "broken.db"
    database_at_version(path, 38)
    SqliteUserDirectory(path).add(FIRST, "retained")
    with transaction(path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("UPDATE users SET plan_key = 'missing'")
    with pytest.raises(MigrationFailed):
        initialize_database(path)
    with transaction(path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 38
        assert connection.execute("SELECT password_hash FROM users").fetchone()[0] == "retained"
        columns = {row[1]: bool(row[3]) for row in connection.execute("PRAGMA table_info(users)")}
        assert columns["password_hash"]
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'provider_identities'"
            ).fetchone()
            is None
        )
        connection.execute("UPDATE users SET plan_key = NULL")
    initialize_database(path)
