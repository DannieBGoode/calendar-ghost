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

    def apply(  # noqa: C901, PLR0912
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
        recorded = (
            run.uow.occurrences.get(series_mapping.id, original_start) if series_mapping else None
        )
        decision, destination = self._decide(
            run,
            series_mapping,
            source_series,
            original_start,
            source_occurrence,
            recorded,
            destination_reported,
        )
        detail = ""
        if decision.reason is SyncReason.DESTINATION_OCCURRENCE_MISSING:
            # A dormant series has no projection to repair, so nothing is missing.
            live = has_live_occurrences(run, self.provider, source_series.reference)
            series_check = None
            if live:
                # The repair re-verifies the series' other occurrences; this one is re-decided.
                if source_occurrence is not None:
                    run.handled.add(source_occurrence.reference)
                series_check = self.repair_series(run, source_series)
                series_mapping = run.uow.mappings.for_source(run.rule.id, source_series.reference)
            decision, destination = self._decide(
                run,
                series_mapping,
                source_series,
                original_start,
                source_occurrence,
                recorded,
                destination_reported,
                has_live_occurrences=live,
            )
            if decision.reason is SyncReason.DESTINATION_OCCURRENCE_MISSING:
                detail = _missing_occurrence_detail(series_check, live, original_start)
        # The stop check and the write share one short lock with rule lifecycle changes.
        with self.locks.for_writes(run.rule.id):
            require_unchanged(run)
            source_ref = (
                source_occurrence.reference
                if source_occurrence is not None
                else recorded.source
                if recorded is not None
                else None
            )
            run.count(decision.action, source_ref or source_series.reference)
            key = occurrence_operation_key(
                run.rule.id,
                source_series.reference,
                original_start,
                source_occurrence.revision if source_occurrence is not None else "absent",
                decision.action,
            )
            destination_ref = destination.reference if destination is not None else None

            if decision.action is SyncAction.UPDATE and decision.projection is not None:
                assert series_mapping is not None
                assert source_occurrence is not None
                written = self.writer.write_occurrence(
                    series_mapping.destination,
                    original_start,
                    source_series.reference,
                    run.rule.id,
                    decision.projection,
                    key,
                )
                destination_ref = written.reference
                self._record(
                    run,
                    recorded,
                    series_mapping,
                    original_start,
                    source_occurrence,
                    destination_ref,
                    OccurrenceState.MODIFIED,
                    self.fingerprinter.fingerprint(decision.projection),
                    key,
                )
            elif decision.action is SyncAction.DELETE:
                assert series_mapping is not None
                self.writer.cancel_occurrence(
                    series_mapping.destination,
                    original_start,
                    source_series.reference,
                    run.rule.id,
                    key,
                )
                if source_occurrence is None:
                    if recorded is not None:
                        run.uow.occurrences.delete(recorded)
                else:
                    assert destination_ref is not None
                    self._record(
                        run,
                        recorded,
                        series_mapping,
                        original_start,
                        source_occurrence,
                        destination_ref,
                        OccurrenceState.CANCELLED,
                        None,
                        key,
                    )
            elif decision.reason is SyncReason.OCCURRENCE_RETIRED and recorded is not None:
                run.uow.occurrences.delete(recorded)
            elif (
                record_current
                and decision.reason in _RECORDED_WHEN_UNCHANGED
                and series_mapping is not None
                and source_occurrence is not None
                and destination_ref is not None
            ):
                state = _RECORDED_WHEN_UNCHANGED[decision.reason]
                fingerprint = (
                    self.fingerprinter.fingerprint(decision.projection)
                    if state is OccurrenceState.MODIFIED and decision.projection is not None
                    else None
                )
                if (
                    recorded is None
                    or recorded.state is not state
                    or recorded.source_revision != source_occurrence.revision
                ):
                    self._record(
                        run,
                        recorded,
                        series_mapping,
                        original_start,
                        source_occurrence,
                        destination_ref,
                        state,
                        fingerprint,
                        key,
                    )

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
            )
            # Commit before the next provider call so no write lock spans network requests.
            run.uow.commit()

    def _decide(  # noqa: PLR0913
        self,
        run: SyncRunContext,
        series_mapping: EventMapping | None,
        source_series: CalendarEvent,
        original_start: OccurrenceStart,
        source_occurrence: CalendarEvent | None,
        recorded: OccurrenceMapping | None,
        destination_reported: bool,
        *,
        has_live_occurrences: bool = True,
    ) -> tuple[SyncDecision, CalendarEvent | None]:
        destination_series = destination = None
        if series_mapping is not None and source_series.managed_origin is None:
            destination_series = self.provider.get_event(series_mapping.destination)
            if (
                destination_series is not None
                and destination_series.status is EventStatus.CONFIRMED
            ):
                destination = self.provider.get_occurrence(
                    series_mapping.destination, original_start
                )
        decision = self.decisions.decide_occurrence(
            run.rule,
            source_series,
            series_mapping,
            original_start,
            source_occurrence,
            recorded,
            destination_series,
            destination,
            destination_reported=destination_reported,
            has_live_occurrences=has_live_occurrences,
        )
        return decision, destination

    @staticmethod
    def _record(  # noqa: PLR0913
        run: SyncRunContext,
        recorded: OccurrenceMapping | None,
        series_mapping: EventMapping,
        original_start: OccurrenceStart,
        source_occurrence: CalendarEvent,
        destination: EventRef,
        state: OccurrenceState,
        fingerprint: ProjectionFingerprint | None,
        key: str,
    ) -> None:
        run.uow.occurrences.save(
            OccurrenceMapping(
                id=recorded.id if recorded is not None else OccurrenceMappingId(key),
                series_mapping_id=series_mapping.id,
                original_start=original_start,
                source=source_occurrence.reference,
                destination=destination,
                state=state,
                source_revision=source_occurrence.revision,
                projection_fingerprint=fingerprint,
            )
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
