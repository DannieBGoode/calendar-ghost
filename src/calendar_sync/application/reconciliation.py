from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from calendar_sync.application.errors import (
    ProviderFailure,
    ProviderFailureKind,
    RuleNotExecutable,
    RuleNotFound,
)
from calendar_sync.application.locking import RuleLocks, RuleWork, RuleWorkKind
from calendar_sync.application.ports import (
    AuditAction,
    AuditEntry,
    AuditOutcome,
    CalendarReader,
    Clock,
    FullPassRecords,
    ProviderCallStats,
    RuleRunOutcome,
    RunIdGenerator,
    RunKind,
    UnitOfWorkFactory,
)
from calendar_sync.application.run_log import UntalliedProviderCalls, call_summary, duration
from calendar_sync.application.synchronization import ExecuteSyncRule, SyncRunResult
from calendar_sync.domain.model import (
    CalendarEvent,
    EventMapping,
    EventMappingId,
    EventProjection,
    EventRef,
    EventStatus,
    NoProjectionExpected,
    OccurrenceCheck,
    OccurrenceMapping,
    OccurrenceStart,
    ReconciliationReport,
    SyncRule,
    SyncRuleId,
)
from calendar_sync.domain.services import EventProjector, ReconciliationService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReconcileSyncRule:
    unit_of_work: UnitOfWorkFactory
    provider: CalendarReader
    projector: EventProjector
    reconciliation: ReconciliationService
    clock: Clock
    run_ids: RunIdGenerator
    locks: RuleLocks = field(default_factory=RuleLocks)
    call_stats: ProviderCallStats = field(default_factory=UntalliedProviderCalls)

    def execute(
        self,
        rule_id: SyncRuleId,
        *,
        run_id: str | None = None,
        already_blocked: AbstractSet[EventRef] = frozenset(),
        work: RuleWork | None = None,
    ) -> ReconciliationReport:
        """Verify every mapping and record each conflict found as a blocked Audit Entry.

        `already_blocked` names sources a Sync Run just blocked, so none is reported twice, and
        `run_id` files the entries under that run. `work` is the larger work this check is part
        of, which its caller reports.
        """
        started = self.clock.now()
        reported = nullcontext() if work else None
        work = work or RuleWork(RuleWorkKind.RECONCILIATION, started)
        with (
            self.locks.for_rule(rule_id),
            reported or self.locks.working(rule_id, work),
            self.call_stats.measure() as calls,
        ):
            run = run_id or self.run_ids.new_run_id()
            names = f"rule={rule_id.value} run={run}"
            logger.info("reconciliation started %s", names)
            try:
                report = self._execute_serialized(rule_id, run, already_blocked)
            except RuleNotExecutable:
                raise
            except Exception as error:
                kind = (
                    error.kind
                    if isinstance(error, ProviderFailure)
                    else ProviderFailureKind.INFRASTRUCTURE
                )
                logger.warning(
                    "reconciliation failed %s kind=%s after %s %s",
                    names,
                    kind.value,
                    duration(self.clock.now() - started),
                    call_summary(calls),
                )
                raise
            logger.info(
                "reconciliation finished %s in %s checked=%d drift=%d conflicts=%d %s",
                names,
                duration(self.clock.now() - started),
                report.checked_mappings,
                len(report.drift),
                len(report.conflicts),
                call_summary(calls),
            )
            return report

    def _execute_serialized(
        self, rule_id: SyncRuleId, run_id: str, already_blocked: AbstractSet[EventRef]
    ) -> ReconciliationReport:
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if rule is None:
                raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
            mappings = uow.mappings.for_rule(rule.id)
            recorded = {mapping.id: uow.occurrences.for_series(mapping.id) for mapping in mappings}

        try:
            report = self._reconcile(rule, mappings, recorded)
        except ProviderFailure as failure:
            self._record(
                RuleRunOutcome(
                    rule.id,
                    RunKind.RECONCILIATION,
                    self.clock.now(),
                    False,
                    full_run=True,
                    failure_kind=failure.kind.value,
                )
            )
            raise
        report = report.excluding(already_blocked)
        self._record(
            RuleRunOutcome(
                rule.id,
                RunKind.RECONCILIATION,
                self.clock.now(),
                True,
                full_run=True,
                conflicts=len(report.conflicts),
                checked_mappings=report.checked_mappings,
                drift=len(report.drift),
            ),
            [
                AuditEntry(
                    occurred_at=self.clock.now(),
                    rule_id=rule.id,
                    action=AuditAction.CONFLICT,
                    outcome=AuditOutcome.BLOCKED,
                    source_event_id=conflict.source.event_id.value if conflict.source else None,
                    destination_event_id=(
                        conflict.destination.event_id.value if conflict.destination else None
                    ),
                    detail=conflict.detail,
                    reason=conflict.reason,
                    run_id=run_id,
                )
                for conflict in report.conflicts
            ],
        )
        return report

    def _record(self, outcome: RuleRunOutcome, entries: Sequence[AuditEntry] = ()) -> None:
        with self.unit_of_work() as uow:
            for entry in entries:
                uow.audit.append(entry)
            uow.run_outcomes.record(outcome)
            uow.commit()

    def _reconcile(
        self,
        rule: SyncRule,
        mappings: Sequence[EventMapping],
        recorded: Mapping[EventMappingId, Sequence[OccurrenceMapping]],
    ) -> ReconciliationReport:
        """Verify the mappings whose source or projection reaches the rule's sync window.

        That is the range the daily pass keeps current, from the Initial Sync Window's start
        onward; an event that ended before it is past and is neither read nor reported. A series
        reaches the window while any of its occurrences does, however long ago it began.
        """
        window_start = self.clock.now() - timedelta(days=rule.initial_lookback_days)
        listed = {
            event.reference: event for event in self.provider.list_events(rule.source, window_start)
        }
        actual = {
            event.reference: event
            for event in self.provider.managed_events(rule.destination, rule.id, window_start)
        }
        checked: list[EventMapping] = []
        expected: dict[EventRef, EventProjection | NoProjectionExpected] = {}
        dormant: set[EventMappingId] = set()
        for mapping in mappings:
            if not mapping.belongs_to(rule):
                # A Conflict whatever the event's age, and proven without reading either side.
                checked.append(mapping)
                continue
            source = listed.get(mapping.source)
            if source is None and mapping.destination not in actual:
                continue  # neither the source nor its projection reaches the window
            checked.append(mapping)
            if source is None:
                # Listed only in the destination: moved out of the window, or gone for good.
                source = self.provider.get_event(mapping.source)
            if source is None:
                continue  # an unreadable source is a Conflict, never permission to delete
            expectation = self._expectation(source, rule)
            if isinstance(expectation, EventProjection) and self._dormant(
                rule, mapping, source, actual
            ):
                # A series with no occurrence left to project has no projection to verify.
                dormant.add(mapping.id)
                continue
            expected[mapping.source] = expectation
        verified = [mapping for mapping in checked if mapping.id not in dormant]
        checks = self._occurrence_checks(
            rule, verified, expected, recorded, _Window(window_start, listed, actual)
        )
        report = self.reconciliation.reconcile(rule, verified, expected, actual, checks)
        return replace(report, checked_mappings=len(checked))

    def _expectation(
        self, source: CalendarEvent, rule: SyncRule
    ) -> EventProjection | NoProjectionExpected:
        if source.managed_origin is not None:
            return NoProjectionExpected.MANAGED_SOURCE
        if not _eligible(source, rule):
            return NoProjectionExpected.INELIGIBLE
        return self.projector.project(source, rule)

    def _occurrence_checks(
        self,
        rule: SyncRule,
        verified: Sequence[EventMapping],
        expected: Mapping[EventRef, EventProjection | NoProjectionExpected],
        recorded: Mapping[EventMappingId, Sequence[OccurrenceMapping]],
        window: _Window,
    ) -> list[OccurrenceCheck]:
        """Checks for the recorded occurrences in the window, reusing the listings' exceptions."""
        checks: list[OccurrenceCheck] = []
        for mapping in verified:
            if not isinstance(expected.get(mapping.source), EventProjection):
                continue  # the series' own finding already covers its occurrences
            for occurrence in recorded.get(mapping.id, ()):
                start = occurrence.original_start
                listed = window.source_exceptions.get((mapping.source, start))
                if not (
                    listed is not None
                    or window.starts_within(start)
                    or (mapping.destination, start) in window.destination_exceptions
                ):
                    continue  # a past occurrence of a series that is still current
                source = (
                    listed
                    if listed is not None
                    else self.provider.get_occurrence(mapping.source, start)
                )
                checks.append(
                    OccurrenceCheck(
                        occurrence,
                        mapping.destination,
                        self.projector.project(source, rule)
                        if source is not None and _eligible(source, rule)
                        else None,
                        # A missing destination series is already reported for its mapping.
                        self.provider.get_occurrence(mapping.destination, start)
                        if mapping.destination in window.destinations
                        else None,
                    )
                )
        return checks

    def _dormant(
        self,
        rule: SyncRule,
        mapping: EventMapping,
        source: CalendarEvent,
        actual: Mapping[EventRef, CalendarEvent],
    ) -> bool:
        """A consistent Series Mapping whose projection is gone because nothing is left to show.

        Absence from the managed listing alone is not enough: a projection that lost its ownership
        metadata is still there and must be reported.
        """
        if (
            source.recurrence is None
            or mapping.destination in actual
            or not mapping.belongs_to(rule)
            or self.provider.has_live_occurrences(source.reference, rule.transformation)
        ):
            return False
        destination = self.provider.get_event(mapping.destination)
        return destination is None or destination.status is EventStatus.CANCELLED


