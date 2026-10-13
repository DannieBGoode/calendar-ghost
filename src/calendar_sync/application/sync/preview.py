from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.errors import ProviderFailure, RuleNotExecutable, RuleNotFound
from calendar_sync.application.sync.locking import RuleLocks, RuleWork, RuleWorkKind
from calendar_sync.application.sync.ports import (
    CalendarReader,
    RecoveryIncidents,
    RulePreviewSummary,
    UnitOfWork,
    UnitOfWorkFactory,
)
from calendar_sync.domain.model import (
    CalendarEvent,
    EventMapping,
    EventRef,
    EventStatus,
    OccurrenceSituation,
    Recurrence,
    SyncAction,
    SyncDecision,
    SyncReason,
    SyncRule,
    SyncRuleId,
)
from calendar_sync.domain.services import EventProjector, SyncDecisionService

PreviewItemKind = Literal["single", "series", "occurrence"]


@dataclass(frozen=True, slots=True)
class PreviewProjection:
    """What the destination would hold for one previewed event, as the policy writes it."""

    title: str
    carries_details: bool
    """Whether it copies a description or location, as only a Details Projection can."""
    recurrence: Recurrence | None


@dataclass(frozen=True, slots=True)
class PreviewItem:
    """One source event beside what the rule would do with it.

    Its content goes to the person who asked for the preview and is never stored.
    """

    source: CalendarEvent
    kind: PreviewItemKind
    planned_action: SyncAction
    reason: SyncReason
    projection: PreviewProjection | None
    """What the destination would hold; None when it would hold nothing for this event."""


@dataclass(frozen=True, slots=True)
class RulePreview:
    rule_id: SyncRuleId
    eligible_events: int
    excluded_events: int
    items: tuple[PreviewItem, ...]
    recurring_series: int = 0
    occurrence_changes: int = 0


@dataclass(slots=True)
class _PreviewScope:
    """Every listed source event, each with its parent series if an occurrence, and whether the
    rule projects it."""

    listed: list[tuple[CalendarEvent, CalendarEvent | None, bool]] = field(default_factory=list)
    live: dict[EventRef, bool] = field(default_factory=dict)
    excluded: int = 0
    series_count: int = 0
    occurrence_changes: int = 0

    @property
    def eligible_events(self) -> int:
        """Events and series; occurrence changes are counted on their own."""
        included = sum(1 for _event, _parent, projects in self.listed if projects)
        return included - self.occurrence_changes


@dataclass(frozen=True, slots=True)
class _Destination:
    """What the rule already wrote: its mappings and Managed Projections, each read once. A
    projection missing from the listing is read alone, so one deleted in the destination plans
    exactly as a Sync Run would."""

    provider: CalendarReader
    mappings: Mapping[EventRef, EventMapping]
    listed: Mapping[EventRef, CalendarEvent]

    def mapping(self, source: EventRef) -> EventMapping | None:
        return self.mappings.get(source)

    def get(self, reference: EventRef) -> CalendarEvent | None:
        """The projection, or None when it is gone; a cancelled one is gone, as a Sync Run reads
        it, so the run would write it again."""
        found = self.listed.get(reference)
        event = found if found is not None else self.provider.get_event(reference)
        return None if event is None or event.status is EventStatus.CANCELLED else event


@dataclass(slots=True)
class PreviewSyncRule:
    unit_of_work: UnitOfWorkFactory
    provider: CalendarReader
    projector: EventProjector
    clock: Clock
    decisions: SyncDecisionService
    locks: RuleLocks
    incidents: RecoveryIncidents | None = None

    def execute(self, rule_id: SyncRuleId) -> RulePreview:
        with self.locks.working(rule_id, RuleWork(RuleWorkKind.PREVIEW, self.clock.now())):
            return self._execute(rule_id)

    def _execute(self, rule_id: SyncRuleId) -> RulePreview:
        rule = self._previewable_rule(rule_id)
        started = self.clock.now()
        try:
            scope, items = self._read(rule)
        except ProviderFailure as failure:
            # Lost authorization a preview meets on either account lapses that account, so
            # Settings and the rule point at the account to reauthorize (ADR 0027).
            if failure.requires_authorization and self.incidents is not None:
                self.incidents.recovery_blocked(rule.id, failure, attempted_at=started)
            raise
        with self.locks.for_writes(rule.id), self.unit_of_work() as uow:
            current = uow.rules.get(rule.id)
            if current is None or current.material_signature != rule.material_signature:
                raise RuleNotExecutable("sync rule changed while preview was running")
            uow.rules.save(current.mark_previewed())
            uow.previews.record(
                RulePreviewSummary(
                    rule.id,
                    self.clock.now(),
                    scope.eligible_events,
                    scope.excluded,
                    recurring_series=scope.series_count,
                    occurrence_changes=scope.occurrence_changes,
                )
            )
            uow.commit()

        return RulePreview(
            rule.id,
            scope.eligible_events,
            scope.excluded,
            items,
            recurring_series=scope.series_count,
            occurrence_changes=scope.occurrence_changes,
        )

    def _read(self, rule: SyncRule) -> tuple[_PreviewScope, tuple[PreviewItem, ...]]:
        cutoff = self.clock.now() - timedelta(days=rule.initial_lookback_days)
        scope = self._classify(rule, self.provider.changes(rule.source, None, cutoff).events)
        with self.unit_of_work() as uow:
            mappings = {mapping.source: mapping for mapping in uow.mappings.for_rule(rule.id)}
            # A rule that never wrote has nothing in the destination to compare with.
            listed = (
                self.provider.managed_events(rule.destination, rule.id, cutoff) if mappings else ()
            )
            planner = _Planner(
                uow,
                rule,
                scope,
                _Destination(self.provider, mappings, {event.reference: event for event in listed}),
                self.provider,
                self.projector,
                self.decisions,
            )
            items = tuple(
                item
                for event, parent, projects in scope.listed
                if _shown(item := planner.item(event, parent, projects))
            )
        return scope, items

    def _previewable_rule(self, rule_id: SyncRuleId) -> SyncRule:
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
        if rule is None:
            raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
        if not rule.can_preview:
            raise RuleNotExecutable(f"sync rule cannot preview from state {rule.state}")
        return rule

    def _classify(self, rule: SyncRule, events: Sequence[CalendarEvent]) -> _PreviewScope:
        """Sort the source listing into what the rule would project and what it excludes."""
        masters = {event.reference: event for event in events if event.occurrence is None}
        scope = _PreviewScope()

        def skipped(master: CalendarEvent) -> bool:
            if not rule.eligible(master):
                return True
            if master.recurrence is None:
                return False
            # Like a Sync Run, a series with no occurrence left to project is not projected.
            if master.reference not in scope.live:
                scope.live[master.reference] = self.provider.has_live_occurrences(
                    master.reference, rule.transformation
                )
            return not scope.live[master.reference]

        for listed in events:
            event, parent = self._with_series(rule, listed, masters)
            projects = not skipped(parent or event)
            scope.listed.append((event, parent, projects))
            if not projects:
                scope.excluded += 1
            elif parent is not None:
                scope.occurrence_changes += 1
            else:
                scope.series_count += event.recurrence is not None
        return scope

    def _with_series(
        self, rule: SyncRule, event: CalendarEvent, masters: Mapping[EventRef, CalendarEvent]
    ) -> tuple[CalendarEvent, CalendarEvent | None]:
        """An occurrence with its series; one whose series is not shown projects on its own, as a
        single event, and so does every other event."""
        if event.occurrence is None:
            return event, None
        parent_ref = EventRef(rule.source, event.occurrence.series_event_id)
        parent = masters.get(parent_ref) or self.provider.get_event(parent_ref)
        return (event, parent) if parent is not None else (event.as_single(), None)


