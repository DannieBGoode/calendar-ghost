import asyncio
import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from threading import Barrier, Event, Lock, Thread
from typing import Any, cast
from unittest.mock import Mock, patch

import pytest

from calendar_sync.application.operations.installation_health import (
    InstallationIncident,
    InstallationIncidentKind,
)
from calendar_sync.application.operations.ports import (
    CauseSighting,
    InstallationUnitOfWork,
    InstallationUnitOfWorkFactory,
    SchedulerProgress,
    UserPlanStanding,
)
from calendar_sync.application.operations.scheduled_pass import (
    PlanNoticeDelivery,
    ScheduledPass,
    ScheduledRun,
    ScheduledServices,
    SyncRuns,
)
from calendar_sync.application.operations.scheduled_plan_holds import ScheduledPlanHolds
from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.errors import ProviderFailure
from calendar_sync.application.sync.health import RuleHealth, RunHealth
from calendar_sync.application.sync.health_ports import IncidentNotifications
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.ports import UnitOfWorkFactory
from calendar_sync.application.sync.run_ports import ProviderCallCounts, ScheduledRule
from calendar_sync.application.sync.sync_run import SOURCE_CHANGE_RETENTION
from calendar_sync.application.sync.synchronization import ExecuteSyncRule, SyncRunResult
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.audit import AuditAction, AuditEntry, AuditOutcome
from calendar_sync.domain.causes import ADMINISTRATOR_CAUSES, Cause
from calendar_sync.domain.incidents import (
    IncidentCategory,
    IncidentMessage,
    IncidentReport,
    IncidentResolution,
)
from calendar_sync.domain.model import (
    ConnectedAccountId,
    SyncReason,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.domain.plan_hold import PlanNotice, PlanNoticeKind
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.domain.runs import RuleRunOutcome, RunKind
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from calendar_sync.infrastructure.clock import SystemClock
from calendar_sync.infrastructure.identifiers import UuidRunIdGenerator
from calendar_sync.infrastructure.persistence.accounts import SqliteConnectedAccountStore
from calendar_sync.infrastructure.persistence.activity_queries import (
    SqliteOperationsQueries,
    open_blocks,
)
from calendar_sync.infrastructure.persistence.health import (
    SqliteIncidentRepository,
    SqliteRuleHealthRecords,
)
from calendar_sync.infrastructure.persistence.installation import (
    SqliteInstallationUnitOfWorkFactory,
)
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryUnitOfWorkFactory,
    InMemoryUserUnitOfWorkFactory,
    MemoryDatabase,
)
from calendar_sync.infrastructure.persistence.memory_installation import (
    InMemoryInstallationUnitOfWork,
    InMemoryInstallationUnitOfWorkFactory,
)
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteConnectedAccountRecords,
    SqliteSyncRuleRepository,
)
from calendar_sync.infrastructure.scheduling import SchedulerWatch, SyncScheduler
from calendar_sync.infrastructure.security import CredentialCipher
from tests.fake_calendar import FakeCalendars, FixedClock
from tests.helpers import endpoint, event, rule
from tests.scheduled_fakes import RecordingExecuteRule, RecordingHealth
from tests.users import (
    OTHER_USER,
    RULE_ACCOUNTS,
    USER,
    add_user,
    memory_units,
    rule_accounts,
    sqlite_units,
)


class RecordingNotifications:
    """The owning User's Incident Notifications, as they are delivered."""

    def __init__(self) -> None:
        self.incidents: list[IncidentReport] = []

    def incident_opened(self, incident: IncidentReport, at: datetime) -> None:
        self.incidents.append(incident)


def _scheduler(execute: object, units: object, health: object, **options: Any) -> SyncScheduler:
    """A scheduler over the store of `units`, running every User's rules with `execute`."""
    services = ScheduledServices(cast(SyncRuns, execute), cast(RunHealth, health))
    return _running(_installation_of(units), lambda _owner: services, **options)


def _running(
    installation: InstallationUnitOfWorkFactory,
    services_for: Callable[[UserId], ScheduledServices],
    *,
    clock: Clock | None = None,
    **options: Any,
) -> SyncScheduler:
    """A scheduler whose passes run each User's rules with the services `services_for` gives."""
    scheduled = ScheduledPass(installation, services_for, clock or SystemClock())
    return SyncScheduler(scheduled, clock=clock, **options)


def _installation_of(units: object) -> InstallationUnitOfWorkFactory:
    if isinstance(units, InMemoryUserUnitOfWorkFactory):
        return InMemoryInstallationUnitOfWorkFactory(units.database)
    # None, when a test never lists rules, or its own installation-wide unit of work.
    return cast(InstallationUnitOfWorkFactory, units)


def _scheduled(rule_: SyncRule) -> ScheduledRule:
    return ScheduledRule(USER, rule_, None)


def _rule_health(
    database: Path,
    unit_of_work: UnitOfWorkFactory,
    notifier: IncidentNotifications | None = None,
    *,
    locks: RuleLocks | None = None,
) -> RuleHealth:
    return RuleHealth(
        unit_of_work,
        SqliteRuleHealthRecords(database, add_user(database)),
        SqliteIncidentRepository(database, add_user(database)),
        SystemClock(),
        locks or RuleLocks(),
        notifier,
    )