class _Window:
    """What the reconciliation listed from the rule's sync window onward."""

    def __init__(
        self,
        start: datetime,
        sources: Mapping[EventRef, CalendarEvent],
        destinations: Mapping[EventRef, CalendarEvent],
    ) -> None:
        self.start = start
        self.destinations = destinations
        self.source_exceptions = _exceptions(sources.values())
        self.destination_exceptions = _exceptions(destinations.values())

    def starts_within(self, original_start: OccurrenceStart) -> bool:
        if isinstance(original_start, datetime):
            return original_start >= self.start
        return original_start >= self.start.date()


def _exceptions(
    events: Iterable[CalendarEvent],
) -> dict[tuple[EventRef, OccurrenceStart], CalendarEvent]:
    """Listed occurrence exceptions, keyed by their series and original start."""
    return {
        (
            EventRef(event.reference.calendar, event.occurrence.series_event_id),
            event.occurrence.original_start,
        ): event
        for event in events
        if event.occurrence is not None
    }


def _eligible(source: CalendarEvent, rule: SyncRule) -> bool:
    return (
        source.status is EventStatus.CONFIRMED
        and source.managed_origin is None
        and rule.transformation.exclusion(source) is None
    )


@dataclass(frozen=True, slots=True)
class ReconcileNowResult:
    sync: SyncRunResult
    report: ReconciliationReport


