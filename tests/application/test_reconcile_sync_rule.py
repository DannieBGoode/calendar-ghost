from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from threading import Thread

from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import AuditAction, AuditOutcome, Clock, RunKind
from calendar_sync.application.reconciliation import ReconcileSyncRule
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    DriftKind,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    EventStatus,
    InvitationResponse,
    ManagedOrigin,
    ProjectionFingerprint,
    ReconciliationReport,
    SyncReason,
    TimedInterval,
    TransformationPolicy,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    ReconciliationService,
    SyncDecisionService,
)
from calendar_sync.infrastructure.identifiers import UuidRunIdGenerator
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.application.test_execute_sync_rule import (
    FakeCalendarProvider,
    FixedClock,
    ScriptedRunIds,
)
from tests.application.test_recurring_sync import _LiveLookupCalendars
from tests.fake_calendar import (
    WRITE_OPERATIONS,
    FakeCalendars,
    ReaderOnlyCalendar,
    enabled_rule_factory,
    sync_use_case,
)
from tests.helpers import NOW, endpoint, event, occurrence, rule, series, week_start


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
        UuidRunIdGenerator(),
    ).execute(rule().id)

    report = ReconcileSyncRule(
        unit_of_work,
        provider,
        projector,
        ReconciliationService(fingerprinter),
        FixedClock(),
        UuidRunIdGenerator(),
    ).execute(rule().id)

    assert report.checked_mappings == 1
    assert report.is_consistent


def test_reconciliation_records_its_outcome() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    provider = FakeCalendarProvider(event())
    fingerprinter = ProjectionFingerprinter()

    report = ReconcileSyncRule(
        unit_of_work,
        provider,
        EventProjector(),
        ReconciliationService(fingerprinter),
        FixedClock(),
        UuidRunIdGenerator(),
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
        UuidRunIdGenerator(),
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
        UuidRunIdGenerator(),
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
        UuidRunIdGenerator(),
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
        UuidRunIdGenerator(),
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
        UuidRunIdGenerator(),
    ).execute(rule().id)

    assert report.drift == ()
    assert report.checked_mappings == 1


def test_reconciliation_accepts_a_dormant_series_whose_every_occurrence_is_declined() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=(week_start(0),))
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    declined = replace(occurrence(master, 0), response=InvitationResponse.DECLINED)
    calendars.report(calendars.put(declined))
    use_case.execute(rule().id)

    report = ReconcileSyncRule(
        factory,
        calendars,
        EventProjector(),
        ReconciliationService(ProjectionFingerprinter()),
        FixedClock(),
        UuidRunIdGenerator(),
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
        UuidRunIdGenerator(),
    ).execute(rule().id)

    assert [(item.kind, item.source) for item in report.drift] == [
        (DriftKind.MISSING, live.reference)
    ]
    assert report.checked_mappings == 2


def test_reconciliation_reports_a_projection_left_for_a_cancelled_source_as_drift() -> None:
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
        UuidRunIdGenerator(),
    ).execute(rule().id)

    # A verified cancellation authorizes the deletion a Sync Run would make; it is not a Conflict.
    assert [item.kind for item in report.drift] == [DriftKind.UNEXPECTED]
    assert report.conflicts == ()
    assert not [entry for entry in factory.state.audit if entry.outcome is AuditOutcome.BLOCKED]


def test_reconciliation_blocks_a_mapping_whose_source_cannot_be_read_without_drift() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    calendars.unreadable.add(event().reference)

    report = ReconcileSyncRule(
        factory,
        calendars,
        EventProjector(),
        ReconciliationService(ProjectionFingerprinter()),
        FixedClock(),
        ScriptedRunIds(iter(["reconciliation-run"])),
    ).execute(rule().id)

    assert report.drift == ()
    assert [item.reason for item in report.conflicts] == [SyncReason.SOURCE_UNVERIFIABLE]
    assert not report.is_consistent
    outcome = factory.state.outcomes[(rule().id, RunKind.RECONCILIATION)]
    assert (outcome.drift, outcome.conflicts) == (0, 1)
    blocked = [entry for entry in factory.state.audit if entry.outcome is AuditOutcome.BLOCKED]
    assert [
        (entry.action, entry.reason, entry.source_event_id, entry.run_id) for entry in blocked
    ] == [
        (
            AuditAction.CONFLICT,
            SyncReason.SOURCE_UNVERIFIABLE,
            event().reference.event_id.value,
            "reconciliation-run",
        )
    ]
    assert blocked[0].event is None


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
        UuidRunIdGenerator(),
    ).execute(rule().id)

    assert calendars.live_lookups == []


