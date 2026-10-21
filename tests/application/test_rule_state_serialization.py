"""Every read-modify-write of a rule waits for the shared per-rule write lock.

Without it, two lifecycle operations can both read the same rule and the last save silently
discards the other's change, for example restoring the previous policy as enabled.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, Lock, Thread

import pytest

from calendar_sync.application.sync.errors import ProviderFailure, RuleNotExecutable
from calendar_sync.application.sync.health import RuleHealth
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.ports import UnitOfWork, UnitOfWorkFactory
from calendar_sync.application.sync.preview import PreviewSyncRule
from calendar_sync.application.sync.provider_ports import CalendarProvider, ProviderChangeSet
from calendar_sync.application.sync.removal import RemoveSyncRule
from calendar_sync.application.sync.synchronization import ExecuteSyncRule, SyncRunResult
from calendar_sync.domain.model import (
    CalendarEndpoint,
    ProjectionContent,
    ProjectionHandling,
    SyncRuleId,
    SyncRuleState,
    TransformationPolicy,
)
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from calendar_sync.infrastructure.identifiers import UuidRunIdGenerator
from tests.adapters.test_plan_races import (
    NEXT_RULE,
    _holds,
    _Job,
    _lower,
    _member_with_rules,
    _previewed_rule,
    _save_grace,
    _stored_rule,
)
from tests.adapters.test_plan_races import _join_plan_workers as _join_plan_workers
from tests.application.test_execute_sync_rule import FakeCalendarProvider, FixedClock
from tests.application.test_health import Incidents, Records
from tests.application.test_plan_holds import engine, expired
from tests.application.test_plan_limits import _units
from tests.fake_calendar import FakeCalendars, enabled_rule_factory
from tests.helpers import NOW, event, occurrence, rule, series, week_start
from tests.users import memory_units

pytestmark = pytest.mark.usefixtures("_join_plan_workers")


def _blocks_until_released(locks: RuleLocks, operation: Callable[[], object]) -> bool:
    held = locks.for_writes(rule().id)
    held.acquire()
    worker = Thread(target=operation)
    worker.start()
    worker.join(0.1)
    blocked = worker.is_alive()
    held.release()
    worker.join(2)
    assert not worker.is_alive()
    return blocked


def test_preview_validation_waits_for_the_rule_write_lock() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.DRAFT)
    locks = RuleLocks()
    preview = PreviewSyncRule(
        unit_of_work,
        FakeCalendarProvider(event()),
        EventProjector(),
        FixedClock(),
        SyncDecisionService(EventProjector(), ProjectionFingerprinter()),
        locks,
    )

    assert _blocks_until_released(locks, lambda: preview.execute(rule().id))
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.PREVIEWED


def test_removal_start_waits_for_the_rule_write_lock() -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.PAUSED)
    locks = RuleLocks()
    removal = RemoveSyncRule(unit_of_work, None, None, FixedClock(), locks)

    assert _blocks_until_released(
        locks, lambda: removal.execute(rule().id, ProjectionHandling.DETACH)
    )
    assert unit_of_work.state.rules == {}


def test_clearing_reprojection_waits_for_the_rule_write_lock() -> None:
    unit_of_work = memory_units()
    changed = rule().change_policy(TransformationPolicy(content=ProjectionContent.DETAILS))
    unit_of_work.state.rules[rule().id] = replace(changed, state=SyncRuleState.ENABLED)
    provider = FakeCalendarProvider(event())
    provider.source_changes = ()
    locks = RuleLocks()
    fingerprinter = ProjectionFingerprinter()
    run = ExecuteSyncRule(
        unit_of_work,
        provider,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
        UuidRunIdGenerator(),
        locks,
    )

    assert _blocks_until_released(locks, lambda: run.execute(rule().id))
    assert unit_of_work.state.rules[rule().id].reprojection_required is False


def test_occurrence_writes_wait_for_the_rule_write_lock() -> None:
    calendars = FakeCalendars()
    calendars.put(series(), starts=(week_start(0), week_start(1)))
    factory = enabled_rule_factory()
    fingerprinter = ProjectionFingerprinter()
    locks = RuleLocks()
    sync = ExecuteSyncRule(
        factory,
        calendars,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
        UuidRunIdGenerator(),
        locks,
    )
    sync.execute(rule().id)
    calendars.report(calendars.put(occurrence(series(), 1, moved_by=timedelta(hours=1))))

    before = len(calendars.writes)
    held = locks.for_writes(rule().id)
    held.acquire()
    worker = Thread(target=sync.execute, args=(rule().id,))
    worker.start()
    worker.join(0.1)
    written_while_held = calendars.writes[before:]
    held.release()
    worker.join(2)

    assert written_while_held == []
    assert not worker.is_alive()
    assert calendars.writes[-1][0] == "write_occurrence"


class _WriterGate:
    """Open settlement's writer unit only after a run reaches its cursor lock."""

    def __init__(self, units: UnitOfWorkFactory) -> None:
        self.units = units
        self.calls = 0
        self.locked = Event()
        self.proceed = Event()

    def __call__(self) -> UnitOfWork:
        self.calls += 1
        if self.calls == 2:
            self.locked.set()
            assert self.proceed.wait(5)
        return self.units()


