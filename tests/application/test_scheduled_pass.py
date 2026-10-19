"""What a scheduled pass does with each rule: retries, failures, and recorded outcomes."""

from __future__ import annotations

import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
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
from calendar_sync.application.sync.watch_ports import SyncCadencePolicy
from calendar_sync.domain.access import UserId
from calendar_sync.domain.cadence import DEFAULT_CADENCE, SCHEDULED_EVERY, SyncCadence
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
    """Every User's records as a pass reads them: the failures they are stopped by, and their
    enabled rules."""

    def __init__(
        self, sightings: Sequence[CauseSighting] = (), rules: Sequence[ScheduledRule] = ()
    ) -> None:
        self.sightings = list(sightings)
        self.rules = list(rules)

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
        return tuple(self.rules)


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


HOUR = timedelta(hours=1)
HOURLY = SyncCadence(instant=False, poll_every=HOUR)
MIDNIGHT = datetime(2026, 8, 31, tzinfo=UTC)


class Plans:
    """Each User's Sync Cadence as their Plan gives it: USER's polls every hour, and any other
    User keeps the default cadence until told otherwise. An unreadable policy fails every read,
    as a locked database would."""

    def __init__(self, *, unreadable: bool = False) -> None:
        self.by_user: dict[UserId, SyncCadence] = {USER: HOURLY}
        self.unreadable = unreadable

    def cadence(self, user: UserId) -> SyncCadence:
        if self.unreadable:
            raise sqlite3.OperationalError("database is locked")
        return self.by_user.get(user, DEFAULT_CADENCE)

    def cadences(self, users: Collection[UserId]) -> Mapping[UserId, SyncCadence]:
        return {user: self.cadence(user) for user in users}


def _enabled(
    owner: UserId,
    rule_id: str,
    *,
    ran: datetime = NOW - timedelta(days=1),
    failing: bool = False,
    full: datetime = NOW - HOUR,
) -> ScheduledRule:
    """An enabled rule that last ran at `ran` and completed its last full pass at `full`, today
    unless told otherwise, so nothing but its interval makes it due."""
    return ScheduledRule(
        owner, replace(rule(), id=SyncRuleId(rule_id)), full, last_run_at=ran, failing=failing
    )


def _scheduling(
    installation: Installation, clock: SteppingClock, cadence: SyncCadencePolicy | None = None
) -> ScheduledPass:
    services = ScheduledServices(
        cast(SyncRuns, RecordingExecuteRule([])), cast(RunHealth, RecordingHealth())
    )
    units = cast(InstallationUnitOfWorkFactory, lambda: installation)
    if cadence is None:
        return ScheduledPass(units, lambda _owner: services, clock)
    return ScheduledPass(units, lambda _owner: services, clock, cadence=cadence)


def _begin(scheduled: ScheduledPass, clock: SteppingClock, begins: datetime) -> list[str]:
    """The rules the pass that begins at `begins` lists, in order."""
    clock.current = begins
    return [run.scheduled.rule.id.value for run in scheduled.begin()]


def _every_five_minutes(hours: int, start: datetime = NOW) -> list[datetime]:
    """When passes begin over `hours` from `start`, both ends included."""
    return [start + SCHEDULED_EVERY * step for step in range(hours * 12 + 1)]


def test_plans_off_lists_every_rule_at_every_pass() -> None:
    ran = NOW - timedelta(minutes=1)
    installation = Installation(
        rules=[_enabled(USER, "mine", ran=ran), _enabled(OTHER_USER, "theirs", ran=ran)]
    )
    clock = SteppingClock()
    scheduled = _scheduling(installation, clock)

    listed = [_begin(scheduled, clock, begins) for begins in _every_five_minutes(hours=2)]

    assert listed == [["mine", "theirs"]] * 25


def test_an_hourly_rule_is_listed_once_per_window_and_an_instant_one_at_every_pass() -> None:
    installation = Installation(rules=[_enabled(USER, "hourly"), _enabled(OTHER_USER, "instant")])
    clock = SteppingClock()
    scheduled = _scheduling(installation, clock, Plans())
    passes = _every_five_minutes(hours=3)

    listed = {begins: _begin(scheduled, clock, begins) for begins in passes}

    hourly = [begins for begins in passes if "hourly" in listed[begins]]
    # It last ran a day ago, so the first pass lists it; then the first pass of each new window.
    assert hourly[0] == NOW
    assert len(hourly) == 4
    assert all(later - earlier == HOUR for earlier, later in pairwise(hourly[1:]))
    assert all("instant" in listed[begins] for begins in passes)