@dataclass(slots=True)
class ReconcileNow:
    """Reconcile Now: a full pass, standing in for that day's scheduled one, then reconciliation.

    The full pass repairs the drift it reaches; the reconciliation after it only reports what is
    still different, and records its conflicts under the pass's run, leaving out any event the
    pass already blocked. Like the scheduler's, the full-pass bookkeeping is best-effort and never
    aborts the run.
    """

    synchronize: ExecuteSyncRule
    reconcile: ReconcileSyncRule
    full_passes: FullPassRecords | None = None

    def execute(self, rule_id: SyncRuleId) -> ReconcileNowResult:
        work = RuleWork(
            RuleWorkKind.RECONCILIATION, self.synchronize.clock.now(), stage=RuleWorkKind.SYNC
        )
        # Reported from start to finish, so a reload between the stages still sees it.
        with self.synchronize.locks.working(rule_id, work):
            floor = self._audit_floor()
            result = self.synchronize.execute(rule_id, full=True, work=work)
            # The full pass succeeded and counts as today's; reconciliation can still fail after.
            if floor is not None:
                self._record_full_pass(rule_id, floor, result.run_id)
            work.begin_stage(RuleWorkKind.RECONCILIATION)
            report = self.reconcile.execute(
                rule_id, run_id=result.run_id, already_blocked=result.blocked, work=work
            )
        return ReconcileNowResult(result, report)

    def _audit_floor(self) -> int | None:
        if self.full_passes is None:
            return None
        try:
            return self.full_passes.audit_floor()
        except Exception:
            logger.exception("Could not read the audit position before Reconcile Now")
            return None

    def _record_full_pass(self, rule_id: SyncRuleId, floor: int, run_id: str | None) -> None:
        assert self.full_passes is not None
        try:
            self.full_passes.record_full_pass(rule_id, floor, run_id)
        except Exception:
            logger.exception("Could not record block health for rule %s", rule_id.value)