@dataclass(frozen=True, slots=True)
class _Planner:
    """Plans each previewed event with provider reads only, as a Sync Run would; nothing is
    written."""

    uow: UnitOfWork
    rule: SyncRule
    scope: _PreviewScope
    destination: _Destination
    provider: CalendarReader
    projector: EventProjector
    decisions: SyncDecisionService

    def item(
        self, event: CalendarEvent, parent: CalendarEvent | None, projects: bool
    ) -> PreviewItem:
        if parent is None:
            decision = self._decide(event)
            kind: PreviewItemKind = "series" if event.recurrence is not None else "single"
        elif not projects:
            # Its series stays out, so the occurrence does too, for the series' reason. Removing
            # the series removes its occurrences with it, so none is counted as a removal again.
            decision = SyncDecision(SyncAction.IGNORE, self._decide(parent).reason)
            kind = "occurrence"
        else:
            decision = self._decide_occurrence(event, parent)
            kind = "occurrence"
        projection = self._projection(event, decision) if projects else None
        return PreviewItem(event, kind, decision.action, decision.reason, projection)

    def _decide(self, event: CalendarEvent) -> SyncDecision:
        mapping = self.destination.mapping(event.reference)
        actual = self.destination.get(mapping.destination) if mapping else None
        live = self.scope.live.get(event.reference, True)
        return self.decisions.decide(self.rule, event, mapping, actual, has_live_occurrences=live)

    def _decide_occurrence(self, event: CalendarEvent, parent: CalendarEvent) -> SyncDecision:
        assert event.occurrence is not None
        rule, start = self.rule, event.occurrence.original_start
        series_mapping = self.destination.mapping(parent.reference)
        destination_series = (
            self.destination.get(series_mapping.destination) if series_mapping else None
        )
        if series_mapping is None or destination_series is None:
            # The series is written, or written again, with this occurrence's change in it.
            return _change_in_new_series(rule, event)
        current = self.provider.get_occurrence(series_mapping.destination, start)
        situation = OccurrenceSituation(
            parent,
            series_mapping,
            start,
            event,
            self.uow.occurrences.get(series_mapping.id, start),
            destination_series,
            current,
        )
        return self.decisions.decide_occurrence(rule, situation)

    def _projection(self, event: CalendarEvent, decision: SyncDecision) -> PreviewProjection | None:
        """What the destination would hold once the rule runs; nothing for a removal or a
        Conflict, which leaves the destination as it is."""
        if decision.action in {SyncAction.DELETE, SyncAction.CONFLICT}:
            return None
        if event.time is None or not self.rule.transformation.projects(event):
            return None
        projected = self.projector.project(event, self.rule)
        return PreviewProjection(
            projected.title,
            bool(projected.description or projected.location),
            projected.recurrence,
        )


def _shown(item: PreviewItem) -> bool:
    """A cancelled event with no time that nothing will change is not on any calendar to show;
    one the rule will remove from the destination is."""
    source = item.source
    return (
        source.time is not None
        or source.occurrence is not None
        or (item.planned_action is not SyncAction.IGNORE)
    )


def _change_in_new_series(rule: SyncRule, event: CalendarEvent) -> SyncDecision:
    """How an occurrence change is written into a series written with it."""
    if event.status is EventStatus.CANCELLED:
        return SyncDecision(SyncAction.DELETE, SyncReason.OCCURRENCE_CANCELLED)
    exclusion = rule.transformation.exclusion(event)
    if exclusion is not None:
        return SyncDecision(SyncAction.DELETE, exclusion.removal_reason)
    return SyncDecision(SyncAction.UPDATE, SyncReason.OCCURRENCE_CHANGED)
