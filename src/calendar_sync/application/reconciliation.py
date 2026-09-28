from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from calendar_sync.application.errors import ProviderFailure, RuleNotExecutable
from calendar_sync.application.ports import (
    CalendarProvider,
    Clock,
    RuleRunOutcome,
    RunKind,
    UnitOfWorkFactory,
)
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    EventMapping,
    EventProjection,
    EventRef,
    EventStatus,
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

    def execute(self, rule_id: SyncRuleId) -> ReconciliationReport:
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if rule is None:
                raise RuleNotExecutable(f"sync rule {rule_id.value} does not exist")
            mappings = uow.mappings.for_rule(rule.id)

        try:
            report = self._reconcile(rule, mappings)
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

    def _reconcile(self, rule: SyncRule, mappings: Sequence[EventMapping]) -> ReconciliationReport:
        expected: dict[EventRef, EventProjection] = {}
        for mapping in mappings:
            source = self.provider.get_event(mapping.source)
            if (
                source is not None
                and source.status is EventStatus.CONFIRMED
                and source.managed_origin is None
                and not (
                    source.is_all_day and rule.transformation.all_day is AllDaySyncPolicy.EXCLUDE
                )
            ):
                expected[mapping.source] = self.projector.project(source, rule)
        actual_events = self.provider.managed_events(rule.destination, rule.id)
        actual = {event.reference: event for event in actual_events}
        return self.reconciliation.reconcile(rule, mappings, expected, actual)
