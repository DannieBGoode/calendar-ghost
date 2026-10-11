from __future__ import annotations

import hashlib
from dataclasses import dataclass

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.errors import UnsupportedProjection
from calendar_sync.application.sync.ports import CalendarProvider
from calendar_sync.application.sync.sync_run import (
    SyncRunContext,
    has_live_occurrences,
    record,
    require_unchanged,
)
from calendar_sync.domain.audit import AuditAction, AuditEntry, AuditOutcome, RecordedEvent
from calendar_sync.domain.model import (
    CalendarEvent,
    EventMapping,
    EventMappingId,
    EventRef,
    EventStatus,
    SyncAction,
    SyncDecision,
    SyncReason,
    SyncRuleId,
)
from calendar_sync.domain.services import ProjectionFingerprinter, SyncDecisionService

_DESTINATION_WRITES = frozenset({SyncAction.CREATE, SyncAction.UPDATE, SyncAction.DELETE})


@dataclass(slots=True)
class SynchronizeEvents:
    """Decides one source event, writes its projection, and records its Event Mapping."""

    provider: CalendarProvider
    decisions: SyncDecisionService
    fingerprinter: ProjectionFingerprinter
    clock: Clock

    def decide_and_write(
        self,
        run: SyncRunContext,
        source_event: CalendarEvent,
        *,
        destination_loaded: bool,
        actual_destination: CalendarEvent | None,
        record_current: bool = True,
    ) -> tuple[EventMapping | None, SyncDecision, bool]:
        """Decide and apply one source event; also whether its revision is new to its mapping."""
        uow, rule = run.uow, run.rule
        mapping = uow.mappings.for_source(rule.id, source_event.reference)
        source_moved = mapping is not None and mapping.source_revision != source_event.revision
        mapping, decision = self._decide(
            run,
            source_event,
            mapping,
            destination_loaded=destination_loaded,
            actual_destination=actual_destination,
        )
        # Deciding may read the provider, which takes time; the User may be disabled meanwhile.
        require_unchanged(run)
        run.count(decision.action, source_event.reference)
        try:
            mapping = self._write(run, source_event, mapping, decision, source_moved=source_moved)
        except UnsupportedProjection as unsupported:
            # The destination cannot hold it exactly, so it is blocked rather than approximated.
            blocked = SyncDecision(SyncAction.CONFLICT, unsupported.reason)
            run.recount(decision.action, blocked.action, source_event.reference)
            decision, source_moved = blocked, False
        if record_current or decision.reason is not SyncReason.PROJECTION_CURRENT:
            record(
                run,
                AuditEntry(
                    occurred_at=self.clock.now(),
                    rule_id=rule.id,
                    action=AuditAction.of(decision.action),
                    outcome=AuditOutcome.of(decision.action),
                    source_event_id=source_event.reference.event_id.value,
                    destination_event_id=mapping.destination.event_id.value if mapping else None,
                    reason=decision.reason,
                    run_id=run.run_id,
                    event=RecordedEvent.of(source_event),
                ),
                observed=source_event,
            )
        uow.commit()
        return mapping, decision, source_moved

    def _decide(
        self,
        run: SyncRunContext,
        source_event: CalendarEvent,
        mapping: EventMapping | None,
        *,
        destination_loaded: bool,
        actual_destination: CalendarEvent | None,
    ) -> tuple[EventMapping | None, SyncDecision]:
        """Decide one source event against its projection; a found interrupted create maps it."""
        rule = run.rule
        actual = actual_destination
        if not destination_loaded and mapping is not None:
            # A listed projection is used once; any later decision this run reads it fresh.
            listed = run.listed_destinations.pop(mapping.destination, None)
            fetched = listed if listed is not None else self.provider.get_event(mapping.destination)
            # A provider may keep deleted events as metadata-less cancellations: they are missing.
            actual = None if fetched is None or fetched.status is EventStatus.CANCELLED else fetched
        decision = self.decisions.decide(
            rule, source_event, mapping, actual, window_start=run.window_start
        )
        if decision.reason is SyncReason.BEFORE_SYNC_WINDOW and self.provider.find_projection(
            rule.destination,
            event_operation_key(
                rule.id, source_event.reference, source_event.revision, SyncAction.CREATE
            ),
        ):
            # The provider acknowledged this create before an interrupted run could record its
            # mapping; complete it idempotently instead of orphaning the projection.
            decision = self.decisions.decide(rule, source_event, mapping, actual)
        if (
            decision.action is SyncAction.CREATE
            and source_event.recurrence is not None
            and not has_live_occurrences(run, self.provider, source_event.reference)
        ):
            # Creating it would only be cancelled again by its occurrences, on every run.
            if mapping is None:
                mapping, actual = self._acknowledged_series(run, source_event)
            decision = self.decisions.decide(
                rule, source_event, mapping, actual, has_live_occurrences=False
            )
        return mapping, decision

    def _write(
        self,
        run: SyncRunContext,
        source_event: CalendarEvent,
        mapping: EventMapping | None,
        decision: SyncDecision,
        *,
        source_moved: bool,
    ) -> EventMapping | None:
        """Apply a decision to the destination and the Event Mapping; answer the mapping now."""
        uow, rule = run.uow, run.rule
        operation_key = event_operation_key(
            rule.id,
            source_event.reference,
            source_event.revision,
            decision.action,
            # Writing a projection again, after its destination lost it, is a create of its own.
            replacing=mapping.destination
            if mapping and decision.action is SyncAction.CREATE
            else None,
        )
        if mapping is not None and decision.action in _DESTINATION_WRITES:
            # Occurrences decided after this write read the series as it now is.
            run.destination_series.pop(mapping.destination, None)
            run.listed_occurrences.pop(mapping.destination, None)
        if decision.action is SyncAction.CREATE and decision.projection is not None:
            created = self.provider.create_projection(
                rule.destination,
                source_event.reference,
                rule.id,
                decision.projection,
                operation_key,
            )
            mapping = EventMapping(
                id=mapping.id if mapping else EventMappingId(operation_key),
                rule_id=rule.id,
                source=source_event.reference,
                destination=created.destination_event.reference,
                source_revision=source_event.revision,
                projection_fingerprint=self.fingerprinter.fingerprint(decision.projection),
            )
            uow.mappings.save(mapping)
            if source_event.recurrence is not None and not run.source_listed:
                # Committed with the mapping, so a retry finishes a replay a failed run began.
                uow.replays.add(mapping.id)
        elif decision.action is SyncAction.UPDATE and decision.projection is not None:
            assert mapping is not None
            updated = self.provider.update_projection(
                mapping.destination,
                source_event.reference,
                rule.id,
                decision.projection,
                operation_key,
            )
            mapping = mapping.record_projection(
                self._recorded_revision(run, mapping, source_event),
                self.fingerprinter.fingerprint(decision.projection),
                updated.reference,
            )
            uow.mappings.save(mapping)
        elif (
            decision.reason is SyncReason.PROJECTION_CURRENT
            and decision.projection is not None
            and mapping is not None
            and source_moved
        ):
            # The destination already shows the new revision, so only the mapping learns it.
            mapping = mapping.record_projection(
                self._recorded_revision(run, mapping, source_event),
                self.fingerprinter.fingerprint(decision.projection),
            )
            uow.mappings.save(mapping)
        elif decision.action is SyncAction.DELETE:
            owned = self.decisions.require_delete_ownership(mapping)
            self.provider.delete_projection(owned.destination, owned.source, rule.id, operation_key)
            uow.mappings.delete(owned)
        return mapping

    @staticmethod
    def _recorded_revision(
        run: SyncRunContext, mapping: EventMapping, source_event: CalendarEvent
    ) -> str:
        """The revision a mapping may record now.

        A series with Occurrence Mappings keeps its previous revision until they are re-verified,
        so a run that fails before then re-verifies them again on its retry.
        """
        if source_event.recurrence is not None and run.uow.occurrences.for_series(mapping.id):
            return mapping.source_revision
        return source_event.revision

    def _acknowledged_series(
        self, run: SyncRunContext, source_event: CalendarEvent
    ) -> tuple[EventMapping | None, CalendarEvent | None]:
        """Find a series the provider created before an interrupted run could record its mapping.

        Its ownership is then verified like any mapped projection before it is removed.
        """
        key = event_operation_key(
            run.rule.id, source_event.reference, source_event.revision, SyncAction.CREATE
        )
        found = self.provider.find_projection(run.rule.destination, key)
        if found is None or found.status is not EventStatus.CONFIRMED or found.occurrence:
            return None, None
        mapping = EventMapping(
            id=EventMappingId(key),
            rule_id=run.rule.id,
            source=source_event.reference,
            destination=found.reference,
            source_revision=source_event.revision,
            projection_fingerprint=self.fingerprinter.fingerprint(
                SyncDecisionService.as_projection(found)
            ),
        )
        return mapping, found


def event_operation_key(
    rule_id: SyncRuleId,
    source: EventRef,
    revision: str,
    action: SyncAction,
    *,
    replacing: EventRef | None = None,
) -> str:
    """The write's stable key. A create that replaces a projection its destination lost names
    the lost one, so it is new for each replacement and the same for each retry of it: a
    provider that keeps the key of a create, as Graph's transactionId does, never answers it
    with the projection it replaces."""
    parts = [
        rule_id.value,
        source.calendar.connected_account_id.value,
        source.calendar.calendar_id.value,
        source.event_id.value,
        revision,
        action.value,
    ]
    if replacing is not None:
        parts.append(replacing.event_id.value)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()
