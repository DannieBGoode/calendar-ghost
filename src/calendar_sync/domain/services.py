from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime

from calendar_sync.domain.errors import DomainValidationError, OwnershipNotEstablished
from calendar_sync.domain.model import (
    AllDayRange,
    AllDaySyncPolicy,
    CalendarEvent,
    DriftKind,
    EventMapping,
    EventProjection,
    EventRef,
    EventStatus,
    NoProjectionExpected,
    OccurrenceCheck,
    OccurrenceMapping,
    OccurrenceStart,
    ProjectionContent,
    ProjectionFingerprint,
    ReconciliationConflict,
    ReconciliationDrift,
    ReconciliationReport,
    SyncAction,
    SyncDecision,
    SyncReason,
    SyncRule,
    TimedInterval,
)


class EventProjector:
    """Produces a destination representation without provider-specific objects."""

    def project(self, event: CalendarEvent, rule: SyncRule) -> EventProjection:
        if event.time is None:
            raise DomainValidationError("cancelled events cannot be projected")
        policy = rule.transformation
        if policy.content is ProjectionContent.BUSY_ONLY:
            title = policy.busy_title
            description = ""
            location = ""
        else:
            title = event.title
            description = event.description
            location = event.location

        return EventProjection(
            time=event.time,
            title=title,
            description=description,
            location=location,
            recurrence=event.recurrence,
        )


