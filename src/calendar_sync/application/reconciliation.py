from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from calendar_sync.application.errors import ProviderFailure, RuleNotExecutable
from calendar_sync.application.locking import RuleLocks, RuleWork, RuleWorkKind
from calendar_sync.application.ports import (
    CalendarReader,
    Clock,
    FullPassRecords,
    RuleRunOutcome,
    RunKind,
    UnitOfWorkFactory,
)
from calendar_sync.application.synchronization import ExecuteSyncRule, SyncRunResult
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    CalendarEvent,
    EventMapping,
    EventMappingId,
    EventProjection,
    EventRef,
    EventStatus,
    OccurrenceCheck,
    OccurrenceMapping,
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
    locks: RuleLocks = field(default_factory=RuleLocks)

    def execute(self, rule_id: SyncRuleId) -> ReconciliationReport:
        work = RuleWork(RuleWorkKind.RECONCILIATION, self.clock.now())
        with self.locks.for_rule(rule_id), self.locks.working(rule_id, work):
            return self._execute_serialized(rule_id)

    def _execute_serialized(self, rule_id: SyncRuleId) -> ReconciliationReport:
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if rule is None:
                raise RuleNotExecutable(f"sync rule {rule_id.value} does not exist")
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
        self._record(
            RuleRunOutcome(
                rule.id,
                RunKind.RECONCILIATION,
                self.clock.now(),
                True,
                full_run=True,
                checked_mappings=report.checked_mappings,
                drift=len(report.drift),
            )
        )
        return report

    def _record(self, outcome: RuleRunOutcome) -> None:
        with self.unit_of_work() as uow:
            uow.run_outcomes.record(outcome)
            uow.commit()

    def _reconcile(
        self,
        rule: SyncRule,
        mappings: Sequence[EventMapping],
        recorded: Mapping[EventMappingId, Sequence[OccurrenceMapping]],
    ) -> ReconciliationReport:
        actual_events = self.provider.managed_events(rule.destination, rule.id)
        actual = {event.reference: event for event in actual_events}
        expected: dict[EventRef, EventProjection] = {}
        dormant: set[EventMappingId] = set()
        for mapping in mappings:
            source = self.provider.get_event(mapping.source)
            if source is None or not _eligible(source, rule):
                continue
            if self._dormant(rule, mapping, source, actual):
                # A series with no occurrence left to project has no projection to verify.
                dormant.add(mapping.id)
                continue
            expected[mapping.source] = self.projector.project(source, rule)
        verified = [mapping for mapping in mappings if mapping.id not in dormant]

        checks: list[OccurrenceCheck] = []
        for mapping in verified:
            if mapping.source not in expected:
                continue  # the series' own inconsistency is already reported
            for occurrence in recorded.get(mapping.id, ()):
                source = self.provider.get_occurrence(mapping.source, occurrence.original_start)
                checks.append(
                    OccurrenceCheck(
                        occurrence,
                        mapping.destination,
                        self.projector.project(source, rule)
                        if source is not None and _eligible(source, rule)
                        else None,
                        # A missing destination series is already reported for its mapping.
                        self.provider.get_occurrence(mapping.destination, occurrence.original_start)
                        if mapping.destination in actual
                        else None,
                    )
                )
        report = self.reconciliation.reconcile(rule, verified, expected, actual, checks)
        return replace(report, checked_mappings=len(mappings))

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
            or self.provider.has_live_occurrences(
                source.reference, include_all_day=rule.transformation.includes_all_day
            )
        ):
            return False
        destination = self.provider.get_event(mapping.destination)
        return destination is None or destination.status is EventStatus.CANCELLED


def _eligible(source: CalendarEvent, rule: SyncRule) -> bool:
    return (
        source.status is EventStatus.CONFIRMED
        and source.managed_origin is None
        and not (source.is_all_day and rule.transformation.all_day is AllDaySyncPolicy.EXCLUDE)
    )


@dataclass(frozen=True, slots=True)
class ReconcileNowResult:
    sync: SyncRunResult
    report: ReconciliationReport


@dataclass(slots=True)
class ReconcileNow:
    """Reconcile Now: a full pass, standing in for that day's scheduled one, then reconciliation.

    Like the scheduler's, the full-pass bookkeeping is best-effort and never aborts the run.
    """

    synchronize: ExecuteSyncRule
    reconcile: ReconcileSyncRule
    full_passes: FullPassRecords | None = None

    def execute(self, rule_id: SyncRuleId) -> ReconcileNowResult:
        floor = self._audit_floor()
        result = self.synchronize.execute(rule_id, full=True)
        # The full pass succeeded and counts as today's; reconciliation can still fail after.
        if floor is not None:
            self._record_full_pass(rule_id, floor, result.run_id)
        return ReconcileNowResult(result, self.reconcile.execute(rule_id))

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
