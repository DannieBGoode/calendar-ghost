from threading import Thread

from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import RunKind
from calendar_sync.application.reconciliation import ReconcileSyncRule
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    ReconciliationService,
    SyncDecisionService,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.application.test_execute_sync_rule import FakeCalendarProvider, FixedClock
from tests.helpers import event, rule


def test_reconciliation_independently_proves_managed_projection() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    provider = FakeCalendarProvider(event())
    projector = EventProjector()
    fingerprinter = ProjectionFingerprinter()
    ExecuteSyncRule(
        unit_of_work,
        provider,
        SyncDecisionService(projector, fingerprinter),
        fingerprinter,
        FixedClock(),
    ).execute(rule().id)

    report = ReconcileSyncRule(
        unit_of_work,
        provider,
        projector,
        ReconciliationService(fingerprinter),
        FixedClock(),
    ).execute(rule().id)

    assert report.checked_mappings == 1
    assert report.is_consistent


def test_reconciliation_records_its_outcome() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    provider = FakeCalendarProvider(event())
    fingerprinter = ProjectionFingerprinter()

    report = ReconcileSyncRule(
        unit_of_work, provider, EventProjector(), ReconciliationService(fingerprinter), FixedClock()
    ).execute(rule().id)

    outcome = unit_of_work.state.outcomes[(rule().id, RunKind.RECONCILIATION)]
    assert outcome.succeeded is True
    assert outcome.checked_mappings == report.checked_mappings
    assert outcome.drift == len(report.drift)


def test_reconciliation_waits_for_the_rule_lock_held_by_removal_or_sync() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    fingerprinter = ProjectionFingerprinter()
    locks = RuleLocks()
    reconcile = ReconcileSyncRule(
        unit_of_work,
        FakeCalendarProvider(event()),
        EventProjector(),
        ReconciliationService(fingerprinter),
        FixedClock(),
        locks,
    )
    held = locks.for_rule(rule().id)
    held.acquire()
    worker = Thread(target=reconcile.execute, args=(rule().id,))
    worker.start()
    worker.join(0.1)
    blocked_while_held = worker.is_alive()
    held.release()
    worker.join(2)

    assert blocked_while_held
    assert not worker.is_alive()
    assert (rule().id, RunKind.RECONCILIATION) in unit_of_work.state.outcomes
