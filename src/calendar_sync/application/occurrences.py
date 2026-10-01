from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    AuditAction,
    AuditEntry,
    AuditOutcome,
    CalendarReader,
    Clock,
    OccurrenceWriter,
    RecordedEvent,
)
from calendar_sync.application.sync_run import (
    SyncRunContext,
    has_live_occurrences,
    read_destination_series,
    record,
    require_unchanged,
)
from calendar_sync.domain.model import (
    CalendarEvent,
    EventMapping,
    EventRef,
    EventStatus,
    OccurrenceMapping,
    OccurrenceMappingId,
    OccurrenceStart,
    OccurrenceState,
    ProjectionFingerprint,
    SyncAction,
    SyncDecision,
    SyncReason,
    SyncRuleId,
)
from calendar_sync.domain.services import ProjectionFingerprinter, SyncDecisionService

_RECORDED_WHEN_UNCHANGED = {
    SyncReason.OCCURRENCE_CURRENT: OccurrenceState.MODIFIED,
    SyncReason.OCCURRENCE_ALREADY_CANCELLED: OccurrenceState.CANCELLED,
}


@dataclass(slots=True)
class SynchronizeOccurrences:
    """Applies source authority to single occurrences of mapped series."""

    provider: CalendarReader
    writer: OccurrenceWriter
    decisions: SyncDecisionService
    fingerprinter: ProjectionFingerprinter
    clock: Clock
    repair_series: Callable[[SyncRunContext, CalendarEvent], SyncReason | None]
    """Repairs a series for one occurrence, answering how the series was found."""
    locks: RuleLocks

    def reverify(
        self, run: SyncRunContext, series_mapping: EventMapping, source_series: CalendarEvent
    ) -> None:
        """Re-decide every recorded occurrence of a series after its master changed."""
        for recorded in run.uow.occurrences.for_series(series_mapping.id):
            if recorded.source in run.handled:
                continue
            source_occurrence = self.provider.get_occurrence(
                source_series.reference, recorded.original_start
            )
            self.apply(
                run,
                series_mapping,
                source_series,
                recorded.original_start,
                source_occurrence,
                record_current=True,
            )

    def replay_exceptions(
        self, run: SyncRunContext, series_mapping: EventMapping, source_series: CalendarEvent
    ) -> None:
        """Apply every cancelled or moved source occurrence to a newly created series."""
        for exception in self.provider.occurrence_exceptions(
            source_series.reference, run.window_start
        ):
            if exception.reference in run.handled or exception.occurrence is None:
                continue
            self.apply(
                run,
                series_mapping,
                source_series,
                exception.occurrence.original_start,
                exception,
                record_current=True,
            )

    def apply(
        self,
        run: SyncRunContext,
        series_mapping: EventMapping | None,
        source_series: CalendarEvent,
        original_start: OccurrenceStart,
        source_occurrence: CalendarEvent | None,
        *,
        record_current: bool,
        destination_reported: bool = False,
    ) -> None:
        occurrence = _OccurrenceEvidence(
            source_series,
            original_start,
            source_occurrence,
            run.uow.occurrences.get(series_mapping.id, original_start) if series_mapping else None,
            destination_reported,
        )
        decision, destination = self._decide(run, series_mapping, occurrence)
        detail = ""
        if decision.reason is SyncReason.DESTINATION_OCCURRENCE_MISSING:
            series_mapping, decision, destination, detail = self._decide_after_series_repair(
                run, series_mapping, occurrence
            )
        # The stop check and the write share one short lock with rule lifecycle changes.
        with self.locks.for_writes(run.rule.id):
            require_unchanged(run)
            run.count(decision.action, occurrence.source_ref or source_series.reference)
            destination_ref = self._write(
                run,
                series_mapping,
                occurrence,
                decision,
                destination.reference if destination is not None else None,
                record_current=record_current,
            )
            source_ref = occurrence.source_ref
            if source_ref is not None:
                run.handled.add(source_ref)
            record(
                run,
                AuditEntry(
                    occurred_at=self.clock.now(),
                    rule_id=run.rule.id,
                    action=AuditAction.of(decision.action),
                    outcome=AuditOutcome.of(decision.action),
                    source_event_id=(source_ref or source_series.reference).event_id.value,
                    destination_event_id=destination_ref.event_id.value
                    if destination_ref
                    else None,
                    detail=detail,
                    reason=decision.reason,
                    run_id=run.run_id,
                    event=_recorded_event(source_occurrence),
                ),
                observed=source_occurrence,
            )
            # Commit before the next provider call so no write lock spans network requests.
            run.uow.commit()

    def _decide_after_series_repair(
        self,
        run: SyncRunContext,
        series_mapping: EventMapping | None,
        occurrence: _OccurrenceEvidence,
    ) -> tuple[EventMapping | None, SyncDecision, CalendarEvent | None, str]:
        """Repair a series missing the occurrence, then decide the occurrence again."""
        source_series = occurrence.source_series
        # A dormant series has no projection to repair, so nothing is missing.
        live = has_live_occurrences(run, self.provider, source_series.reference)
        series_check = None
        if live:
            # The repair re-verifies the series' other occurrences; this one is re-decided.
            if occurrence.source is not None:
                run.handled.add(occurrence.source.reference)
            series_check = self.repair_series(run, source_series)
            series_mapping = run.uow.mappings.for_source(run.rule.id, source_series.reference)
        decision, destination = self._decide(
            run, series_mapping, occurrence, has_live_occurrences=live
        )
        detail = (
            _missing_occurrence_detail(series_check, live, occurrence.original_start)
            if decision.reason is SyncReason.DESTINATION_OCCURRENCE_MISSING
            else ""
        )
        return series_mapping, decision, destination, detail

    def _write(
        self,
        run: SyncRunContext,
        series_mapping: EventMapping | None,
        occurrence: _OccurrenceEvidence,
        decision: SyncDecision,
        destination: EventRef | None,
        *,
        record_current: bool,
    ) -> EventRef | None:
        """Apply the decision to the destination and its Occurrence Mapping; answer where."""
        key = occurrence.operation_key(run.rule.id, decision.action)
        if decision.action is SyncAction.UPDATE and decision.projection is not None:
            assert series_mapping is not None
            assert occurrence.source is not None
            written = self.writer.write_occurrence(
                series_mapping.destination,
                occurrence.original_start,
                occurrence.source_series.reference,
                run.rule.id,
                decision.projection,
                key,
            ).reference
            fingerprint = self.fingerprinter.fingerprint(decision.projection)
            run.uow.occurrences.save(
                occurrence.mapping(
                    series_mapping, written, OccurrenceState.MODIFIED, fingerprint, key
                )
            )
            return written
        if decision.action is SyncAction.DELETE:
            assert series_mapping is not None
            self.writer.cancel_occurrence(
                series_mapping.destination,
                occurrence.original_start,
                occurrence.source_series.reference,
                run.rule.id,
                key,
            )
            if occurrence.source is not None:
                assert destination is not None
                run.uow.occurrences.save(
                    occurrence.mapping(
                        series_mapping, destination, OccurrenceState.CANCELLED, None, key
                    )
                )
            elif occurrence.recorded is not None:
                run.uow.occurrences.delete(occurrence.recorded)
        elif decision.reason is SyncReason.OCCURRENCE_RETIRED and occurrence.recorded is not None:
            run.uow.occurrences.delete(occurrence.recorded)
        elif record_current and series_mapping is not None and destination is not None:
            self._record_unchanged(run, series_mapping, occurrence, decision, destination, key)
        return destination

    def _record_unchanged(
        self,
        run: SyncRunContext,
        series_mapping: EventMapping,
        occurrence: _OccurrenceEvidence,
        decision: SyncDecision,
        destination: EventRef,
        key: str,
    ) -> None:
        """Record an occurrence found current or already cancelled, unless it is recorded so."""
        state = _RECORDED_WHEN_UNCHANGED.get(decision.reason)
        source, recorded = occurrence.source, occurrence.recorded
        if state is None or source is None:
            return
        if (
            recorded is not None
            and recorded.state is state
            and recorded.source_revision == source.revision
        ):
            return
        fingerprint = (
            self.fingerprinter.fingerprint(decision.projection)
            if state is OccurrenceState.MODIFIED and decision.projection is not None
            else None
        )
        run.uow.occurrences.save(
            occurrence.mapping(series_mapping, destination, state, fingerprint, key)
        )

    def _decide(
        self,
        run: SyncRunContext,
        series_mapping: EventMapping | None,
        occurrence: _OccurrenceEvidence,
        *,
        has_live_occurrences: bool = True,
    ) -> tuple[SyncDecision, CalendarEvent | None]:
        destination_series = destination = None
        source_series = occurrence.source_series
        if series_mapping is not None and source_series.managed_origin is None:
            destination_series = read_destination_series(
                run, self.provider, series_mapping.destination
            )
            if (
                destination_series is not None
                and destination_series.status is EventStatus.CONFIRMED
            ):
                destination = self.provider.get_occurrence(
                    series_mapping.destination, occurrence.original_start
                )
        decision = self.decisions.decide_occurrence(
            run.rule,
            source_series,
            series_mapping,
            occurrence.original_start,
            occurrence.source,
            occurrence.recorded,
            destination_series,
            destination,
            destination_reported=occurrence.destination_reported,
            has_live_occurrences=has_live_occurrences,
        )
        return decision, destination


