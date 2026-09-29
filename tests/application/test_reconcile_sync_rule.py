from dataclasses import replace
from datetime import timedelta
from threading import Thread

from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import RunKind
from calendar_sync.application.reconciliation import ReconcileSyncRule
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.domain.model import DriftKind, EventStatus
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    ReconciliationService,
    SyncDecisionService,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.application.test_execute_sync_rule import FakeCalendarProvider, FixedClock
from tests.application.test_recurring_sync import _LiveLookupCalendars
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import event, occurrence, rule, series, week_start


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


def test_reconciliation_counts_occurrence_drift_in_the_recorded_outcome() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=tuple(week_start(w) for w in range(3)))
    calendars.put(occurrence(master, 1, moved_by=timedelta(hours=1)))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    destination = factory.state.mappings[(rule().id, master.reference)].destination
    edited = calendars.get_occurrence(destination, week_start(1))
    assert edited is not None
    calendars.put(replace(edited, title="Edited"))

    report = ReconcileSyncRule(
        factory,
        calendars,
        EventProjector(),
        ReconciliationService(ProjectionFingerprinter()),
        FixedClock(),
    ).execute(rule().id)

    assert [(item.kind, item.source) for item in report.drift] == [
        (DriftKind.INCORRECT_PROJECTION, occurrence(master, 1).reference)
    ]
    outcome = factory.state.outcomes[(rule().id, RunKind.RECONCILIATION)]
    assert outcome.checked_mappings == 1
    assert outcome.drift == 1


def test_reconciliation_reports_a_recorded_occurrence_deleted_in_the_destination() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=tuple(week_start(w) for w in range(3)))
    calendars.put(occurrence(master, 1, moved_by=timedelta(hours=1)))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    destination = factory.state.mappings[(rule().id, master.reference)].destination
    calendars.cancel_occurrence(destination, week_start(1), master.reference, rule().id, "user")

    report = ReconcileSyncRule(
        factory,
        calendars,
        EventProjector(),
        ReconciliationService(ProjectionFingerprinter()),
        FixedClock(),
    ).execute(rule().id)

    assert [item.kind for item in report.drift] == [DriftKind.MISSING]


def test_reconciliation_reports_a_deleted_destination_series_without_failing() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=tuple(week_start(w) for w in range(3)))
    calendars.put(occurrence(master, 1, moved_by=timedelta(hours=1)))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    destination = factory.state.mappings[(rule().id, master.reference)].destination
    for instance in calendars.instances_of(destination):
        del calendars.events[instance.reference]
    del calendars.events[destination]

    report = ReconcileSyncRule(
        factory,
        calendars,
        EventProjector(),
        ReconciliationService(ProjectionFingerprinter()),
        FixedClock(),
    ).execute(rule().id)

    assert DriftKind.MISSING in [item.kind for item in report.drift]


def test_reconciliation_accepts_a_dormant_series_whose_every_occurrence_is_cancelled() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=(week_start(0),))
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    calendars.report(calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED)))
    use_case.execute(rule().id)

    report = ReconcileSyncRule(
        factory,
        calendars,
        EventProjector(),
        ReconciliationService(ProjectionFingerprinter()),
        FixedClock(),
    ).execute(rule().id)

    assert report.drift == ()
    assert report.checked_mappings == 1


def test_reconciliation_still_reports_a_deleted_live_series_beside_a_dormant_one() -> None:
    calendars = FakeCalendars()
    dormant = calendars.put(series("dormant-series"), starts=(week_start(0),))
    live = calendars.put(series(), starts=(week_start(0), week_start(1)))
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    calendars.report(calendars.put(occurrence(dormant, 0, status=EventStatus.CANCELLED)))
    use_case.execute(rule().id)
    deleted = factory.state.mappings[(rule().id, live.reference)].destination
    del calendars.events[deleted]

    report = ReconcileSyncRule(
        factory,
        calendars,
        EventProjector(),
        ReconciliationService(ProjectionFingerprinter()),
        FixedClock(),
    ).execute(rule().id)

    assert [(item.kind, item.source) for item in report.drift] == [
        (DriftKind.MISSING, live.reference)
    ]
    assert report.checked_mappings == 2


def test_reconciliation_reports_a_mapping_whose_source_is_no_longer_eligible() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    calendars.put(replace(event(), status=EventStatus.CANCELLED, time=None))

    report = ReconcileSyncRule(
        factory,
        calendars,
        EventProjector(),
        ReconciliationService(ProjectionFingerprinter()),
        FixedClock(),
    ).execute(rule().id)

    assert [item.kind for item in report.drift] == [DriftKind.MAPPING_INCONSISTENCY]


def test_reconciliation_of_a_projected_series_asks_for_no_live_lookup() -> None:
    calendars = _LiveLookupCalendars()
    calendars.put(series(), starts=(week_start(0), week_start(1)))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    calendars.live_lookups.clear()

    ReconcileSyncRule(
        factory,
        calendars,
        EventProjector(),
        ReconciliationService(ProjectionFingerprinter()),
        FixedClock(),
    ).execute(rule().id)

    assert calendars.live_lookups == []
