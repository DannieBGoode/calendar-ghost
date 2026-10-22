"""What the Operator Overview reads across Users from SQLite agrees with what each User reads."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from calendar_sync.application.operations.operator_overview import UserStatuses
from calendar_sync.application.operations.status import (
    Dashboard,
    GetInstallationStatus,
    InstallationStatus,
)
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.rules import ListSyncRules
from calendar_sync.domain.access import UserId
from calendar_sync.domain.audit import AuditAction, AuditEntry, AuditOutcome
from calendar_sync.domain.model import SyncReason, SyncRuleId
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.persistence import installation as installation_module
from calendar_sync.infrastructure.persistence.activity_queries import SqliteOperationsQueries
from calendar_sync.infrastructure.persistence.connections import open_connection, transaction
from calendar_sync.infrastructure.persistence.installation import (
    SqliteInstallationUnitOfWorkFactory,
)
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.interfaces.api.status_payload import status_response
from tests.helpers import RecentSchedulerHeartbeat, endpoint, rule
from tests.users import OTHER_USER, USER, sqlite_units

START = datetime(2026, 9, 28, 15, 0, tzinfo=UTC)
THIRD_USER = UserId("user-3")


def _block(rule_id: str, event: str, minutes: int) -> AuditEntry:
    return AuditEntry(
        START + timedelta(minutes=minutes),
        SyncRuleId(rule_id),
        AuditAction.CONFLICT,
        AuditOutcome.BLOCKED,
        source_event_id=event,
        reason=SyncReason.MAPPING_INCONSISTENT,
    )


def _seed(database: Path, user: UserId, rules: int) -> None:
    """`rules` rules of `user`, each with an open block and one its daily pass retired."""
    accounts = (f"{user.value}-source", f"{user.value}-destination")
    with sqlite_units(database, user=user, accounts=accounts)() as uow:
        for number in range(rules):
            rule_id = f"{user.value}-rule-{number}"
            uow.rules.add(
                replace(
                    rule(),
                    id=SyncRuleId(rule_id),
                    source=endpoint(accounts[0], f"calendar-{number}"),
                    destination=endpoint(accounts[1], f"calendar-{number}"),
                )
            )
            uow.audit.append(_block(rule_id, "retired", number))
            uow.audit.append(_block(rule_id, "open", number))
        uow.commit()
    with transaction(database) as connection:
        for number in range(rules):
            rule_id = f"{user.value}-rule-{number}"
            retired = connection.execute(
                "SELECT id FROM audit_entries WHERE rule_id = ? AND source_event_id = 'retired'",
                (rule_id,),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO rule_block_checks (rule_id, user_id, audit_floor, checked_at)
                VALUES (?, ?, ?, '2026-09-28')
                """,
                (rule_id, user.value, retired),
            )
        connection.execute(
            """
            INSERT INTO incidents (id, deduplication_key, rule_id, category, state, summary,
                opened_at, updated_at, user_id)
            VALUES (?, ?, ?, 'temporary', 'open', 'Google Calendar is temporarily unavailable',
                '2026-09-28', '2026-09-28', ?)
            """,
            (f"{user.value}-incident", f"{user.value}-key", f"{user.value}-rule-0", user.value),
        )
        connection.execute(
            "UPDATE connected_accounts SET authorization_lapsed_at = '2026-09-28' WHERE id = ?",
            (accounts[0],),
        )


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "test.db"
    initialize_database(path)
    _seed(path, USER, 2)
    _seed(path, OTHER_USER, 3)
    return path


def test_each_users_records_agree_with_what_that_user_reads(database: Path) -> None:
    with SqliteInstallationUnitOfWorkFactory(database)() as installation:
        records = installation.status_records([USER, OTHER_USER])

    for user in (USER, OTHER_USER):
        own = SqliteOperationsQueries(database, user)
        assert records[user].overview == own.overview()
        assert records[user].assessment_incidents == tuple(own.assessment_incidents())
        assert records[user].incidents == tuple(i for i in own.incidents() if i.state == "open")
        assert len(records[user].overview.open_blocks) == len(records[user].rules)


def _verdict(status: InstallationStatus) -> object:
    """Everything a status says but the names of calendars."""
    return (
        status.health,
        status.problems,
        [(rule.summary.rule, rule.summary.last_sync, rule.problem) for rule in status.rules],
        status.open_incidents,
        status.overview,
        dict(status.providers),
    )