@dataclass(frozen=True, slots=True)
class _OccurrenceEvidence:
    """What one decision knows about an occurrence before it reads the destination."""

    source_series: CalendarEvent
    original_start: OccurrenceStart
    source: CalendarEvent | None
    """The source occurrence, or None when the series no longer has it."""
    recorded: OccurrenceMapping | None
    destination_reported: bool
    """The destination feed reported this occurrence, so a difference is drift."""

    @property
    def source_ref(self) -> EventRef | None:
        if self.source is not None:
            return self.source.reference
        return self.recorded.source if self.recorded is not None else None

    def operation_key(self, rule_id: SyncRuleId, action: SyncAction) -> str:
        revision = self.source.revision if self.source is not None else "absent"
        return occurrence_operation_key(
            rule_id, self.source_series.reference, self.original_start, revision, action
        )

    def mapping(
        self,
        series_mapping: EventMapping,
        destination: EventRef,
        state: OccurrenceState,
        fingerprint: ProjectionFingerprint | None,
        key: str,
    ) -> OccurrenceMapping:
        """The Occurrence Mapping to save for a source occurrence this rule wrote or verified."""
        assert self.source is not None
        return OccurrenceMapping(
            id=self.recorded.id if self.recorded is not None else OccurrenceMappingId(key),
            series_mapping_id=series_mapping.id,
            original_start=self.original_start,
            source=self.source.reference,
            destination=destination,
            state=state,
            source_revision=self.source.revision,
            projection_fingerprint=fingerprint,
        )


