"""What a scheduled pass does with each rule: retries, failures, and recorded outcomes."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from typing import cast

import pytest

from calendar_sync.application.operations.ports import CauseSighting, InstallationUnitOfWorkFactory
from calendar_sync.application.operations.scheduled_pass import (
    RECHECK_INTERVAL,
    ScheduledPass,
    ScheduledRun,
    ScheduledServices,
    SyncRuns,
    fairly_ordered,
)
from calendar_sync.application.sync.errors import ProviderFailure, RuleNotExecutable
from calendar_sync.application.sync.health import RunHealth
from calendar_sync.application.sync.ports import ScheduledRule
from calendar_sync.application.sync.synchronization import SyncRunResult
from calendar_sync.domain.access import UserId
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.model import SyncRuleId
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.domain.runs import RuleRunOutcome, RunKind
from calendar_sync.infrastructure.persistence.memory_installation import (
    InMemoryInstallationUnitOfWorkFactory,
)
from tests.fake_calendar import FixedClock
from tests.helpers import NOW, endpoint, rule
from tests.scheduled_fakes import RecordingExecuteRule, RecordingHealth
from tests.users import OTHER_USER, USER, memory_units, rule_accounts


def _pass(execute: object, health: object) -> ScheduledPass:
    services = ScheduledServices(cast(SyncRuns, execute), cast(RunHealth, health))
    # These runs are given to the pass directly, so it never lists rules.
    return ScheduledPass(
        cast(InstallationUnitOfWorkFactory, None), lambda _owner: services, FixedClock()
    )


def _run(*, full: bool = False) -> ScheduledRun:
    return ScheduledRun(ScheduledRule(USER, rule(), None), full)


def test_a_temporary_failure_is_retried_and_then_recorded_as_a_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = ProviderFailure(ProviderFailureKind.TEMPORARY, "outage")
    execute = RecordingExecuteRule([temporary, None])
    health = RecordingHealth()
    monkeypatch.setattr(
        "calendar_sync.application.operations.scheduled_pass.time.sleep", lambda _delay: None
    )

    successful = _pass(execute, health).run(_run())

    assert successful is True
    assert execute.calls == 2
    assert health.successes == 1
    assert health.failures == []


def test_a_permanent_failure_is_not_retried() -> None:
    permanent = ProviderFailure(ProviderFailureKind.PERMANENT, "rejected")
    execute = RecordingExecuteRule([permanent])
    health = RecordingHealth()

    successful = _pass(execute, health).run(_run())

    assert successful is False
    assert execute.calls == 1
    assert health.failures == [permanent]


def test_an_unexpected_failure_is_recorded_as_an_infrastructure_failure() -> None:
    execute = RecordingExecuteRule([ValueError("corrupt local state")])
    health = RecordingHealth()

    successful = _pass(execute, health).run(_run())

    assert successful is False
    assert execute.calls == 1
    assert len(health.failures) == 1
    assert health.failures[0].kind is ProviderFailureKind.INFRASTRUCTURE


def test_a_rule_removed_or_edited_during_a_pass_is_skipped_without_an_incident() -> None:
    execute = RecordingExecuteRule([RuleNotExecutable("sync rule rule-1 does not exist")])
    health = RecordingHealth()

    successful = _pass(execute, health).run(_run())

    assert successful is True
    assert execute.calls == 1
    assert health.failures == []
    assert health.successes == 0


def test_a_run_that_listed_everything_checks_blocks_as_the_daily_pass() -> None:
    class ListingEverything:
        """A reprojection or a rejected cursor lists both calendars in full."""

        def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
            return SyncRunResult(rule_id, run_id="forced", listed_in_full=True)

    health = RecordingHealth()

    assert _pass(ListingEverything(), health).run(_run(full=False)) is True
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

    assert _pass(RecordingExecuteRule([None]), health).run(_run(full=True)) is True
    assert health.failures == []


def test_a_pass_lists_a_full_run_only_for_rules_whose_daily_pass_is_due() -> None:
    clock = FixedClock()
    second = replace(rule(), id=SyncRuleId("rule-2"), source=endpoint("other", "calendar"))
    units = memory_units(accounts=rule_accounts(rule(), second))
    with units() as uow:
        uow.rules.add(rule())
        uow.rules.add(second)
        completed = clock.now() - timedelta(hours=1)
        uow.run_outcomes.record(
            RuleRunOutcome(rule().id, RunKind.SYNC, completed, True, full_run=True)
        )
        uow.commit()
    services = ScheduledServices(
        cast(SyncRuns, RecordingExecuteRule([])), cast(RunHealth, RecordingHealth())
    )
    installation = InMemoryInstallationUnitOfWorkFactory(units.database)

    runs = ScheduledPass(installation, lambda _owner: services, clock).begin()

    # rule-1 completed today's full pass; rule-2 never did, so only it lists everything.
    assert [(run.scheduled.rule.id.value, run.full) for run in runs] == [
        ("rule-1", False),
        ("rule-2", True),
    ]


def test_rules_take_turns_between_users() -> None:
    def owned(owner: UserId, rule_id: str) -> ScheduledRule:
        return ScheduledRule(owner, replace(rule(), id=SyncRuleId(rule_id)), None)

    many = [owned(USER, f"mine-{number}") for number in range(3)]
    few = [owned(OTHER_USER, "theirs")]

    ordered = fairly_ordered([*many, *few])

    assert [item.rule.id.value for item in ordered] == ["mine-0", "theirs", "mine-1", "mine-2"]


class Installation:
    """Every User's records as a pass reads them, with the failures they are stopped by."""

    def __init__(self, sightings: list[CauseSighting]) -> None:
        self.sightings = sightings

    def __enter__(self) -> Installation:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def commit(self) -> None:
        return None

    def forget_change_values(self, before: datetime) -> None:
        return None

    def forget_provider_calls(self, before: object) -> None:
        return None

    def users_with_unfinished_lapses(self) -> tuple[UserId, ...]:
        return ()

    def failure_causes(self, since: datetime) -> list[CauseSighting]:
        return self.sightings

    def scheduled_rules(self) -> tuple[ScheduledRule, ...]:
        return ()