def test_sync_now_every_minute_never_keeps_a_rule_from_being_listed() -> None:
    hourly = _enabled(USER, "hourly", ran=NOW)
    installation = Installation(rules=[hourly])
    clock = SteppingClock()
    scheduled = _scheduling(installation, clock, Plans())
    listings: list[datetime] = []

    for minute in range(3 * 60 + 1):
        at = NOW + timedelta(minutes=minute)
        # A Sync Now completes every minute, as a pass begins: it moves the rule's last run, and
        # never when the scheduler listed it.
        installation.rules = [replace(hourly, last_run_at=at)]
        if minute % 5 == 0 and _begin(scheduled, clock, at):
            listings.append(at)

    assert len(listings) == 3
    assert all(later - earlier == HOUR for earlier, later in pairwise(listings))


def test_a_restart_lists_a_rule_from_its_last_run_once() -> None:
    # One rule's last run completed as the restarted service's first pass begins, the other's
    # more than an hour before it.
    just_ran = _enabled(USER, "just-ran", ran=NOW)
    ran_before = _enabled(USER, "ran-before", ran=NOW - HOUR - timedelta(seconds=1))
    installation = Installation(rules=[just_ran, ran_before])
    clock = SteppingClock()
    restarted = _scheduling(installation, clock, Plans())
    passes = _every_five_minutes(hours=2)

    listed = {begins: _begin(restarted, clock, begins) for begins in passes}

    def listings(rule_id: str) -> list[datetime]:
        return [begins for begins in passes if rule_id in listed[begins]]

    # Due in its next window, not at once; then once per window.
    assert NOW not in listings("just-ran")
    assert len(listings("just-ran")) == 2
    assert listings("just-ran")[1] - listings("just-ran")[0] == HOUR
    # Its last run was in an earlier window, so the first pass lists it.
    assert listings("ran-before")[0] == NOW
    assert len(listings("ran-before")) == 3


def test_a_restart_never_starves_the_daily_full_pass() -> None:
    passes = _every_five_minutes(hours=2, start=MIDNIGHT)
    listed: list[tuple[datetime, bool]] = []

    for begins in passes:
        # The service restarts before every pass, and a Sync Now completed a minute before it.
        hourly = _enabled(USER, "hourly", ran=begins - timedelta(minutes=1), full=MIDNIGHT - HOUR)
        clock = SteppingClock()
        clock.current = begins
        runs = _scheduling(Installation(rules=[hourly]), clock, Plans()).begin()
        listed.extend((begins, run.full) for run in runs)

    # Its phase falls in the first hour after midnight, so from then on every pass lists its
    # full pass, until one succeeds.
    assert all(full for _, full in listed)
    assert all((begins, True) in listed for begins in passes if begins >= MIDNIGHT + HOUR)


def test_a_plan_change_mid_window_takes_effect_at_the_next_due_pass() -> None:
    plans = Plans()
    installation = Installation(
        rules=[_enabled(USER, "upgraded"), _enabled(OTHER_USER, "downgraded")]
    )
    clock = SteppingClock()
    scheduled = _scheduling(installation, clock, plans)
    first_hour = _every_five_minutes(hours=1)
    second_hour = [begins + HOUR for begins in first_hour[1:]]

    before = [_begin(scheduled, clock, begins) for begins in first_hour]
    plans.by_user = {OTHER_USER: HOURLY}
    after = [_begin(scheduled, clock, begins) for begins in second_hour]

    # Hourly, then Instant: listed at the first pass after the change, and at every pass on.
    assert sum("upgraded" in listed for listed in before) == 2
    assert all("upgraded" in listed for listed in after)
    # Instant, then hourly: listed again only in its next window.
    assert all("downgraded" in listed for listed in before)
    assert sum("downgraded" in listed for listed in after) == 1


def test_a_failing_hourly_rule_is_listed_at_every_pass() -> None:
    installation = Installation(rules=[_enabled(USER, "hourly", ran=NOW, failing=True)])
    clock = SteppingClock()
    scheduled = _scheduling(installation, clock, Plans())

    listed = [_begin(scheduled, clock, begins) for begins in _every_five_minutes(hours=1)]

    assert listed == [["hourly"]] * 13


def test_a_failed_cadence_read_lists_every_rule(caplog: pytest.LogCaptureFixture) -> None:
    installation = Installation(
        rules=[_enabled(USER, "mine", ran=NOW), _enabled(OTHER_USER, "theirs", ran=NOW)]
    )
    clock = SteppingClock()
    scheduled = _scheduling(installation, clock, Plans(unreadable=True))

    listed = [_begin(scheduled, clock, begins) for begins in _every_five_minutes(hours=1)]

    assert listed == [["mine", "theirs"]] * 13
    assert "they count as instant" in caplog.text


def test_marks_forget_rules_that_are_no_longer_enabled() -> None:
    kept, paused = _enabled(USER, "kept"), _enabled(USER, "paused")
    installation = Installation(rules=[kept, paused])
    clock = SteppingClock()
    scheduled = _scheduling(installation, clock, Plans())
    _begin(scheduled, clock, NOW)

    installation.rules = [kept]
    _begin(scheduled, clock, NOW + SCHEDULED_EVERY)

    assert set(scheduled._listed) == {kept.rule.id}