def test_reconciliation_under_an_all_day_exclusion_accepts_a_series_left_with_all_day_only() -> (
    None
):
    excluding = replace(
        rule(), transformation=TransformationPolicy(all_day=AllDaySyncPolicy.EXCLUDE)
    )
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=(week_start(0), week_start(1)))
    calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED))
    factory = enabled_rule_factory(excluding)
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    # The last timed occurrence becomes all-day, so the rule cancels it and Google the series.
    calendars.report(calendars.put(occurrence(master, 1, all_day=True)))
    use_case.execute(rule().id)

    report = ReconcileSyncRule(
        factory,
        calendars,
        EventProjector(),
        ReconciliationService(ProjectionFingerprinter()),
        FixedClock(),
        UuidRunIdGenerator(),
    ).execute(rule().id)

    assert report.drift == ()
    assert report.checked_mappings == 1


def test_reconciliation_reports_a_projection_left_behind_for_a_declined_event() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    # Declined without the feed reporting it, so only reconciliation sees the leftover projection.
    calendars.put(replace(event(), revision="revision-2", response=InvitationResponse.DECLINED))

    report = _reconcile(factory, calendars)

    assert [item.kind for item in report.drift] == [DriftKind.UNEXPECTED]


def _reconcile(
    factory: InMemoryUnitOfWorkFactory, calendars: FakeCalendars, clock: Clock | None = None
) -> ReconciliationReport:
    return ReconcileSyncRule(
        factory,
        calendars,
        EventProjector(),
        ReconciliationService(ProjectionFingerprinter()),
        clock or FixedClock(),
        UuidRunIdGenerator(),
    ).execute(rule().id)


@dataclass(frozen=True)
class _ClockAt:
    at: datetime

    def now(self) -> datetime:
        return self.at


# Ten weeks into a weekly series, so its first weeks ended before the 30-day sync window.
LATER = _ClockAt(week_start(9) + timedelta(days=1))


def test_reconciliation_reports_a_projection_that_lost_its_ownership_metadata() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=(week_start(0),))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    destination = factory.state.mappings[(rule().id, master.reference)].destination
    # Another tool strips the metadata; the projection is still there, though no longer listed.
    calendars.events[destination] = replace(calendars.events[destination], managed_origin=None)
    calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED))

    report = _reconcile(factory, calendars)

    assert DriftKind.MISSING in [item.kind for item in report.drift]


def test_reconciliation_reports_an_inconsistent_mapping_even_when_its_series_is_dormant() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=(week_start(0),))
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    calendars.report(calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED)))
    use_case.execute(rule().id)
    key = (rule().id, master.reference)
    mapping = factory.state.mappings[key]
    elsewhere = endpoint("work-account", "another-calendar")
    factory.state.mappings[key] = replace(
        mapping, destination=EventRef(elsewhere, mapping.destination.event_id)
    )

    report = _reconcile(factory, calendars)

    assert report.drift == ()
    assert [item.reason for item in report.conflicts] == [SyncReason.MAPPING_INCONSISTENT]


def test_reconciliation_runs_against_a_calendar_that_can_only_read() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=tuple(week_start(w) for w in range(3)))
    calendars.put(occurrence(master, 1, moved_by=timedelta(hours=1)))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    destination = factory.state.mappings[(rule().id, master.reference)].destination
    edited = calendars.get_occurrence(destination, week_start(1))
    assert edited is not None
    calendars.put(replace(edited, title="Edited"))
    writes = list(calendars.writes)
    reader = ReaderOnlyCalendar(calendars)

    report = ReconcileSyncRule(
        factory,
        reader,
        EventProjector(),
        ReconciliationService(ProjectionFingerprinter()),
        FixedClock(),
        UuidRunIdGenerator(),
    ).execute(rule().id)

    assert not any(hasattr(reader, name) for name in WRITE_OPERATIONS)
    assert [item.kind for item in report.drift] == [DriftKind.INCORRECT_PROJECTION]
    assert calendars.writes == writes


