"""Migration 21 turns the single administrator's installation into one owned by User #1."""

import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest

from calendar_sync.application.errors import IncorrectCredentials
from calendar_sync.application.identity import SetOwnEmail, SignIn
from calendar_sync.infrastructure.persistence import sqlite as sqlite_module
from calendar_sync.infrastructure.persistence.sqlite import MigrationFailed, initialize_database
from calendar_sync.infrastructure.persistence.users import SqliteSessions, SqliteUserDirectory
from calendar_sync.infrastructure.scheduling import SystemClock
from calendar_sync.infrastructure.security import ScryptPasswords, hash_password
from calendar_sync.infrastructure.throttle import MemorySignInThrottle

ADMIN_HASH = "scrypt$stored-admin-hash"
LATEST_VERSION = max(version for version, _ in sqlite_module._FORWARD_MIGRATIONS)
OWNED_TABLES = (
    "connected_accounts",
    "calendar_names",
    "sync_rules",
    "event_mappings",
    "occurrence_mappings",
    "pending_exception_replays",
    "sync_cursors",
    "destination_sync_cursors",
    "rule_run_outcomes",
    "rule_previews",
    "rule_block_checks",
    "rule_failures",
    "source_observations",
    "audit_entries",
    "incidents",
    "integration_tokens",
    "user_sessions",
)


def database_at_version(path: Path, version: int) -> None:
    """A database migrated only as far as `version`, as an earlier release left it."""
    migrations = files("calendar_sync.infrastructure.persistence")
    names = sorted(
        entry.name
        for entry in migrations.iterdir()
        if entry.name.endswith(".sql") and int(entry.name[:4]) <= version
    )
    with sqlite3.connect(path) as connection:
        for name in names:
            connection.executescript(migrations.joinpath(name).read_text())
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, '2026-09-01')",
                (int(name[:4]),),
            )


def seed_single_administrator(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            f"""
            INSERT INTO installation_admin(singleton, password_hash, created_at)
            VALUES (1, '{ADMIN_HASH}', '2026-01-01T00:00:00+00:00');
            INSERT INTO admin_sessions(token_hash, created_at, expires_at)
            VALUES ('session-hash', '2026-10-01T00:00:00+00:00', '9999-01-01T00:00:00+00:00');
            INSERT INTO oauth_states(state_hash, created_at, expires_at)
            VALUES ('state-hash', '2026-10-01T00:00:00+00:00', '2026-10-01T00:10:00+00:00');
            INSERT INTO connected_accounts (id, provider, display_name, email,
                encrypted_credentials, state, created_at, updated_at)
            VALUES ('personal', 'google', 'Personal', 'me@example.test', x'00', 'connected',
                '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
            INSERT INTO calendar_names VALUES ('personal', 'primary', 'Family', '2026-01-01');
            INSERT INTO sync_rules (id, source_account_id, source_calendar_id,
                destination_account_id, destination_calendar_id, privacy_policy, all_day_policy,
                busy_title, initial_lookback_days, state)
            VALUES ('rule-1', 'personal', 'primary', 'personal', 'work', 'busy_only', 'include',
                'Busy', 30, 'enabled');
            INSERT INTO event_mappings VALUES ('mapping-1', 'rule-1', 'personal', 'primary',
                'event-1', 'personal', 'work', 'projection-1', 'r1', 'fingerprint');
            INSERT INTO occurrence_mappings VALUES ('occurrence-1', 'mapping-1',
                '2026-10-01', 'personal', 'primary', 'event-1_1', 'personal', 'work',
                'projection-1_1', 'cancelled', 'r1', NULL);
            INSERT INTO pending_exception_replays VALUES ('mapping-1');
            INSERT INTO sync_cursors VALUES ('rule-1', 'source-cursor');
            INSERT INTO destination_sync_cursors VALUES ('rule-1', 'destination-cursor');
            INSERT INTO rule_run_outcomes (rule_id, kind, completed_at, succeeded)
            VALUES ('rule-1', 'sync', '2026-10-01T00:00:00+00:00', 1);
            INSERT INTO rule_previews (rule_id, completed_at, eligible_events, excluded_events)
            VALUES ('rule-1', '2026-10-01T00:00:00+00:00', 3, 1);
            INSERT INTO rule_block_checks VALUES ('rule-1', 0, '2026-10-01T00:00:00+00:00');
            INSERT INTO rule_failures VALUES ('rule-1', 1, 'temporary', '2026-10-01');
            -- Left by an earlier release that removed its rule without it; nothing reads it.
            INSERT INTO rule_failures VALUES ('removed-rule', 4, 'temporary', '2026-10-01');
            INSERT INTO source_observations VALUES ('rule-1', 'personal', 'primary', 'event-1',
                'r1', '2026-10-01', 'Dentist', 0, '2026-10-02', x'00');
            INSERT INTO audit_entries (id, occurred_at, rule_id, action, outcome, detail)
            VALUES (7, '2026-10-01T00:00:00+00:00', 'rule-1', 'create', 'completed', '');
            INSERT INTO incidents (id, deduplication_key, rule_id, category, state, summary,
                opened_at, updated_at)
            VALUES ('incident-1', 'provider:rule-1', 'rule-1', 'temporary', 'open', 'Waiting',
                '2026-10-01', '2026-10-01');
            INSERT INTO integration_tokens (id, name, token_hash, scope, created_at)
            VALUES ('token-1', 'Uptime Kuma', 'token-hash', 'status:read', '2026-10-01');
            """
        )
        # Entries cleared since keep their identifiers retired, so none is issued again.
        connection.execute("UPDATE sqlite_sequence SET seq = 40 WHERE name = 'audit_entries'")