class SteppingClock:
    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current


class Fixes:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    def execute(self) -> int:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return 1


def _checking(
    sightings: list[CauseSighting], fixes: dict[UserId, Fixes], clock: SteppingClock
) -> ScheduledPass:
    installation = Installation(sightings)

    def services_for(owner: UserId) -> ScheduledServices:
        return ScheduledServices(
            cast(SyncRuns, RecordingExecuteRule([])),
            cast(RunHealth, RecordingHealth()),
            fixes.get(owner),
        )

    return ScheduledPass(
        cast(InstallationUnitOfWorkFactory, lambda: installation), services_for, clock
    )


def _pass_with_checks(scheduled: ScheduledPass) -> tuple[ScheduledRun, ...]:
    """A pass as the scheduler runs it: its rules, and beside them the checks it chose."""
    runs = scheduled.begin()
    for owner in scheduled.checks_due():
        scheduled.check_administrator_fixes(owner)
    return runs


def test_a_user_an_administrators_cause_stopped_is_checked_again_at_most_once_an_hour() -> None:
    third = UserId("third-user")
    sightings = [
        CauseSighting(USER, Cause.OAUTH_CLIENT_INVALID, NOW, True),
        # The owner fixes this one, and this administrator's one is no longer open.
        CauseSighting(OTHER_USER, Cause.ACCESS_REVOKED, NOW, True),
        CauseSighting(third, Cause.API_DISABLED, NOW, False),
    ]
    fixes = {USER: Fixes(), OTHER_USER: Fixes(), third: Fixes()}
    clock = SteppingClock()
    scheduled = _checking(sightings, fixes, clock)

    _pass_with_checks(scheduled)
    clock.current = NOW + timedelta(minutes=59)
    _pass_with_checks(scheduled)
    clock.current = NOW + RECHECK_INTERVAL
    _pass_with_checks(scheduled)

    assert [fixes[user].calls for user in (USER, OTHER_USER, third)] == [2, 0, 0]


def test_a_check_that_fails_never_stops_the_pass(caplog: pytest.LogCaptureFixture) -> None:
    sightings = [CauseSighting(USER, Cause.OAUTH_CLIENT_INVALID, NOW, True)]
    fixes = {USER: Fixes(sqlite3.OperationalError("database is locked"))}

    scheduled = _checking(sightings, fixes, SteppingClock())

    runs = _pass_with_checks(scheduled)

    assert runs == ()
    assert fixes[USER].calls == 1
    # Each check is handed out once, so a pass never runs it twice.
    assert scheduled.checks_due() == ()
    assert "Checking accounts an administrator's cause stopped failed" in caplog.text
