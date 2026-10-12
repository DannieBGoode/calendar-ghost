from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime

from calendar_sync.domain.errors import DomainValidationError, OwnershipNotEstablished
from calendar_sync.domain.model import (
    AllDayRange,
    CalendarEvent,
    DriftKind,
    EventMapping,
    EventProjection,
    EventRef,
    EventStatus,
    NoProjectionExpected,
    OccurrenceCheck,
    OccurrenceSituation,
    OccurrenceStart,
    ProjectionContent,
    ProjectionFingerprint,
    ReconciliationConflict,
    ReconciliationDrift,
    ReconciliationReport,
    Recurrence,
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
        if policy.marks_tentative(event):
            title = _tentative_title(title, policy.content)

        return EventProjection(
            time=event.time,
            title=title,
            description=description,
            location=location,
            recurrence=event.recurrence,
        )


def _tentative_title(title: str, content: ProjectionContent) -> str:
    """'Busy (tentative)' for a Busy-Only Projection; 'Maybe: Standup' for a Details Projection."""
    if content is ProjectionContent.BUSY_ONLY:
        return f"{title} (tentative)"
    return f"Maybe: {title}" if title else "Maybe"


def _canonical_lines(recurrence: Recurrence | None) -> list[str] | None:
    """Recurrence lines with each rule's parts in one order. RFC 5545 lets a rule list its parts
    in any order, and a provider may store them in its own, such as `UNTIL` before `BYDAY`.
    The rule repeats the same either way, so the order is no difference to repair."""
    if recurrence is None:
        return None
    return [_canonical_line(line) for line in recurrence.lines]


def _canonical_line(line: str) -> str:
    name, separator, value = line.partition(":")
    if not separator or name.upper() not in {"RRULE", "EXRULE"}:
        return line
    parts = sorted(value.split(";"), key=lambda part: (not part.upper().startswith("FREQ="), part))
    return f"{name}:{';'.join(parts)}"


class ProjectionFingerprinter:
    """Creates a stable, non-reversible digest of normalized projection content."""

    def fingerprint(self, projection: EventProjection) -> ProjectionFingerprint:
        return self._digest(projection, _canonical_lines(projection.recurrence))

    def matches(self, projection: EventProjection, stored: ProjectionFingerprint | None) -> bool:
        """Whether `stored` was taken of this projection. A fingerprint stored before rules were
        compared by their parts hashed the lines as written, and is kept until the next write."""
        if stored is None:
            return False
        if self.fingerprint(projection) == stored:
            return True
        written = list(projection.recurrence.lines) if projection.recurrence else None
        return projection.recurrence is not None and self._digest(projection, written) == stored

    def _digest(
        self, projection: EventProjection, recurrence: list[str] | None
    ) -> ProjectionFingerprint:
        payload = {
            "time": self._serialize_time(
                projection.time, recurring=projection.recurrence is not None
            ),
            "title": projection.title,
            "description": projection.description,
            "location": projection.location,
            "recurrence": recurrence,
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
        # whose projection is the one last written, such as another guest's reply, left the
        # destination edit to repair.
        if mapping.source_revision != source_event.revision and not self._fingerprinter.matches(
            projection, mapping.projection_fingerprint
        ):
            reason = SyncReason.SOURCE_CHANGED
        elif rule.reprojection_required and self._fingerprinter.matches(
            self.as_projection(actual_destination), mapping.projection_fingerprint
        ):
            # The destination is as last written, so the rule's changed policy calls for this.
            reason = SyncReason.POLICY_APPLIED
        else:
            reason = SyncReason.DESTINATION_DRIFT_REPAIRED
        return SyncDecision(SyncAction.UPDATE, reason, projection)

    def decide_occurrence(self, rule: SyncRule, situation: OccurrenceSituation) -> SyncDecision:
        """Decide one occurrence of a mapped series from the evidence in `situation`."""
        # In order: loop prevention, identity conflicts, removals, projection.
        series_mapping = situation.series_mapping
        ignored = _unsynchronized_series(rule, situation.source_series)
        if ignored is not None:
            return ignored
        if series_mapping is None:
            return SyncDecision(SyncAction.IGNORE, SyncReason.SERIES_NOT_SYNCHRONIZED)
        unproven = _occurrence_identity_decision(rule, situation, series_mapping)
        if unproven is not None:
            return unproven
        source, destination = situation.source_occurrence, situation.destination_occurrence
        if source is None:
            if _is_absent(destination):
                return SyncDecision(SyncAction.IGNORE, SyncReason.OCCURRENCE_RETIRED)
            return SyncDecision(SyncAction.DELETE, SyncReason.OCCURRENCE_REMOVED_FROM_SERIES)
        removal = _occurrence_removal(rule, source, destination)
        if removal is not None:
            return removal
        if destination is None:
            return SyncDecision(SyncAction.CONFLICT, SyncReason.DESTINATION_OCCURRENCE_MISSING)
        return self._occurrence_projection_decision(rule, situation, source, destination)

    def _occurrence_projection_decision(
        self,
        rule: SyncRule,
        situation: OccurrenceSituation,
        source: CalendarEvent,
        destination: CalendarEvent,
    ) -> SyncDecision:
        """Restore or update an occurrence whose projection differs from the source's."""
        projection = self._projector.project(source, rule)
        expected = self._fingerprinter.fingerprint(projection)
        recorded = situation.occurrence_mapping
        # As for a series, only a projection the source now calls for differently than the one
        # last written is a source change (ADR 0017).
        source_changed = not situation.destination_reported and (
            recorded is None
            or (
                recorded.source_revision != source.revision
                and recorded.projection_fingerprint != expected
            )
        )
        changed = (
            SyncReason.OCCURRENCE_CHANGED
            if source_changed
            else SyncReason.OCCURRENCE_DRIFT_REPAIRED
        )
        if destination.status is EventStatus.CANCELLED:
            return SyncDecision(SyncAction.UPDATE, changed, projection)
        actual = self._fingerprinter.fingerprint(self.as_projection(destination))
        if expected == actual:
            return SyncDecision(SyncAction.IGNORE, SyncReason.OCCURRENCE_CURRENT, projection)
        if (
            rule.reprojection_required
            and not source_changed
            and recorded is not None
            and recorded.projection_fingerprint == actual
        ):
            return SyncDecision(SyncAction.UPDATE, SyncReason.POLICY_APPLIED, projection)
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
    exclusion = rule.transformation.exclusion(source_event)
    if exclusion is not None:
        if mapping is None:
            return SyncDecision(SyncAction.IGNORE, exclusion.skip_reason)
        return SyncDecision(SyncAction.DELETE, exclusion.removal_reason)
    # A projected series with no live occurrence is cancelled by the provider, so none is
    # created. A mapping stays dormant with its cancelled occurrences, so restoring one
    # occurrence later cannot resurrect the others; only a live projection is removed.
    if source_event.recurrence is not None and not has_live_occurrences:
        if actual_destination is None:
            return SyncDecision(SyncAction.IGNORE, SyncReason.SERIES_WITHOUT_OCCURRENCES)
        return SyncDecision(SyncAction.DELETE, SyncReason.SERIES_WITHOUT_OCCURRENCES_REMOVED)
    return None


def _unsynchronized_series(rule: SyncRule, source_series: CalendarEvent) -> SyncDecision | None:
    """Ignore occurrences of a series this rule does not synchronize."""
    if source_series.reference.calendar != rule.source:
        return SyncDecision(SyncAction.IGNORE, SyncReason.OUTSIDE_SOURCE_CALENDAR)
    if source_series.managed_origin is not None:
        return SyncDecision(SyncAction.IGNORE, SyncReason.MANAGED_PROJECTION_SOURCE)
    if source_series.status is EventStatus.CANCELLED:
        return SyncDecision(SyncAction.IGNORE, SyncReason.SERIES_NOT_SYNCHRONIZED)
    return None


def _occurrence_identity_decision(
    rule: SyncRule, situation: OccurrenceSituation, series_mapping: EventMapping
) -> SyncDecision | None:
    """Stop when the mappings or the destination cannot prove this rule owns the occurrence."""
    if _occurrence_mappings_inconsistent(rule, situation, series_mapping):
        return SyncDecision(SyncAction.CONFLICT, SyncReason.MAPPING_INCONSISTENT)
    unproven = _destination_series_decision(rule, situation, series_mapping)
    if unproven is not None:
        return unproven
    conflict = _destination_occurrence_conflict(rule, situation, series_mapping)
    return SyncDecision(SyncAction.CONFLICT, conflict) if conflict is not None else None


def _occurrence_mappings_inconsistent(
    rule: SyncRule, situation: OccurrenceSituation, series_mapping: EventMapping
) -> bool:
    """The Series Mapping or Occurrence Mapping names another rule, series, or occurrence."""
    source_series, start = situation.source_series, situation.original_start
    recorded, source = situation.occurrence_mapping, situation.source_occurrence
    return (
        not series_mapping.belongs_to(rule)
        or series_mapping.source != source_series.reference
        or (
            recorded is not None
            and (
                recorded.series_mapping_id != series_mapping.id or recorded.original_start != start
            )
        )
        or (source is not None and not _is_occurrence_of(source, source_series.reference, start))
    )


def _destination_series_decision(
    rule: SyncRule, situation: OccurrenceSituation, series_mapping: EventMapping
) -> SyncDecision | None:
    """Stop when the destination series is missing, dormant, or not this rule's projection."""
    destination_series = situation.destination_series
    if (
        destination_series is None
        or destination_series.status is EventStatus.CANCELLED
        or destination_series.reference != series_mapping.destination
    ):
        # A dormant series has no projection until one of its occurrences is restored.
        if not situation.has_live_occurrences and _is_absent(destination_series):
            return SyncDecision(SyncAction.IGNORE, SyncReason.SERIES_WITHOUT_OCCURRENCES)
        return SyncDecision(SyncAction.CONFLICT, SyncReason.DESTINATION_OCCURRENCE_MISSING)
    origin = destination_series.managed_origin
    if origin is None or not origin.owns(rule, situation.source_series.reference):
        return SyncDecision(SyncAction.CONFLICT, SyncReason.DESTINATION_OWNERSHIP_INCONSISTENT)
    return None


def _destination_occurrence_conflict(
    rule: SyncRule, situation: OccurrenceSituation, series_mapping: EventMapping
) -> SyncReason | None:
    """Why the destination occurrence is not this rule's projection of it, if so."""
    destination = situation.destination_occurrence
    if destination is None:
        return None
    if not _is_occurrence_of(destination, series_mapping.destination, situation.original_start):
        return SyncReason.DESTINATION_IDENTITY_INCONSISTENT
    # A provider may omit metadata on cancelled instances; the parent series proves it.
    origin = destination.managed_origin
    if origin is not None and not origin.owns(rule, situation.source_series.reference):
        return SyncReason.DESTINATION_OWNERSHIP_INCONSISTENT
    return None


def _occurrence_removal(
    rule: SyncRule, source: CalendarEvent, destination: CalendarEvent | None
) -> SyncDecision | None:
    """Cancel, or leave cancelled, an occurrence the source cancelled or the rule excludes."""
    cancelled = source.status is EventStatus.CANCELLED
    exclusion = None if cancelled else rule.transformation.exclusion(source)
    if not cancelled and exclusion is None:
        return None
    if _is_absent(destination):
        return SyncDecision(SyncAction.IGNORE, SyncReason.OCCURRENCE_ALREADY_CANCELLED)
    reason = exclusion.removal_reason if exclusion is not None else SyncReason.OCCURRENCE_CANCELLED
    return SyncDecision(SyncAction.DELETE, reason)


def _is_absent(event: CalendarEvent | None) -> bool:
    """No such event exists, or the provider keeps it only as a cancellation."""
    return event is None or event.status is EventStatus.CANCELLED


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
