from __future__ import annotations

from contextlib import nullcontext, suppress
from dataclasses import dataclass, field

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.change_feeds import ChangeFeedCursors
from calendar_sync.application.sync.errors import (
    ProviderFailure,
    RuleNotExecutable,
    RuleNotFound,
    UnsupportedProjection,
)
from calendar_sync.application.sync.event_sync import SynchronizeEvents, event_operation_key
from calendar_sync.application.sync.exception_replays import ExceptionReplays
from calendar_sync.application.sync.locking import RuleLocks, RuleWork, RuleWorkKind
from calendar_sync.application.sync.occurrences import SeriesRepairs, SynchronizeOccurrences
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
    record,
    require_unchanged,
)
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.audit import AuditAction, AuditEntry, AuditOutcome, RecordedEvent
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.model import (
    CalendarEvent,
    EventRef,
    EventStatus,
    ProjectionFingerprint,
    SyncAction,
    SyncDecision,
    SyncReason,
    SyncRule,
    SyncRuleId,
)
from calendar_sync.domain.providers import ProviderFailureKind
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
    if not rule.synchronizes:
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
    locks: RuleLocks
    call_stats: ProviderCallStats = field(default_factory=UntalliedProviderCalls)
    change_feeds: ChangeFeedCursors = field(init=False, repr=False)
    events: SynchronizeEvents = field(init=False, repr=False)
    occurrences: SynchronizeOccurrences = field(init=False, repr=False)
    exception_replays: ExceptionReplays = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.change_feeds = ChangeFeedCursors(self.provider, self.clock, self.run_ids, self.locks)
        self.events = SynchronizeEvents(
            self.provider, self.decisions, self.fingerprinter, self.clock
        )
        self.occurrences = SynchronizeOccurrences(
            self.provider,
            self.provider,
            self.decisions,
            self.fingerprinter,
            self.clock,
            SeriesRepairs(self._repair_series, self._rebuild_series),
            self.locks,
        )
        self.exception_replays = ExceptionReplays(self.provider, self.occurrences)

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
            self._record_failure(
                rule_id, full, failure.kind, failure.provider_cause, failure.provider
            )
            raise
        except Exception:
            log.failed(ProviderFailureKind.INFRASTRUCTURE.value)
            # A local failure: no provider refused, so it has no Cause.
            self._record_failure(rule_id, full, ProviderFailureKind.INFRASTRUCTURE)
            raise

    def _record_failure(
        self,
        rule_id: SyncRuleId,
        full: bool,
        kind: ProviderFailureKind,
        cause: Cause | None = None,
        provider: ProviderKind | None = None,
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
                        failure_provider=provider,
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
            self.exception_replays.finish_pending(run)
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

    def _rebuild_series(
        self, run: SyncRunContext, source_series: CalendarEvent
    ) -> SyncReason | None:
        """Delete the destination series and write it again from the source, with its moved and
        cancelled occurrences, to bring back an occurrence its provider cannot restore (ADR 0034).

        Deleting it is guarded as any deletion is, so a series someone invited guests to is not
        rebuilt; the answer is then why, and None once the series is written again.
        """
        run.rebuilt.add(source_series.reference)
        with self.locks.for_writes(run.rule.id):
            require_unchanged(run)
            mapping = run.uow.mappings.for_source(run.rule.id, source_series.reference)
            if mapping is None:
                return SyncReason.OCCURRENCE_NOT_RESTORABLE
            try:
                self.provider.delete_projection(
                    mapping.destination,
                    source_series.reference,
                    run.rule.id,
                    event_operation_key(
                        run.rule.id,
                        source_series.reference,
                        source_series.revision,
                        SyncAction.DELETE,
                    ),
                )
            except UnsupportedProjection as unsupported:
                return unsupported.reason
            run.count(SyncAction.DELETE, source_series.reference)
            record(
                run,
                AuditEntry(
                    occurred_at=self.clock.now(),
                    rule_id=run.rule.id,
                    action=AuditAction.of(SyncAction.DELETE),
                    outcome=AuditOutcome.of(SyncAction.DELETE),
                    source_event_id=source_series.reference.event_id.value,
                    destination_event_id=mapping.destination.event_id.value,
                    reason=SyncReason.SERIES_REBUILT,
                    run_id=run.run_id,
                    event=RecordedEvent.of(source_series),
                ),
            )
            run.uow.commit()
        # Found missing, the series is written again and every recorded occurrence re-applied,
        # including those this run checked against the series just deleted.
        for recorded in run.uow.occurrences.for_series(mapping.id):
            run.handled.discard(recorded.source)
        self._synchronize_event(
            run, source_series, destination_loaded=False, actual_destination=None
        )
        return None

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
            mapping, decision, source_moved = self.events.decide_and_write(
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
            self.exception_replays.replay(run, mapping, source_event)
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


def stored_fingerprint(value: str) -> ProjectionFingerprint:
    """Reconstitute a persisted fingerprint without exposing event content."""
    return ProjectionFingerprint(value)
