from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

import pytest

from calendar_sync.application.errors import RuleNotExecutable
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import AuditAction, AuditOutcome, RunKind
from calendar_sync.application.reconciliation import ReconcileNow, ReconcileSyncRule
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.domain.model import (
    EventId,
    EventRef,
    ManagedOrigin,
    SyncReason,
    SyncRuleId,
    SyncRuleState,
    TimedInterval,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    ReconciliationService,
    SyncDecisionService,
)
from calendar_sync.infrastructure.identifiers import UuidRunIdGenerator
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.application.test_run_logging import SteppedClock
from tests.fake_calendar import FakeCalendars, FixedClock, enabled_rule_factory, sync_use_case
from tests.helpers import NOW, event, rule


class RecordingFullPasses:
    def __init__(self, *, fail_floor: bool = False, fail_record: bool = False) -> None:
        self.fail_floor = fail_floor
        self.fail_record = fail_record
        self.recorded: list[tuple[SyncRuleId, int, str | None]] = []

    def audit_floor(self) -> int:
        if self.fail_floor:
            raise RuntimeError("database is locked")
        return 7

    def record_full_pass(self, rule_id: SyncRuleId, floor: int, run_id: str | None = None) -> None:
        if self.fail_record:
            raise RuntimeError("database is locked")
        self.recorded.append((rule_id, floor, run_id))


def _reconcile_now(
    unit_of_work: InMemoryUnitOfWorkFactory, full_passes: RecordingFullPasses
) -> tuple[ReconcileNow, FakeCalendars]:
    calendars = FakeCalendars()
    calendars.put(event())
    reconcile = ReconcileSyncRule(
        unit_of_work,
        calendars,
        EventProjector(),
        ReconciliationService(ProjectionFingerprinter()),
        FixedClock(),
        UuidRunIdGenerator(),
    )
    return ReconcileNow(sync_use_case(unit_of_work, calendars), reconcile, full_passes), calendars


def test_reconcile_now_runs_a_full_pass_that_counts_as_the_daily_one() -> None:
    full_passes = RecordingFullPasses()
    reconcile_now, _ = _reconcile_now(enabled_rule_factory(), full_passes)

    result = reconcile_now.execute(rule().id)

    assert result.sync.created == 1
    assert result.report.checked_mappings == 1
    assert result.report.is_consistent
    assert full_passes.recorded == [(rule().id, 7, result.sync.run_id)]


@pytest.mark.parametrize("failing", ["floor", "record"])
def test_failed_bookkeeping_never_aborts_reconcile_now(failing: str) -> None:
    full_passes = RecordingFullPasses(
        fail_floor=failing == "floor", fail_record=failing == "record"
    )
    reconcile_now, _ = _reconcile_now(enabled_rule_factory(), full_passes)

    result = reconcile_now.execute(rule().id)

    assert result.report.checked_mappings == 1
    assert full_passes.recorded == []


def test_reconcile_now_is_refused_for_a_rule_that_cannot_run() -> None:
    full_passes = RecordingFullPasses()
    reconcile_now, calendars = _reconcile_now(
        enabled_rule_factory(rule(state=SyncRuleState.PAUSED)), full_passes
    )

    with pytest.raises(RuleNotExecutable):
        reconcile_now.execute(rule().id)

    assert calendars.writes == []
    assert full_passes.recorded == []


class _EarlierClock:
    def now(self) -> datetime:
        return NOW - timedelta(days=60)


def test_reconcile_now_leaves_events_that_ended_before_the_sync_window_unread() -> None:
    factory = enabled_rule_factory()
    reconcile_now, calendars = _reconcile_now(factory, RecordingFullPasses())
    del calendars.events[event().reference]
    # Synchronized two months ago, so the event ended before today's sync window.
    old = calendars.put(
        replace(event(), time=TimedInterval(NOW - timedelta(days=60), NOW - timedelta(days=59)))
    )
    fingerprinter = ProjectionFingerprinter()
    ExecuteSyncRule(
        factory,
        calendars,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        _EarlierClock(),
        UuidRunIdGenerator(),
    ).execute(rule().id)
    destination = factory.state.mappings[(rule().id, old.reference)].destination
    calendars.put(replace(calendars.events[destination], title="Edited"))
    calendars.reads.clear()

    result = reconcile_now.execute(rule().id)

    # The event is past: neither the full pass nor the check reads, repairs, or reports it.
    assert (result.sync.created, result.sync.updated) == (0, 0)
    assert result.report.is_consistent
    assert result.report.checked_mappings == 0
    assert old.reference not in calendars.reads
    assert calendars.events[destination].title == "Edited"
    outcome = factory.state.outcomes[(rule().id, RunKind.RECONCILIATION)]
    assert (outcome.checked_mappings, outcome.drift, outcome.conflicts) == (0, 0, 0)


