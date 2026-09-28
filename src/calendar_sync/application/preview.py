from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from calendar_sync.application.errors import RuleNotExecutable
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    CalendarProvider,
    Clock,
    RulePreviewSummary,
    UnitOfWork,
    UnitOfWorkFactory,
)
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    CalendarEvent,
    EventRef,
    EventStatus,
    SyncAction,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.domain.services import EventProjector, SyncDecisionService

_SAMPLE_SIZE = 10


@dataclass(frozen=True, slots=True)
class PreviewItem:
    source_event_id: str
    projected_title: str
    all_day: bool
    kind: str
    planned_action: SyncAction


@dataclass(frozen=True, slots=True)
class RulePreview:
    rule_id: SyncRuleId
    eligible_events: int
    excluded_events: int
    sample: tuple[PreviewItem, ...]
    recurring_series: int = 0
    occurrence_changes: int = 0


def _excluded(event: CalendarEvent, rule: SyncRule) -> bool:
    return (
        event.managed_origin is not None
        or event.status is EventStatus.CANCELLED
        or (event.is_all_day and rule.transformation.all_day is AllDaySyncPolicy.EXCLUDE)
    )


@dataclass(slots=True)
class PreviewSyncRule:
    unit_of_work: UnitOfWorkFactory
    provider: CalendarProvider
    projector: EventProjector
    clock: Clock
    decisions: SyncDecisionService
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
        events = self.provider.changes(rule.source, None, cutoff).events
        masters = {event.reference: event for event in events if event.occurrence is None}
        eligible: list[tuple[CalendarEvent, CalendarEvent | None]] = []
        excluded = series_count = occurrence_changes = 0
        for event in events:
            if event.occurrence is None:
                if _excluded(event, rule):
                    excluded += 1
                    continue
                series_count += event.recurrence is not None
                eligible.append((event, None))
                continue
            parent_ref = EventRef(rule.source, event.occurrence.series_event_id)
            parent = masters.get(parent_ref) or self.provider.get_event(parent_ref)
            if parent is None or _excluded(parent, rule):
                excluded += 1
                continue
            occurrence_changes += 1
            eligible.append((event, parent))

        with self.unit_of_work() as uow:
            sample = tuple(
                self._item(uow, rule, event, parent) for event, parent in eligible[:_SAMPLE_SIZE]
            )
        with self.locks.for_writes(rule.id), self.unit_of_work() as uow:
            current = uow.rules.get(rule.id)
            if current is None or current.material_signature != rule.material_signature:
                raise RuleNotExecutable("sync rule changed while preview was running")
            uow.rules.save(current.mark_dry_run_validated())
            uow.previews.record(
                RulePreviewSummary(
                    rule.id,
                    self.clock.now(),
                    len(eligible) - occurrence_changes,
                    excluded,
                    recurring_series=series_count,
                    occurrence_changes=occurrence_changes,
                )
            )
            uow.commit()

        return RulePreview(
            rule.id,
            len(eligible) - occurrence_changes,
            excluded,
            sample,
            recurring_series=series_count,
            occurrence_changes=occurrence_changes,
        )

    def _item(
        self, uow: UnitOfWork, rule: SyncRule, event: CalendarEvent, parent: CalendarEvent | None
    ) -> PreviewItem:
        """Plan one item with provider reads only; nothing is written."""
        title = self.projector.project(event, rule).title if event.time is not None else ""
        if parent is None:
            mapping = uow.mappings.for_source(rule.id, event.reference)
            actual = self.provider.get_event(mapping.destination) if mapping else None
            action = self.decisions.decide(rule, event, mapping, actual).action
            kind = "series" if event.recurrence is not None else "single"
            return PreviewItem(
                event.reference.event_id.value, title, event.is_all_day, kind, action
            )
        assert event.occurrence is not None
        start = event.occurrence.original_start
        series_mapping = uow.mappings.for_source(rule.id, parent.reference)
        if series_mapping is None:
            cancels = event.status is EventStatus.CANCELLED or (
                event.is_all_day and rule.transformation.all_day is AllDaySyncPolicy.EXCLUDE
            )
            action = SyncAction.DELETE if cancels else SyncAction.UPDATE
        else:
            destination_series = self.provider.get_event(series_mapping.destination)
            destination = (
                self.provider.get_occurrence(series_mapping.destination, start)
                if destination_series is not None
                and destination_series.status is EventStatus.CONFIRMED
                else None
            )
            action = self.decisions.decide_occurrence(
                rule,
                parent,
                series_mapping,
                start,
                event,
                uow.occurrences.get(series_mapping.id, start),
                destination_series,
                destination,
            ).action
        return PreviewItem(
            event.reference.event_id.value, title, event.is_all_day, "occurrence", action
        )
