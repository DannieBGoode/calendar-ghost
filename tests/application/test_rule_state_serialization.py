"""Every read-modify-write of a rule waits for the shared per-rule write lock.

Without it, two lifecycle operations can both read the same rule and the last save silently
discards the other's change, for example restoring the previous policy as enabled.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from threading import Thread

from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.preview import PreviewSyncRule
from calendar_sync.application.removal import RemoveSyncRule
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.domain.model import (
    ProjectionContent,
    ProjectionHandling,
    SyncRuleState,
    TransformationPolicy,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.application.test_execute_sync_rule import FakeCalendarProvider, FixedClock
from tests.fake_calendar import FakeCalendars, enabled_rule_factory
from tests.helpers import event, occurrence, rule, series, week_start


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
    unit_of_work = InMemoryUnitOfWorkFactory()
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
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.PAUSED)
    locks = RuleLocks()
    removal = RemoveSyncRule(unit_of_work, None, None, FixedClock(), locks)

    assert _blocks_until_released(
        locks, lambda: removal.execute(rule().id, ProjectionHandling.DETACH)
    )
    assert unit_of_work.state.rules == {}


def test_clearing_reprojection_waits_for_the_rule_write_lock() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
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
