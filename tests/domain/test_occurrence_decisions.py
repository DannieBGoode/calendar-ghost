from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    CalendarEvent,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    EventStatus,
    ManagedOrigin,
    OccurrenceMapping,
    OccurrenceMappingId,
    OccurrenceState,
    ProjectionContent,
    ProjectionFingerprint,
    SyncAction,
    SyncDecision,
    SyncReason,
    SyncRule,
    SyncRuleId,
    TimedInterval,
    TransformationPolicy,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from tests.helpers import occurrence, rule, series, week_start

SOURCE = series()
DESTINATION = series(
    "projection-1",
    calendar=rule().destination,
    title="Busy",
    managed_origin=ManagedOrigin(rule().id, SOURCE.reference),
)
SERIES_MAPPING = EventMapping(
    EventMappingId("series-mapping"),
    rule().id,
    SOURCE.reference,
    DESTINATION.reference,
    SOURCE.revision,
    ProjectionFingerprint("series-fingerprint"),
)
START = week_start(1)


def service() -> SyncDecisionService:
    return SyncDecisionService(EventProjector(), ProjectionFingerprinter())


def busy_instance(**changes: object) -> CalendarEvent:
    instance = occurrence(DESTINATION, 1, title="Busy")
    return replace(instance, description="", location="", **changes)  # type: ignore[arg-type]


def recorded(
    state: OccurrenceState = OccurrenceState.MODIFIED, revision: str = "occurrence-revision-1"
) -> OccurrenceMapping:
    return OccurrenceMapping(
        OccurrenceMappingId("occurrence-mapping"),
        SERIES_MAPPING.id,
        START,
        occurrence(SOURCE, 1).reference,
        busy_instance().reference,
        state,
        revision,
        ProjectionFingerprint("f") if state is OccurrenceState.MODIFIED else None,
    )


def decide(
    source_occurrence: CalendarEvent | None,
    destination_occurrence: CalendarEvent | None,
    *,
    sync_rule: SyncRule | None = None,
    source_series: CalendarEvent = SOURCE,
    series_mapping: EventMapping | None = SERIES_MAPPING,
    occurrence_mapping: OccurrenceMapping | None = None,
    destination_series: CalendarEvent | None = DESTINATION,
    destination_reported: bool = False,
    has_live_occurrences: bool = True,
) -> SyncDecision:
    return service().decide_occurrence(
        sync_rule or rule(),
        source_series,
        series_mapping,
        START,
        source_occurrence,
        occurrence_mapping,
        destination_series,
        destination_occurrence,
        destination_reported=destination_reported,
        has_live_occurrences=has_live_occurrences,
    )


def test_series_master_projects_as_a_series_with_its_time_zone() -> None:
    decision = service().decide(rule(), SOURCE, None, None)

    assert decision.action is SyncAction.CREATE
    assert decision.projection is not None
    assert decision.projection.recurrence == SOURCE.recurrence
    assert isinstance(decision.projection.time, TimedInterval)
    assert decision.projection.time.time_zone == "Europe/Madrid"
    assert decision.projection.title == "Busy"


def test_single_event_decision_rejects_occurrence_exceptions() -> None:
    with pytest.raises(DomainValidationError):
        service().decide(rule(), occurrence(SOURCE, 1), None, None)


def test_moved_occurrence_updates_destination_with_busy_title_only() -> None:
    moved = occurrence(SOURCE, 1, moved_by=timedelta(hours=2), title="Secret offsite")

    decision = decide(moved, busy_instance())

    assert decision.action is SyncAction.UPDATE
    assert decision.reason is SyncReason.OCCURRENCE_CHANGED
    assert decision.projection is not None
    assert decision.projection.title == "Busy"
    assert decision.projection.description == ""
    assert decision.projection.location == ""
    assert decision.projection.recurrence is None
    assert decision.projection.time == moved.time