class _CursorLocks(RuleLocks):
    def __init__(self) -> None:
        super().__init__()
        self.armed = Event()
        self.attempted = Event()

    def for_writes(self, rule_id: SyncRuleId) -> Lock:
        lock = super().for_writes(rule_id)
        if self.armed.is_set():
            self.attempted.set()
        return lock


def _run(units: UnitOfWorkFactory, provider: CalendarProvider, locks: RuleLocks) -> ExecuteSyncRule:
    fingerprinter = ProjectionFingerprinter()
    return ExecuteSyncRule(
        units,
        provider,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
        UuidRunIdGenerator(),
        locks,
    )


def test_cursor_advance_and_settle_finish_without_busy_timeout(tmp_path: Path) -> None:
    plans, units = _member_with_rules(tmp_path / "test.db", rule())
    gate = _WriterGate(units)
    locks = _CursorLocks()
    provider = FakeCalendarProvider(event())
    provider.source_changes = ()
    holding = _Job(_holds(gate, plans, locks).settle)
    try:
        assert gate.locked.wait(2)
        locks.armed.set()
        running = _Job(lambda: _run(units, provider, locks).execute(rule().id))
        assert locks.attempted.wait(2)
    finally:
        gate.proceed.set()
    assert holding.finish() is None
    assert isinstance(running.finish(), SyncRunResult)
    with units() as uow:
        assert uow.cursors.get(rule().id) == "source-cursor-1"
        assert uow.destination_cursors.get(rule().id) == "destination-cursor-1"


def test_in_flight_run_stops_before_its_next_write_after_hold(tmp_path: Path) -> None:
    plans, units = _member_with_rules(
        tmp_path / "test.db", _previewed_rule(NEXT_RULE).enable(), rule()
    )
    _lower(plans)
    _save_grace(units)
    locks = RuleLocks()
    reading, proceed = Event(), Event()

    class HeldReadProvider(FakeCalendarProvider):
        def changes(
            self, source: CalendarEndpoint, cursor: str | None, not_ended_before: datetime
        ) -> ProviderChangeSet:
            if source == rule().source:
                reading.set()
                assert proceed.wait(5)
            return super().changes(source, cursor, not_ended_before)

    provider = HeldReadProvider(event())
    running = _Job(lambda: _run(units, provider, locks).execute(rule().id))
    try:
        assert reading.wait(2)
        # A live run owns its run lock, but settlement can take its idle write lock.
        notice = _holds(units, plans, locks).settle()
        assert notice is not None
        assert notice.held == 1
        assert _stored_rule(units, rule().id).held_by_plan
    finally:
        proceed.set()
    assert isinstance(running.finish(), RuleNotExecutable)
    assert provider.destination is None
    assert provider.operation_keys == []
    assert provider.updated == provider.deleted == 0
    with units() as uow:
        assert uow.cursors.get(rule().id) is None


def test_hold_release_as_lapse_then_intervention_prevents_authorized_restoration() -> None:
    units = _units(_previewed_rule(NEXT_RULE).enable(), rule())
    locks = RuleLocks()
    expired(units)
    holds = engine(units, locks=locks)
    notice = holds.settle()
    assert notice is not None
    assert notice.held == 1
    account = rule().source.connected_account_id
    units.state.lapsed[account] = NOW
    units.state.rules[NEXT_RULE] = units.state.rules[NEXT_RULE].pause()
    holds.settle()
    assert units.state.rules[rule().id].awaiting_reauthorization
    health = RuleHealth(units, Records(), Incidents(), FixedClock(), locks)
    health.record_failure(rule(), ProviderFailure(ProviderFailureKind.PERMANENT, "synthetic"))
    assert health.lapses.restored(account, accepted_at=NOW) == 0
    assert units.state.rules[rule().id].state is SyncRuleState.DEGRADED
    assert units.state.rules[rule().id].stop_cause is None
    provider = FakeCalendarProvider(event())
    with pytest.raises(RuleNotExecutable):
        _run(units, provider, locks).execute(rule().id)
    assert provider.operation_keys == []
    assert provider.destination is None
