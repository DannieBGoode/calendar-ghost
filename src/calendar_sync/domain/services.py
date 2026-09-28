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
    ManagedOrigin,
    OccurrenceCheck,
    OccurrenceMapping,
    OccurrenceStart,
    PrivacyPolicy,
    ProjectionFingerprint,
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
        if policy.privacy is PrivacyPolicy.BUSY_ONLY:
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
    ) -> SyncDecision:
        if source_event.reference.calendar != rule.source:
            return SyncDecision(SyncAction.IGNORE, SyncReason.OUTSIDE_SOURCE_CALENDAR)
        if source_event.managed_origin is not None:
            return SyncDecision(SyncAction.IGNORE, SyncReason.MANAGED_PROJECTION_SOURCE)
        if source_event.occurrence is not None:
            raise DomainValidationError("occurrence exceptions are decided through their series")

        if mapping is not None and (
            mapping.rule_id != rule.id
            or mapping.source != source_event.reference
            or mapping.destination.calendar != rule.destination
        ):
            return SyncDecision(SyncAction.CONFLICT, SyncReason.MAPPING_INCONSISTENT)
        if mapping is not None and actual_destination is not None:
            if actual_destination.reference != mapping.destination:
                return SyncDecision(
                    SyncAction.CONFLICT, SyncReason.DESTINATION_IDENTITY_INCONSISTENT
                )
            origin = actual_destination.managed_origin
            if (
                origin is None
                or origin.rule_id != rule.id
                or origin.source != source_event.reference
            ):
                return SyncDecision(
                    SyncAction.CONFLICT, SyncReason.DESTINATION_OWNERSHIP_INCONSISTENT
                )

        excluded_all_day = (
            source_event.is_all_day and rule.transformation.all_day is AllDaySyncPolicy.EXCLUDE
        )
        if source_event.status is EventStatus.CANCELLED:
            if mapping is None:
                return SyncDecision(SyncAction.IGNORE, SyncReason.CANCELLED_WITHOUT_PROJECTION)
            return SyncDecision(SyncAction.DELETE, SyncReason.SOURCE_CANCELLED)
        if excluded_all_day:
            if mapping is None:
                return SyncDecision(SyncAction.IGNORE, SyncReason.ALL_DAY_EXCLUDED)
            return SyncDecision(SyncAction.DELETE, SyncReason.ALL_DAY_EXCLUDED_REMOVED)

        projection = self._projector.project(source_event, rule)
        if mapping is None:
            return SyncDecision(SyncAction.CREATE, SyncReason.SOURCE_CREATED, projection)
        if actual_destination is None:
            return SyncDecision(SyncAction.CREATE, SyncReason.PROJECTION_MISSING, projection)

        expected = self._fingerprinter.fingerprint(projection)
        actual = self._fingerprinter.fingerprint(self._as_projection(actual_destination))
        source_unchanged = mapping.source_revision == source_event.revision
        if source_unchanged and expected == actual:
            return SyncDecision(SyncAction.IGNORE, SyncReason.PROJECTION_CURRENT)
        reason = (
            SyncReason.DESTINATION_DRIFT_REPAIRED if source_unchanged else SyncReason.SOURCE_CHANGED
        )
        return SyncDecision(SyncAction.UPDATE, reason, projection)

    def decide_occurrence(
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
    ) -> SyncDecision:
        """Decide one occurrence of a mapped series; `None` means no such occurrence exists."""
        if source_series.reference.calendar != rule.source:
            return SyncDecision(SyncAction.IGNORE, SyncReason.OUTSIDE_SOURCE_CALENDAR)
        if source_series.managed_origin is not None:
            return SyncDecision(SyncAction.IGNORE, SyncReason.MANAGED_PROJECTION_SOURCE)
        if series_mapping is None or source_series.status is EventStatus.CANCELLED:
            return SyncDecision(SyncAction.IGNORE, SyncReason.SERIES_NOT_SYNCHRONIZED)
        if (
            series_mapping.rule_id != rule.id
            or series_mapping.source != source_series.reference
            or series_mapping.destination.calendar != rule.destination
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
            return SyncDecision(SyncAction.CONFLICT, SyncReason.DESTINATION_OCCURRENCE_MISSING)
        if not _owned_by(destination_series.managed_origin, rule, source_series.reference):
            return SyncDecision(SyncAction.CONFLICT, SyncReason.DESTINATION_OWNERSHIP_INCONSISTENT)
        if destination_occurrence is not None:
            if not _is_occurrence_of(
                destination_occurrence, series_mapping.destination, original_start
            ):
                return SyncDecision(
                    SyncAction.CONFLICT, SyncReason.DESTINATION_IDENTITY_INCONSISTENT
                )
            # Google omits metadata on cancelled instances; the parent series proves ownership.
            if destination_occurrence.managed_origin is not None and not _owned_by(
                destination_occurrence.managed_origin, rule, source_series.reference
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
        source_unchanged = (
            occurrence_mapping is not None
            and occurrence_mapping.source_revision == source_occurrence.revision
        )
        changed = (
            SyncReason.OCCURRENCE_DRIFT_REPAIRED
            if source_unchanged or destination_reported
            else SyncReason.OCCURRENCE_CHANGED
        )
        if destination_occurrence.status is EventStatus.CANCELLED:
            return SyncDecision(SyncAction.UPDATE, changed, projection)
        expected = self._fingerprinter.fingerprint(projection)
        actual = self._fingerprinter.fingerprint(self._as_projection(destination_occurrence))
        if expected == actual and (occurrence_mapping is None or source_unchanged):
            return SyncDecision(SyncAction.IGNORE, SyncReason.OCCURRENCE_CURRENT, projection)
        return SyncDecision(SyncAction.UPDATE, changed, projection)

    @staticmethod
    def require_delete_ownership(mapping: EventMapping | None) -> EventMapping:
        if mapping is None:
            raise OwnershipNotEstablished("destination deletion requires an event mapping")
        return mapping

    @staticmethod
    def _as_projection(event: CalendarEvent) -> EventProjection:
        if event.time is None:
            raise DomainValidationError("cancelled destination events cannot be projected")
        return EventProjection(
            time=event.time,
            title=event.title,
            description=event.description,
            location=event.location,
            recurrence=event.recurrence,
        )


def _is_occurrence_of(event: CalendarEvent, series: EventRef, start: OccurrenceStart) -> bool:
    return (
        event.occurrence is not None
        and event.reference.calendar == series.calendar
        and event.occurrence.series_event_id == series.event_id
        and event.occurrence.original_start == start
    )


def _owned_by(origin: ManagedOrigin | None, rule: SyncRule, source: EventRef) -> bool:
    return origin is not None and origin.rule_id == rule.id and origin.source == source


class ReconciliationService:
    """Proves mapped provider state against freshly derived expected projections."""

    def __init__(self, fingerprinter: ProjectionFingerprinter) -> None:
        self._fingerprinter = fingerprinter

    def reconcile(
        self,
        rule: SyncRule,
        mappings: Iterable[EventMapping],
        expected_by_source: Mapping[EventRef, EventProjection],
        actual_by_destination: Mapping[EventRef, CalendarEvent],
        occurrences: Iterable[OccurrenceCheck] = (),
    ) -> ReconciliationReport:
        mapping_list = tuple(mappings)
        drift: list[ReconciliationDrift] = []
        managed_destinations: set[EventRef] = set()

        for mapping in mapping_list:
            if mapping.rule_id != rule.id or mapping.destination.calendar != rule.destination:
                drift.append(
                    ReconciliationDrift(
                        DriftKind.MAPPING_INCONSISTENCY,
                        mapping.source,
                        mapping.destination,
                        "mapping is outside this directional relationship",
                    )
                )
                continue

            managed_destinations.add(mapping.destination)
            expected = expected_by_source.get(mapping.source)
            actual = actual_by_destination.get(mapping.destination)
            if expected is None:
                drift.append(
                    ReconciliationDrift(
                        DriftKind.MAPPING_INCONSISTENCY,
                        mapping.source,
                        mapping.destination,
                        "source event is unavailable for this mapping",
                    )
                )
            elif actual is None:
                drift.append(
                    ReconciliationDrift(
                        DriftKind.MISSING,
                        mapping.source,
                        mapping.destination,
                        "managed projection is missing",
                    )
                )
            elif self._fingerprinter.fingerprint(expected) != self._fingerprinter.fingerprint(
                SyncDecisionService._as_projection(actual)
            ):
                drift.append(
                    ReconciliationDrift(
                        DriftKind.INCORRECT_PROJECTION,
                        mapping.source,
                        mapping.destination,
                        "managed projection differs from source authority",
                    )
                )

        checked_occurrences: set[tuple[EventRef, OccurrenceStart]] = set()
        for check in occurrences:
            checked_occurrences.add((check.destination_series, check.mapping.original_start))
            drift.extend(self._occurrence_drift(check))

        for destination in actual_by_destination.keys() - managed_destinations:
            parent = actual_by_destination[destination].occurrence
            if parent is not None:
                series_ref = EventRef(destination.calendar, parent.series_event_id)
                if series_ref in managed_destinations:
                    if (series_ref, parent.original_start) not in checked_occurrences:
                        drift.append(
                            ReconciliationDrift(
                                DriftKind.INCORRECT_PROJECTION,
                                None,
                                destination,
                                "managed occurrence has no occurrence mapping",
                            )
                        )
                    continue
            drift.append(
                ReconciliationDrift(
                    DriftKind.UNEXPECTED,
                    None,
                    destination,
                    "managed provider event has no mapping",
                )
            )

        return ReconciliationReport(rule.id, len(mapping_list), tuple(drift))

    def _occurrence_drift(self, check: OccurrenceCheck) -> list[ReconciliationDrift]:
        actual = check.actual
        if actual is None or actual.status is not EventStatus.CONFIRMED:
            if check.expected is None:
                return []
            kind, detail = DriftKind.MISSING, "managed occurrence is missing"
        elif check.expected is None:
            kind, detail = DriftKind.INCORRECT_PROJECTION, "managed occurrence should be cancelled"
        elif self._fingerprinter.fingerprint(check.expected) == self._fingerprinter.fingerprint(
            SyncDecisionService._as_projection(actual)
        ):
            return []
        else:
            kind, detail = (
                DriftKind.INCORRECT_PROJECTION,
                "managed occurrence differs from source authority",
            )
        return [ReconciliationDrift(kind, check.mapping.source, check.mapping.destination, detail)]
