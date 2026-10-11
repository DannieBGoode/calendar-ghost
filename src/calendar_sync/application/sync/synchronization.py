from __future__ import annotations

import hashlib
from contextlib import nullcontext, suppress
from dataclasses import dataclass, field

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.change_feeds import ChangeFeedCursors
from calendar_sync.application.sync.errors import (
    ProviderFailure,
    ProviderFailureKind,
    RuleNotExecutable,
    RuleNotFound,
)
from calendar_sync.application.sync.locking import RuleLocks, RuleWork, RuleWorkKind
from calendar_sync.application.sync.occurrences import SynchronizeOccurrences
from calendar_sync.application.sync.own_writes import is_own_occurrence_write, is_own_write
from calendar_sync.application.sync.ports import (
    CalendarProvider,
    ProviderCallStats,
    ProviderCallTally,
    ProviderChangeSet,
    RunIdGenerator,
    UnitOfWork,
    UnitOfWorkFactory,
)
from calendar_sync.application.sync.resource_use import record_provider_calls
from calendar_sync.application.sync.run_log import UntalliedProviderCalls
from calendar_sync.application.sync.sync_run import (
    SyncRunContext,
    SyncRunLog,
    has_live_occurrences,
    record,
    require_unchanged,
)
from calendar_sync.domain.audit import AuditAction, AuditEntry, AuditOutcome, RecordedEvent
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.model import (
    CalendarEvent,
    EventMapping,
    EventMappingId,
    EventRef,
    EventStatus,
    ProjectionFingerprint,
    SyncAction,
    SyncDecision,
    SyncReason,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.domain.runs import RuleRunOutcome, RunKind
from calendar_sync.domain.services import ProjectionFingerprinter, SyncDecisionService


@dataclass(frozen=True, slots=True)
class SyncRunResult:
    rule_id: SyncRuleId
    created: int = 0
    updated: int = 0
    deleted: int = 0
    ignored: int = 0
    conflicts: int = 0
    run_id: str | None = None
    """Identifies this run's Audit Entries."""
    listed_in_full: bool = False
    """Both calendars were listed in full, so every event in the window was decided again."""
    blocked: frozenset[EventRef] = frozenset()
    """Source events and occurrences this run blocked, each already recorded as an Audit Entry."""


def _executable_rule(uow: UnitOfWork, rule_id: SyncRuleId) -> SyncRule:
    rule = uow.rules.get(rule_id)
    if rule is None:
        raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
    if rule.state is not SyncRuleState.ENABLED:
        raise RuleNotExecutable(f"sync rule is {rule.state}, not enabled")
    # The scheduler lists rules before it runs them, so a User disabled since is caught here.
    if not uow.user_active():
        raise RuleNotExecutable("the rule's User is disabled")
    return rule


@dataclass(slots=True)
class ExecuteSyncRule:
    unit_of_work: UnitOfWorkFactory
    provider: CalendarProvider
    decisions: SyncDecisionService
    fingerprinter: ProjectionFingerprinter
    clock: Clock
    run_ids: RunIdGenerator
    locks: RuleLocks = field(default_factory=RuleLocks)
    call_stats: ProviderCallStats = field(default_factory=UntalliedProviderCalls)
    occurrences: SynchronizeOccurrences = field(init=False, repr=False)
    change_feeds: ChangeFeedCursors = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.change_feeds = ChangeFeedCursors(self.provider, self.clock, self.run_ids, self.locks)
        self.occurrences = SynchronizeOccurrences(
            self.provider,
            self.provider,
            self.decisions,
            self.fingerprinter,
            self.clock,
            self._repair_series,
            self.locks,
        )

    def execute(
        self, rule_id: SyncRuleId, *, full: bool = False, work: RuleWork | None = None
    ) -> SyncRunResult:
        """Run once; `work` is the larger work this run is part of, which its caller reports."""
        reported = nullcontext() if work else None
        work = work or RuleWork(RuleWorkKind.SYNC, self.clock.now())
        with (
            self.locks.for_rule(rule_id),
            reported or self.locks.working(rule_id, work),
            self.call_stats.measure() as calls,
        ):
            try:
                return self._execute_measured(rule_id, full, work, calls)
            finally:
                record_provider_calls(self.unit_of_work, self.clock, calls)

    def _execute_measured(
        self, rule_id: SyncRuleId, full: bool, work: RuleWork, calls: ProviderCallTally
    ) -> SyncRunResult:
        log = SyncRunLog(rule_id, self.clock, calls, work.started_at)
        try:
            return self._execute_serialized(rule_id, full=full, log=log, work=work)
        except RuleNotExecutable:
            log.stopped()
            raise
        except ProviderFailure as failure:
            log.failed(failure.kind.value)
            self._record_failure(rule_id, full, failure.kind.value, failure.provider_cause)
            raise
        except Exception:
            log.failed(ProviderFailureKind.INFRASTRUCTURE.value)
            # A local failure: no provider refused, so it has no Cause.
            self._record_failure(rule_id, full, ProviderFailureKind.INFRASTRUCTURE.value, None)
            raise

    def _record_failure(
        self, rule_id: SyncRuleId, full: bool, kind: str, cause: Cause | None
    ) -> None:
        # Recording evidence must never replace the failure the scheduler classifies.
        with suppress(Exception), self.unit_of_work() as uow:
            if uow.rules.get(rule_id) is not None:
                uow.run_outcomes.record(
                    RuleRunOutcome(
                        rule_id,
                        RunKind.SYNC,
                        self.clock.now(),
                        False,
                        full,
                        failure_kind=kind,
                        failure_cause=cause,
                    )
                )
                uow.commit()

    def _execute_serialized(
        self, rule_id: SyncRuleId, *, full: bool, log: SyncRunLog, work: RuleWork
    ) -> SyncRunResult:
        with self.unit_of_work() as uow:
            rule = _executable_rule(uow, rule_id)
            run, feeds = self.change_feeds.begin(uow, rule, full=full, log=log, work=work)
            self._synchronize_sources(run, feeds.source)
            self._repair_destinations(run, feeds.destination)
            if run.reproject:
                self._reproject_remaining(run)
            self._finish_pending_replays(run)
            self.change_feeds.advance(run, feeds)
        log.finished(run.counts)

        counts = run.counts
        return SyncRunResult(
            rule_id=rule_id,
            created=counts[SyncAction.CREATE],
            updated=counts[SyncAction.UPDATE],
            deleted=counts[SyncAction.DELETE],
            ignored=counts[SyncAction.IGNORE],
            conflicts=counts[SyncAction.CONFLICT],
            run_id=run.run_id,
            listed_in_full=feeds.listed_in_full,
            blocked=frozenset(run.blocked),
        )

    def _synchronize_sources(self, run: SyncRunContext, changes: ProviderChangeSet) -> None:
        """Apply the source batch, committing after each event."""
        # Series masters first, so an exception can always resolve its parent's mapping.
        for source_event in sorted(changes.events, key=lambda item: item.occurrence is not None):
            if source_event.occurrence is not None:
                self._synchronize_source_exception(run, source_event)
            else:
                self._synchronize_event(
                    run, source_event, destination_loaded=False, actual_destination=None
                )
                run.handled.add(source_event.reference)
            run.uow.commit()
            run.handled_one()

    def _repair_destinations(self, run: SyncRunContext, changes: ProviderChangeSet) -> None:
        """Repair drift the destination feed reports on projections the source batch left alone."""
        for destination_event in changes.events:
            if destination_event.occurrence is not None:
                self._repair_destination_occurrence(run, destination_event)
                run.uow.commit()
            else:
                self._repair_destination_event(run, destination_event)
            run.handled_one()

    def _repair_destination_event(
        self, run: SyncRunContext, destination_event: CalendarEvent
    ) -> None:
        mapping = run.uow.mappings.for_destination(run.rule.id, destination_event.reference)
        if mapping is None or mapping.source in run.handled:
            return
        if is_own_write(run, self.fingerprinter, mapping, destination_event):
            run.count(SyncAction.IGNORE, mapping.source)
            return
        authoritative_source = self.provider.get_event(mapping.source)
        if authoritative_source is None:
            self._record_unverifiable(run, mapping.source, mapping.destination)
        else:
            self._synchronize_event(
                run,
                authoritative_source,
                destination_loaded=True,
                actual_destination=(
                    None if destination_event.status is EventStatus.CANCELLED else destination_event
                ),
            )
            run.handled.add(mapping.source)
        run.uow.commit()

    def _reproject_remaining(self, run: SyncRunContext) -> None:
        """Apply a changed policy to mappings the change feeds did not report."""
        remaining = [
            mapping
            for mapping in run.uow.mappings.for_rule(run.rule.id)
            if mapping.source not in run.handled
        ]
        if run.log is not None:
            run.log.reprojecting(len(remaining))
        run.expect(len(remaining))
        for mapping in remaining:
            # Applying an earlier series can handle a later mapping's source.
            if mapping.source not in run.handled:
                authoritative_source = self.provider.get_event(mapping.source)
                if authoritative_source is None:
                    self._record_unverifiable(run, mapping.source, mapping.destination)
                else:
                    # Reprojection re-verifies every recorded occurrence of a series as well.
                    self._synchronize_event(
                        run,
                        authoritative_source,
                        destination_loaded=False,
                        actual_destination=None,
                    )
                run.handled.add(mapping.source)
                run.uow.commit()
            run.handled_one()

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
        if is_own_occurrence_write(run, self.fingerprinter, series_mapping, destination_event):
            run.count(SyncAction.IGNORE, series_mapping.source)
            return
        if (series_mapping.source, identity.original_start) in run.handled_occurrences:
            # Already decided this run from its source; a full listing reports every exception.
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
        run.count(SyncAction.IGNORE, exception.reference)
        record(
            run,
            AuditEntry(
                occurred_at=self.clock.now(),
                rule_id=run.rule.id,
                action=AuditAction.IGNORE,
                outcome=AuditOutcome.SKIPPED,
                source_event_id=exception.reference.event_id.value,
                reason=SyncReason.SERIES_NOT_SYNCHRONIZED,
                run_id=run.run_id,
                event=RecordedEvent.of(exception),
            ),
        )

    def _record_unverifiable(
        self, run: SyncRunContext, source: EventRef, destination: EventRef | None
    ) -> None:
        run.count(SyncAction.CONFLICT, source)
        run.uow.audit.append(
            AuditEntry(
                occurred_at=self.clock.now(),
                rule_id=run.rule.id,
                action=AuditAction.CONFLICT,
                outcome=AuditOutcome.BLOCKED,
                source_event_id=source.event_id.value,
                destination_event_id=destination.event_id.value if destination else None,
                reason=SyncReason.SOURCE_UNVERIFIABLE,
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
            mapping, decision, source_moved = self._decide_and_write(
                run,
                source_event,
                destination_loaded=destination_loaded,
                actual_destination=actual_destination,
                record_current=record_current,
            )
        # Occurrence re-verification takes the write lock per occurrence, so it runs outside it.
        # A new series revision can change its occurrences even when the series needs no write.
        series_changed = decision.action in {SyncAction.CREATE, SyncAction.UPDATE} or (
            source_moved and decision.reason is SyncReason.PROJECTION_CURRENT
        )
        if (
            mapping is not None
            and decision.action is not SyncAction.DELETE
            and (series_changed or (run.reproject and decision.action is SyncAction.IGNORE))
        ):
            self.occurrences.reverify(run, mapping, source_event)
            if source_event.recurrence is not None:
                self._complete_series_revision(run, source_event)
        if (
            mapping is not None
            and decision.action is SyncAction.CREATE
            and source_event.recurrence is not None
            and not run.source_listed
        ):
            self._replay_exceptions(run, mapping, source_event)
        return decision

    def _complete_series_revision(self, run: SyncRunContext, source_series: CalendarEvent) -> None:
        """Record a series' new revision once every Occurrence Mapping was re-verified under it."""
        with self.locks.for_writes(run.rule.id):
            require_unchanged(run)
            mapping = run.uow.mappings.for_source(run.rule.id, source_series.reference)
            if mapping is None or mapping.source_revision == source_series.revision:
                return
            run.uow.mappings.save(mapping.confirm_revision(source_series.revision))
            run.uow.commit()

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
        pending = run.uow.replays.pending(run.rule.id)
        if pending and run.log is not None:
            run.log.replaying(len(pending))
        for mapping in pending:
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
        mapping = self._write(run, source_event, mapping, decision, source_moved=source_moved)
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
        operation_key = self._operation_key(
            rule.id, source_event.reference, source_event.revision, decision.action
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


_DESTINATION_WRITES = frozenset({SyncAction.CREATE, SyncAction.UPDATE, SyncAction.DELETE})


def stored_fingerprint(value: str) -> ProjectionFingerprint:
    """Reconstitute a persisted fingerprint without exposing event content."""
    return ProjectionFingerprint(value)