def test_three_temporary_failures_open_one_incident(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    unit_of_work = sqlite_units(database)
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
    assert incidents == [("The calendar provider is temporarily unavailable", "open")]


def test_authentication_failure_degrades_rule_immediately(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    unit_of_work = sqlite_units(database)
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
    unit_of_work = sqlite_units(database)
    with unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()
    channel = RecordingNotifications()
    health = _rule_health(database, unit_of_work, channel)
    failure = ProviderFailure(ProviderFailureKind.PERMANENT, "synthetic rejection")

    health.record_failure(rule(), failure)
    health.record_failure(rule(), failure)

    assert len(channel.incidents) == 1
    assert channel.incidents[0].rule_id == rule().id


def test_success_resolves_existing_incident_and_resets_failure_count(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    unit_of_work = sqlite_units(database)
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


def test_degrading_after_an_authorization_failure_waits_for_a_concurrent_rule_change(
    tmp_path: Path,
) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    unit_of_work = sqlite_units(database)
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
    unit_of_work = sqlite_units(database)
    with unit_of_work() as uow:
        uow.rules.add(rule(state=SyncRuleState.REMOVING))
        uow.commit()
    channel = RecordingNotifications()
    health = _rule_health(database, unit_of_work, channel)
    failure = ProviderFailure(ProviderFailureKind.AUTHORIZATION, "synthetic denial")

    health.removal_blocked(rule().id, failure, attempted_at=datetime.now(UTC))
    health.removal_blocked(rule().id, failure, attempted_at=datetime.now(UTC))

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
            "Rule Removal stopped: Access to the calendar provider was denied",
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
    second = replace(rule(), id=SyncRuleId("rule-2"), source=endpoint("other", "calendar"))
    factory = memory_units(accounts=rule_accounts(rule(), second))
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
        scheduler = _scheduler(execute, factory, health)
        asyncio.run(scheduler.run_once())

    # rule-1 finished today's full pass; rule-2 never did, so only it lists everything again.
    # The two rules run side by side, so either may start first.
    assert sorted(execute.full) == sorted([("rule-1", False), ("rule-2", True)] * 2)
    # Rule health learns which runs were full passes, where persisting blocks become incidents.
    assert health.full_successes == 2


class ConcurrencyRecordingExecuteRule:
    """Records the most runs in flight at once; each waits until `together` are, or for `hold`."""

    def __init__(self, *, together: int = 1, hold: float = 0.0) -> None:
        self._barrier = Barrier(together, timeout=5)
        self._hold = hold
        self._guard = Lock()
        self._running = 0
        self.most_at_once = 0
        self.ran: list[str] = []

    def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
        with self._guard:
            self._running += 1
            self.most_at_once = max(self.most_at_once, self._running)
        try:
            self._barrier.wait()
            time.sleep(self._hold)
        finally:
            with self._guard:
                self._running -= 1
                self.ran.append(rule_id.value)
        return SyncRunResult(rule_id)


def _enabled_rules(count: int) -> InMemoryUserUnitOfWorkFactory:
    rules = [
        replace(
            rule(),
            id=SyncRuleId(f"rule-{number}"),
            source=endpoint(f"account-{number}", "calendar"),
        )
        for number in range(1, count + 1)
    ]
    factory = memory_units(accounts=rule_accounts(*rules))
    with factory() as uow:
        for each in rules:
            uow.rules.add(each)
        uow.commit()
    return factory


def _awaiting_reauthorization() -> InMemoryUserUnitOfWorkFactory:
    factory = memory_units()
    with factory() as uow:
        uow.rules.add(rule().degrade(awaiting_reauthorization=True))
        uow.commit()
    return factory


def test_a_pass_first_resumes_rules_an_interrupted_restoration_left_stopped() -> None:
    units = _awaiting_reauthorization()

    class Resuming(RecordingHealth):
        def finish_interrupted_lapses(self) -> int:
            with units() as uow:
                stopped = uow.rules.get(rule().id)
                assert stopped is not None
                uow.rules.save(stopped.resume_after_reauthorization())
                uow.commit()
            return 1

    execute = RecordingExecuteRule([None])

    asyncio.run(_scheduler(execute, units, Resuming()).run_once())

    # Resumed before the pass listed its rules, so the rule ran in the same pass.
    assert execute.calls == 1


def test_a_failure_to_resume_rules_never_stops_the_pass(caplog: pytest.LogCaptureFixture) -> None:
    units = _awaiting_reauthorization()
    running = replace(rule(), id=SyncRuleId("running"), source=endpoint("other", "cal"))
    memory_units(InMemoryUnitOfWorkFactory(units.database), accounts=rule_accounts(running))
    with units() as uow:
        uow.rules.add(running)
        uow.commit()

    class Failing(RecordingHealth):
        def finish_interrupted_lapses(self) -> int:
            raise sqlite3.OperationalError("database is locked")

    execute = RecordingExecuteRule([None])

    asyncio.run(_scheduler(execute, units, Failing()).run_once())

    assert execute.calls == 1
    assert "Finishing an interrupted lapse or restoration failed" in caplog.text


def test_a_pass_runs_different_rules_at_the_same_time() -> None:
    # A rule that waits on a slow provider must not hold up every other rule behind it.
    execute = ConcurrencyRecordingExecuteRule(together=2)
    health = RecordingHealth()
    scheduler = _scheduler(execute, _enabled_rules(2), health, concurrency=2)

    asyncio.run(scheduler.run_once())

    assert sorted(execute.ran) == ["rule-1", "rule-2"]
    assert health.failures == []
    assert health.successes == 2


def test_a_pass_runs_no_more_rules_at_once_than_its_concurrency() -> None:
    # Each run lasts long enough that, unbounded, all four would overlap.
    execute = ConcurrencyRecordingExecuteRule(hold=0.05)
    health = RecordingHealth()
    scheduler = _scheduler(execute, _enabled_rules(4), health, concurrency=2)

    asyncio.run(scheduler.run_once())

    assert execute.most_at_once == 2
    assert sorted(execute.ran) == ["rule-1", "rule-2", "rule-3", "rule-4"]
    assert health.successes == 4


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
    unit_of_work = sqlite_units(database)
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
            " reason, run_id, detail, user_id)"
            " VALUES ('2026-09-29', 'rule-1', 'conflict', 'blocked',"
            " 'occurrence', 'destination_occurrence_missing', 'later', '', 'user-1')"
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
            " reason, run_id, detail, user_id)"
            " VALUES ('2026-09-30', 'rule-1', 'update', 'completed',"
            " 'occurrence', 'occurrence_changed', 'next-daily', '', 'user-1')"
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
        assert open_blocks(connection, USER.value) == []


def test_unrelated_activity_never_hides_an_open_block(tmp_path: Path) -> None:
    database, _health = _health_with(tmp_path, _block("incremental"))
    other = replace(rule(), id=SyncRuleId("rule-2"), source=endpoint("other", "calendar"))
    with sqlite_units(database, accounts=(*RULE_ACCOUNTS, "other"))() as uow:
        uow.rules.add(other)
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.executemany(
            "INSERT INTO audit_entries (occurred_at, rule_id, action, outcome, source_event_id,"
            " reason, run_id, detail, user_id)"
            " VALUES ('2026-09-30', 'rule-2', 'ignore', 'skipped', ?,"
            " 'projection_current', 'busy', '', 'user-1')",
            ((str(index),) for index in range(60_000)),
        )
        assert open_blocks(connection, USER.value) == [(1, "rule-1")]


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
    with sqlite_units(database)() as uow:
        uow.rules.remove(rule().id)
        uow.commit()

    health.record_success(rule(), full_pass_floor=1)

    assert _incidents(database) == []


def test_block_health_waits_for_a_rule_removal_in_progress(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    unit_of_work = sqlite_units(database)
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


def test_blocked_incident_is_notified_after_the_rule_lock_is_released(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    unit_of_work = sqlite_units(database)
    with unit_of_work() as uow:
        uow.rules.add(rule())
        uow.audit.append(_block("incremental"))
        uow.audit.append(_block("daily"))
        uow.commit()
    locks = RuleLocks()
    held: list[bool] = []

    class LockChecking:
        def incident_opened(self, incident: IncidentReport, at: datetime) -> None:
            held.append(locks.for_rule(rule().id).locked())

    health = _rule_health(database, unit_of_work, LockChecking(), locks=locks)

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
        assert open_blocks(connection, USER.value) == [(2, "rule-1")]


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
    incidents = SqliteIncidentRepository(database, add_user(database))
    at = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
    report = IncidentReport(
        "provider:rule-1",
        rule().id,
        IncidentCategory.AUTHENTICATION,
        "s",
        ConnectedAccountId("personal"),
    )

    incidents.open(report, at)
    first = SqliteOperationsQueries(database, add_user(database)).incidents()[0].account_id
    incidents.open(replace(report, account_id=ConnectedAccountId("work")), at)
    refreshed = SqliteOperationsQueries(database, add_user(database)).incidents()[0].account_id
    incidents.open(replace(report, account_id=None), at)
    unknown = SqliteOperationsQueries(database, add_user(database)).incidents()[0].account_id

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
    incidents = SqliteIncidentRepository(database, add_user(database))
    report = IncidentReport(
        "provider:rule-1", rule().id, IncidentCategory.TEMPORARY, "first summary"
    )
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


def test_incident_messages_round_trip_and_refresh(tmp_path: Path) -> None:
    database = tmp_path / "calendar.db"
    initialize_database(database)
    incidents = SqliteIncidentRepository(database, add_user(database))
    queries = SqliteOperationsQueries(database, add_user(database))
    at = datetime(2026, 10, 3, tzinfo=UTC)
    first = IncidentReport(
        "provider:r1",
        SyncRuleId("r1"),
        IncidentCategory.RATE_LIMIT,
        "Google Calendar is limiting requests",
        message=IncidentMessage("provider_failure", {"kind": "rate_limit", "provider": "google"}),
    )
    incidents.open(first, at)
    assert queries.incidents()[0].message == first.message
    refreshed = replace(
        first,
        category=IncidentCategory.AUTHORIZATION,
        summary="Access to Google Calendar was denied",
        message=IncidentMessage(
            "provider_failure", {"kind": "authorization", "provider": "google"}
        ),
    )
    incidents.open(refreshed, at)
    assert queries.incidents()[0].message == refreshed.message
    # A refresh that changes the code replaces the code as well as the params.
    recoded = replace(
        refreshed,
        message=IncidentMessage("removal_stopped", {"kind": "permanent", "provider": None}),
    )
    incidents.open(recoded, at)
    assert queries.incidents()[0].message == recoded.message


def test_refreshing_a_legacy_incident_records_its_message(tmp_path: Path) -> None:
    database = tmp_path / "calendar.db"
    initialize_database(database)
    add_user(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO incidents (
                id, deduplication_key, rule_id, category, state, summary, opened_at,
                updated_at, message_code, message_params, user_id
            ) VALUES ('legacy', 'provider:r1', NULL, 'temporary', 'open', 'Old', ?, ?, NULL, NULL,
                (SELECT id FROM users ORDER BY rowid LIMIT 1))
            """,
            ("2026-10-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00"),
        )
    report = IncidentReport(
        "provider:r1",
        SyncRuleId("r1"),
        IncidentCategory.RATE_LIMIT,
        "Google Calendar is limiting requests",
        message=IncidentMessage("provider_failure", {"kind": "rate_limit", "provider": "google"}),
    )

    opened = SqliteIncidentRepository(database, add_user(database)).open(
        report, datetime(2026, 10, 3, tzinfo=UTC)
    )

    with sqlite3.connect(database) as connection:
        stored = connection.execute(
            "SELECT id, message_code, message_params FROM incidents"
        ).fetchall()
    assert opened is False
    assert stored == [
        ("legacy", "provider_failure", '{"kind": "rate_limit", "provider": "google"}')
    ]


def test_legacy_and_corrupt_incident_messages_read_as_none(tmp_path: Path) -> None:
    database = tmp_path / "calendar.db"
    initialize_database(database)
    add_user(database)
    with sqlite3.connect(database) as connection:
        for key, code, params in (
            ("a", None, None),
            ("b", "provider_failure", "{not json"),
            ("c", "x", "[1]"),
            ("d", "provider_failure", '{"kind": []}'),
            ("e", "events_still_blocked", '{"count": true}'),
        ):
            connection.execute(
                """
                INSERT INTO incidents (
                    id, deduplication_key, rule_id, category, state, summary, opened_at,
                    updated_at, message_code, message_params, user_id
                ) VALUES (?, ?, NULL, 'temporary', 'open', 'Old', ?, ?, ?, ?,
                    (SELECT id FROM users ORDER BY rowid LIMIT 1))
                """,
                (key, key, "2026-10-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00", code, params),
            )
    assert [
        incident.message
        for incident in SqliteOperationsQueries(database, add_user(database)).incidents()
    ] == [None] * 5


def test_each_scheduler_pass_forgets_change_values_of_every_rule() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.PAUSED)
    now = datetime(2026, 9, 30, 10, tzinfo=UTC)

    class FixedClock:
        def now(self) -> datetime:
            return now

    scheduler = _scheduler(
        RecordingExecuteRule([]),
        unit_of_work,
        RecordingHealth(),
        clock=FixedClock(),
    )

    asyncio.run(scheduler.run_once())

    # Paused and removed rules never run, so their values expire here rather than in a run.
    assert unit_of_work.state.change_values_forgotten_before == now - SOURCE_CHANGE_RETENTION


def test_each_scheduler_pass_forgets_provider_calls_older_than_30_days() -> None:
    unit_of_work = memory_units()
    today = date(2026, 9, 30)
    for days_ago in (0, 29, 30):
        unit_of_work.state.provider_calls[(ProviderKind.GOOGLE, today - timedelta(days_ago))] = (
            ProviderCallCounts(days_ago + 1)
        )

    class LateClock:
        def now(self) -> datetime:
            # Still the 29th west of UTC, already the 30th in UTC.
            return datetime(2026, 9, 29, 22, tzinfo=timezone(timedelta(hours=-5)))

    scheduler = _scheduler(
        RecordingExecuteRule([]), unit_of_work, RecordingHealth(), clock=LateClock()
    )

    asyncio.run(scheduler.run_once())

    assert sorted(day for _, day in unit_of_work.state.provider_calls) == [
        today - timedelta(29),
        today,
    ]


def test_a_failed_pass_is_logged_and_the_next_interval_runs_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    unit_of_work = memory_units()
    opened = 0

    def locked_once() -> InstallationUnitOfWork:
        # Clearing Activity can hold the database through VACUUM for longer than a busy timeout.
        nonlocal opened
        opened += 1
        if opened == 1:
            raise sqlite3.OperationalError("database is locked")
        return InMemoryInstallationUnitOfWork(unit_of_work.database)

    scheduler = _scheduler(
        RecordingExecuteRule([]),
        locked_once,
        RecordingHealth(),
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

    # Preparation and listing use separate scopes so per-User writes are visible.
    assert opened >= 2
    assert [record.getMessage() for record in caplog.records] == [
        "Scheduled pass failed; trying again at the next interval"
    ]
    assert caplog.records[0].exc_info is not None


class SteppingClock:
    """A clock that moves forward by one minute each time it is read."""

    def __init__(self, start: datetime) -> None:
        self.moment = start

    def now(self) -> datetime:
        current = self.moment
        self.moment = current + timedelta(minutes=1)
        return current


def test_the_scheduler_reports_when_it_started_and_its_last_completed_pass() -> None:
    clock = SteppingClock(datetime(2026, 10, 3, 9, 0, tzinfo=UTC))
    scheduler = _scheduler(
        RecordingExecuteRule([]),
        memory_units(),
        Mock(),
        clock=clock,
    )

    before = scheduler.progress()
    asyncio.run(scheduler.run_once())
    after = scheduler.progress()

    assert before.running_since == datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
    assert before.pass_started_at is None
    assert before.last_completed_at is None
    assert after.pass_started_at is None
    assert after.last_completed_at is not None
    assert after.last_completed_at > after.running_since


def test_a_pass_that_raises_is_not_counted_as_completed() -> None:
    class BrokenUnitOfWork:
        def __call__(self) -> InstallationUnitOfWork:
            raise sqlite3.OperationalError("database is locked")

    scheduler = _scheduler(
        RecordingExecuteRule([]),
        BrokenUnitOfWork(),
        Mock(),
        clock=SteppingClock(datetime(2026, 10, 3, 9, 0, tzinfo=UTC)),
    )

    with pytest.raises(sqlite3.OperationalError):
        asyncio.run(scheduler.run_once())

    progress = scheduler.progress()
    assert progress.pass_started_at is None
    assert progress.last_completed_at is None
    assert progress.last_pass_rule_ids == frozenset()


class ObservingClock(SteppingClock):
    """A stepping clock that also records what the scheduler reports each time it is read."""

    def __init__(self, start: datetime) -> None:
        super().__init__(start)
        self.scheduler: SyncScheduler | None = None
        self.seen: list[SchedulerProgress] = []

    def now(self) -> datetime:
        if self.scheduler is not None:
            self.seen.append(self.scheduler.progress())
        return super().now()


def test_a_completed_pass_is_published_before_the_running_pass_is_cleared() -> None:
    clock = ObservingClock(datetime(2026, 10, 3, 9, 0, tzinfo=UTC))
    scheduler = _scheduler(
        RecordingExecuteRule([]),
        memory_units(),
        Mock(),
        clock=clock,
    )
    clock.scheduler = scheduler

    asyncio.run(scheduler.run_once())

    # The first read starts the pass. Every later read happens while it runs, so none may show
    # "no pass running" next to the previous completion: a request thread would read stalled.
    assert clock.seen[1:]
    assert all(progress.pass_started_at is not None for progress in clock.seen[1:])
    assert scheduler.progress().pass_started_at is None
    assert scheduler.progress().last_completed_at is not None


def test_the_rules_a_pass_listed_are_published_only_when_it_completes() -> None:
    unit_of_work = memory_units()
    enabled = rule()
    paused = replace(rule(state=SyncRuleState.PAUSED), id=SyncRuleId("paused-rule"))
    unit_of_work.state.rules[enabled.id] = enabled
    unit_of_work.state.rules[paused.id] = paused
    seen_during_pass: list[frozenset[str]] = []

    class ObservingExecuteRule:
        def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
            seen_during_pass.append(scheduler.progress().last_pass_rule_ids)
            return SyncRunResult(rule_id)

    scheduler = _scheduler(
        ObservingExecuteRule(),
        unit_of_work,
        RecordingHealth(),
        clock=SteppingClock(datetime(2026, 10, 3, 9, 0, tzinfo=UTC)),
    )

    assert scheduler.progress().last_pass_rule_ids == frozenset()
    asyncio.run(scheduler.run_once())

    assert seen_during_pass == [frozenset()]
    # Only enabled rules are listed by a pass; a paused one is not.
    assert scheduler.progress().last_pass_rule_ids == frozenset({enabled.id.value})


def test_restoring_an_account_while_its_rule_is_being_stopped_leaves_the_rule_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Restoration clears the lapse after the stopping run read it, but before that run's write.
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    add_user(database)
    work = store.for_user(USER).save(
        "Work", "work@example.test", "{}", provider=ProviderKind.GOOGLE
    )
    running = replace(
        rule(), source=endpoint(work.id.value, "home"), destination=endpoint(work.id.value, "work")
    )
    unit_of_work = sqlite_units(database)
    with unit_of_work() as uow:
        uow.rules.add(running)
        uow.commit()
    health = _rule_health(database, unit_of_work)
    restoring: list[Thread] = []
    checked = SqliteConnectedAccountRecords.authorized

    def restored_after_reading(
        self: SqliteConnectedAccountRecords, account_id: ConnectedAccountId
    ) -> bool:
        authorized = checked(self, account_id)
        if restoring:
            return authorized
        restoring.append(
            Thread(
                target=health.lapses.restored,
                args=(work.id,),
                kwargs={"accepted_at": datetime.now(UTC)},
            )
        )
        restoring[0].start()
        # Restoration clears the lapse at once, then waits for this rule's write lock.
        while _lapsed(store, work.id):
            time.sleep(0.01)
        return authorized

    monkeypatch.setattr(SqliteConnectedAccountRecords, "authorized", restored_after_reading)
    expired = ProviderFailure(ProviderFailureKind.AUTHENTICATION, "expired", account_id=work.id)

    health.record_failure(running, expired, attempted_at=datetime.now(UTC))
    restoring[0].join(timeout=5)

    with unit_of_work() as uow:
        stopped = uow.rules.get(running.id)
    assert stopped is not None
    assert stopped.state is SyncRuleState.ENABLED


def test_a_pass_finishes_a_restoration_the_process_stopped_before(tmp_path: Path) -> None:
    # Reauthorizing saved the new credentials, clearing the lapse, then the process stopped
    # before restoring resumed the rule or resolved the account's Incident.
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    add_user(database)
    work = store.for_user(USER).save(
        "Work", "work@example.test", "{}", provider=ProviderKind.GOOGLE
    )
    stopped = replace(
        rule(), source=endpoint(work.id.value, "home"), destination=endpoint(work.id.value, "work")
    )
    unit_of_work = sqlite_units(database)
    with unit_of_work() as uow:
        uow.rules.add(stopped)
        uow.commit()
    health = _rule_health(database, unit_of_work)
    expired = ProviderFailure(ProviderFailureKind.AUTHENTICATION, "expired", account_id=work.id)
    health.record_failure(stopped, expired, attempted_at=datetime.now(UTC))
    store.for_user(USER).save("Work", "work@example.test", "{}", provider=ProviderKind.GOOGLE)
    assert not _lapsed(store, work.id)
    execute = RecordingExecuteRule([None])
    services = ScheduledServices(cast(SyncRuns, execute), health)

    asyncio.run(
        _running(SqliteInstallationUnitOfWorkFactory(database), lambda _owner: services).run_once()
    )

    with unit_of_work() as uow:
        resumed = uow.rules.get(stopped.id)
    with sqlite3.connect(database) as connection:
        incidents = connection.execute("SELECT state, resolution FROM incidents").fetchall()
    assert resumed is not None
    assert resumed.state is SyncRuleState.ENABLED
    assert incidents == [("resolved", "access_restored")]
    assert execute.calls == 1


def test_a_check_waiting_on_the_provider_holds_up_no_rule() -> None:
    # The check answers only once the rule has run, so a pass that ran checks before its rules,
    # or after them, would wait for the full timeout.
    ran = Event()

    class WaitingFixes:
        def execute(self) -> int:
            assert ran.wait(timeout=5), "the rule never ran while the check waited"
            return 0

    class SignallingRule(RecordingExecuteRule):
        def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
            ran.set()
            return super().execute(rule_id, full=full)

    units = _enabled_rules(1)
    installation = InMemoryInstallationUnitOfWorkFactory(units.database)
    execute = SignallingRule([None])
    services = ScheduledServices(
        cast(SyncRuns, execute), cast(RunHealth, RecordingHealth()), WaitingFixes()
    )
    sightings = [CauseSighting(USER, Cause.OAUTH_CLIENT_INVALID, datetime.now(UTC), True)]
    with patch.object(InMemoryInstallationUnitOfWork, "failure_causes", lambda *_: sightings):
        started = time.monotonic()
        asyncio.run(_running(installation, lambda _owner: services, concurrency=2).run_once())

    assert execute.calls == 1
    assert time.monotonic() - started < 5


def test_the_incidents_name_the_accounts_an_administrators_cause_stopped(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    add_user(database)
    accounts = store.for_user(USER)
    work = accounts.save("Work", "work@example.test", "{}", provider=ProviderKind.GOOGLE)
    home = accounts.save("Home", "home@example.test", "{}", provider=ProviderKind.GOOGLE)
    unit_of_work = sqlite_units(database)
    health = _rule_health(database, unit_of_work)
    for account, cause in ((work, Cause.OAUTH_CLIENT_INVALID), (home, Cause.ACCESS_REVOKED)):
        refused = ProviderFailure(
            ProviderFailureKind.AUTHENTICATION, "refused", account_id=account.id, cause=cause
        )
        health.lapses.lapsed(account.id, refused, attempted_at=datetime.now(UTC))

    incidents = SqliteIncidentRepository(database, add_user(database))

    assert incidents.accounts_lapsed_by(ADMINISTRATOR_CAUSES) == {work.id}
    assert incidents.accounts_lapsed_by(()) == frozenset()


def test_a_lapse_committed_while_a_rule_resumes_keeps_it_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Another rule's run commits a new lapse after resuming checked the accounts, before it saved.
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    add_user(database)
    work = store.for_user(USER).save(
        "Work", "work@example.test", "{}", provider=ProviderKind.GOOGLE
    )
    stopped = replace(
        rule(), source=endpoint(work.id.value, "home"), destination=endpoint(work.id.value, "work")
    ).degrade(awaiting_reauthorization=True)
    unit_of_work = sqlite_units(database)
    with unit_of_work() as uow:
        uow.rules.add(stopped)
        uow.commit()
    health = _rule_health(database, unit_of_work)
    save = SqliteSyncRuleRepository.save

    def lapsing_first(self: SqliteSyncRuleRepository, saved: SyncRule) -> None:
        with sqlite3.connect(database) as connection:
            connection.execute(
                "UPDATE connected_accounts SET authorization_lapsed_at = ? WHERE id = ?",
                (datetime.now(UTC).isoformat(), work.id.value),
            )
        save(self, saved)

    monkeypatch.setattr(SqliteSyncRuleRepository, "save", lapsing_first)

    assert health.finish_interrupted_lapses() == 0
    with unit_of_work() as uow:
        kept = uow.rules.get(stopped.id)
    assert kept is not None
    assert kept.state is SyncRuleState.DEGRADED


def test_a_pass_resolves_an_authorized_accounts_incident_with_no_rule_waiting(
    tmp_path: Path,
) -> None:
    # A lapse opened the account's Incident while no rule awaited the account, as when the User
    # paused or removed the one it stopped. Reauthorizing then saved new credentials, clearing the
    # lapse, and the process stopped before restoring resolved the Incident.
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    add_user(database)
    work = store.for_user(USER).save(
        "Work", "work@example.test", "{}", provider=ProviderKind.GOOGLE
    )
    unit_of_work = sqlite_units(database)
    health = _rule_health(database, unit_of_work)
    expired = ProviderFailure(ProviderFailureKind.AUTHENTICATION, "expired", account_id=work.id)
    health.lapses.lapsed(work.id, expired, attempted_at=datetime.now(UTC))
    store.for_user(USER).save("Work", "work@example.test", "{}", provider=ProviderKind.GOOGLE)
    services = ScheduledServices(cast(SyncRuns, RecordingExecuteRule([])), health)

    asyncio.run(
        _running(SqliteInstallationUnitOfWorkFactory(database), lambda _owner: services).run_once()
    )

    with sqlite3.connect(database) as connection:
        incidents = connection.execute("SELECT state, resolution FROM incidents").fetchall()
    assert incidents == [("resolved", "access_restored")]


def _work_account(database: Path) -> tuple[ConnectedAccountId, SyncRule, UnitOfWorkFactory]:
    """A Google account recorded with its credentials, and an enabled rule that uses it."""
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    add_user(database)
    work = store.for_user(USER).save(
        "Work", "work@example.test", "{}", provider=ProviderKind.GOOGLE
    )
    running = replace(
        rule(), source=endpoint(work.id.value, "home"), destination=endpoint(work.id.value, "work")
    )
    unit_of_work = sqlite_units(database)
    with unit_of_work() as uow:
        uow.rules.add(running)
        uow.commit()
    return work.id, running, unit_of_work


def _account_incidents(database: Path) -> list[tuple[str, str, str, str]]:
    with sqlite3.connect(database) as connection:
        return connection.execute(
            "SELECT deduplication_key, state, category, cause FROM incidents"
        ).fetchall()


def test_a_pass_finishes_a_lapse_the_process_stopped_after_recording(tmp_path: Path) -> None:
    # The lapse committed, then the process stopped before it stopped the account's rules or
    # opened its Incident.
    database = tmp_path / "test.db"
    initialize_database(database)
    work, running, unit_of_work = _work_account(database)
    with unit_of_work() as uow:
        assert uow.accounts.lapse(work, attempted_at=datetime.now(UTC))
        uow.commit()
    notifications = RecordingNotifications()
    health = _rule_health(database, unit_of_work, notifications)
    execute = RecordingExecuteRule([])
    services = ScheduledServices(cast(SyncRuns, execute), health)
    scheduler = _running(SqliteInstallationUnitOfWorkFactory(database), lambda _owner: services)

    asyncio.run(scheduler.run_once())
    asyncio.run(scheduler.run_once())

    with unit_of_work() as uow:
        stopped = uow.rules.get(running.id)
    assert stopped is not None
    assert (stopped.state, stopped.awaiting_reauthorization) == (SyncRuleState.DEGRADED, True)
    assert execute.calls == 0
    # No refusal is at hand, so the Incident says what every lapse means, with no Cause.
    assert _account_incidents(database) == [
        (f"authorization:{work.value}", "open", "authentication", "none")
    ]
    (notified,) = notifications.incidents
    # The core names no provider; the Web UI names it from the message's `provider`.
    assert notified.summary == "Authorization for the calendar provider expired"


def test_finishing_a_lapse_keeps_the_incident_a_lapse_opens_meanwhile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Another request's lapse opens the Incident after finishing read that none was open.
    database = tmp_path / "test.db"
    initialize_database(database)
    work, _, unit_of_work = _work_account(database)
    notifications = RecordingNotifications()
    health = _rule_health(database, unit_of_work, notifications)
    refused = ProviderFailure(
        ProviderFailureKind.AUTHORIZATION,
        "client invalid",
        account_id=work,
        provider=ProviderKind.GOOGLE,
        cause=Cause.OAUTH_CLIENT_INVALID,
    )
    health.lapses.lapsed(work, refused, attempted_at=datetime.now(UTC))
    monkeypatch.setattr(
        SqliteIncidentRepository, "accounts_with_open_incidents", lambda _self: frozenset()
    )

    health.finish_interrupted_lapses()

    assert _account_incidents(database) == [
        (f"authorization:{work.value}", "open", "authorization", "oauth_client_invalid")
    ]
    assert len(notifications.incidents) == 1


def _lapsed(store: SqliteConnectedAccountStore, account_id: ConnectedAccountId) -> bool:
    account = store.for_user(USER).get(account_id)
    return account is not None and account.authorization_lapsed_at is not None


def test_a_refusal_from_before_reauthorization_neither_lapses_nor_stops(tmp_path: Path) -> None:
    # The run began with the old credentials; Google refused it after the account was
    # reauthorized and restored, so the refusal says nothing about the fresh credentials.
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    add_user(database)
    began = datetime.now(UTC)
    work = store.for_user(USER).save(
        "Work", "work@example.test", "{}", provider=ProviderKind.GOOGLE
    )
    running = replace(
        rule(), source=endpoint(work.id.value, "home"), destination=endpoint(work.id.value, "work")
    )
    unit_of_work = sqlite_units(database)
    with unit_of_work() as uow:
        uow.rules.add(running)
        uow.commit()
    health = _rule_health(database, unit_of_work)
    expired = ProviderFailure(ProviderFailureKind.AUTHENTICATION, "expired", account_id=work.id)

    health.record_failure(running, expired, attempted_at=began)

    assert not _lapsed(store, work.id)
    with unit_of_work() as uow:
        kept = uow.rules.get(running.id)
    assert kept is not None
    assert kept.state is SyncRuleState.ENABLED
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM incidents").fetchone() == (0,)


def _theirs(rule_id: SyncRuleId) -> SyncRule:
    """Another User's rule, on accounts of their own, as a rule's accounts must be its User's."""
    return replace(
        rule(),
        id=rule_id,
        source=endpoint("their-personal-account", "personal-calendar"),
        destination=endpoint("their-work-account", "work-calendar"),
    )


def test_each_rule_runs_with_its_owners_services() -> None:
    database = InMemoryUnitOfWorkFactory()
    theirs = _theirs(SyncRuleId("rule-2"))
    for user, owned in ((USER, rule()), (OTHER_USER, theirs)):
        memory_units(database, user=user, accounts=rule_accounts(owned))
        with database.for_user(user)() as uow:
            uow.rules.add(owned)
            uow.commit()
    ran: list[tuple[UserId, str]] = []

    def services_for(owner: UserId) -> ScheduledServices:
        class OwnersRuns:
            def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
                ran.append((owner, rule_id.value))
                return SyncRunResult(rule_id)

        return ScheduledServices(cast(SyncRuns, OwnersRuns()), cast(RunHealth, RecordingHealth()))

    asyncio.run(_running(database.installation(), services_for).run_once())

    assert sorted(ran, key=lambda item: item[1]) == [(USER, "rule-1"), (OTHER_USER, "rule-2")]


def test_a_disabled_users_rules_are_held_until_they_are_enabled_again() -> None:
    database = InMemoryUnitOfWorkFactory()
    for user, owned in ((USER, rule()), (OTHER_USER, _theirs(SyncRuleId("rule-2")))):
        memory_units(database, user=user, accounts=rule_accounts(owned))
        with database.for_user(user)() as uow:
            uow.rules.add(owned)
            uow.commit()
    execute = FullPassRecordingExecuteRule()
    scheduler = _scheduler(execute, database.for_user(USER), RecordingHealth())

    database.database.disabled.add(OTHER_USER)
    asyncio.run(scheduler.run_once())
    held = [rule_id for rule_id, _ in execute.full]
    database.database.disabled.discard(OTHER_USER)
    asyncio.run(scheduler.run_once())

    assert held == ["rule-1"]
    assert sorted(rule_id for rule_id, _ in execute.full) == ["rule-1", "rule-1", "rule-2"]


def test_a_queued_rule_does_not_run_once_its_user_is_disabled() -> None:
    """A pass lists rules before running them; a User disabled in between gets no writes."""
    database = InMemoryUnitOfWorkFactory()
    theirs = _theirs(SyncRuleId("rule-2"))
    for user, owned in ((USER, rule()), (OTHER_USER, theirs)):
        memory_units(database, user=user, accounts=rule_accounts(owned))
        with database.for_user(user)() as uow:
            uow.rules.add(owned)
            uow.commit()
    calendars = FakeCalendars()
    calendars.put(event(calendar=theirs.source))
    health = RecordingHealth()

    class DisablingTheOtherUser:
        def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
            database.database.disabled.add(OTHER_USER)
            return SyncRunResult(rule_id)

    fingerprinter = ProjectionFingerprinter()
    their_runs = ExecuteSyncRule(
        database.for_user(OTHER_USER),
        calendars,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
        UuidRunIdGenerator(),
        locks=RuleLocks(),
    )

    def services_for(owner: UserId) -> ScheduledServices:
        runs = their_runs if owner == OTHER_USER else DisablingTheOtherUser()
        return ScheduledServices(cast(SyncRuns, runs), cast(RunHealth, health))

    asyncio.run(_running(database.installation(), services_for, concurrency=1).run_once())

    assert calendars.writes == []
    assert health.failures == []


class Progressing:
    def __init__(self, progress: SchedulerProgress) -> None:
        self.current = progress

    def progress(self) -> SchedulerProgress:
        return self.current


class HeardIncidents:
    def __init__(self) -> None:
        self.heard: list[InstallationIncident] = []

    def installation_incident_opened(self, incident: InstallationIncident) -> None:
        self.heard.append(incident)


def test_the_installation_hears_once_when_the_scheduler_stalls_and_again_after_it_recovers() -> (
    None
):
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    ticking = SchedulerProgress(now - timedelta(days=1), None, now - timedelta(minutes=2))
    stalled = replace(ticking, last_completed_at=now - timedelta(minutes=20))
    heartbeat = Progressing(ticking)
    heard = HeardIncidents()

    class Clock:
        def now(self) -> datetime:
            return now

    watch = SchedulerWatch(heartbeat, heard, Clock())
    watch.check()
    heartbeat.current = stalled
    watch.check()
    watch.check()
    heartbeat.current = ticking
    watch.check()
    heartbeat.current = stalled
    watch.check()

    assert (
        heard.heard
        == [
            InstallationIncident(
                InstallationIncidentKind.SCHEDULER_STALLED, now - timedelta(minutes=20)
            )
        ]
        * 2
    )


def test_the_scheduler_says_when_its_next_pass_begins(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FixedClock()
    scheduler = _running(
        InMemoryUnitOfWorkFactory().installation(),
        lambda _owner: cast(ScheduledServices, None),
        interval_seconds=300,
        clock=clock,
    )
    resting: list[SchedulerProgress] = []

    async def sleep(_seconds: float) -> None:
        resting.append(scheduler.progress())
        raise asyncio.CancelledError

    monkeypatch.setattr("calendar_sync.infrastructure.scheduling.asyncio.sleep", sleep)

    before = scheduler.progress()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scheduler.run_forever())

    # Before its first pass it is about to run; between passes it rests for the interval.
    assert before.next_pass_at == clock.now()
    assert [progress.next_pass_at for progress in resting] == [clock.now() + timedelta(seconds=300)]


class PlanMailPass(ScheduledPass):
    """A pass with controllable notices and one rule, without a provider."""

    def __init__(self) -> None:
        from calendar_sync.domain.plan_hold import PlanNotice, PlanNoticeKind

        self.notice = PlanNotice(PlanNoticeKind.GRACE_STARTED, 2, 1, 1, FixedClock().now())
        self.due = [(USER, self.notice), (OTHER_USER, self.notice)]
        self.started = Event()
        self.release = Event()
        self.sent: list[tuple[UserId, PlanNotice]] = []
        self.threads: list[str] = []
        self.listings = 0
        self.runs = 0

    def begin(self, *, notices: dict[UserId, PlanNotice] | None = None) -> tuple[ScheduledRun, ...]:
        if notices is not None:
            notices.update(self.plan_notices_due())
        self.listings += 1
        return (ScheduledRun(ScheduledRule(USER, rule(), None), False),)

    def run(self, item: ScheduledRun) -> bool:
        self.runs += 1
        return True

    def checks_due(self) -> tuple[UserId, ...]:
        return ()

    def plan_notices_due(self) -> tuple[tuple[UserId, PlanNotice], ...]:
        due, self.due = self.due, []
        return tuple(due)

    def send_plan_notice(self, owner: UserId, notice: PlanNotice) -> None:
        from threading import current_thread

        self.threads.append(current_thread().name)
        self.sent.append((owner, notice))
        if len(self.sent) == 1:
            self.started.set()
            assert self.release.wait(5)


def _queued_notices(planned: PlanMailPass) -> tuple[PlanNoticeDelivery, ...]:
    return tuple(
        PlanNoticeDelivery(owner.value, partial(planned.send_plan_notice, owner, notice))
        for owner, notice in planned.plan_notices_due()
    )


async def _until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0)


def test_slow_plan_email_holds_up_no_rule() -> None:
    planned = PlanMailPass()
    scheduler = SyncScheduler(planned, concurrency=1)

    async def scenario() -> None:
        try:
            await asyncio.wait_for(scheduler.run_once(), 2)
            await _until(planned.started.is_set)
            assert planned.runs == 1
            assert scheduler.progress().last_completed_at is not None
        finally:
            planned.release.set()
            scheduler._mail.close()

    asyncio.run(scenario())
    assert all(name.startswith("plan-mail") for name in planned.threads)


def test_next_pass_lists_while_smtp_is_blocked() -> None:
    planned = PlanMailPass()
    scheduler = SyncScheduler(planned, concurrency=1)

    async def scenario() -> None:
        try:
            await scheduler.run_once()
            await _until(planned.started.is_set)
            await asyncio.wait_for(scheduler.run_once(), 2)
            assert planned.listings == 2
            assert planned.runs == 2
            assert len(planned.sent) == 1
        finally:
            planned.release.set()
            scheduler._mail.close()

    asyncio.run(scenario())


def test_plan_mail_replaces_latest_pending_and_never_drains_twice() -> None:
    planned = PlanMailPass()
    scheduler = SyncScheduler(planned)
    newer = replace(planned.notice, held=2)
    latest = replace(planned.notice, held=3)

    async def scenario() -> None:
        try:
            await scheduler.run_once()
            await _until(planned.started.is_set)
            planned.due = [(USER, newer)]
            await scheduler.run_once()
            planned.due = [(USER, latest)]
            await scheduler.run_once()
            await scheduler.run_once()
            planned.release.set()
            await _until(lambda: len(planned.sent) == 3)
            await _until(lambda: scheduler._mail._task is None)
            assert planned.sent == [
                (USER, planned.notice),
                (OTHER_USER, planned.notice),
                (USER, latest),
            ]
        finally:
            scheduler._mail.close()
            planned.release.set()

    asyncio.run(scenario())


def test_cancelling_scheduler_starts_no_subsequent_plan_send() -> None:
    planned = PlanMailPass()
    scheduler = SyncScheduler(planned)

    async def scenario() -> None:
        task = asyncio.create_task(scheduler.run_forever())
        try:
            await _until(planned.started.is_set)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            planned.release.set()
            await asyncio.sleep(0.02)
            assert planned.sent == [(USER, planned.notice)]
        finally:
            planned.release.set()
            task.cancel()

    asyncio.run(scenario())


def test_scheduler_restart_reopens_mail_after_cancellation() -> None:
    planned = PlanMailPass()
    scheduler = SyncScheduler(planned)

    async def scenario() -> None:
        first = asyncio.create_task(scheduler.run_forever())
        try:
            await _until(planned.started.is_set)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            planned.due = [(OTHER_USER, replace(planned.notice, held=3))]
            restarted = asyncio.create_task(scheduler.run_forever())
            try:
                await _until(lambda: planned.listings >= 2)
                assert len(planned.sent) == 1
                planned.release.set()
                await _until(lambda: len(planned.sent) == 2)
                assert len(set(planned.threads)) == 1
                assert planned.sent[1] == (OTHER_USER, replace(planned.notice, held=3))
            finally:
                restarted.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await restarted
        finally:
            planned.release.set()
            first.cancel()

    asyncio.run(scenario())


def test_cancel_before_mail_task_starts_can_restart() -> None:
    planned = PlanMailPass()
    planned.release.set()
    scheduler = SyncScheduler(planned)

    async def scenario() -> None:
        scheduler._mail.queue(_queued_notices(planned))
        await scheduler._mail.stop()
        assert planned.sent == []
        assert scheduler._mail._task is None
        planned.due = [(USER, planned.notice)]
        await scheduler.run_once()
        await _until(lambda: len(planned.sent) == 1)
        await scheduler._mail.stop()

    asyncio.run(scenario())


def test_plan_mail_has_only_one_sending_batch_of_at_most_one_hundred() -> None:
    planned = PlanMailPass()
    planned.due = [(UserId(f"user-{index:03}"), planned.notice) for index in range(205)]
    scheduler = SyncScheduler(planned)

    async def scenario() -> None:
        try:
            await scheduler.run_once()
            await _until(planned.started.is_set)
            # Only the first hundred left pending state; its one active send holds the batch.
            assert len(scheduler._mail._pending) == 105
            assert len(planned.sent) == 1
            await scheduler.run_once()
            assert len(scheduler._mail._pending) == 105
            await scheduler._mail.stop()
            planned.release.set()
            assert scheduler._mail._pending == {}
        finally:
            planned.release.set()
            await scheduler._mail.stop()

    asyncio.run(scenario())


def test_failed_plan_delivery_does_not_stop_next_notice_or_rules(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    planned = PlanMailPass()
    planned.release.set()

    def send(owner: UserId, notice: PlanNotice) -> None:
        planned.sent.append((owner, notice))
        if owner == USER:
            raise OSError("private credentials")

    monkeypatch.setattr(planned, "send_plan_notice", send)
    scheduler = SyncScheduler(planned)

    async def scenario() -> None:
        await scheduler.run_once()
        await _until(lambda: len(planned.sent) == 2)
        assert planned.runs == 1
        await scheduler._mail.stop()

    asyncio.run(scenario())
    assert "OSError" in caplog.text
    assert "private credentials" not in caplog.text


class _NoticeSettlement(ScheduledPlanHolds):
    def __init__(self, old: PlanNotice, blocked: bool) -> None:
        self.pending: tuple[tuple[UserId, PlanNotice], ...] = ((USER, old),)
        self.started, self.release = Event(), Event()
        self.blocked = blocked

    def settle(
        self, standings: Sequence[UserPlanStanding]
    ) -> tuple[tuple[UserId, PlanNotice], ...]:
        pending, self.pending = self.pending, ()
        if self.blocked and pending:
            self.started.set()
            assert self.release.wait(5)
        return pending


class _NoticeListing(InMemoryInstallationUnitOfWork):
    def __init__(self, database: MemoryDatabase, fail_listing: bool) -> None:
        super().__init__(database)
        self.count = 0
        self.fail_listing = fail_listing

    def scheduled_rules(self) -> tuple[ScheduledRule, ...]:
        self.count += 1
        if self.fail_listing and self.count == 1:
            raise RuntimeError("listing unavailable")
        return super().scheduled_rules()


def _notice_publication_world(
    *, fail_listing: bool = False, block_settlement: bool = False
) -> tuple[SyncScheduler, _NoticeSettlement, _NoticeListing, list[PlanNotice], PlanNotice]:
    units = memory_units()
    old = PlanNotice(PlanNoticeKind.GRACE_STARTED, 2, 1, 1, FixedClock().now())
    sent: list[PlanNotice] = []

    class Notices:
        def plan_changed(self, notice: PlanNotice) -> None:
            sent.append(notice)

    settlement = _NoticeSettlement(old, block_settlement)
    listing = _NoticeListing(units.database, fail_listing)
    services = ScheduledServices(
        cast(SyncRuns, RecordingExecuteRule([])),
        cast(RunHealth, RecordingHealth()),
        plan_notices=Notices(),
    )
    scheduled = ScheduledPass(
        lambda: listing, lambda owner: services, FixedClock(), plan_holds=settlement
    )
    scheduler = SyncScheduler(scheduled, concurrency=1)
    return scheduler, settlement, listing, sent, old


def test_cancelled_lifecycle_discards_notice_retained_after_listing_failure() -> None:
    scheduler, settlement, listing, sent, old = _notice_publication_world(fail_listing=True)
    new = replace(old, held=2)

    async def scenario() -> None:
        first = asyncio.create_task(scheduler.run_forever())
        await _until(lambda: listing.count == 1 and scheduler.progress().next_pass_at is not None)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        restarted = asyncio.create_task(scheduler.run_forever())
        try:
            await _until(lambda: listing.count == 2)
            await _until(lambda: scheduler.progress().last_completed_at is not None)
            await _until(lambda: scheduler._mail._task is None)
            assert sent == []
            settlement.pending = ((USER, new),)
            await scheduler.run_once()
            await _until(lambda: len(sent) == 1)
            assert sent == [new]
        finally:
            restarted.cancel()
            with pytest.raises(asyncio.CancelledError):
                await restarted

    asyncio.run(scenario())


def test_cancelled_lifecycle_discards_late_notice_from_blocked_begin() -> None:
    scheduler, settlement, listing, sent, old = _notice_publication_world(block_settlement=True)
    new = replace(old, held=2)

    async def scenario() -> None:
        first = asyncio.create_task(scheduler.run_forever())
        try:
            await _until(settlement.started.is_set)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(first, 2)
            assert not settlement.release.is_set()
            settlement.release.set()
            await _until(lambda: listing.count == 1)
            restarted = asyncio.create_task(scheduler.run_forever())
            try:
                await _until(lambda: listing.count == 2)
                await _until(lambda: scheduler.progress().last_completed_at is not None)
                await _until(lambda: scheduler._mail._task is None)
                assert sent == []
                settlement.pending = ((USER, new),)
                await scheduler.run_once()
                await _until(lambda: len(sent) == 1)
                assert sent == [new]
            finally:
                restarted.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await restarted
        finally:
            settlement.release.set()
            first.cancel()

    asyncio.run(scenario())