def test_details_rule_copies_occurrence_details() -> None:
    details = replace(
        rule(), transformation=TransformationPolicy(content=ProjectionContent.DETAILS)
    )
    moved = occurrence(SOURCE, 1, title="Offsite")

    decision = decide(moved, busy_instance(), sync_rule=details)

    assert decision.projection is not None
    assert decision.projection.title == "Offsite"


def test_matching_occurrence_is_current_and_keeps_its_projection() -> None:
    decision = decide(occurrence(SOURCE, 1), busy_instance())

    assert decision.action is SyncAction.IGNORE
    assert decision.reason is SyncReason.OCCURRENCE_CURRENT
    assert decision.projection is not None


def test_changed_source_occurrence_whose_projection_matches_needs_no_write() -> None:
    renamed = occurrence(SOURCE, 1, revision="occurrence-revision-2", title="Renamed")

    decision = decide(renamed, busy_instance(), occurrence_mapping=recorded())

    assert decision.action is SyncAction.IGNORE
    assert decision.reason is SyncReason.OCCURRENCE_CURRENT


def test_destination_edit_with_unchanged_source_is_drift_repair() -> None:
    edited = busy_instance(title="Edited in destination")

    decision = decide(occurrence(SOURCE, 1), edited, occurrence_mapping=recorded())

    assert decision.action is SyncAction.UPDATE
    assert decision.reason is SyncReason.OCCURRENCE_DRIFT_REPAIRED


def test_unmapped_destination_edit_reported_by_the_feed_is_drift_repair() -> None:
    edited = busy_instance(title="Edited in destination")

    decision = decide(occurrence(SOURCE, 1), edited, destination_reported=True)

    assert decision.reason is SyncReason.OCCURRENCE_DRIFT_REPAIRED


def test_cancelled_destination_occurrence_is_restored() -> None:
    cancelled = occurrence(DESTINATION, 1, status=EventStatus.CANCELLED)

    decision = decide(occurrence(SOURCE, 1), cancelled, destination_reported=True)

    assert decision.action is SyncAction.UPDATE
    assert decision.projection is not None


def test_cancelled_source_occurrence_cancels_the_destination_occurrence() -> None:
    cancelled = occurrence(SOURCE, 1, status=EventStatus.CANCELLED)

    decision = decide(cancelled, busy_instance())

    assert decision.action is SyncAction.DELETE
    assert decision.reason is SyncReason.OCCURRENCE_CANCELLED


def test_already_cancelled_destination_occurrence_is_left_alone() -> None:
    cancelled = occurrence(SOURCE, 1, status=EventStatus.CANCELLED)
    destination = occurrence(DESTINATION, 1, status=EventStatus.CANCELLED)

    decision = decide(cancelled, destination)

    assert decision.action is SyncAction.IGNORE
    assert decision.reason is SyncReason.OCCURRENCE_ALREADY_CANCELLED


def test_occurrence_no_longer_in_source_series_is_cancelled() -> None:
    decision = decide(None, busy_instance(), occurrence_mapping=recorded())

    assert decision.action is SyncAction.DELETE
    assert decision.reason is SyncReason.OCCURRENCE_REMOVED_FROM_SERIES


def test_occurrence_absent_on_both_sides_is_retired() -> None:
    decision = decide(None, None, occurrence_mapping=recorded())

    assert decision.action is SyncAction.IGNORE
    assert decision.reason is SyncReason.OCCURRENCE_RETIRED


def test_all_day_occurrence_under_an_excluding_rule_is_cancelled() -> None:
    timed_only = replace(
        rule(), transformation=TransformationPolicy(all_day=AllDaySyncPolicy.EXCLUDE)
    )

    decision = decide(occurrence(SOURCE, 1, all_day=True), busy_instance(), sync_rule=timed_only)

    assert decision.action is SyncAction.DELETE
    assert decision.reason is SyncReason.ALL_DAY_EXCLUDED_REMOVED


def test_occurrence_of_an_unsynchronized_series_is_ignored() -> None:
    decision = decide(occurrence(SOURCE, 1), None, series_mapping=None, destination_series=None)

    assert decision.action is SyncAction.IGNORE
    assert decision.reason is SyncReason.SERIES_NOT_SYNCHRONIZED


