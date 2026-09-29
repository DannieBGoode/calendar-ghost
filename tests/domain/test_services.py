from dataclasses import replace
from datetime import timedelta, timezone

from calendar_sync.domain.model import (
    AllDayRange,
    AllDaySyncPolicy,
    CalendarEvent,
    DriftKind,
    EventId,
    EventMapping,
    EventMappingId,
    EventProjection,
    EventRef,
    EventStatus,
    ManagedOrigin,
    NoProjectionExpected,
    OccurrenceCheck,
    OccurrenceMapping,
    OccurrenceMappingId,
    OccurrenceState,
    ProjectionContent,
    ProjectionFingerprint,
    Recurrence,
    SyncAction,
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
from tests.helpers import NOW, all_day_event, event, occurrence, rule, series, week_start

projector = EventProjector()
fingerprinter = ProjectionFingerprinter()
decisions = SyncDecisionService(projector, fingerprinter)


def _mapping(source: CalendarEvent, destination: CalendarEvent) -> EventMapping:
    projection = projector.project(source, rule())
    return EventMapping(
        EventMappingId("mapping-1"),
        rule().id,
        source.reference,
        destination.reference,
        source.revision,
        fingerprinter.fingerprint(projection),
    )


def _destination(source: CalendarEvent, title: str = "Busy") -> CalendarEvent:
    return CalendarEvent(
        EventRef(rule().destination, EventId("destination-event")),
        source.time,
        "destination-revision",
        title=title,
        managed_origin=ManagedOrigin(rule().id, source.reference),
    )


def test_busy_only_projection_omits_private_content() -> None:
    projection = projector.project(event(), rule())

    assert projection.title == "Busy"
    assert projection.description == ""
    assert projection.location == ""


def test_details_policy_is_rule_wide() -> None:
    details_rule = replace(
        rule(), transformation=TransformationPolicy(content=ProjectionContent.DETAILS)
    )

    projection = projector.project(event(), details_rule)

    assert projection.title == "Private appointment"
    assert projection.description == "Sensitive description"


def test_destination_drift_is_overwritten_not_conflicted() -> None:
    source = event()
    destination = _destination(source, title="Edited on destination")

    decision = decisions.decide(rule(), source, _mapping(source, destination), destination)

    assert decision.action is SyncAction.UPDATE
    assert decision.projection is not None
    assert decision.projection.title == "Busy"


def test_current_projection_is_ignored() -> None:
    source = event()
    destination = _destination(source)

    decision = decisions.decide(rule(), source, _mapping(source, destination), destination)

    assert decision.action is SyncAction.IGNORE


def test_cancelled_mapped_source_deletes_owned_projection() -> None:
    source = replace(event(), status=EventStatus.CANCELLED)
    destination = _destination(source)

    decision = decisions.decide(rule(), source, _mapping(source, destination), destination)

    assert decision.action is SyncAction.DELETE


def test_mismatched_destination_origin_blocks_update_and_delete() -> None:
    source = event()
    wrong_origin = event("different-source").reference
    destination = replace(
        _destination(source, title="Edited"),
        managed_origin=ManagedOrigin(rule().id, wrong_origin),
    )
    mapping = _mapping(source, destination)

    update = decisions.decide(rule(), source, mapping, destination)
    deletion = decisions.decide(
        rule(), replace(source, status=EventStatus.CANCELLED), mapping, destination
    )

    assert update.action is SyncAction.CONFLICT
    assert deletion.action is SyncAction.CONFLICT
    assert update.reason is SyncReason.DESTINATION_OWNERSHIP_INCONSISTENT


def test_excluded_all_day_event_is_not_created() -> None:
    exclude_rule = replace(
        rule(),
        transformation=TransformationPolicy(all_day=AllDaySyncPolicy.EXCLUDE),
    )

    decision = decisions.decide(exclude_rule, all_day_event(), None, None)

    assert decision.action is SyncAction.IGNORE


def test_managed_projection_cannot_become_a_source() -> None:
    source = replace(event(), managed_origin=ManagedOrigin(rule().id, event().reference))

    decision = decisions.decide(rule(), source, None, None)

    assert decision.action is SyncAction.IGNORE
    assert decision.reason is SyncReason.MANAGED_PROJECTION_SOURCE


def test_unmapped_single_event_that_ended_before_the_window_is_skipped() -> None:
    window_start = NOW - timedelta(days=30)
    old = replace(
        event(),
        time=TimedInterval(window_start - timedelta(hours=2), window_start - timedelta(hours=1)),
    )
    old_all_day = replace(
        all_day_event(),
        time=AllDayRange(
            window_start.date() - timedelta(days=2), window_start.date() - timedelta(days=1)
        ),
    )

    for source in (old, old_all_day):
        decision = decisions.decide(rule(), source, None, None, window_start=window_start)
        assert decision.action is SyncAction.IGNORE
        assert decision.reason is SyncReason.BEFORE_SYNC_WINDOW


def test_window_does_not_block_mapped_events_or_series_that_began_before_it() -> None:
    window_start = NOW + timedelta(days=1)
    source = replace(event(), revision="revision-2")
    destination = _destination(event())
    old_series = replace(event(), recurrence=Recurrence(("RRULE:FREQ=WEEKLY",)))

    mapped = decisions.decide(
        rule(), source, _mapping(event(), destination), destination, window_start=window_start
    )
    series_start = decisions.decide(rule(), old_series, None, None, window_start=window_start)

    assert mapped.action is SyncAction.UPDATE
    assert series_start.action is SyncAction.CREATE


def test_recurring_series_is_created_as_a_series() -> None:
    source = replace(event(), recurrence=Recurrence(("RRULE:FREQ=WEEKLY",)))

    decision = decisions.decide(rule(), source, None, None)

    assert decision.action is SyncAction.CREATE
    assert decision.projection is not None
    assert decision.projection.recurrence == source.recurrence


def test_series_without_live_occurrences_is_never_projected() -> None:
    source = series()
    destination = replace(_destination(source), recurrence=source.recurrence)
    mapping = _mapping(source, destination)

    unmapped = decisions.decide(rule(), source, None, None, has_live_occurrences=False)
    missing = decisions.decide(rule(), source, mapping, None, has_live_occurrences=False)
    live = decisions.decide(rule(), source, mapping, destination, has_live_occurrences=False)
    single = decisions.decide(rule(), event(), None, None, has_live_occurrences=False)

    dormant = (SyncAction.IGNORE, SyncReason.SERIES_WITHOUT_OCCURRENCES)
    assert (unmapped.action, unmapped.reason) == dormant
    # The mapping is kept, so its cancelled occurrences survive a later restore.
    assert (missing.action, missing.reason) == dormant
    assert (live.action, live.reason) == (
        SyncAction.DELETE,
        SyncReason.SERIES_WITHOUT_OCCURRENCES_REMOVED,
    )
    assert single.action is SyncAction.CREATE


def test_cancelled_and_excluded_all_day_events_record_distinct_reasons() -> None:
    exclude_rule = replace(
        rule(),
        transformation=TransformationPolicy(all_day=AllDaySyncPolicy.EXCLUDE),
    )
    cancelled = replace(event(), status=EventStatus.CANCELLED, time=None)
    all_day = all_day_event()
    all_day_destination = _destination(all_day)

    assert decisions.decide(rule(), cancelled, None, None).reason is (
        SyncReason.CANCELLED_WITHOUT_PROJECTION
    )
    assert decisions.decide(exclude_rule, all_day, None, None).reason is (
        SyncReason.ALL_DAY_EXCLUDED
    )
    removal = decisions.decide(
        exclude_rule, all_day, _mapping(all_day, all_day_destination), all_day_destination
    )
    assert removal.action is SyncAction.DELETE
    assert removal.reason is SyncReason.ALL_DAY_EXCLUDED_REMOVED


def test_update_reason_distinguishes_source_change_from_destination_drift() -> None:
    source = event()
    edited_destination = _destination(source, title="Edited in destination")
    mapping = _mapping(source, edited_destination)

    drift = decisions.decide(rule(), source, mapping, edited_destination)
    changed = decisions.decide(
        rule(), replace(source, revision="revision-2"), mapping, _destination(source)
    )

    assert drift.action is SyncAction.UPDATE
    assert drift.reason is SyncReason.DESTINATION_DRIFT_REPAIRED
    assert changed.action is SyncAction.UPDATE
    assert changed.reason is SyncReason.SOURCE_CHANGED


def test_reconciliation_reports_a_missing_projection_as_drift_and_an_unmapped_one_as_conflict() -> (
    None
):
    source = event()
    destination = _destination(source)
    mapping = _mapping(source, destination)
    unmapped = replace(
        destination,
        reference=EventRef(rule().destination, EventId("unexpected-managed")),
    )
    service = ReconciliationService(fingerprinter)

    report = service.reconcile(
        rule(),
        [mapping],
        {source.reference: projector.project(source, rule())},
        {unmapped.reference: unmapped},
    )

    assert [item.kind for item in report.drift] == [DriftKind.MISSING]
    # No mapping proves ownership of the managed event, so it is a Conflict, not Drift.
    assert [(item.reason, item.source, item.destination) for item in report.conflicts] == [
        (SyncReason.PROJECTION_UNMAPPED, source.reference, unmapped.reference)
    ]


def test_a_mapping_conflict_leaves_the_rule_inconsistent_without_counting_as_drift() -> None:
    source = event()
    destination = _destination(source)
    service = ReconciliationService(fingerprinter)

    # The source could not be read, so it has no expected entry.
    report = service.reconcile(
        rule(), [_mapping(source, destination)], {}, {destination.reference: destination}
    )

    assert report.drift == ()
    assert [(item.reason, item.source, item.destination) for item in report.conflicts] == [
        (SyncReason.SOURCE_UNVERIFIABLE, source.reference, destination.reference)
    ]
    assert not report.is_consistent


def test_a_mapping_outside_the_relationship_or_to_a_managed_source_is_a_conflict() -> None:
    source = event()
    destination = _destination(source)
    elsewhere = replace(
        _mapping(source, destination),
        destination=EventRef(rule().source, destination.reference.event_id),
    )
    service = ReconciliationService(fingerprinter)

    outside = service.reconcile(
        rule(), [elsewhere], {source.reference: projector.project(source, rule())}, {}
    )
    managed = service.reconcile(
        rule(),
        [_mapping(source, destination)],
        {source.reference: NoProjectionExpected.MANAGED_SOURCE},
        {destination.reference: destination},
    )

    for report in (outside, managed):
        assert report.drift == ()
        assert [item.reason for item in report.conflicts] == [SyncReason.MAPPING_INCONSISTENT]


def test_a_projection_left_for_an_ineligible_source_is_unexpected_drift() -> None:
    source = event()
    destination = _destination(source)
    mapping = _mapping(source, destination)
    service = ReconciliationService(fingerprinter)
    ineligible = {source.reference: NoProjectionExpected.INELIGIBLE}

    left_behind = service.reconcile(
        rule(), [mapping], ineligible, {destination.reference: destination}
    )
    already_gone = service.reconcile(rule(), [mapping], ineligible, {})

    assert [item.kind for item in left_behind.drift] == [DriftKind.UNEXPECTED]
    assert left_behind.conflicts == ()
    assert already_gone.is_consistent


def test_a_report_excluding_blocked_sources_keeps_findings_about_other_events() -> None:
    source = event()
    other = event("other-event")
    destination = _destination(source)
    report = ReconciliationService(fingerprinter).reconcile(
        rule(),
        [
            _mapping(source, destination),
            replace(
                _mapping(other, destination),
                id=EventMappingId("mapping-2"),
                destination=EventRef(rule().destination, EventId("other-destination")),
            ),
        ],
        {other.reference: projector.project(other, rule())},
        {destination.reference: destination},
    )

    remaining = report.excluding({source.reference})

    assert [item.source for item in report.conflicts] == [source.reference]
    assert remaining.conflicts == ()
    assert [(item.kind, item.source) for item in remaining.drift] == [
        (DriftKind.MISSING, other.reference)
    ]
    assert remaining.checked_mappings == 2


def test_fingerprint_compares_timed_bounds_as_instants() -> None:
    offset = timezone(timedelta(hours=2))
    utc = EventProjection(TimedInterval(NOW, NOW + timedelta(hours=1)), "Busy")
    local = EventProjection(
        TimedInterval(NOW.astimezone(offset), (NOW + timedelta(hours=1)).astimezone(offset)),
        "Busy",
    )

    assert fingerprinter.fingerprint(utc) == fingerprinter.fingerprint(local)


def test_fingerprint_includes_time_zone_only_for_series() -> None:
    zoned = TimedInterval(NOW, NOW + timedelta(hours=1), "Europe/Madrid")
    plain = TimedInterval(NOW, NOW + timedelta(hours=1))
    weekly = Recurrence(("RRULE:FREQ=WEEKLY",))

    assert fingerprinter.fingerprint(EventProjection(zoned, "Busy")) == fingerprinter.fingerprint(
        EventProjection(plain, "Busy")
    )
    assert fingerprinter.fingerprint(
        EventProjection(zoned, "Busy", recurrence=weekly)
    ) != fingerprinter.fingerprint(EventProjection(plain, "Busy", recurrence=weekly))


def _series_reconciliation_inputs() -> tuple[
    CalendarEvent, CalendarEvent, EventMapping, dict[EventRef, EventProjection]
]:
    source = series()
    destination = series(
        "projection-1",
        calendar=rule().destination,
        title="Busy",
        managed_origin=ManagedOrigin(rule().id, source.reference),
    )
    destination = replace(destination, description="", location="")
    mapping = EventMapping(
        EventMappingId("series-mapping"),
        rule().id,
        source.reference,
        destination.reference,
        source.revision,
        ProjectionFingerprint("f"),
    )
    expected = {source.reference: EventProjector().project(source, rule())}
    return source, destination, mapping, expected


def _occurrence_mapping(
    mapping: EventMapping, destination: CalendarEvent, state: OccurrenceState
) -> OccurrenceMapping:
    return OccurrenceMapping(
        OccurrenceMappingId("o-1"),
        mapping.id,
        week_start(1),
        occurrence(series(), 1).reference,
        occurrence(destination, 1).reference,
        state,
        "r-1",
        ProjectionFingerprint("f") if state is OccurrenceState.MODIFIED else None,
    )


def test_reconciliation_reports_edited_and_resurrected_occurrences() -> None:
    source, destination, mapping, expected = _series_reconciliation_inputs()
    edited = replace(occurrence(destination, 1, title="Edited"), description="", location="")
    service = ReconciliationService(ProjectionFingerprinter())

    report = service.reconcile(
        rule(),
        [mapping],
        expected,
        {destination.reference: destination, edited.reference: edited},
        [
            OccurrenceCheck(
                _occurrence_mapping(mapping, destination, OccurrenceState.MODIFIED),
                destination.reference,
                EventProjector().project(occurrence(source, 1), rule()),
                edited,
            ),
            OccurrenceCheck(
                replace(
                    _occurrence_mapping(mapping, destination, OccurrenceState.CANCELLED),
                    original_start=week_start(2),
                ),
                destination.reference,
                None,
                replace(occurrence(destination, 2, title="Busy"), description="", location=""),
            ),
        ],
    )

    assert [item.kind for item in report.drift] == [
        DriftKind.INCORRECT_PROJECTION,
        DriftKind.INCORRECT_PROJECTION,
    ]
    assert report.checked_mappings == 1


def test_reconciliation_reports_a_missing_occurrence() -> None:
    source, destination, mapping, expected = _series_reconciliation_inputs()

    report = ReconciliationService(ProjectionFingerprinter()).reconcile(
        rule(),
        [mapping],
        expected,
        {destination.reference: destination},
        [
            OccurrenceCheck(
                _occurrence_mapping(mapping, destination, OccurrenceState.MODIFIED),
                destination.reference,
                EventProjector().project(occurrence(source, 1), rule()),
                None,
            )
        ],
    )

    assert [item.kind for item in report.drift] == [DriftKind.MISSING]


def test_unmapped_managed_exception_of_a_mapped_series_is_incorrect_not_unexpected() -> None:
    _source, destination, mapping, expected = _series_reconciliation_inputs()
    stray = replace(
        occurrence(destination, 3, title="Edited"),
        managed_origin=destination.managed_origin,
    )

    report = ReconciliationService(ProjectionFingerprinter()).reconcile(
        rule(),
        [mapping],
        expected,
        {destination.reference: destination, stray.reference: stray},
    )

    assert [item.kind for item in report.drift] == [DriftKind.INCORRECT_PROJECTION]