def _missing_occurrence_detail(
    series_check: SyncReason | None, live: bool, original_start: OccurrenceStart
) -> str:
    """What the run verified before blocking, so a recurring block can be diagnosed later."""
    check = (
        series_check.value
        if series_check is not None
        else "already made this run"
        if live
        else "not made, no live occurrence"
    )
    return (
        f"Series check before blocking: {check}. "
        f"No destination occurrence originally starts at {original_start.isoformat()}."
    )


def _recorded_event(source_occurrence: CalendarEvent | None) -> RecordedEvent:
    if source_occurrence is not None:
        return RecordedEvent.of(source_occurrence)
    # An occurrence absent from its series has no title or time of its own, and may have had a
    # title other than the series'; Activity names it from what it last recorded for it.
    return RecordedEvent(title="", recurring=True, cancelled=True)


def occurrence_operation_key(
    rule_id: SyncRuleId,
    source_series: EventRef,
    original_start: OccurrenceStart,
    revision: str,
    action: SyncAction,
) -> str:
    raw = "|".join(
        (
            rule_id.value,
            source_series.calendar.connected_account_id.value,
            source_series.calendar.calendar_id.value,
            source_series.event_id.value,
            original_start.isoformat(),
            revision,
            action.value,
        )
    )
    return hashlib.sha256(raw.encode()).hexdigest()
