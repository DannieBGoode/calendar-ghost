from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from calendar_sync.application.errors import RuleNotExecutable
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import CalendarProvider, Clock, UnitOfWorkFactory
from calendar_sync.domain.model import AllDaySyncPolicy, EventStatus, SyncRuleId, SyncRuleState
from calendar_sync.domain.services import EventProjector


@dataclass(frozen=True, slots=True)
class PreviewItem:
    source_event_id: str
    projected_title: str
    all_day: bool


@dataclass(frozen=True, slots=True)
class RulePreview:
    rule_id: SyncRuleId
    eligible_events: int
    excluded_events: int
    sample: tuple[PreviewItem, ...]


@dataclass(slots=True)
class PreviewSyncRule:
    unit_of_work: UnitOfWorkFactory
    provider: CalendarProvider
    projector: EventProjector
    clock: Clock
    locks: RuleLocks = field(default_factory=RuleLocks)

    def execute(self, rule_id: SyncRuleId) -> RulePreview:
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
        if rule is None:
            raise RuleNotExecutable(f"sync rule {rule_id.value} does not exist")
        if rule.state not in {
            SyncRuleState.DRAFT,
            SyncRuleState.PAUSED,
            SyncRuleState.DEGRADED,
        }:
            raise RuleNotExecutable(f"sync rule cannot preview from state {rule.state}")

        cutoff = self.clock.now() - timedelta(days=rule.initial_lookback_days)
        changes = self.provider.changes(rule.source, None, cutoff)
        eligible = []
        excluded = 0
        for event in changes.events:
            should_exclude = (
                event.managed_origin is not None
                or event.status is EventStatus.CANCELLED
                or event.recurrence is not None
                or event.occurrence is not None
                or (event.is_all_day and rule.transformation.all_day is AllDaySyncPolicy.EXCLUDE)
            )
            if should_exclude:
                excluded += 1
                continue
            projection = self.projector.project(event, rule)
            eligible.append(
                PreviewItem(
                    source_event_id=event.reference.event_id.value,
                    projected_title=projection.title,
                    all_day=event.is_all_day,
                )
            )

        with self.locks.for_writes(rule.id), self.unit_of_work() as uow:
            current = uow.rules.get(rule.id)
            if current is None or current.material_signature != rule.material_signature:
                raise RuleNotExecutable("sync rule changed while preview was running")
            uow.rules.save(current.mark_dry_run_validated())
            uow.commit()

        return RulePreview(rule.id, len(eligible), excluded, tuple(eligible[:10]))