def test_upgrading_makes_the_administrator_user_one_and_gives_them_every_record(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calendar-sync.db"
    database_at_version(database, 20)
    seed_single_administrator(database)

    initialize_database(database)
    initialize_database(database)

    with sqlite3.connect(database) as connection:
        users = connection.execute(
            "SELECT id, email, password_hash, role, state FROM users"
        ).fetchall()
        assert len(users) == 1
        user_id, email, password_hash, role, state = users[0]
        assert (email, password_hash, role, state) == (
            None,
            ADMIN_HASH,
            "installation_administrator",
            "active",
        )
        for table in OWNED_TABLES:
            owners = connection.execute(f"SELECT DISTINCT user_id FROM {table}").fetchall()
            assert owners == [(user_id,)], table
        assert connection.execute("SELECT rule_id FROM rule_failures").fetchall() == [("rule-1",)]
        # Existing monitors keep the answer they had: the whole installation, now User #1's.
        assert connection.execute("SELECT scopes FROM integration_tokens").fetchall() == [
            ("installation:read status:read",)
        ]
        assert connection.execute("SELECT COUNT(*) FROM oauth_states").fetchone() == (0,)
        versions = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
        assert 21 in versions
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
        assert not tables & {"installation_admin", "admin_sessions"}
        # Upgraded installations start as new ones do: nobody else may join.
        assert connection.execute(
            "SELECT registration_policy FROM installation_settings"
        ).fetchall() == [("only_me",)]
        connection.execute(
            """
            INSERT INTO audit_entries (occurred_at, rule_id, action, outcome, detail, user_id)
            VALUES ('2026-10-02T00:00:00+00:00', 'rule-1', 'create', 'completed', '', ?)
            """,
            (user_id,),
        )
        newest = connection.execute("SELECT MAX(id) FROM audit_entries").fetchone()
    assert newest == (41,)


def test_upgrading_an_installation_never_set_up_creates_no_user(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    database_at_version(database, 20)

    initialize_database(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone() == (0,)


def test_an_upgrade_that_would_break_a_reference_changes_nothing(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    database_at_version(database, 20)
    seed_single_administrator(database)
    with sqlite3.connect(database) as connection:
        # A rule whose account is gone could never run, but it is the administrator's record.
        connection.execute("DELETE FROM calendar_names")
        connection.execute("DELETE FROM connected_accounts")

    with pytest.raises(MigrationFailed, match="sync_rules"):
        initialize_database(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone() == (20,)
        assert connection.execute("SELECT COUNT(*) FROM installation_admin").fetchone() == (1,)


def test_a_fresh_database_does_not_recreate_the_single_administrator_tables(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calendar-sync.db"

    initialize_database(database)
    initialize_database(database)

    with sqlite3.connect(database) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert "users" in tables
    assert not tables & {"installation_admin", "admin_sessions"}


def test_the_upgraded_administrator_signs_in_by_password_alone_until_they_add_an_email(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calendar-sync.db"
    database_at_version(database, 20)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO installation_admin VALUES (1, ?, '2026-01-01T00:00:00+00:00')",
            (hash_password("the administrator's password"),),
        )
    initialize_database(database)
    users, passwords = SqliteUserDirectory(database), ScryptPasswords()
    sessions = SqliteSessions(database, SystemClock())
    sign_in = SignIn(users, passwords, sessions, MemorySignInThrottle(SystemClock()), SystemClock())

    upgraded = sign_in.execute(None, "the administrator's password", "client").user_id
    SetOwnEmail(users, passwords).execute(upgraded, "admin@example.test", None)

    with pytest.raises(IncorrectCredentials):
        sign_in.execute(None, "the administrator's password", "client")
    by_email = sign_in.execute("admin@example.test", "the administrator's password", "client")
    assert by_email.user_id == upgraded