def test_occurrence_of_a_managed_series_is_ignored() -> None:
    managed = replace(SOURCE, managed_origin=ManagedOrigin(SyncRuleId("other"), SOURCE.reference))

    decision = decide(occurrence(managed, 1), None, source_series=managed, series_mapping=None)

    assert decision.reason is SyncReason.MANAGED_PROJECTION_SOURCE


def test_destination_series_owned_by_another_rule_blocks_the_write() -> None:
    foreign = replace(
        DESTINATION, managed_origin=ManagedOrigin(SyncRuleId("other"), SOURCE.reference)
    )

    decision = decide(occurrence(SOURCE, 1), busy_instance(), destination_series=foreign)

    assert decision.action is SyncAction.CONFLICT
    assert decision.reason is SyncReason.DESTINATION_OWNERSHIP_INCONSISTENT


def test_destination_occurrence_of_another_series_blocks_the_write() -> None:
    other_parent = replace(
        DESTINATION, reference=EventRef(rule().destination, EventId("unrelated"))
    )

    decision = decide(occurrence(SOURCE, 1), occurrence(other_parent, 1))

    assert decision.action is SyncAction.CONFLICT
    assert decision.reason is SyncReason.DESTINATION_IDENTITY_INCONSISTENT


def test_destination_occurrence_naming_another_source_blocks_the_write() -> None:
    wrong_origin = busy_instance(
        managed_origin=ManagedOrigin(rule().id, EventRef(rule().source, EventId("someone-else")))
    )

    decision = decide(occurrence(SOURCE, 1), wrong_origin)

    assert decision.action is SyncAction.CONFLICT
    assert decision.reason is SyncReason.DESTINATION_OWNERSHIP_INCONSISTENT


def test_occurrence_mapping_of_another_series_is_inconsistent() -> None:
    foreign = replace(recorded(), series_mapping_id=EventMappingId("other-series"))

    decision = decide(occurrence(SOURCE, 1), busy_instance(), occurrence_mapping=foreign)

    assert decision.action is SyncAction.CONFLICT
    assert decision.reason is SyncReason.MAPPING_INCONSISTENT


def test_missing_destination_occurrence_is_a_conflict_not_a_guess() -> None:
    decision = decide(occurrence(SOURCE, 1), None)

    assert decision.action is SyncAction.CONFLICT
    assert decision.reason is SyncReason.DESTINATION_OCCURRENCE_MISSING


@pytest.mark.parametrize(
    "destination_series",
    [None, replace(DESTINATION, status=EventStatus.CANCELLED, time=None)],
)
def test_occurrence_of_a_dormant_series_without_a_projection_is_skipped(
    destination_series: CalendarEvent | None,
) -> None:
    cancelled = occurrence(SOURCE, 1, status=EventStatus.CANCELLED)

    dormant = decide(
        cancelled, None, destination_series=destination_series, has_live_occurrences=False
    )
    live = decide(cancelled, None, destination_series=destination_series)

    assert (dormant.action, dormant.reason) == (
        SyncAction.IGNORE,
        SyncReason.SERIES_WITHOUT_OCCURRENCES,
    )
    # A series that still has live occurrences must have its projection repaired instead.
    assert (live.action, live.reason) == (
        SyncAction.CONFLICT,
        SyncReason.DESTINATION_OCCURRENCE_MISSING,
    )


def test_dormant_series_mapped_to_another_destination_series_is_still_a_conflict() -> None:
    other = replace(DESTINATION, reference=EventRef(rule().destination, EventId("unrelated")))

    decision = decide(
        occurrence(SOURCE, 1, status=EventStatus.CANCELLED),
        None,
        destination_series=other,
        has_live_occurrences=False,
    )

    assert decision.action is SyncAction.CONFLICT
    assert decision.reason is SyncReason.DESTINATION_OCCURRENCE_MISSING
