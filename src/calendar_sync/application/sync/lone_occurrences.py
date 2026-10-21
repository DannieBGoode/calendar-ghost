from __future__ import annotations

from dataclasses import dataclass

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.errors import UnsupportedProjection
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.planning import event_operation_key
from calendar_sync.application.sync.provider_ports import CalendarProvider
from calendar_sync.application.sync.sync_run import SyncRunContext, record, require_unchanged
from calendar_sync.domain.audit import AuditAction, AuditEntry, AuditOutcome, RecordedEvent
from calendar_sync.domain.model import (
    CalendarEvent,
    EventMapping,
    EventStatus,
    OccurrenceIdentity,
    OccurrenceSituation,
    SyncAction,
    SyncReason,
)
from calendar_sync.domain.services import SyncDecisionService

_SHOWN = frozenset({SyncReason.OCCURRENCE_CURRENT, SyncReason.OCCURRENCE_ALREADY_CANCELLED})


@dataclass(slots=True)
class RetireLoneOccurrences:
    """Removes the single projection of an occurrence once its series is shown.

    An occurrence whose series its calendar did not show was projected on its own (ADR 0011).
    Once the destination series shows that occurrence as the source projects it, the single
    projection would show it twice. Until then it stays, so the occurrence is never shown wrong
    or not at all; one someone invited guests to stays too, and is recorded as blocked. A series
    the rule excludes projects none of its occurrences (ADR 0018), so once the calendar shows it,
    their single projections are removed as the series' exclusion says.
    """

    provider: CalendarProvider
    decisions: SyncDecisionService
    clock: Clock
    locks: RuleLocks

    def retire(
        self, run: SyncRunContext, series_mapping: EventMapping, source_series: CalendarEvent
    ) -> None:
        for lone in run.uow.mappings.lone_occurrences(run.rule.id, source_series.reference):
            assert lone.occurrence is not None
            source = self.provider.get_occurrence(
                source_series.reference, lone.occurrence.original_start
            )
            if source is None:
                continue  # unreadable, so decided as the event it was projected as
            if source.status is EventStatus.CANCELLED:
                self._remove(run, lone, source, SyncReason.SOURCE_CANCELLED, source.revision)
            elif self._shown(run, series_mapping, source_series, lone.occurrence, source):
                self._remove(
                    run, lone, source, SyncReason.OCCURRENCE_JOINED_SERIES, source.revision
                )

    def retire_excluded(self, run: SyncRunContext, source_series: CalendarEvent) -> None:
        """Remove the single projections of the occurrences of a shown series the rule does not
        project: one the rule excludes, or one deleted, which removes every occurrence with it."""
        deleted = source_series.status is EventStatus.CANCELLED
        if not deleted and run.rule.transformation.exclusion(source_series) is None:
            return
        for lone in run.uow.mappings.lone_occurrences(run.rule.id, source_series.reference):
            assert lone.occurrence is not None
            source = (
                None
                if deleted
                else self.provider.get_occurrence(
                    source_series.reference, lone.occurrence.original_start
                )
            )
            reason = self.decisions.lone_projection_removal(run.rule, source_series, source)
            if reason is not None:
                self._remove(run, lone, source, reason, (source or source_series).revision)

    def _shown(
        self,
        run: SyncRunContext,
        series_mapping: EventMapping,
        source_series: CalendarEvent,
        identity: OccurrenceIdentity,
        source: CalendarEvent,
    ) -> bool:
        """Whether the destination series shows the occurrence as the source projects it now."""
        start = identity.original_start
        destination_series = self.provider.get_event(series_mapping.destination)
        if destination_series is None or destination_series.status is not EventStatus.CONFIRMED:
            return False
        decision = self.decisions.decide_occurrence(
            run.rule,
            OccurrenceSituation(
                source_series,
                series_mapping,
                start,
                source,
                run.uow.occurrences.get(series_mapping.id, start),
                destination_series,
                self.provider.get_occurrence(series_mapping.destination, start),
            ),
        )
        return decision.action is SyncAction.IGNORE and decision.reason in _SHOWN

    def _remove(
        self,
        run: SyncRunContext,
        lone: EventMapping,
        source: CalendarEvent | None,
        reason: SyncReason,
        revision: str,
    ) -> None:
        """Delete the single projection; `source` is the occurrence, None once it is gone with
        its series, and `revision` what the deletion's Operation Key is taken of."""
        with self.locks.for_writes(run.rule.id):
            require_unchanged(run)
            mapping = run.uow.mappings.for_source(run.rule.id, lone.source)
            if mapping is None:
                return
            try:
                self.provider.delete_projection(
                    mapping.destination,
                    mapping.source,
                    run.rule.id,
                    event_operation_key(run.rule.id, mapping.source, revision, SyncAction.DELETE),
                )
            except UnsupportedProjection as unsupported:
                self._record(run, mapping, source, SyncAction.CONFLICT, unsupported.reason)
                return
            run.uow.mappings.delete(mapping)
            if reason is not SyncReason.SOURCE_CANCELLED:
                # Its series shows it as it is, or projects none of it, so nothing later this run
                # projects it again. A cancelled one is still applied to its series when its own
                # change arrives.
                run.handled.add(mapping.source)
            self._record(run, mapping, source, SyncAction.DELETE, reason)

    def _record(
        self,
        run: SyncRunContext,
        mapping: EventMapping,
        source: CalendarEvent | None,
        action: SyncAction,
        reason: SyncReason,
    ) -> None:
        """Record what became of the single projection and commit, inside the write lock."""
        run.count(action, mapping.source)
        record(
            run,
            AuditEntry(
                occurred_at=self.clock.now(),
                rule_id=run.rule.id,
                action=AuditAction.of(action),
                outcome=AuditOutcome.of(action),
                source_event_id=mapping.source.event_id.value,
                destination_event_id=mapping.destination.event_id.value,
                reason=reason,
                run_id=run.run_id,
                event=RecordedEvent.of_occurrence(source),
            ),
        )
        run.uow.commit()
