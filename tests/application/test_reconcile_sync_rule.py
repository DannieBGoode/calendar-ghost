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
