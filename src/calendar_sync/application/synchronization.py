from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import uuid4

from calendar_sync.application.errors import (
    ProviderFailure,
    ProviderFailureKind,
    RuleNotExecutable,
)
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.occurrences import SynchronizeOccurrences
from calendar_sync.application.ports import (
    AuditEntry,
    CalendarProvider,
    Clock,
    RecordedEvent,
    RuleRunOutcome,
    RunKind,
    UnitOfWorkFactory,
)
from calendar_sync.application.sync_run import (
    OUTCOMES,
    SyncRunContext,
    has_live_occurrences,
    record,
    require_unchanged,
)
from calendar_sync.domain.model import (
    CalendarEvent,
    EventMapping,
    EventMappingId,
    EventRef,
    EventStatus,
    OccurrenceState,
    ProjectionFingerprint,
    SyncAction,
    SyncDecision,
    SyncReason,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.domain.services import ProjectionFingerprinter, SyncDecisionService


@dataclass(frozen=True, slots=True)
class SyncRunResult:
    rule_id: SyncRuleId
    created: int = 0
    updated: int = 0
    deleted: int = 0
    ignored: int = 0
    conflicts: int = 0


@dataclass(slots=True)
class ExecuteSyncRule:
    unit_of_work: UnitOfWorkFactory
    provider: CalendarProvider
    decisions: SyncDecisionService
    fingerprinter: ProjectionFingerprinter
    clock: Clock
    locks: RuleLocks = field(default_factory=RuleLocks)
    new_run_id: Callable[[], str] = field(default=lambda: uuid4().hex)
    occurrences: SynchronizeOccurrences = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.occurrences = SynchronizeOccurrences(
            self.provider,
            self.decisions,
            self.fingerprinter,
            self.clock,
            self._repair_series,
            self.locks,
        )

    def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
        with self.locks.for_rule(rule_id):
            try:
                return self._execute_serialized(rule_id, full=full)
            except RuleNotExecutable:
                raise
            except ProviderFailure as failure:
                self._record_failure(rule_id, full, failure.kind.value)
                raise
            except Exception:
                self._record_failure(rule_id, full, ProviderFailureKind.INFRASTRUCTURE.value)
                raise

    def _record_failure(self, rule_id: SyncRuleId, full: bool, kind: str) -> None:
        # Recording evidence must never replace the failure the scheduler classifies.
        with suppress(Exception), self.unit_of_work() as uow:
            if uow.rules.get(rule_id) is not None:
                uow.run_outcomes.record(
                    RuleRunOutcome(
                        rule_id, RunKind.SYNC, self.clock.now(), False, full, failure_kind=kind
                    )
                )
                uow.commit()

    def _execute_serialized(self, rule_id: SyncRuleId, *, full: bool) -> SyncRunResult:
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if rule is None:
                raise RuleNotExecutable(f"sync rule {rule_id.value} does not exist")
            if rule.state is not SyncRuleState.ENABLED:
                raise RuleNotExecutable(f"sync rule is {rule.state}, not enabled")

            run_id = self.new_run_id()
            reproject = rule.reprojection_required
            full_run = full or reproject
            previous_cursor = uow.cursors.get(rule.id)
            cursor = None if full_run else previous_cursor
            destination_cursor = None if full_run else uow.destination_cursors.get(rule.id)
            cutoff = self.clock.now() - timedelta(days=rule.initial_lookback_days)
            changes = self.provider.changes(rule.source, cursor, cutoff)
            destination_changes = self.provider.changes(
                rule.destination, destination_cursor, cutoff
            )
            # A missing or rejected cursor also yields a full listing instead of changes.
            source_listed = cursor is None or changes.complete
            destination_listed = destination_cursor is None or destination_changes.complete
            counts = {action: 0 for action in SyncAction}
            run = SyncRunContext(
                uow,
                rule,
                run_id,
                counts,
                cutoff,
                reproject,
                incremental=not source_listed and not destination_listed,
                daily_pass=source_listed and previous_cursor is not None,
                source_listed=source_listed,
            )
            if destination_listed:
                # A full listing already holds each projection, so decisions need not re-read it.
                run.listed_destinations = {
                    event.reference: event
                    for event in destination_changes.events
                    if event.occurrence is None
                }

            # Series masters first, so an exception can always resolve its parent's mapping.
            for source_event in sorted(
                changes.events, key=lambda item: item.occurrence is not None
            ):
                if source_event.occurrence is not None:
                    self._synchronize_source_exception(run, source_event)
                else:
                    self._synchronize_event(
                        run, source_event, destination_loaded=False, actual_destination=None
                    )
                    run.handled.add(source_event.reference)
                uow.commit()

            for destination_event in destination_changes.events:
                if destination_event.occurrence is not None:
                    self._repair_destination_occurrence(run, destination_event)
                    uow.commit()
                    continue
                mapping = uow.mappings.for_destination(rule.id, destination_event.reference)
                if mapping is None or mapping.source in run.handled:
                    continue
                if self._is_own_write(run, mapping, destination_event):
                    run.counts[SyncAction.IGNORE] += 1
                    continue
                authoritative_source = self.provider.get_event(mapping.source)
                if authoritative_source is None:
                    self._record_unverifiable(run, mapping.source, mapping.destination)
                    uow.commit()
                    continue
                self._synchronize_event(
                    run,
                    authoritative_source,
                    destination_loaded=True,
                    actual_destination=(
                        None
                        if destination_event.status is EventStatus.CANCELLED
                        else destination_event
                    ),
                )
                run.handled.add(mapping.source)
                uow.commit()

            if reproject:
                self._reproject_remaining(run)
            self._finish_pending_replays(run)

            uow.cursors.save(rule.id, changes.next_cursor)
            uow.destination_cursors.save(rule.id, destination_changes.next_cursor)
            with self.locks.for_writes(rule.id):
                if reproject:
                    current = uow.rules.get(rule.id)
                    # An edit made while this run was in flight keeps reprojection pending.
                    if (
                        current is not None
                        and current.reprojection_required
                        and current.material_signature == rule.material_signature
                    ):
                        uow.rules.save(current.complete_reprojection())
                uow.commit()
            uow.run_outcomes.record(
                RuleRunOutcome(
                    rule.id,
                    RunKind.SYNC,
                    self.clock.now(),
                    True,
                    # Listing both calendars in full, as a first run does, completes the daily pass.
                    source_listed and destination_listed,
                    created=counts[SyncAction.CREATE],
                    updated=counts[SyncAction.UPDATE],
                    deleted=counts[SyncAction.DELETE],
                    conflicts=counts[SyncAction.CONFLICT],
                )
            )
            uow.commit()

        return SyncRunResult(
            rule_id=rule_id,
            created=counts[SyncAction.CREATE],
            updated=counts[SyncAction.UPDATE],
            deleted=counts[SyncAction.DELETE],
            ignored=counts[SyncAction.IGNORE],
            conflicts=counts[SyncAction.CONFLICT],
        )

    def _is_own_write(
        self, run: SyncRunContext, mapping: EventMapping, destination: CalendarEvent
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
            and origin.rule_id == run.rule.id
            and origin.source == mapping.source
            and self.fingerprinter.fingerprint(SyncDecisionService.as_projection(destination))
            == mapping.projection_fingerprint
        )

    def _is_own_occurrence_write(
        self, run: SyncRunContext, series_mapping: EventMapping, destination: CalendarEvent
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
            and origin.rule_id == run.rule.id
            and origin.source == series_mapping.source
            and self.fingerprinter.fingerprint(SyncDecisionService.as_projection(destination))
            == recorded.projection_fingerprint
        )

    def _reproject_remaining(self, run: SyncRunContext) -> None:
        """Apply a changed policy to mappings the change feeds did not report."""
        for mapping in run.uow.mappings.for_rule(run.rule.id):
            if mapping.source in run.handled:
                continue
            authoritative_source = self.provider.get_event(mapping.source)
            if authoritative_source is None:
                self._record_unverifiable(run, mapping.source, mapping.destination)
            else:
                # Reprojection re-verifies every recorded occurrence of a series as well.
                self._synchronize_event(
                    run, authoritative_source, destination_loaded=False, actual_destination=None
                )
            run.handled.add(mapping.source)
            run.uow.commit()

    def _synchronize_source_exception(self, run: SyncRunContext, exception: CalendarEvent) -> None:
        identity = exception.occurrence
        assert identity is not None
        if exception.reference in run.handled:
            # A replay or re-verification already applied it this run from a fresher read.
            return
        series_ref = EventRef(run.rule.source, identity.series_event_id)
        source_series = self.provider.get_event(series_ref)
        series_mapping = run.uow.mappings.for_source(run.rule.id, series_ref)
        if source_series is None:
            if series_mapping is None:
                self._record_skipped_occurrence(run, exception)
            else:
                self._record_unverifiable(run, exception.reference, series_mapping.destination)
            return
        if series_mapping is None and series_ref not in run.handled:
            # Creating the series replays its exceptions; this one is applied below.
            run.handled.add(exception.reference)
            self._synchronize_event(
                run, source_series, destination_loaded=False, actual_destination=None
            )
            run.handled.add(series_ref)
            series_mapping = run.uow.mappings.for_source(run.rule.id, series_ref)
        self.occurrences.apply(
            run,
            series_mapping,
            source_series,
            identity.original_start,
            exception,
            record_current=True,
        )

    def _repair_destination_occurrence(
        self, run: SyncRunContext, destination_event: CalendarEvent
    ) -> None:
        identity = destination_event.occurrence
        assert identity is not None
        series_mapping = run.uow.mappings.for_destination(
            run.rule.id, EventRef(run.rule.destination, identity.series_event_id)
        )
        if series_mapping is None:
            return
        if self._is_own_occurrence_write(run, series_mapping, destination_event):
            run.counts[SyncAction.IGNORE] += 1
            return
        source_series = self.provider.get_event(series_mapping.source)
        if source_series is None:
            self._record_unverifiable(run, series_mapping.source, destination_event.reference)
            return
        source_occurrence = (
            None
            if source_series.status is EventStatus.CANCELLED
            else self.provider.get_occurrence(series_mapping.source, identity.original_start)
        )
        if source_occurrence is not None and source_occurrence.reference in run.handled:
            return
        self.occurrences.apply(
            run,
            series_mapping,
            source_series,
            identity.original_start,
            source_occurrence,
            record_current=False,
            destination_reported=True,
        )

    def _repair_series(
        self, run: SyncRunContext, source_series: CalendarEvent
    ) -> SyncReason | None:
        """Repair a series for one of its occurrences; the reason is None if already repaired."""
        if source_series.reference in run.repaired:
            return None
        run.repaired.add(source_series.reference)
        # Cascading re-applies every recorded occurrence if the repair recreated the series.
        # A series found current is evidence for the occurrence's decision, not an entry of its own.
        return self._synchronize_event(
            run,
            source_series,
            destination_loaded=False,
            actual_destination=None,
            record_current=False,
        ).reason

    def _record_skipped_occurrence(self, run: SyncRunContext, exception: CalendarEvent) -> None:
        """An exception of a series this rule never projected has nothing to protect."""
        run.counts[SyncAction.IGNORE] += 1
        record(
            run,
            AuditEntry(
                occurred_at=self.clock.now(),
                rule_id=run.rule.id,
                action=SyncAction.IGNORE.value,
                outcome=OUTCOMES[SyncAction.IGNORE],
                source_event_id=exception.reference.event_id.value,
                reason=SyncReason.SERIES_NOT_SYNCHRONIZED.value,
                run_id=run.run_id,
                event=RecordedEvent.of(exception),
            ),
        )

    def _record_unverifiable(
        self, run: SyncRunContext, source: EventRef, destination: EventRef | None
    ) -> None:
        run.counts[SyncAction.CONFLICT] += 1
        run.uow.audit.append(
            AuditEntry(
                occurred_at=self.clock.now(),
                rule_id=run.rule.id,
                action=SyncAction.CONFLICT.value,
                outcome="blocked",
                source_event_id=source.event_id.value,
                destination_event_id=destination.event_id.value if destination else None,
                reason=SyncReason.SOURCE_UNVERIFIABLE.value,
                run_id=run.run_id,
            )
        )

    def _synchronize_event(
        self,
        run: SyncRunContext,
        source_event: CalendarEvent,
        *,
        destination_loaded: bool,
        actual_destination: CalendarEvent | None,
        record_current: bool = True,
    ) -> SyncDecision:
        with self.locks.for_writes(run.rule.id):
            require_unchanged(run)
            mapping, decision = self._decide_and_write(
                run,
                source_event,
                destination_loaded=destination_loaded,
                actual_destination=actual_destination,
                record_current=record_current,
            )
        # Occurrence re-verification takes the write lock per occurrence, so it runs outside it.
        series_changed = decision.action in {SyncAction.CREATE, SyncAction.UPDATE}
        if (
            mapping is not None
            and decision.action is not SyncAction.DELETE
            and (series_changed or (run.reproject and decision.action is SyncAction.IGNORE))
        ):
            self.occurrences.reverify(run, mapping, source_event)
        if (
            mapping is not None
            and decision.action is SyncAction.CREATE
            and source_event.recurrence is not None
            and not run.source_listed
        ):
            self._replay_exceptions(run, mapping, source_event)
        return decision

    def _replay_exceptions(
        self, run: SyncRunContext, mapping: EventMapping, source_series: CalendarEvent
    ) -> None:
        """A new series starts from its recurrence alone; its exceptions come from the source.

        This covers exceptions the incremental feed did not report and cancellations that were
        never recorded. The pending replay is cleared only after every exception was applied.
        """
        self.occurrences.replay_exceptions(run, mapping, source_series)
        run.uow.replays.remove(mapping.id)
        run.uow.commit()

    def _finish_pending_replays(self, run: SyncRunContext) -> None:
        """Complete replays an earlier failed run left unfinished."""
        for mapping in run.uow.replays.pending(run.rule.id):
            source_series = None if run.source_listed else self.provider.get_event(mapping.source)
            if source_series is None or source_series.recurrence is None:
                # A full listing already applied every exception in the window, and a series
                # that is gone or no longer recurring is decided by its own change.
                run.uow.replays.remove(mapping.id)
                run.uow.commit()
                continue
            self._replay_exceptions(run, mapping, source_series)

    def _decide_and_write(
        self,
        run: SyncRunContext,
        source_event: CalendarEvent,
        *,
        destination_loaded: bool,
        actual_destination: CalendarEvent | None,
        record_current: bool = True,
    ) -> tuple[EventMapping | None, SyncDecision]:
        uow, rule = run.uow, run.rule
        mapping = uow.mappings.for_source(rule.id, source_event.reference)
        actual = actual_destination
        if not destination_loaded and mapping is not None:
            # A listed projection is used once; any later decision this run reads it fresh.
            listed = run.listed_destinations.pop(mapping.destination, None)
            fetched = listed if listed is not None else self.provider.get_event(mapping.destination)
            # Google keeps deleted events as metadata-less cancellations; treat them as missing.
            actual = None if fetched is None or fetched.status is EventStatus.CANCELLED else fetched
        decision = self.decisions.decide(
            rule, source_event, mapping, actual, window_start=run.window_start
        )
        if decision.reason is SyncReason.BEFORE_SYNC_WINDOW and self.provider.find_projection(
            rule.destination,
            self._operation_key(
                rule.id, source_event.reference, source_event.revision, SyncAction.CREATE
            ),
        ):
            # Google acknowledged this create before an interrupted run could record its
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
        run.counts[decision.action] += 1
        operation_key = self._operation_key(
            rule.id, source_event.reference, source_event.revision, decision.action
        )

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
            mapping = EventMapping(
                id=mapping.id,
                rule_id=mapping.rule_id,
                source=mapping.source,
                destination=updated.reference,
                source_revision=source_event.revision,
                projection_fingerprint=self.fingerprinter.fingerprint(decision.projection),
            )
            uow.mappings.save(mapping)
        elif decision.action is SyncAction.DELETE:
            owned = self.decisions.require_delete_ownership(mapping)
            self.provider.delete_projection(
                owned.destination,
                owned.source,
                rule.id,
                operation_key,
            )
            uow.mappings.delete(owned)

        if record_current or decision.reason is not SyncReason.PROJECTION_CURRENT:
            record(
                run,
                AuditEntry(
                    occurred_at=self.clock.now(),
                    rule_id=rule.id,
                    action=decision.action.value,
                    outcome=OUTCOMES.get(decision.action, "completed"),
                    source_event_id=source_event.reference.event_id.value,
                    destination_event_id=mapping.destination.event_id.value if mapping else None,
                    reason=decision.reason.value,
                    run_id=run.run_id,
                    event=RecordedEvent.of(source_event),
                ),
            )
        uow.commit()
        return mapping, decision

    def _acknowledged_series(
        self, run: SyncRunContext, source_event: CalendarEvent
    ) -> tuple[EventMapping | None, CalendarEvent | None]:
        """Find a series Google created before an interrupted run could record its mapping.

        Its ownership is then verified like any mapped projection before it is removed.
        """
        key = self._operation_key(
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

    @staticmethod
    def _operation_key(
        rule_id: SyncRuleId,
        source: EventRef,
        revision: str,
        action: SyncAction,
    ) -> str:
        raw = "|".join(
            (
                rule_id.value,
                source.calendar.connected_account_id.value,
                source.calendar.calendar_id.value,
                source.event_id.value,
                revision,
                action.value,
            )
        )
        return hashlib.sha256(raw.encode()).hexdigest()


def stored_fingerprint(value: str) -> ProjectionFingerprint:
    """Reconstitute a persisted fingerprint without exposing event content."""
    return ProjectionFingerprint(value)