def _edit_destination_occurrence(
    factory: InMemoryUnitOfWorkFactory, calendars: FakeCalendars, master_ref: EventRef, week: int
) -> None:
    destination = factory.state.mappings[(rule().id, master_ref)].destination
    edited = calendars.get_occurrence(destination, week_start(week))
    assert edited is not None
    calendars.put(replace(edited, title="Edited"))


def test_reconciliation_checks_a_current_series_but_not_its_past_occurrences() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=tuple(week_start(w) for w in range(10)))
    calendars.put(occurrence(master, 1, moved_by=timedelta(hours=1)))
    upcoming = calendars.put(occurrence(master, 8, moved_by=timedelta(hours=1)))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    _edit_destination_occurrence(factory, calendars, master.reference, 1)
    _edit_destination_occurrence(factory, calendars, master.reference, 8)

    report = _reconcile(factory, calendars, LATER)

    # The series began before the window but still repeats, so it and its later weeks are
    # checked; the edit to week 1, long past, is not.
    assert report.checked_mappings == 1
    assert [(item.kind, item.source) for item in report.drift] == [
        (DriftKind.INCORRECT_PROJECTION, upcoming.reference)
    ]


def test_reconciliation_checks_a_past_occurrence_moved_into_the_window() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=tuple(week_start(w) for w in range(10)))
    moved = calendars.put(occurrence(master, 1, moved_by=timedelta(weeks=7, hours=1)))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    _edit_destination_occurrence(factory, calendars, master.reference, 1)

    report = _reconcile(factory, calendars, LATER)

    # Its original week ended long ago, but the source now shows it inside the window.
    assert [(item.kind, item.source) for item in report.drift] == [
        (DriftKind.INCORRECT_PROJECTION, moved.reference)
    ]


def test_reconciliation_verifies_listed_sources_without_reading_each_one() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    calendars.put(event("second-event"))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    calendars.reads.clear()

    report = _reconcile(factory, calendars)

    assert report.checked_mappings == 2
    assert report.is_consistent
    assert calendars.listings == [rule().source]
    assert calendars.reads == []


def test_reconciliation_reads_a_source_moved_out_of_the_window_with_a_current_projection() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    long_ago = TimedInterval(NOW - timedelta(days=60), NOW - timedelta(days=60, hours=-1))
    calendars.put(replace(event(), time=long_ago, revision="revision-2"))

    report = _reconcile(factory, calendars)

    assert [(item.kind, item.source) for item in report.drift] == [
        (DriftKind.INCORRECT_PROJECTION, event().reference)
    ]
    assert event().reference in calendars.reads


def test_reconciliation_ignores_an_unmapped_projection_that_ended_before_the_window() -> None:
    calendars = FakeCalendars()
    factory = enabled_rule_factory()
    origin = ManagedOrigin(rule().id, EventRef(rule().source, EventId("gone")))
    past = calendars.put(
        replace(
            event("past-orphan", calendar=rule().destination),
            time=TimedInterval(NOW - timedelta(days=60), NOW - timedelta(days=60, hours=-1)),
            managed_origin=origin,
        )
    )
    current = calendars.put(
        replace(event("current-orphan", calendar=rule().destination), managed_origin=origin)
    )

    report = _reconcile(factory, calendars)

    assert [item.destination for item in report.conflicts] == [current.reference]
    assert past.reference not in [item.destination for item in report.conflicts]


def test_reconciliation_reports_an_inconsistent_mapping_of_a_past_event_without_reading_it() -> (
    None
):
    calendars = FakeCalendars()
    factory = enabled_rule_factory()
    old = calendars.put(
        replace(
            event(),
            time=TimedInterval(NOW - timedelta(days=60), NOW - timedelta(days=60, hours=-1)),
        )
    )
    elsewhere = endpoint("work-account", "another-calendar")
    factory.state.mappings[(rule().id, old.reference)] = EventMapping(
        EventMappingId("mapping-1"),
        rule().id,
        old.reference,
        EventRef(elsewhere, EventId("projection")),
        old.revision,
        ProjectionFingerprint("fingerprint"),
    )

    report = _reconcile(factory, calendars)

    # Outside the window, but the mapping points outside the rule: that is a Conflict at any age.
    assert report.checked_mappings == 1
    assert [item.reason for item in report.conflicts] == [SyncReason.MAPPING_INCONSISTENT]
    assert calendars.reads == []