def test_reconcile_now_blocks_an_unmapped_projection_as_a_conflict_not_drift() -> None:
    factory = enabled_rule_factory()
    reconcile_now, calendars = _reconcile_now(factory, RecordingFullPasses())
    orphan = calendars.put(
        replace(
            event("orphan", calendar=rule().destination),
            title="Busy",
            managed_origin=ManagedOrigin(rule().id, EventRef(rule().source, EventId("gone"))),
        )
    )

    result = reconcile_now.execute(rule().id)

    assert result.report.drift == ()
    assert not result.report.is_consistent
    assert [(item.reason, item.source, item.destination) for item in result.report.conflicts] == [
        (SyncReason.PROJECTION_UNMAPPED, EventRef(rule().source, EventId("gone")), orphan.reference)
    ]
    assert orphan.reference in calendars.events
    blocked = [entry for entry in factory.state.audit if entry.outcome is AuditOutcome.BLOCKED]
    assert [
        (entry.action, entry.reason, entry.source_event_id, entry.destination_event_id)
        for entry in blocked
    ] == [(AuditAction.CONFLICT, SyncReason.PROJECTION_UNMAPPED, "gone", "orphan")]
    # Filed under the full pass's run, so Activity shows one heading for Reconcile Now.
    assert blocked[0].run_id == result.sync.run_id
    outcome = factory.state.outcomes[(rule().id, RunKind.RECONCILIATION)]
    assert (outcome.drift, outcome.conflicts) == (0, 1)


def test_reconcile_now_does_not_report_again_an_event_its_full_pass_blocked() -> None:
    factory = enabled_rule_factory()
    reconcile_now, calendars = _reconcile_now(factory, RecordingFullPasses())
    sync_use_case(factory, calendars).execute(rule().id)
    # The source is gone for good; its projection is still listed in the destination.
    del calendars.events[event().reference]

    result = reconcile_now.execute(rule().id)

    assert result.sync.conflicts == 1
    assert result.sync.blocked == frozenset({event().reference})
    assert result.report.conflicts == ()
    assert result.report.drift == ()
    blocked = [entry for entry in factory.state.audit if entry.outcome is AuditOutcome.BLOCKED]
    assert [entry.reason for entry in blocked] == [SyncReason.SOURCE_UNVERIFIABLE]


@dataclass
class _WatchedCalendars(FakeCalendars):
    """Records the rule's reported work at every read, moving the clock on each time."""

    locks: RuleLocks = field(default_factory=RuleLocks)
    clock: SteppedClock = field(default_factory=SteppedClock)
    seen: list[tuple[str, str | None, datetime, int | None]] = field(default_factory=list)

    def _watch(self) -> None:
        work = self.locks.current_work(rule().id)
        if work is not None:
            stage = work.stage.value if work.stage else None
            self.seen.append((work.kind.value, stage, work.started_at, work.total))
        self.clock.advance(20)

    def changes(self, *args: Any, **kwargs: Any) -> Any:
        self._watch()
        return super().changes(*args, **kwargs)

    def list_events(self, *args: Any, **kwargs: Any) -> Any:
        self._watch()
        return super().list_events(*args, **kwargs)

    def managed_events(self, *args: Any, **kwargs: Any) -> Any:
        self._watch()
        return super().managed_events(*args, **kwargs)


def test_reconcile_now_reports_one_reconciliation_from_its_start_naming_each_stage() -> None:
    calendars = _WatchedCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    fingerprinter = ProjectionFingerprinter()
    synchronize = ExecuteSyncRule(
        factory,
        calendars,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        calendars.clock,
        UuidRunIdGenerator(),
        calendars.locks,
    )
    reconcile = ReconcileSyncRule(
        factory,
        calendars,
        EventProjector(),
        ReconciliationService(fingerprinter),
        calendars.clock,
        UuidRunIdGenerator(),
        calendars.locks,
    )

    ReconcileNow(synchronize, reconcile).execute(rule().id)

    kinds = {kind for kind, _, _, _ in calendars.seen}
    starts = {started for _, _, started, _ in calendars.seen}
    stages = [stage for _, stage, _, _ in calendars.seen]
    assert kinds == {"reconciliation"}
    assert starts == {NOW}
    # The full pass, then the check, each read at least once.
    assert [
        stage for index, stage in enumerate(stages) if stages[index - 1 : index] != [stage]
    ] == [
        "sync",
        "reconciliation",
    ]
    # The check counts nothing, so it never shows the full pass's count.
    assert all(total is None for _, stage, _, total in calendars.seen if stage == "reconciliation")
    assert calendars.locks.current_work(rule().id) is None
