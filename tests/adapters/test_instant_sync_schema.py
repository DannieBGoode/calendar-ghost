"""Migration 31 keeps what Instant Sync needs: each User's watches and requests, which go with
their account, rule, and User, and the installation's Delivery Evidence."""

import sqlite3
from pathlib import Path

import pytest

from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from tests.adapters.test_user_migration import database_at_version
from tests.helpers import NOW, rule
from tests.users import OTHER_USER, USER, add_account, add_user, sqlite_units

OWNED = ("calendar_watches", "watch_coverage", "watch_registrations", "instant_sync_requests")


def test_migration_31_lets_every_existing_user_want_instant_sync(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    database_at_version(database, 30)
    add_user(database, USER)
    add_user(database, OTHER_USER, state="disabled")

    initialize_database(database)
    initialize_database(database)

    with sqlite3.connect(database) as connection:
        wanted = connection.execute("SELECT id, instant_sync FROM users ORDER BY id").fetchall()
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        broken = connection.execute("PRAGMA foreign_key_check").fetchall()
    assert wanted == [(USER.value, 1), (OTHER_USER.value, 1)]
    assert {*OWNED, "delivery_evidence"} <= tables
    assert broken == []


def _watch_with_a_request(database: Path) -> None:
    """USER's watch of RULE's Source Calendar, a live registration, and RULE's request."""
    with sqlite_units(database)() as uow:
        uow.rules.add(rule())
        uow.commit()
    with transaction(database) as connection:
        connection.execute(
            """
            INSERT INTO calendar_watches (id, user_id, account_id, scope_key)
            VALUES ('watch-1', ?, 'personal-account', 'calendar:personal-calendar')
            """,
            (USER.value,),
        )
        connection.execute(
            """
            INSERT INTO watch_coverage (watch_id, user_id, calendar_id)
            VALUES ('watch-1', ?, 'personal-calendar')
            """,
            (USER.value,),
        )
        connection.execute(
            """
            INSERT INTO watch_registrations (
                id, watch_id, user_id, state, address, token_hash, created_at, requested_until
            ) VALUES (
                'registration-1', 'watch-1', ?, 'live',
                'https://calendar.example.test/api/v1/watch-notices/test/registration-1',
                'token-hash', ?, ?
            )
            """,
            (USER.value, NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO instant_sync_requests (
                rule_id, user_id, requested_seq, handled_seq, first_requested_at,
                last_requested_at
            ) VALUES ('rule-1', ?, 1, 0, ?, ?)
            """,
            (USER.value, NOW.isoformat(), NOW.isoformat()),
        )


def test_instant_sync_records_refer_through_their_user_and_go_with_them(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    _watch_with_a_request(database)
    add_account(database, "their-account", OTHER_USER)
    refused: tuple[tuple[str, tuple[str, ...]], ...] = (
        # Another User's watch of this User's account.
        (
            """
            INSERT INTO calendar_watches (id, user_id, account_id, scope_key)
            VALUES ('watch-2', ?, 'personal-account', 'account')
            """,
            (OTHER_USER.value,),
        ),
        # Another User's coverage of this User's watch.
        (
            """
            INSERT INTO watch_coverage (watch_id, user_id, calendar_id)
            VALUES ('watch-1', ?, 'family')
            """,
            (OTHER_USER.value,),
        ),
        # A registration in a state the lifecycle does not know.
        (
            """
            INSERT INTO watch_registrations (
                id, watch_id, user_id, state, address, token_hash, created_at, requested_until
            ) VALUES ('registration-2', 'watch-1', ?, 'paused', 'address', 'other-hash', ?, ?)
            """,
            (USER.value, NOW.isoformat(), NOW.isoformat()),
        ),
        # A second registration with the same token.
        (
            """
            INSERT INTO watch_registrations (
                id, watch_id, user_id, state, address, token_hash, created_at, requested_until
            ) VALUES ('registration-3', 'watch-1', ?, 'live', 'address', 'token-hash', ?, ?)
            """,
            (USER.value, NOW.isoformat(), NOW.isoformat()),
        ),
        # A request for a rule that does not exist.
        (
            """
            INSERT INTO instant_sync_requests (
                rule_id, user_id, requested_seq, handled_seq, first_requested_at,
                last_requested_at
            ) VALUES ('missing-rule', ?, 1, 0, ?, ?)
            """,
            (USER.value, NOW.isoformat(), NOW.isoformat()),
        ),
    )
    for statement, values in refused:
        with pytest.raises(sqlite3.IntegrityError), transaction(database) as connection:
            connection.execute(statement, values)

    with transaction(database) as connection:
        connection.execute("DELETE FROM users WHERE id = ?", (USER.value,))

    with sqlite3.connect(database) as connection:
        left = [
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in OWNED
        ]
        broken = connection.execute("PRAGMA foreign_key_check").fetchall()
    assert left == [0, 0, 0, 0]
    assert broken == []


def test_removing_an_account_or_a_rule_removes_what_instant_sync_kept_of_it(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    _watch_with_a_request(database)

    with transaction(database) as connection:
        connection.execute("DELETE FROM sync_rules WHERE id = 'rule-1'")
        connection.execute("DELETE FROM connected_accounts WHERE id = 'personal-account'")

    with sqlite3.connect(database) as connection:
        left = [
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in OWNED
        ]
    assert left == [0, 0, 0, 0]
