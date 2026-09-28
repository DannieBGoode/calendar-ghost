from dataclasses import replace
from datetime import timedelta, timezone

from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    CalendarEvent,
    EventId,
    EventMapping,
    EventMappingId,
    EventProjection,
    EventRef,
    EventStatus,
    ManagedOrigin,
    PrivacyPolicy,
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
from tests.helpers import NOW, all_day_event, event, rule

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
        rule(), transformation=TransformationPolicy(privacy=PrivacyPolicy.COPY_DETAILS)
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


def test_recurring_series_is_created_as_a_series() -> None:
    source = replace(event(), recurrence=Recurrence(("RRULE:FREQ=WEEKLY",)))

    decision = decisions.decide(rule(), source, None, None)

    assert decision.action is SyncAction.CREATE
    assert decision.projection is not None
    assert decision.projection.recurrence == source.recurrence


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


def test_reconciliation_reports_missing_and_unexpected_events() -> None:
    source = event()
    destination = _destination(source)
    mapping = _mapping(source, destination)
    unexpected = replace(
        destination,
        reference=EventRef(rule().destination, EventId("unexpected-managed")),
    )
    service = ReconciliationService(fingerprinter)

    report = service.reconcile(
        rule(),
        [mapping],
        {source.reference: projector.project(source, rule())},
        {unexpected.reference: unexpected},
    )

    assert {item.kind.value for item in report.drift} == {"missing", "unexpected"}


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