def test_each_users_status_is_the_one_their_own_overview_computes(database: Path) -> None:
    locks, clock = RuleLocks(), SystemClock()
    heartbeat = RecentSchedulerHeartbeat(clock)
    statuses = UserStatuses(SqliteInstallationUnitOfWorkFactory(database), locks, clock, heartbeat)

    labelled = statuses.of([USER, OTHER_USER])

    for user in (USER, OTHER_USER):
        own = GetInstallationStatus(
            ListSyncRules(sqlite_units(database, user=user, accounts=()), locks),
            SqliteOperationsQueries(database, user),
            clock,
            heartbeat,
        ).execute()
        assert own.problems
        assert _verdict(labelled[user]) == _verdict(own)
        assert labelled[user].rules[0].name == "Calendar 1 → Calendar 2"


def test_a_page_of_users_is_read_in_as_many_queries_however_many_rules_they_have(
    database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    statements: list[str] = []

    def counted(path: Path) -> sqlite3.Connection:
        connection = open_connection(path)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(installation_module, "open_connection", counted)

    def queries(users: list[UserId]) -> int:
        statements.clear()
        with SqliteInstallationUnitOfWorkFactory(database)() as installation:
            installation.status_records(users)
        return len(statements)

    few = queries([USER])
    _seed(database, THIRD_USER, 12)

    assert queries([USER, OTHER_USER, THIRD_USER]) == few


def test_a_user_with_more_than_100_open_incidents_reads_the_same_in_both_paths(
    database: Path,
) -> None:
    """Both readers keep the 100 most recent open incidents and count them all (review on PR 68)."""
    with transaction(database) as connection:
        for number in range(101):
            connection.execute(
                """
                INSERT INTO incidents (id, deduplication_key, rule_id, category, state, summary,
                    opened_at, updated_at, user_id)
                VALUES (?, ?, NULL, 'temporary', 'open', 'Google is temporarily unavailable',
                    '2026-09-28', ?, ?)
                """,
                (
                    f"many-{number}",
                    f"many-{number}",
                    f"2026-09-28T00:{number // 60:02d}:{number % 60:02d}",
                    USER.value,
                ),
            )

    with SqliteInstallationUnitOfWorkFactory(database)() as installation:
        records = installation.status_records([USER])[USER]
    own = SqliteOperationsQueries(database, USER)

    assert records.incidents == tuple(i for i in own.incidents() if i.state == "open")
    assert len(records.incidents) == 100
    assert records.overview.open_incidents == own.overview().open_incidents == 102
    assert len(own.assessment_incidents()) == 100
    assert records.assessment_incidents == tuple(own.assessment_incidents())


def test_dashboard_held_incident_count_is_exact_beyond_page_limit(database: Path) -> None:
    with transaction(database) as connection:
        connection.execute(
            "UPDATE sync_rules SET state = 'degraded', awaiting_reauthorization = 2 WHERE id = ?",
            (f"{USER.value}-rule-0",),
        )
        for number in range(150):
            connection.execute(
                """
                INSERT INTO incidents (id, deduplication_key, rule_id, category, state, summary,
                    opened_at, updated_at, user_id)
                VALUES (?, ?, ?, 'temporary', 'open', 'Provider temporarily unavailable',
                    '2026-09-28', ?, ?)
                """,
                (
                    f"mixed-{number}",
                    f"mixed-{number}",
                    f"{USER.value}-rule-{number % 2}",
                    f"2026-09-28T00:{number // 60:02d}:{number % 60:02d}",
                    USER.value,
                ),
            )
    with SqliteInstallationUnitOfWorkFactory(database)() as installation:
        records = installation.status_records([USER, OTHER_USER])
    own = SqliteOperationsQueries(database, USER)
    assert own.overview() == records[USER].overview
    assert own.overview().open_incidents == 151
    assert own.overview().held_open_incidents == 76
    assert records[OTHER_USER].overview.held_open_incidents == 0
    assert len(records[USER].incidents) == 100

    clock, locks = SystemClock(), RuleLocks()
    heartbeat = RecentSchedulerHeartbeat(clock)
    labelled = UserStatuses(SqliteInstallationUnitOfWorkFactory(database), locks, clock, heartbeat)
    own_status = GetInstallationStatus(
        ListSyncRules(sqlite_units(database, user=USER, accounts=()), locks), own, clock, heartbeat
    ).execute()
    for status in (own_status, labelled.of([USER])[USER]):
        assert status.overview.open_incidents == 151
        assert len(status.open_incidents) == 100
        assert Dashboard.of(status).open_incidents == 75


def test_operator_overview_matches_held_own_status(database: Path) -> None:
    with transaction(database) as connection:
        connection.execute(
            "UPDATE sync_rules SET state = 'degraded', awaiting_reauthorization = 2 "
            "WHERE user_id = ?",
            (USER.value,),
        )
    clock, locks = SystemClock(), RuleLocks()
    heartbeat = RecentSchedulerHeartbeat(clock)
    labelled = UserStatuses(SqliteInstallationUnitOfWorkFactory(database), locks, clock, heartbeat)
    own = GetInstallationStatus(
        ListSyncRules(sqlite_units(database, user=USER, accounts=()), locks),
        SqliteOperationsQueries(database, USER),
        clock,
        heartbeat,
    ).execute()
    status = labelled.of([USER])[USER]
    assert _verdict(status) == _verdict(own)
    assert status.counts == own.counts
    assert (status.counts.held, status.counts.stopped) == (2, 0)
    payload = status_response(status).model_dump(mode="json")
    assert payload["rules"][0]["name"] == "Calendar 1 → Calendar 2"
    assert payload["rules"][0]["stop_cause"] == "plan_hold"
    assert all(r["source"]["number"] is not None for r in payload["rules"])
    assert "calendar-0" not in str(payload)


@pytest.mark.parametrize("account_owned", [False, True])
def test_held_incident_page_cannot_hide_an_older_active_problem(
    database: Path, account_owned: bool
) -> None:
    with transaction(database) as connection:
        connection.execute("DELETE FROM incidents WHERE user_id = ?", (USER.value,))
        connection.execute("DELETE FROM audit_entries WHERE user_id = ?", (USER.value,))
        connection.execute(
            "UPDATE connected_accounts SET authorization_lapsed_at = NULL WHERE user_id = ?",
            (USER.value,),
        )
        connection.execute(
            "UPDATE sync_rules SET state = 'degraded', awaiting_reauthorization = 2 WHERE id = ?",
            (f"{USER.value}-rule-0",),
        )
        for number in range(101):
            connection.execute(
                """
                INSERT INTO incidents (id, deduplication_key, rule_id, category, state, summary,
                    opened_at, updated_at, user_id)
                VALUES (?, ?, ?, 'permanent', 'open', 'Provider refused',
                    '2026-09-29', '2026-09-29', ?)
                """,
                (f"held-{number}", f"held-{number}", f"{USER.value}-rule-0", USER.value),
            )
        connection.execute(
            """
            INSERT INTO incidents (id, deduplication_key, rule_id, account_id, category, state,
                summary, opened_at, updated_at, user_id)
            VALUES ('older-active', 'older-active', ?, ?, 'permanent', 'open',
                'An active problem', '2026-09-28', '2026-09-28', ?)
            """,
            (
                None if account_owned else f"{USER.value}-rule-1",
                f"{USER.value}-source" if account_owned else None,
                USER.value,
            ),
        )
    clock, locks = SystemClock(), RuleLocks()
    heartbeat = RecentSchedulerHeartbeat(clock)
    own = GetInstallationStatus(
        ListSyncRules(sqlite_units(database, user=USER, accounts=()), locks),
        SqliteOperationsQueries(database, USER),
        clock,
        heartbeat,
    ).execute()
    labelled = UserStatuses(SqliteInstallationUnitOfWorkFactory(database), locks, clock, heartbeat)
    for status in (own, labelled.of([USER])[USER]):
        assert status.needs_attention
        assert [problem.summary for problem in status.problems] == ["An active problem"]
        assert len(status.open_incidents) == 100
        assert all(incident.rule_id == f"{USER.value}-rule-0" for incident in status.open_incidents)
        assert status.overview.open_incidents == 102
        assert Dashboard.of(status).open_incidents == 1
