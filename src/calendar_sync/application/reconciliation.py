from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from calendar_sync.application.errors import ProviderFailure, RuleNotExecutable
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    CalendarProvider,
    Clock,
    RuleRunOutcome,
    RunKind,
    UnitOfWorkFactory,
)
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


@dataclass(slots=True)
class ReconcileSyncRule:
    unit_of_work: UnitOfWorkFactory
    provider: CalendarProvider
    projector: EventProjector
    reconciliation: ReconciliationService
    clock: Clock
    locks: RuleLocks = field(default_factory=RuleLocks)

    def execute(self, rule_id: SyncRuleId) -> ReconciliationReport:
        with self.locks.for_rule(rule_id):
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
        expected: dict[EventRef, EventProjection] = {}
        for mapping in mappings:
            source = self.provider.get_event(mapping.source)
            if source is not None and _eligible(source, rule):
                expected[mapping.source] = self.projector.project(source, rule)
        actual_events = self.provider.managed_events(rule.destination, rule.id)
        actual = {event.reference: event for event in actual_events}

        checks: list[OccurrenceCheck] = []
        for mapping in mappings:
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
        return self.reconciliation.reconcile(rule, mappings, expected, actual, checks)


def _eligible(source: CalendarEvent, rule: SyncRule) -> bool:
    return (
        source.status is EventStatus.CONFIRMED
        and source.managed_origin is None
        and not (source.is_all_day and rule.transformation.all_day is AllDaySyncPolicy.EXCLUDE)
    )