class ProjectionFingerprinter:
    """Creates a stable, non-reversible digest of normalized projection content."""

    def fingerprint(self, projection: EventProjection) -> ProjectionFingerprint:
        payload = {
            "time": self._serialize_time(
                projection.time, recurring=projection.recurrence is not None
            ),
            "title": projection.title,
            "description": projection.description,
            "location": projection.location,
            "recurrence": projection.recurrence.lines if projection.recurrence else None,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return ProjectionFingerprint(hashlib.sha256(encoded.encode()).hexdigest())

    @staticmethod
    def _serialize_time(value: TimedInterval | AllDayRange, *, recurring: bool) -> dict[str, str]:
        if isinstance(value, TimedInterval):
            serialized = {
                "kind": "timed",
                "starts_at": _serialize_temporal(value.starts_at.astimezone(UTC)),
                "ends_at": _serialize_temporal(value.ends_at.astimezone(UTC)),
            }
            # Only a series expands in its zone; single instants are zone-independent.
            if recurring and value.time_zone is not None:
                serialized["time_zone"] = value.time_zone
            return serialized
        return {
            "kind": "all_day",
            "starts_on": _serialize_temporal(value.starts_on),
            "ends_before": _serialize_temporal(value.ends_before),
        }


def _serialize_temporal(value: date | datetime) -> str:
    return value.isoformat()


class SyncDecisionService:
    """Selects an idempotent synchronization action under source authority."""

    def __init__(self, projector: EventProjector, fingerprinter: ProjectionFingerprinter) -> None:
        self._projector = projector
        self._fingerprinter = fingerprinter

    def decide(
        self,
        rule: SyncRule,
        source_event: CalendarEvent,
        mapping: EventMapping | None,
        actual_destination: CalendarEvent | None,
        *,
        window_start: datetime | None = None,
        has_live_occurrences: bool = True,
    ) -> SyncDecision:
        # In order: loop prevention, identity conflicts, removals, the sync window, projection.
        if source_event.reference.calendar != rule.source:
            return SyncDecision(SyncAction.IGNORE, SyncReason.OUTSIDE_SOURCE_CALENDAR)
        if source_event.managed_origin is not None:
            return SyncDecision(SyncAction.IGNORE, SyncReason.MANAGED_PROJECTION_SOURCE)
        if source_event.occurrence is not None:
            raise DomainValidationError("occurrence exceptions are decided through their series")
        conflict = _identity_conflict(rule, source_event, mapping, actual_destination)
        if conflict is not None:
            return SyncDecision(SyncAction.CONFLICT, conflict)
        removal = _removal(rule, source_event, mapping, actual_destination, has_live_occurrences)
        if removal is not None:
            return removal
        # Incremental feeds report changes to any event, however old; only mapped ones stay current.
        if mapping is None and window_start is not None and source_event.ended_before(window_start):
            return SyncDecision(SyncAction.IGNORE, SyncReason.BEFORE_SYNC_WINDOW)
        return self._projection_decision(rule, source_event, mapping, actual_destination)

    def _projection_decision(
        self,
        rule: SyncRule,
        source_event: CalendarEvent,
        mapping: EventMapping | None,
        actual_destination: CalendarEvent | None,
    ) -> SyncDecision:
        """Create a missing projection, or update one that differs from the source's."""
        projection = self._projector.project(source_event, rule)
        if mapping is None:
            return SyncDecision(SyncAction.CREATE, SyncReason.SOURCE_CREATED, projection)
        if actual_destination is None:
            return SyncDecision(SyncAction.CREATE, SyncReason.PROJECTION_MISSING, projection)

        expected = self._fingerprinter.fingerprint(projection)
        actual = self._fingerprinter.fingerprint(self.as_projection(actual_destination))
        if expected == actual:
            # A new source revision is evidence to check, not a reason to write (ADR 0017).
            return SyncDecision(SyncAction.IGNORE, SyncReason.PROJECTION_CURRENT, projection)
        # Only a projection the source now calls for differently is a source change; a revision
        # whose projection is the one last written, such as a reply to an invitation, left the
        # destination edit to repair.
        source_changed = (
            mapping.source_revision != source_event.revision
            and expected != mapping.projection_fingerprint
        )
        reason = (
            SyncReason.SOURCE_CHANGED if source_changed else SyncReason.DESTINATION_DRIFT_REPAIRED
        )
        return SyncDecision(SyncAction.UPDATE, reason, projection)

    # Ordered decision table; each guard returns a reason. Its inputs are the evidence it weighs.
    def decide_occurrence(  # noqa: C901, PLR0912, PLR0913
        self,
        rule: SyncRule,
        source_series: CalendarEvent,
        series_mapping: EventMapping | None,
        original_start: OccurrenceStart,
        source_occurrence: CalendarEvent | None,
        occurrence_mapping: OccurrenceMapping | None,
        destination_series: CalendarEvent | None,
        destination_occurrence: CalendarEvent | None,
        *,
        destination_reported: bool = False,
        has_live_occurrences: bool = True,
    ) -> SyncDecision:
        """Decide one occurrence of a mapped series; `None` means no such occurrence exists."""
        if source_series.reference.calendar != rule.source:
            return SyncDecision(SyncAction.IGNORE, SyncReason.OUTSIDE_SOURCE_CALENDAR)
        if source_series.managed_origin is not None:
            return SyncDecision(SyncAction.IGNORE, SyncReason.MANAGED_PROJECTION_SOURCE)
        if series_mapping is None or source_series.status is EventStatus.CANCELLED:
            return SyncDecision(SyncAction.IGNORE, SyncReason.SERIES_NOT_SYNCHRONIZED)
        if (
            not series_mapping.belongs_to(rule)
            or series_mapping.source != source_series.reference
            or (
                occurrence_mapping is not None
                and (
                    occurrence_mapping.series_mapping_id != series_mapping.id
                    or occurrence_mapping.original_start != original_start
                )
            )
            or (
                source_occurrence is not None
                and not _is_occurrence_of(
                    source_occurrence, source_series.reference, original_start
                )
            )
        ):
            return SyncDecision(SyncAction.CONFLICT, SyncReason.MAPPING_INCONSISTENT)
        if (
            destination_series is None
            or destination_series.status is EventStatus.CANCELLED
            or destination_series.reference != series_mapping.destination
        ):
            # A dormant series has no projection until one of its occurrences is restored.
            if not has_live_occurrences and (
                destination_series is None or destination_series.status is EventStatus.CANCELLED
            ):
                return SyncDecision(SyncAction.IGNORE, SyncReason.SERIES_WITHOUT_OCCURRENCES)
            return SyncDecision(SyncAction.CONFLICT, SyncReason.DESTINATION_OCCURRENCE_MISSING)
        origin = destination_series.managed_origin
        if origin is None or not origin.owns(rule, source_series.reference):
            return SyncDecision(SyncAction.CONFLICT, SyncReason.DESTINATION_OWNERSHIP_INCONSISTENT)
        if destination_occurrence is not None:
            if not _is_occurrence_of(
                destination_occurrence, series_mapping.destination, original_start
            ):
                return SyncDecision(
                    SyncAction.CONFLICT, SyncReason.DESTINATION_IDENTITY_INCONSISTENT
                )
            # Google omits metadata on cancelled instances; the parent series proves ownership.
            occurrence_origin = destination_occurrence.managed_origin
            if occurrence_origin is not None and not occurrence_origin.owns(
                rule, source_series.reference
            ):
                return SyncDecision(
                    SyncAction.CONFLICT, SyncReason.DESTINATION_OWNERSHIP_INCONSISTENT
                )

        destination_absent = (
            destination_occurrence is None or destination_occurrence.status is EventStatus.CANCELLED
        )
        if source_occurrence is None:
            if destination_absent:
                return SyncDecision(SyncAction.IGNORE, SyncReason.OCCURRENCE_RETIRED)
            return SyncDecision(SyncAction.DELETE, SyncReason.OCCURRENCE_REMOVED_FROM_SERIES)
        excluded_all_day = (
            source_occurrence.is_all_day and rule.transformation.all_day is AllDaySyncPolicy.EXCLUDE
        )
        if source_occurrence.status is EventStatus.CANCELLED or excluded_all_day:
            if destination_absent:
                return SyncDecision(SyncAction.IGNORE, SyncReason.OCCURRENCE_ALREADY_CANCELLED)
            reason = (
                SyncReason.OCCURRENCE_CANCELLED
                if source_occurrence.status is EventStatus.CANCELLED
                else SyncReason.ALL_DAY_EXCLUDED_REMOVED
            )
            return SyncDecision(SyncAction.DELETE, reason)
        if destination_occurrence is None:
            return SyncDecision(SyncAction.CONFLICT, SyncReason.DESTINATION_OCCURRENCE_MISSING)

        projection = self._projector.project(source_occurrence, rule)
        expected = self._fingerprinter.fingerprint(projection)
        # As for a series, only a projection the source now calls for differently than the one
        # last written is a source change (ADR 0017).
        source_changed = not destination_reported and (
            occurrence_mapping is None
            or (
                occurrence_mapping.source_revision != source_occurrence.revision
                and occurrence_mapping.projection_fingerprint != expected
            )
        )
        changed = (
            SyncReason.OCCURRENCE_CHANGED
            if source_changed
            else SyncReason.OCCURRENCE_DRIFT_REPAIRED
        )
        if destination_occurrence.status is EventStatus.CANCELLED:
            return SyncDecision(SyncAction.UPDATE, changed, projection)
        actual = self._fingerprinter.fingerprint(self.as_projection(destination_occurrence))
        if expected == actual:
            return SyncDecision(SyncAction.IGNORE, SyncReason.OCCURRENCE_CURRENT, projection)
        return SyncDecision(SyncAction.UPDATE, changed, projection)

    @staticmethod
    def require_delete_ownership(mapping: EventMapping | None) -> EventMapping:
        if mapping is None:
            raise OwnershipNotEstablished("destination deletion requires an event mapping")
        return mapping

    @staticmethod
    def as_projection(event: CalendarEvent) -> EventProjection:
        if event.time is None:
            raise DomainValidationError("cancelled destination events cannot be projected")
        return EventProjection(
            time=event.time,
            title=event.title,
            description=event.description,
            location=event.location,
            recurrence=event.recurrence,
        )


def _identity_conflict(
    rule: SyncRule,
    source_event: CalendarEvent,
    mapping: EventMapping | None,
    actual_destination: CalendarEvent | None,
) -> SyncReason | None:
    """Why the mapping or its destination cannot prove this rule owns the projection, if so."""
    if mapping is None:
        return None
    if not mapping.belongs_to(rule) or mapping.source != source_event.reference:
        return SyncReason.MAPPING_INCONSISTENT
    if actual_destination is None:
        return None
    if actual_destination.reference != mapping.destination:
        return SyncReason.DESTINATION_IDENTITY_INCONSISTENT
    origin = actual_destination.managed_origin
    if origin is None or not origin.owns(rule, source_event.reference):
        return SyncReason.DESTINATION_OWNERSHIP_INCONSISTENT
    return None


def _removal(
    rule: SyncRule,
    source_event: CalendarEvent,
    mapping: EventMapping | None,
    actual_destination: CalendarEvent | None,
    has_live_occurrences: bool,
) -> SyncDecision | None:
    """Remove, or never create, the projection of a source the rule no longer projects."""
    if source_event.status is EventStatus.CANCELLED:
        if mapping is None:
            return SyncDecision(SyncAction.IGNORE, SyncReason.CANCELLED_WITHOUT_PROJECTION)
        return SyncDecision(SyncAction.DELETE, SyncReason.SOURCE_CANCELLED)
    if source_event.is_all_day and rule.transformation.all_day is AllDaySyncPolicy.EXCLUDE:
        if mapping is None:
            return SyncDecision(SyncAction.IGNORE, SyncReason.ALL_DAY_EXCLUDED)
        return SyncDecision(SyncAction.DELETE, SyncReason.ALL_DAY_EXCLUDED_REMOVED)
    # A projected series with no live occurrence is cancelled by the provider, so none is
    # created. A mapping stays dormant with its cancelled occurrences, so restoring one
    # occurrence later cannot resurrect the others; only a live projection is removed.
    if source_event.recurrence is not None and not has_live_occurrences:
        if actual_destination is None:
            return SyncDecision(SyncAction.IGNORE, SyncReason.SERIES_WITHOUT_OCCURRENCES)
        return SyncDecision(SyncAction.DELETE, SyncReason.SERIES_WITHOUT_OCCURRENCES_REMOVED)
    return None


def _is_occurrence_of(event: CalendarEvent, series: EventRef, start: OccurrenceStart) -> bool:
    return (
        event.occurrence is not None
        and event.reference.calendar == series.calendar
        and event.occurrence.series_event_id == series.event_id
        and event.occurrence.original_start == start
    )


class ReconciliationService:
    """Proves mapped provider state against freshly derived expected projections."""

    def __init__(self, fingerprinter: ProjectionFingerprinter) -> None:
        self._fingerprinter = fingerprinter

    def reconcile(
        self,
        rule: SyncRule,
        mappings: Iterable[EventMapping],
        expected_by_source: Mapping[EventRef, EventProjection | NoProjectionExpected],
        actual_by_destination: Mapping[EventRef, CalendarEvent],
        occurrences: Iterable[OccurrenceCheck] = (),
    ) -> ReconciliationReport:
        """Compare each mapping's expected and actual state; a source absent from
        `expected_by_source` could not be read."""
        mapping_list = tuple(mappings)
        findings: list[ReconciliationDrift | ReconciliationConflict | None] = []
        managed_destinations: set[EventRef] = set()

        for mapping in mapping_list:
            if mapping.belongs_to(rule):
                managed_destinations.add(mapping.destination)
            findings.append(
                self._mapping_finding(
                    rule,
                    mapping,
                    expected_by_source.get(mapping.source),
                    actual_by_destination.get(mapping.destination),
                )
            )

        checked_occurrences: set[tuple[EventRef, OccurrenceStart]] = set()
        for check in occurrences:
            checked_occurrences.add((check.destination_series, check.mapping.original_start))
            findings.extend(self._occurrence_drift(check))

        findings.extend(
            _unmapped_finding(
                destination,
                actual_by_destination[destination],
                managed_destinations,
                checked_occurrences,
            )
            for destination in actual_by_destination.keys() - managed_destinations
        )

        return ReconciliationReport(
            rule.id,
            len(mapping_list),
            tuple(item for item in findings if isinstance(item, ReconciliationDrift)),
            tuple(item for item in findings if isinstance(item, ReconciliationConflict)),
        )

    def _mapping_finding(
        self,
        rule: SyncRule,
        mapping: EventMapping,
        expected: EventProjection | NoProjectionExpected | None,
        actual: CalendarEvent | None,
    ) -> ReconciliationDrift | ReconciliationConflict | None:
        if not mapping.belongs_to(rule):
            return ReconciliationConflict(
                SyncReason.MAPPING_INCONSISTENT,
                mapping.source,
                mapping.destination,
                "mapping is outside this directional relationship",
            )
        if expected is None:
            return ReconciliationConflict(
                SyncReason.SOURCE_UNVERIFIABLE,
                mapping.source,
                mapping.destination,
                "source event could not be read for this mapping",
            )
        if expected is NoProjectionExpected.MANAGED_SOURCE:
            return ReconciliationConflict(
                SyncReason.MAPPING_INCONSISTENT,
                mapping.source,
                mapping.destination,
                "mapped source event is itself a managed projection",
            )
        if expected is NoProjectionExpected.INELIGIBLE:
            if actual is None:
                return None
            return ReconciliationDrift(
                DriftKind.UNEXPECTED,
                mapping.source,
                mapping.destination,
                "managed projection remains for a cancelled or excluded source",
            )
        if actual is None:
            return ReconciliationDrift(
                DriftKind.MISSING,
                mapping.source,
                mapping.destination,
                "managed projection is missing",
            )
        if self._fingerprinter.fingerprint(expected) != self._fingerprinter.fingerprint(
            SyncDecisionService.as_projection(actual)
        ):
            return ReconciliationDrift(
                DriftKind.INCORRECT_PROJECTION,
                mapping.source,
                mapping.destination,
                "managed projection differs from source authority",
            )
        return None

    def _occurrence_drift(self, check: OccurrenceCheck) -> list[ReconciliationDrift]:
        actual = check.actual
        if actual is None or actual.status is not EventStatus.CONFIRMED:
            if check.expected is None:
                return []
            kind, detail = DriftKind.MISSING, "managed occurrence is missing"
        elif check.expected is None:
            kind, detail = DriftKind.INCORRECT_PROJECTION, "managed occurrence should be cancelled"
        elif self._fingerprinter.fingerprint(check.expected) == self._fingerprinter.fingerprint(
            SyncDecisionService.as_projection(actual)
        ):
            return []
        else:
            kind, detail = (
                DriftKind.INCORRECT_PROJECTION,
                "managed occurrence differs from source authority",
            )
        return [ReconciliationDrift(kind, check.mapping.source, check.mapping.destination, detail)]


def _unmapped_finding(
    destination: EventRef,
    event: CalendarEvent,
    managed_destinations: set[EventRef],
    checked_occurrences: set[tuple[EventRef, OccurrenceStart]],
) -> ReconciliationDrift | ReconciliationConflict | None:
    """A managed provider event no mapping accounts for, unless a checked occurrence is it."""
    parent = event.occurrence
    if parent is not None:
        series_ref = EventRef(destination.calendar, parent.series_event_id)
        if series_ref in managed_destinations:
            if (series_ref, parent.original_start) in checked_occurrences:
                return None
            return ReconciliationDrift(
                DriftKind.INCORRECT_PROJECTION,
                None,
                destination,
                "managed occurrence has no occurrence mapping",
            )
    # No mapping proves ownership, so nothing may change or delete it.
    return ReconciliationConflict(
        SyncReason.PROJECTION_UNMAPPED,
        event.managed_origin.source if event.managed_origin else None,
        destination,
        "managed provider event has no mapping",
    )
