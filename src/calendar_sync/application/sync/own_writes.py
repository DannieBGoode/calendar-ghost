from __future__ import annotations

from calendar_sync.application.sync.sync_run import SyncRunContext
from calendar_sync.domain.model import CalendarEvent, EventMapping, EventStatus, OccurrenceState
from calendar_sync.domain.services import ProjectionFingerprinter, SyncDecisionService


def is_own_write(
    run: SyncRunContext,
    fingerprinter: ProjectionFingerprinter,
    mapping: EventMapping,
    destination: CalendarEvent,
) -> bool:
    """A reported projection still exactly as this rule last wrote it has not drifted.

    The incremental feed reports this rule's own writes back on the next run. Source changes
    arrive through the source feed, so an unedited projection needs no source read to confirm
    it. Full runs keep verifying every reported projection against its source.
    """
    origin = destination.managed_origin
    return (
        run.incremental
        and destination.status is EventStatus.CONFIRMED
        and origin is not None
        and origin.owns(run.rule, mapping.source)
        and fingerprinter.matches(
            SyncDecisionService.as_projection(destination), mapping.projection_fingerprint
        )
    )


def is_own_occurrence_write(
    run: SyncRunContext,
    fingerprinter: ProjectionFingerprinter,
    series_mapping: EventMapping,
    destination: CalendarEvent,
) -> bool:
    """An occurrence still as this rule last wrote or cancelled it has not drifted."""
    identity = destination.occurrence
    assert identity is not None
    recorded = run.uow.occurrences.get(series_mapping.id, identity.original_start)
    if not run.incremental or recorded is None or recorded.destination != destination.reference:
        return False
    if recorded.state is OccurrenceState.CANCELLED:
        return destination.status is EventStatus.CANCELLED
    origin = destination.managed_origin
    return (
        destination.status is EventStatus.CONFIRMED
        and origin is not None
        and origin.owns(run.rule, series_mapping.source)
        and fingerprinter.matches(
            SyncDecisionService.as_projection(destination), recorded.projection_fingerprint
        )
    )
