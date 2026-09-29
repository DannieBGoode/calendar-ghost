from __future__ import annotations

import pytest

from calendar_sync.application.errors import RuleNotExecutable
from calendar_sync.application.reconciliation import ReconcileNow, ReconcileSyncRule
from calendar_sync.domain.model import SyncRuleId, SyncRuleState
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    ReconciliationService,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.fake_calendar import FakeCalendars, FixedClock, enabled_rule_factory, sync_use_case
from tests.helpers import event, rule


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
