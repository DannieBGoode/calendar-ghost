from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.errors import UnsupportedProjection
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.provider_ports import CalendarReader, OccurrenceWriter
from calendar_sync.application.sync.sync_run import (
    SyncRunContext,
    has_live_occurrences,
    read_destination_series,
    read_occurrence,
    record,
    require_unchanged,
)
from calendar_sync.domain.audit import AuditAction, AuditEntry, AuditOutcome, RecordedEvent
from calendar_sync.domain.model import (
    CalendarEvent,
    EventMapping,
    EventRef,
    EventStatus,
    OccurrenceMapping,
    OccurrenceMappingId,
    OccurrenceSituation,
    OccurrenceStart,
    OccurrenceState,
    ProjectionFingerprint,
    SyncAction,
    SyncDecision,
    SyncReason,
    SyncRuleId,
)
from calendar_sync.domain.services import ProjectionFingerprinter, SyncDecisionService


@dataclass(frozen=True, slots=True)
class SeriesRepairs:
    """What an occurrence may ask of its series: repair it when it is missing the occurrence, or
    rebuild it when its destination cannot restore an occurrence deleted there. Each answers the
    reason it found, or None."""

    repair: Callable[[SyncRunContext, CalendarEvent], SyncReason | None]
    rebuild: Callable[[SyncRunContext, CalendarEvent], SyncReason | None]


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
    series: SeriesRepairs
    locks: RuleLocks

    def reverify(
        self, run: SyncRunContext, series_mapping: EventMapping, source_series: CalendarEvent
    ) -> None:
        """Re-decide every recorded occurrence of a series after its master changed.

        One listing of each calendar's series answers most of them; any occurrence a listing did
        not find is looked up on its own.
        """
        pending = [
            recorded
            for recorded in run.uow.occurrences.for_series(series_mapping.id)
            if recorded.source not in run.handled
        ]
        if not pending:
            return
        series = (source_series.reference, series_mapping.destination)
        starts = [recorded.original_start for recorded in pending]
        for reference in series:
            run.listed_occurrences[reference] = dict(
                self.provider.list_occurrences(reference, starts)
            )
        try:
            for recorded in pending:
                source_occurrence = read_occurrence(
                    run, self.provider, source_series.reference, recorded.original_start
                )
                self.apply(
                    run,
                    series_mapping,
                    source_series,
                    recorded.original_start,
                    source_occurrence,
                    record_current=True,
                )
        finally:
            # Listings are only as fresh as this re-verification; later decisions read again.
            for reference in series:
                run.listed_occurrences.pop(reference, None)

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
            counted = occurrence.source_ref or source_series.reference
            run.count(decision.action, counted)
            try:
                destination_ref = self._write(
                    run,
                    series_mapping,
                    occurrence,
                    decision,
                    destination.reference if destination is not None else None,
                    record_current=record_current,
                )
            except UnsupportedProjection as unsupported:
                if self._rebuilds(run, series_mapping, unsupported):
                    # Decided again once the series is rebuilt, so not counted or recorded now.
                    run.uncount(decision.action)
                    rebuild = True
                else:
                    # The destination cannot write it exactly: blocked, never approximated.
                    blocked = SyncDecision(SyncAction.CONFLICT, unsupported.reason)
                    run.recount(decision.action, blocked.action, counted)
                    decision, rebuild = blocked, False
                destination_ref = destination.reference if destination is not None else None
            else:
                rebuild = False
            if not rebuild:
                self._record(run, occurrence, decision, destination_ref, detail)
        if rebuild:
            self._rebuild(run, occurrence, destination_ref)

    @staticmethod
    def _rebuilds(
        run: SyncRunContext, series_mapping: EventMapping | None, unsupported: UnsupportedProjection
    ) -> bool:
        """Whether an occurrence its destination cannot restore is brought back by rebuilding its
        series, once a run."""
        return (
            unsupported.reason is SyncReason.OCCURRENCE_NOT_RESTORABLE
            and series_mapping is not None
            and series_mapping.source not in run.rebuilt
        )

    def _rebuild(
        self, run: SyncRunContext, occurrence: _OccurrenceEvidence, destination: EventRef | None
    ) -> None:
        """Rebuild the occurrence's series, which decides the occurrence again; if it cannot be
        rebuilt, the occurrence is blocked for the reason found."""
        refused = self.series.rebuild(run, occurrence.source_series)
        if refused is None:
            return
        with self.locks.for_writes(run.rule.id):
            require_unchanged(run)
            run.count(
                SyncAction.CONFLICT, occurrence.source_ref or occurrence.source_series.reference
            )
            self._record(
                run, occurrence, SyncDecision(SyncAction.CONFLICT, refused), destination, ""
            )

    def _record(
        self,
        run: SyncRunContext,
        occurrence: _OccurrenceEvidence,
        decision: SyncDecision,
        destination_ref: EventRef | None,
        detail: str,
    ) -> None:
        """Record the occurrence's decision and commit, inside the write lock."""
        source_series = occurrence.source_series
        source_ref = occurrence.source_ref
        if source_ref is not None:
            run.handled.add(source_ref)
            run.handled_occurrences.add((source_series.reference, occurrence.original_start))
        record(
            run,
            AuditEntry(
                occurred_at=self.clock.now(),
                rule_id=run.rule.id,
                action=AuditAction.of(decision.action),
                outcome=AuditOutcome.of(decision.action),
                source_event_id=(source_ref or source_series.reference).event_id.value,
                destination_event_id=destination_ref.event_id.value if destination_ref else None,
                detail=detail,
                reason=decision.reason,
                run_id=run.run_id,
                event=RecordedEvent.of_occurrence(occurrence.source),
            ),
            observed=occurrence.source,
            own_identity=source_ref is not None,
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
            series_check = self.series.repair(run, source_series)
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
                destination = read_occurrence(
                    run, self.provider, series_mapping.destination, occurrence.original_start
                )
        decision = self.decisions.decide_occurrence(
            run.rule,
            OccurrenceSituation(
                source_series,
                series_mapping,
                occurrence.original_start,
                occurrence.source,
                occurrence.recorded,
                destination_series,
                destination,
                destination_reported=occurrence.destination_reported,
                has_live_occurrences=has_live_occurrences,
            ),
            window_start=run.window_start,
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
