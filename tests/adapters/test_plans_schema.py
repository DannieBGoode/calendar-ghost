"""Migration 33 keeps Plans: the limits an administrator defines, whether Plans are on and which
one is the default, each User's own Plan, and the place a Rule Replacement draft keeps
(ADR 0038)."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from calendar_sync.application.sync.errors import MissingReference
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import SyncRuleId, SyncRuleState
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.installation import (
    SqliteInstallationUnitOfWorkFactory,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.sqlite import SqliteUnitOfWorkFactory
from tests.adapters.test_user_migration import database_at_version
from tests.helpers import NOW, endpoint, rule
from tests.users import OTHER_USER, USER, add_account, add_user, sqlite_units


def _release_32_records(database: Path) -> None:
    """An administrator with two accounts and an enabled rule, and a second User, as release 32
    kept them: its rules have no `keeps_place` column yet, so the rule is written directly."""
    add_user(database, USER)
    add_user(database, OTHER_USER, role="user")
    for account in ("personal-account", "work-account"):
        add_account(database, account, USER)
    with transaction(database) as connection:
        connection.execute(
            """
            INSERT INTO sync_rules (id, user_id, source_account_id, source_calendar_id,
                destination_account_id, destination_calendar_id, privacy_policy,
                all_day_policy, busy_title, initial_lookback_days, state)
            VALUES ('rule-1', ?, 'personal-account', 'personal-calendar', 'work-account',
                'work-calendar', 'busy_only', 'include', 'Busy', 30, 'enabled')
            """,
            (USER.value,),
        )


def _family_assigned(database: Path) -> None:
    """The Plan `family`, which USER assigned to OTHER_USER as their own."""
    with transaction(database) as connection:
        connection.execute(
            """
            INSERT INTO plans (key, name, rule_limit, account_limit, token_limit, sync_interval,
                created_at, updated_at)
            VALUES ('family', 'Family', 5, 3, 2, 'instant', ?, ?)
            """,
            (NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute(
            """
            UPDATE users SET plan_key = 'family', plan_assigned_by = 'administrator',
                plan_assigner_id = ?, plan_assigned_at = ?
            WHERE id = ?
            """,
            (USER.value, NOW.isoformat(), OTHER_USER.value),
        )


def test_migration_33_adds_plans_turned_off_and_limits_nobody(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    database_at_version(database, 32)
    _release_32_records(database)

    initialize_database(database)
    initialize_database(database)

    with sqlite3.connect(database) as connection:
        setting = connection.execute(
            "SELECT plans_enabled, default_plan_key FROM installation_settings"
        ).fetchall()
        assignments = connection.execute(
            """
            SELECT id, plan_key, plan_assigned_by, plan_assigner_id, plan_assigned_at
            FROM users ORDER BY id
            """
        ).fetchall()
        places = connection.execute("SELECT id, keeps_place FROM sync_rules").fetchall()
        plans = connection.execute("SELECT COUNT(*) FROM plans").fetchone()
        broken = connection.execute("PRAGMA foreign_key_check").fetchall()
    with sqlite_units(database)() as uow:
        kept = uow.rules.get(rule().id)

    assert setting == [(0, None)]
    assert assignments == [
        (USER.value, None, None, None, None),
        (OTHER_USER.value, None, None, None, None),
    ]
    assert places == [("rule-1", 0)]
    assert plans == (0,)
    assert broken == []
    assert kept == rule()


def test_the_database_refuses_to_delete_a_plan_a_user_or_the_default_names(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    add_user(database, USER)
    add_user(database, OTHER_USER, role="user")
    _family_assigned(database)

    with pytest.raises(sqlite3.IntegrityError), transaction(database) as connection:
        connection.execute("DELETE FROM plans WHERE key = 'family'")
    with transaction(database) as connection:
        connection.execute("UPDATE users SET plan_key = NULL")
        connection.execute("UPDATE installation_settings SET default_plan_key = 'family'")
    with pytest.raises(sqlite3.IntegrityError), transaction(database) as connection:
        connection.execute("DELETE FROM plans WHERE key = 'family'")

    with transaction(database) as connection:
        kept = [tuple(row) for row in connection.execute("SELECT key FROM plans")]
    assert kept == [("family",)]


def test_a_place_left_on_a_rule_that_is_no_draft_reads_as_no_place(tmp_path: Path) -> None:
    """Only a draft or previewed rule keeps a place, so a mark left on any other row never stops
    the rule from being read."""
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    units = sqlite_units(database)
    draft = replace(
        rule(),
        id=SyncRuleId("rule-9"),
        destination=endpoint("work-account", "replacement-calendar"),
        state=SyncRuleState.DRAFT,
    )
    with units() as uow:
        uow.rules.add(rule())
        uow.rules.add(draft)
        uow.commit()
    with transaction(database) as connection:
        connection.execute("UPDATE sync_rules SET keeps_place = 1")

    with units() as uow:
        enabled, kept = uow.rules.get(rule().id), uow.rules.get(draft.id)
    with SqliteInstallationUnitOfWorkFactory(database)() as installation:
        scheduled = installation.scheduled_rules()

    assert enabled == rule()
    assert kept == replace(draft, keeps_place=True)
    assert [item.rule for item in scheduled] == [rule()]


def test_migration_34_preserves_rules_and_has_zero_default_admissions(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    database_at_version(database, 33)
    _release_32_records(database)
    _family_assigned(database)
    with transaction(database) as connection:
        before = [tuple(row) for row in connection.execute("SELECT * FROM sync_rules")]
    initialize_database(database)
    initialize_database(database)
    with transaction(database) as connection:
        after = [tuple(row) for row in connection.execute("SELECT * FROM sync_rules")]
        assert [row[:-1] for row in after] == before
        assert [row[-1] for row in after] == [0]
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT plan_holds_at, plan_grace_limit, plan_grace_admissions, "
                "plan_admissions FROM users"
            )
        ] == [(None, None, None, 0), (None, None, None, 0)]
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version = 34"
            ).fetchone()[0]
            == 1
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        user_columns = {
            row[1]: tuple(row[2:5]) for row in connection.execute("PRAGMA table_info(users)")
        }
        assert {
            name: user_columns[name]
            for name in (
                "plan_holds_at",
                "plan_grace_limit",
                "plan_grace_admissions",
                "plan_admissions",
            )
        } == {
            "plan_holds_at": ("TEXT", 0, None),
            "plan_grace_limit": ("INTEGER", 0, None),
            "plan_grace_admissions": ("INTEGER", 0, None),
            "plan_admissions": ("INTEGER", 1, "0"),
        }
        rule_columns = {
            row[1]: tuple(row[2:5]) for row in connection.execute("PRAGMA table_info(sync_rules)")
        }
        assert rule_columns["plan_kept"] == ("INTEGER", 1, "0")
        assert (
            connection.execute(
                "SELECT plan_key FROM users WHERE id = ?", (OTHER_USER.value,)
            ).fetchone()[0]
            == "family"
        )
    with sqlite_units(database)() as uow:
        assert uow.rules.get(rule().id) == rule()


@pytest.mark.parametrize("code", [0, 1, 2, 9, -1])
@pytest.mark.parametrize("state", list(SyncRuleState))
def test_stop_codes_read_and_write_exactly(tmp_path: Path, code: int, state: SyncRuleState) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    units = sqlite_units(database)
    with units() as uow:
        uow.rules.add(replace(rule(), state=state))
        uow.commit()
    with transaction(database) as connection:
        connection.execute("UPDATE sync_rules SET awaiting_reauthorization = ?", (code,))
    with units() as uow:
        stored = uow.rules.get(rule().id)
        assert stored == replace(
            rule(),
            state=state if code in (0, 1, 2) else SyncRuleState.DEGRADED,
            awaiting_reauthorization=code == 1,
            held_by_plan=code == 2 and state is SyncRuleState.DEGRADED,
        )
        assert stored is not None
        uow.rules.save(stored)
        uow.commit()
    with transaction(database) as connection:
        written = connection.execute("SELECT awaiting_reauthorization FROM sync_rules").fetchone()[
            0
        ]
        assert written == (2 if stored.held_by_plan else 1 if code == 1 else 0)


def test_grace_acquire_requires_an_existing_user(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    with (
        SqliteUnitOfWorkFactory(database).for_user(UserId("absent"))() as uow,
        pytest.raises(MissingReference),
    ):
        uow.plan_grace.acquire()


def test_grace_acquire_takes_the_sqlite_writer_before_reads(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    units = sqlite_units(database)
    with units() as uow:
        uow.plan_grace.acquire()
        with (
            pytest.raises(sqlite3.OperationalError, match="locked"),
            transaction(database, timeout=0) as connection,
        ):
            connection.execute("UPDATE users SET plan_admissions = 99 WHERE id = ?", (USER.value,))
        assert uow.plan_grace.admissions() == 0
    with units() as uow:
        uow.plan_grace.admit()
        uow.commit()
    with units() as uow:
        assert uow.plan_grace.admissions() == 1


def test_memory_grace_acquire_refuses_an_owner_removed_while_the_unit_is_open() -> None:
    units = InMemoryUnitOfWorkFactory()
    with units.for_user(USER)() as uow:
        units.database.partitions.pop(USER)
        with pytest.raises(MissingReference):
            uow.plan_grace.acquire()
