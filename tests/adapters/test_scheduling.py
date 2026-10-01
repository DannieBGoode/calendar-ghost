import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from typing import cast

import pytest

from calendar_sync.application.errors import (
    ProviderFailure,
    ProviderFailureKind,
    RuleNotExecutable,
)
from calendar_sync.application.health import RuleHealth, RunHealth
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    AuditAction,
    AuditEntry,
    AuditOutcome,
    IncidentReport,
    IncidentResolution,
    RuleRunOutcome,
    RunKind,
    UnitOfWork,
    UnitOfWorkFactory,
)
from calendar_sync.application.sync_run import SOURCE_CHANGE_RETENTION
from calendar_sync.application.synchronization import ExecuteSyncRule, SyncRunResult
from calendar_sync.domain.model import ConnectedAccountId, SyncReason, SyncRuleId, SyncRuleState
from calendar_sync.infrastructure.notifications import (
    IncidentNotification,
    IncidentNotifier,
    NotificationChannel,
)
from calendar_sync.infrastructure.persistence.activity_queries import (
    SqliteOperationsQueries,
    open_blocks,
)
from calendar_sync.infrastructure.persistence.health import (
    SqliteIncidentRepository,
    SqliteRuleHealthRecords,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from calendar_sync.infrastructure.scheduling import SyncScheduler, SystemClock
from tests.helpers import endpoint, rule


class RecordingChannel(NotificationChannel):
    def __init__(self) -> None:
        self.incidents: list[IncidentNotification] = []

    def send(self, incident: IncidentNotification) -> None:
        self.incidents.append(incident)


class RecordingExecuteRule:
    def __init__(self, outcomes: list[Exception | None]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if outcome is not None:
            raise outcome
        return SyncRunResult(rule_id)


class RecordingHealth:
    def __init__(self) -> None:
        self.successes = 0
        self.full_successes = 0
        self.failures: list[ProviderFailure] = []

    def record_success(
        self,
        _rule: object,
        *,
        full_pass_floor: int | None = None,
        full_pass_run: str | None = None,
    ) -> None:
        self.successes += 1
        self.full_successes += full_pass_floor is not None
        self.full_pass_run = full_pass_run

    def audit_floor(self) -> int:
        return 0

    def record_failure(self, _rule: object, failure: ProviderFailure) -> None:
        self.failures.append(failure)


def _rule_health(
    database: Path,
    unit_of_work: UnitOfWorkFactory,
    notifier: IncidentNotifier | None = None,
    *,
    locks: RuleLocks | None = None,
) -> RuleHealth:
    return RuleHealth(
        unit_of_work,
        SqliteRuleHealthRecords(database),
        SqliteIncidentRepository(database),
        SystemClock(),
        locks or RuleLocks(),
        notifier,
    )


def test_three_temporary_failures_open_one_incident(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    unit_of_work = SqliteUnitOfWorkFactory(database)
    with unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()
    health = _rule_health(database, unit_of_work)
    failure = ProviderFailure(ProviderFailureKind.TEMPORARY, "synthetic provider outage")

    health.record_failure(rule(), failure)
    health.record_failure(rule(), failure)
    health.record_failure(rule(), failure)

    with sqlite3.connect(database) as connection:
        incidents = connection.execute("SELECT summary, state FROM incidents").fetchall()
    assert incidents == [("Google Calendar is temporarily unavailable", "open")]


def test_authentication_failure_degrades_rule_immediately(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    unit_of_work = SqliteUnitOfWorkFactory(database)
    with unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()
    health = _rule_health(database, unit_of_work)

    health.record_failure(
        rule(), ProviderFailure(ProviderFailureKind.AUTHENTICATION, "synthetic expiry")
    )

    with unit_of_work() as uow:
        degraded = uow.rules.get(rule().id)
    assert degraded is not None
    assert degraded.state.value == "degraded"


def test_open_incident_notification_is_deduplicated(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    unit_of_work = SqliteUnitOfWorkFactory(database)
    with unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()
    channel = RecordingChannel()
    health = _rule_health(database, unit_of_work, IncidentNotifier([channel]))
    failure = ProviderFailure(ProviderFailureKind.PERMANENT, "synthetic rejection")

    health.record_failure(rule(), failure)
    health.record_failure(rule(), failure)

    assert len(channel.incidents) == 1
    assert channel.incidents[0].rule_id == rule().id.value


def test_success_resolves_existing_incident_and_resets_failure_count(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    unit_of_work = SqliteUnitOfWorkFactory(database)
    with unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()
    health = _rule_health(database, unit_of_work)
    health.record_failure(rule(), ProviderFailure(ProviderFailureKind.PERMANENT, "rejected"))

    health.record_success(rule())

    with sqlite3.connect(database) as connection:
        incident_state = connection.execute("SELECT state FROM incidents").fetchone()[0]
        failures = connection.execute("SELECT COUNT(*) FROM rule_failures").fetchone()[0]
    assert incident_state == "resolved"
    assert failures == 0


def test_scheduler_retries_temporary_failure_then_records_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = ProviderFailure(ProviderFailureKind.TEMPORARY, "outage")
    execute = RecordingExecuteRule([temporary, None])
    health = RecordingHealth()
    monkeypatch.setattr("calendar_sync.infrastructure.scheduling.time.sleep", lambda _delay: None)
    scheduler = SyncScheduler(
        cast(ExecuteSyncRule, execute),
        cast(UnitOfWorkFactory, None),
        cast(RunHealth, health),
    )

    successful = scheduler._execute_with_retry(rule())

    assert successful is True
    assert execute.calls == 2
    assert health.successes == 1
    assert health.failures == []


def test_scheduler_does_not_retry_permanent_failure() -> None:
    permanent = ProviderFailure(ProviderFailureKind.PERMANENT, "rejected")
    execute = RecordingExecuteRule([permanent])
    health = RecordingHealth()
    scheduler = SyncScheduler(
        cast(ExecuteSyncRule, execute),
        cast(UnitOfWorkFactory, None),
        cast(RunHealth, health),
    )

    successful = scheduler._execute_with_retry(rule())

    assert successful is False
    assert execute.calls == 1
    assert health.failures == [permanent]


def test_scheduler_isolates_unexpected_rule_failure() -> None:
    execute = RecordingExecuteRule([ValueError("corrupt local state")])
    health = RecordingHealth()
    scheduler = SyncScheduler(
        cast(ExecuteSyncRule, execute),
        cast(UnitOfWorkFactory, None),
        cast(RunHealth, health),
    )

    successful = scheduler._execute_with_retry(rule())

    assert successful is False
    assert execute.calls == 1
    assert len(health.failures) == 1
    assert health.failures[0].kind is ProviderFailureKind.INFRASTRUCTURE


def test_rule_removed_or_edited_during_a_pass_is_skipped_without_an_incident() -> None:
    execute = RecordingExecuteRule([RuleNotExecutable("sync rule rule-1 does not exist")])
    health = RecordingHealth()
    scheduler = SyncScheduler(
        cast(ExecuteSyncRule, execute),
        cast(UnitOfWorkFactory, None),
        cast(RunHealth, health),
    )

    successful = scheduler._execute_with_retry(rule())

    assert successful is True
    assert execute.calls == 1
    assert health.failures == []
    assert health.successes == 0


def test_degrading_after_an_authorization_failure_waits_for_a_concurrent_rule_change(
    tmp_path: Path,
) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    unit_of_work = SqliteUnitOfWorkFactory(database)
    with unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()
    locks = RuleLocks()
    health = _rule_health(database, unit_of_work, locks=locks)
    held = locks.for_writes(rule().id)
    held.acquire()
    worker = Thread(
        target=health.record_failure,
        args=(rule(), ProviderFailure(ProviderFailureKind.AUTHENTICATION, "expired")),
    )
    worker.start()
    worker.join(0.1)
    blocked = worker.is_alive()
    held.release()
    worker.join(2)

    assert blocked
    with unit_of_work() as uow:
        degraded = uow.rules.get(rule().id)
    assert degraded is not None
    assert degraded.state is SyncRuleState.DEGRADED


def test_blocked_removal_opens_one_incident_that_completed_removal_resolves(
    tmp_path: Path,
) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    unit_of_work = SqliteUnitOfWorkFactory(database)
    with unit_of_work() as uow:
        uow.rules.add(rule(state=SyncRuleState.REMOVING))
        uow.commit()
    channel = RecordingChannel()
    health = _rule_health(database, unit_of_work, IncidentNotifier([channel]))
    failure = ProviderFailure(ProviderFailureKind.AUTHORIZATION, "synthetic denial")

    health.removal_blocked(rule().id, failure)
    health.removal_blocked(rule().id, failure)

    with sqlite3.connect(database) as connection:
        incidents = connection.execute(
            "SELECT deduplication_key, rule_id, category, state, summary FROM incidents"
        ).fetchall()
    assert incidents == [
        (
            "removal:rule-1",
            "rule-1",
            "authorization",
            "open",
            "Rule Removal stopped: Google calendar access was denied",
        )
    ]
    assert len(channel.incidents) == 1
    with sqlite3.connect(database) as connection:
        rule_state = connection.execute("SELECT state FROM sync_rules").fetchone()
    assert rule_state == ("disabled",)

    with unit_of_work() as uow:
        uow.rules.remove(rule().id)
        uow.commit()

    with sqlite3.connect(database) as connection:
        states = connection.execute("SELECT state FROM incidents").fetchall()
    assert states == [("resolved",)]


class FullPassRecordingExecuteRule:
    def __init__(self) -> None:
        self.full: list[tuple[str, bool]] = []

    def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
        self.full.append((rule_id.value, full))
        return SyncRunResult(rule_id)


def test_daily_full_pass_is_due_per_rule_and_survives_a_restart() -> None:
    factory = InMemoryUnitOfWorkFactory()
    second = replace(rule(), id=SyncRuleId("rule-2"), source=endpoint("other", "calendar"))
    with factory() as uow:
        uow.rules.add(rule())
        uow.rules.add(second)
        uow.run_outcomes.record(
            RuleRunOutcome(rule().id, RunKind.SYNC, datetime.now(UTC), True, full_run=True)
        )
        uow.commit()
    execute = FullPassRecordingExecuteRule()
    health = RecordingHealth()

    for _restart in range(2):
        scheduler = SyncScheduler(cast(ExecuteSyncRule, execute), factory, cast(RunHealth, health))
        asyncio.run(scheduler.run_once())

    # rule-1 finished today's full pass; rule-2 never did, so only it lists everything again.
    assert execute.full == [("rule-1", False), ("rule-2", True)] * 2
    # Rule health learns which runs were full passes, where persisting blocks become incidents.
    assert health.full_successes == 2


def _block(
    run_id: str, source_event_id: str = "occurrence", action: str = "conflict"
) -> AuditEntry:
    return AuditEntry(
        occurred_at=datetime(2026, 9, 29, 17, 5, tzinfo=UTC),
        rule_id=rule().id,
        action=AuditAction(action),
        outcome=AuditOutcome.BLOCKED if action == "conflict" else AuditOutcome.COMPLETED,
        source_event_id=source_event_id,
        reason=SyncReason.DESTINATION_OCCURRENCE_MISSING
        if action == "conflict"
        else SyncReason.OCCURRENCE_CHANGED,
        run_id=run_id,
    )


def _health_with(tmp_path: Path, *entries: AuditEntry) -> tuple[Path, RuleHealth]:
    database = tmp_path / "test.db"
    initialize_database(database)
    unit_of_work = SqliteUnitOfWorkFactory(database)
    with unit_of_work() as uow:
        uow.rules.add(rule())
        for entry in entries:
            uow.audit.append(entry)
        uow.commit()
    return database, _rule_health(database, unit_of_work)


def _incidents(database: Path) -> list[tuple[str, str, str, str]]:
    with sqlite3.connect(database) as connection:
        return connection.execute(
            "SELECT deduplication_key, category, state, summary FROM incidents"
        ).fetchall()


def test_block_still_there_at_the_daily_pass_opens_an_incident(tmp_path: Path) -> None:
    # The daily pass began after entry 1, so entry 2 is its decision.
    database, health = _health_with(tmp_path, _block("incremental"), _block("daily"))

    health.record_success(rule(), full_pass_floor=1)

    assert _incidents(database) == [
        (
            "blocked:rule-1",
            "conflict",
            "open",
            "1 event could not be synced and was still blocked at the daily check.",
        )
    ]


def test_first_block_or_an_incremental_run_opens_no_incident(tmp_path: Path) -> None:
    database, health = _health_with(tmp_path, _block("incremental"))

    health.record_success(rule(), full_pass_floor=0)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO audit_entries (occurred_at, rule_id, action, outcome, source_event_id,"
            " reason, run_id, detail) VALUES ('2026-09-29', 'rule-1', 'conflict', 'blocked',"
            " 'occurrence', 'destination_occurrence_missing', 'later', '')"
        )
    health.record_success(rule())

    assert _incidents(database) == []


def test_block_resolved_in_between_is_not_persisting(tmp_path: Path) -> None:
    database, health = _health_with(
        tmp_path, _block("first"), _block("fixed", action="update"), _block("daily")
    )

    health.record_success(rule(), full_pass_floor=2)

    assert _incidents(database) == []


def test_daily_pass_without_persisting_blocks_resolves_the_incident(tmp_path: Path) -> None:
    database, health = _health_with(tmp_path, _block("incremental"), _block("daily"))
    health.record_success(rule(), full_pass_floor=1)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO audit_entries (occurred_at, rule_id, action, outcome, source_event_id,"
            " reason, run_id, detail) VALUES ('2026-09-30', 'rule-1', 'update', 'completed',"
            " 'occurrence', 'occurrence_changed', 'next-daily', '')"
        )

    health.record_success(rule(), full_pass_floor=2)

    assert [(key, state) for key, _category, state, _summary in _incidents(database)] == [
        ("blocked:rule-1", "resolved")
    ]


def test_a_block_the_daily_pass_did_not_decide_again_is_no_longer_open(tmp_path: Path) -> None:
    # Two blocks of an occurrence whose series was then deleted: the deletion is recorded against
    # the series, so nothing newer names the occurrence, and the daily pass never decides it again.
    database, health = _health_with(
        tmp_path,
        _block("incremental"),
        _block("daily-1"),
        _block("deleted", source_event_id="series", action="delete"),
    )
    health.record_success(rule(), full_pass_floor=1)
    assert [state for _key, _category, state, _summary in _incidents(database)] == ["open"]

    health.record_success(rule(), full_pass_floor=3)

    assert [state for _key, _category, state, _summary in _incidents(database)] == ["resolved"]
    with sqlite3.connect(database) as connection:
        assert open_blocks(connection) == []


def test_unrelated_activity_never_hides_an_open_block(tmp_path: Path) -> None:
    database, _health = _health_with(tmp_path, _block("incremental"))
    other = replace(rule(), id=SyncRuleId("rule-2"), source=endpoint("other", "calendar"))
    with SqliteUnitOfWorkFactory(database)() as uow:
        uow.rules.add(other)
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.executemany(
            "INSERT INTO audit_entries (occurred_at, rule_id, action, outcome, source_event_id,"
            " reason, run_id, detail) VALUES ('2026-09-30', 'rule-2', 'ignore', 'skipped', ?,"
            " 'projection_current', 'busy', '')",
            ((str(index),) for index in range(60_000)),
        )
        assert open_blocks(connection) == [(1, "rule-1")]


def test_scheduler_passes_the_audit_floor_before_a_daily_pass(tmp_path: Path) -> None:
    database, health = _health_with(tmp_path, _block("earlier"))

    assert health.audit_floor() == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM rule_block_checks").fetchone() == (0,)
    health.record_success(rule(), full_pass_floor=1)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT rule_id, audit_floor FROM rule_block_checks"
        ).fetchall() == [("rule-1", 1)]


def test_a_rule_removed_after_its_pass_gets_no_blocked_incident(tmp_path: Path) -> None:
    database, health = _health_with(tmp_path, _block("incremental"), _block("daily"))
    with SqliteUnitOfWorkFactory(database)() as uow:
        uow.rules.remove(rule().id)
        uow.commit()

    health.record_success(rule(), full_pass_floor=1)

    assert _incidents(database) == []


def test_block_health_waits_for_a_rule_removal_in_progress(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    unit_of_work = SqliteUnitOfWorkFactory(database)
    with unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()
    locks = RuleLocks()
    health = _rule_health(database, unit_of_work, locks=locks)
    removal = locks.for_rule(rule().id)
    removal.acquire()
    worker = Thread(target=health.record_full_pass, args=(rule().id, 0))
    worker.start()
    worker.join(0.1)
    waited = worker.is_alive()
    removal.release()
    worker.join(2)

    assert waited


def test_a_scheduled_run_that_listed_everything_checks_blocks_as_the_daily_pass() -> None:
    factory = InMemoryUnitOfWorkFactory()
    with factory() as uow:
        uow.rules.add(rule())
        uow.commit()

    class ListingEverything:
        """A reprojection or a rejected cursor lists both calendars in full."""

        def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
            return SyncRunResult(rule_id, run_id="forced", listed_in_full=True)

    health = RecordingHealth()
    scheduler = SyncScheduler(
        cast(ExecuteSyncRule, ListingEverything()), factory, cast(RunHealth, health)
    )

    assert scheduler._execute_with_retry(rule(), full=False) is True
    assert (health.full_successes, health.full_pass_run) == (1, "forced")


def test_failing_to_record_health_never_reports_a_successful_run_as_failed() -> None:
    class BrokenHealth(RecordingHealth):
        def record_success(
            self,
            _rule: object,
            *,
            full_pass_floor: int | None = None,
            full_pass_run: str | None = None,
        ) -> None:
            raise sqlite3.OperationalError("database is locked")

        def audit_floor(self) -> int:
            raise sqlite3.OperationalError("database is locked")

    health = BrokenHealth()
    scheduler = SyncScheduler(
        cast(ExecuteSyncRule, RecordingExecuteRule([None])),
        cast(UnitOfWorkFactory, None),
        cast(RunHealth, health),
    )

    assert scheduler._execute_with_retry(rule(), full=True) is True
    assert health.failures == []


def test_blocked_incident_is_notified_after_the_rule_lock_is_released(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    unit_of_work = SqliteUnitOfWorkFactory(database)
    with unit_of_work() as uow:
        uow.rules.add(rule())
        uow.audit.append(_block("incremental"))
        uow.audit.append(_block("daily"))
        uow.commit()
    locks = RuleLocks()
    held: list[bool] = []

    class LockCheckingChannel(NotificationChannel):
        def send(self, incident: IncidentNotification) -> None:
            held.append(locks.for_rule(rule().id).locked())

    health = _rule_health(
        database, unit_of_work, IncidentNotifier([LockCheckingChannel()]), locks=locks
    )

    health.record_full_pass(rule().id, 1)

    assert held == [False]


def test_a_block_first_found_by_a_retried_daily_pass_is_not_persisting(tmp_path: Path) -> None:
    # The first attempt recorded the block and then hit a retryable failure; the retry, a run of
    # its own, recorded it again. Neither predates the pass.
    database, health = _health_with(tmp_path, _block("attempt-1"), _block("attempt-2"))

    health.record_full_pass(rule().id, 0, "attempt-2")

    assert _incidents(database) == []


def test_a_run_interleaved_with_the_daily_pass_does_not_decide_its_incident(
    tmp_path: Path,
) -> None:
    # A block from before the pass, then a Sync Now that ran between the pass and its health
    # check blocked the same event again. The pass itself did not decide it.
    database, health = _health_with(tmp_path, _block("earlier"), _block("sync-now"))

    health.record_full_pass(rule().id, 1, "daily")

    assert _incidents(database) == []
    with sqlite3.connect(database) as connection:
        # The interleaved block is still the event's latest decision, so it stays open.
        assert open_blocks(connection) == [(2, "rule-1")]


def test_a_later_interleaved_decision_does_not_hide_the_daily_pass_verdict(
    tmp_path: Path,
) -> None:
    # Blocked before the pass, blocked again by the pass, then a Sync Now that ran before the
    # pass's health check decided the same event once more.
    database, health = _health_with(
        tmp_path, _block("earlier"), _block("daily"), _block("sync-now")
    )

    health.record_full_pass(rule().id, 1, "daily")

    assert [(key, state) for key, _category, state, _summary in _incidents(database)] == [
        ("blocked:rule-1", "open")
    ]


def test_an_incident_names_the_account_whose_failure_last_refreshed_it(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    incidents = SqliteIncidentRepository(database)
    at = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
    report = IncidentReport(
        "provider:rule-1", rule().id, "authentication", "s", ConnectedAccountId("personal")
    )

    incidents.open(report, at)
    first = SqliteOperationsQueries(database).incidents()[0].account_id
    incidents.open(replace(report, account_id=ConnectedAccountId("work")), at)
    refreshed = SqliteOperationsQueries(database).incidents()[0].account_id
    incidents.open(replace(report, account_id=None), at)
    unknown = SqliteOperationsQueries(database).incidents()[0].account_id

    assert (first, refreshed, unknown) == ("personal", "work", None)


def test_a_legacy_recurring_skip_is_not_evidence_of_an_earlier_block(tmp_path: Path) -> None:
    # Earlier releases recorded skipped recurring events as conflicts; they are skips.
    legacy = replace(_block("upgrade"), reason=SyncReason.RECURRING_UNSUPPORTED)
    database, health = _health_with(tmp_path, legacy, _block("daily"))

    health.record_full_pass(rule().id, 1, "daily")

    assert _incidents(database) == []


def test_incidents_open_once_refresh_while_open_and_reopen_after_resolving(
    tmp_path: Path,
) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    incidents = SqliteIncidentRepository(database)
    report = IncidentReport("provider:rule-1", rule().id, "temporary", "first summary")
    opened_at = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
    refreshed_at = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
    resolved_at = datetime(2026, 9, 29, 11, 0, tzinfo=UTC)
    reopened_at = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    columns = "state, summary, opened_at, updated_at, resolved_at, resolution"

    opened = incidents.open(report, opened_at)
    refreshed = incidents.open(replace(report, summary="second summary"), refreshed_at)
    with sqlite3.connect(database) as connection:
        while_open = connection.execute(f"SELECT {columns} FROM incidents").fetchone()
    incidents.resolve(report.key, resolved_at, IncidentResolution.SYNC_SUCCEEDED)
    with sqlite3.connect(database) as connection:
        resolved = connection.execute(f"SELECT {columns} FROM incidents").fetchone()
    reopened = incidents.open(report, reopened_at)

    assert (opened, refreshed, reopened) == (True, False, True)
    # Refreshing keeps when the episode began; resolving records when and why it ended.
    assert while_open == (
        "open",
        "second summary",
        opened_at.isoformat(),
        refreshed_at.isoformat(),
        None,
        None,
    )
    assert resolved == (
        "resolved",
        "second summary",
        opened_at.isoformat(),
        resolved_at.isoformat(),
        resolved_at.isoformat(),
        "sync_succeeded",
    )
    # Reopening starts a new episode, so "Since" never reaches back to an earlier one.
    with sqlite3.connect(database) as connection:
        rows = connection.execute(f"SELECT deduplication_key, {columns} FROM incidents").fetchall()
    assert rows == [
        (
            "provider:rule-1",
            "open",
            "first summary",
            reopened_at.isoformat(),
            reopened_at.isoformat(),
            None,
            None,
        )
    ]


def test_each_scheduler_pass_forgets_change_values_of_every_rule() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.PAUSED)
    now = datetime(2026, 9, 30, 10, tzinfo=UTC)

    class FixedClock:
        def now(self) -> datetime:
            return now

    scheduler = SyncScheduler(
        cast(ExecuteSyncRule, RecordingExecuteRule([])),
        unit_of_work,
        cast(RunHealth, RecordingHealth()),
        clock=FixedClock(),
    )

    asyncio.run(scheduler.run_once())

    # Paused and removed rules never run, so their values expire here rather than in a run.
    assert unit_of_work.state.change_values_forgotten_before == now - SOURCE_CHANGE_RETENTION


def test_a_failed_pass_is_logged_and_the_next_interval_runs_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    opened = 0

    def locked_once() -> UnitOfWork:
        # Clearing Activity can hold the database through VACUUM for longer than a busy timeout.
        nonlocal opened
        opened += 1
        if opened == 1:
            raise sqlite3.OperationalError("database is locked")
        return unit_of_work()

    scheduler = SyncScheduler(
        cast(ExecuteSyncRule, RecordingExecuteRule([])),
        locked_once,
        cast(RunHealth, RecordingHealth()),
        interval_seconds=0,
    )

    async def two_passes() -> None:
        task = asyncio.create_task(scheduler.run_forever())
        while unit_of_work.state.change_values_forgotten_before is None:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    with caplog.at_level("ERROR", logger="calendar_sync.infrastructure.scheduling"):
        asyncio.run(asyncio.wait_for(two_passes(), timeout=5))

    assert opened == 2
    assert [record.getMessage() for record in caplog.records] == [
        "Scheduled pass failed; trying again at the next interval"
    ]
    assert caplog.records[0].exc_info is not None
