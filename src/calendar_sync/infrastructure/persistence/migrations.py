"""SQLite schema migrations: each runs once, in order, and proves its references."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from calendar_sync.infrastructure.persistence.connections import open_connection

_FORWARD_MIGRATIONS = (
    (2, "0002_account_avatar.sql"),
    (3, "0003_audit_reasons.sql"),
    (4, "0004_rule_editing.sql"),
    (5, "0005_occurrence_mappings.sql"),
    (6, "0006_rule_previews.sql"),
    (7, "0007_audit_run_index.sql"),
    (8, "0008_last_full_sync.sql"),
    (9, "0009_audit_event_titles.sql"),
    (10, "0010_pending_exception_replays.sql"),
    (11, "0011_rule_block_checks.sql"),
    (12, "0012_incident_resolutions.sql"),
    (13, "0013_incident_accounts.sql"),
    (14, "0014_source_changes.sql"),
    (15, "0015_invitation_responses.sql"),
    (16, "0016_calendar_names.sql"),
    (17, "0017_provider_kinds.sql"),
    (18, "0018_integration_tokens.sql"),
    (19, "0019_incident_messages.sql"),
    (20, "0020_lapsed_authorization.sql"),
    (21, "0021_users.sql"),
    (22, "0022_registration.sql"),
    (23, "0023_token_scopes.sql"),
    (24, "0024_rule_creation_order.sql"),
    (25, "0025_provider_calls.sql"),
    (26, "0026_failure_causes.sql"),
    (27, "0027_failure_providers.sql"),
    (28, "0028_oauth_state_providers.sql"),
)


_CHECKED_FROM = 21
"""Migrations from here on prove every reference before committing. Earlier ones ran before
references were checked, and a database they left may hold rows no reference reaches."""


class MigrationFailed(RuntimeError):
    """A migration would have left a record referring to one that does not exist."""


def initialize_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    migrations = files("calendar_sync.infrastructure.persistence")
    with closing(open_connection(path)) as connection:
        # Recorded in the database file, so every later connection writes ahead too: a reader then
        # never keeps the scheduler from committing, nor the scheduler a request from reading.
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {
            int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")
        }
        if 1 not in applied:
            # Only a new database: later migrations replace tables the initial schema creates.
            connection.executescript(migrations.joinpath("0001_initial.sql").read_text())
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (1, datetime.now(UTC).isoformat()),
            )
            connection.commit()
        # SQLite rebuilds a table only with references unchecked, and changes that setting only
        # outside a transaction; each migration checks its own before it commits.
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            for version, name in _FORWARD_MIGRATIONS:
                if version not in applied:
                    _migrate(connection, version, migrations.joinpath(name).read_text())
        finally:
            connection.execute("PRAGMA foreign_keys = ON")


def _migrate(connection: sqlite3.Connection, version: int, script: str) -> None:
    """Apply one migration with its version record atomically, so it runs at most once."""
    connection.executescript(f"BEGIN;\n{script}")
    broken = (
        connection.execute("PRAGMA foreign_key_check").fetchall()
        if version >= _CHECKED_FROM
        else []
    )
    if broken:
        connection.rollback()
        tables = ", ".join(sorted({str(row[0]) for row in broken}))
        raise MigrationFailed(
            f"migration {version} would leave records in {tables} that refer to missing records; "
            "nothing was changed"
        )
    connection.execute(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (version, datetime.now(UTC).isoformat()),
    )
    connection.commit()
