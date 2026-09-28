import sqlite3
from pathlib import Path
from threading import Thread
from typing import cast

import pytest

from calendar_sync.application.errors import (
    ProviderFailure,
    ProviderFailureKind,
    RuleNotExecutable,
)
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import UnitOfWorkFactory
from calendar_sync.application.synchronization import ExecuteSyncRule, SyncRunResult
from calendar_sync.domain.model import SyncRuleId, SyncRuleState
from calendar_sync.infrastructure.notifications import (
    IncidentNotification,
    IncidentNotifier,
    NotificationChannel,
)
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from calendar_sync.infrastructure.scheduling import SqliteRuleHealth, SyncScheduler
from tests.helpers import rule


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
        self.failures: list[ProviderFailure] = []

    def record_success(self, _rule: object) -> None:
        self.successes += 1

    def record_failure(self, _rule: object, failure: ProviderFailure) -> None:
        self.failures.append(failure)


def test_three_temporary_failures_open_one_incident(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    unit_of_work = SqliteUnitOfWorkFactory(database)
    with unit_of_work() as uow:
        uow.rules.add(rule())
        uow.commit()
    health = SqliteRuleHealth(database, unit_of_work)
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
    health = SqliteRuleHealth(database, unit_of_work)

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
    health = SqliteRuleHealth(database, unit_of_work, IncidentNotifier([channel]))
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
    health = SqliteRuleHealth(database, unit_of_work)
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
        cast(SqliteRuleHealth, health),
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
        cast(SqliteRuleHealth, health),
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
        cast(SqliteRuleHealth, health),
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
        cast(SqliteRuleHealth, health),
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
    health = SqliteRuleHealth(database, unit_of_work, locks=locks)
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
    assert degraded is not None and degraded.state is SyncRuleState.DEGRADED
