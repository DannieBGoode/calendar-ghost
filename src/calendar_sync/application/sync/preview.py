from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Literal

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.errors import ProviderFailure, RuleNotExecutable, RuleNotFound
from calendar_sync.application.sync.health_ports import RecoveryIncidents
from calendar_sync.application.sync.locking import RuleLocks, RuleWork, RuleWorkKind
from calendar_sync.application.sync.planning import EventPlanner, decided_before_its_occurrences
from calendar_sync.application.sync.ports import UnitOfWork, UnitOfWorkFactory
from calendar_sync.application.sync.provider_ports import CalendarReader
from calendar_sync.application.sync.record_ports import RulePreviewSummary
from calendar_sync.application.sync.sync_run import UNRECORDED_REASONS
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
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)

PreviewItemKind = Literal["single", "series", "occurrence"]

# A preview lists what the run records in Activity (ADR 0013), so an event deleted before the
# rule projected it is not listed. Events other rules project into the source calendar are: they
# are on that calendar, and the rule leaves them out.
_UNLISTED = UNRECORDED_REASONS - {SyncReason.MANAGED_PROJECTION_SOURCE}
_HELD = frozenset({SyncAction.CREATE, SyncAction.UPDATE, SyncAction.CONFLICT})


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
class _Tally:
    """What a preview counts: events and series the destination will hold, those it will not,
    and the occurrence changes of series it will hold, which are counted on their own."""

    eligible_events: int = 0
    excluded: int = 0
    series_count: int = 0
    occurrence_changes: int = 0

    def add(self, item: PreviewItem, projects: bool) -> None:
        if not projects:
            self.excluded += 1
        elif item.kind == "occurrence":
            self.occurrence_changes += 1
        else:
            self.eligible_events += 1
            self.series_count += item.kind == "series"


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
            tally, items = self._read(rule)
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
                    tally.eligible_events,
                    tally.excluded,
                    recurring_series=tally.series_count,
                    occurrence_changes=tally.occurrence_changes,
                )
            )
            uow.commit()

        return RulePreview(
            rule.id,
            tally.eligible_events,
            tally.excluded,
            items,
            recurring_series=tally.series_count,
            occurrence_changes=tally.occurrence_changes,
        )

    def _read(self, rule: SyncRule) -> tuple[_Tally, tuple[PreviewItem, ...]]:
        cutoff = self.clock.now() - timedelta(days=rule.initial_lookback_days)
        with self.unit_of_work() as uow:
            cursor = uow.cursors.get(rule.id)
        events = self._source_events(rule, cursor, cutoff)
        with self.unit_of_work() as uow:
            mappings = {mapping.source: mapping for mapping in uow.mappings.for_rule(rule.id)}
            # A rule that never wrote has nothing in the destination to compare with.
            listed = (
                self.provider.managed_events(rule.destination, rule.id, cutoff) if mappings else ()
            )
            planner = _Planner(
                uow,
                rule,
                cutoff,
                _Destination(self.provider, mappings, {event.reference: event for event in listed}),
                # Fingerprints are pure; the run's and this one agree on every projection.
                EventPlanner(self.provider, self.decisions, ProjectionFingerprinter()),
                self.projector,
            )
            masters = {event.reference: event for event in events if event.occurrence is None}
            listed_refs = {event.reference for event in events}
            tally, items = _Tally(), []

            def add(planned: tuple[PreviewItem, bool]) -> None:
                item, projects = planned
                if item.reason not in _UNLISTED:
                    tally.add(item, projects)
                    items.append(item)

            for event in events:
                series = self._series_of(rule, event, masters)
                if series is not None and planner.decides_first(series, listed=masters):
                    # The listing leaves the series out, but the run decides it with its
                    # occurrence, such as a deleted one only the occurrence reports.
                    masters[series.reference] = series
                    add(planner.plan(series, None))
                    for removal in planner.lone_removals(series, listed=listed_refs):
                        add(removal)
                add(planner.plan(event, series))
                for removal in planner.lone_removals(event, listed=listed_refs):
                    add(removal)
        return tally, tuple(items)

    def _source_events(
        self, rule: SyncRule, cursor: str | None, cutoff: datetime
    ) -> tuple[CalendarEvent, ...]:
        """Every source event in the window, and, for a rule that has run, every change its next
        Sync Run will read from the saved cursor that the window no longer shows: an event deleted,
        or moved before the window, while the rule was paused. Reading from the cursor moves
        nothing; only a Sync Run saves the next one."""
        listed = self.provider.changes(rule.source, None, cutoff).events
        if cursor is None:
            return listed
        seen = {event.reference for event in listed}
        # An event changed twice since the cursor is read in its latest form.
        pending = {
            event.reference: event
            for event in self.provider.changes(rule.source, cursor, cutoff).events
        }
        return listed + tuple(
            event for reference, event in pending.items() if reference not in seen
        )

    def _previewable_rule(self, rule_id: SyncRuleId) -> SyncRule:
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
        if rule is None:
            raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
        if not rule.can_preview:
            raise RuleNotExecutable(f"sync rule cannot preview from state {rule.state}")
        return rule

    def _series_of(
        self, rule: SyncRule, event: CalendarEvent, masters: Mapping[EventRef, CalendarEvent]
    ) -> CalendarEvent | None:
        """An occurrence's series, or None for an event that is not one or whose series its
        calendar does not show."""
        if event.occurrence is None:
            return None
        series = EventRef(rule.source, event.occurrence.series_event_id)
        return masters.get(series) or self.provider.get_event(series)


@dataclass(slots=True)
class _Planner:
    """Plans each previewed event with provider reads only, through the decisions a Sync Run
    makes; nothing is written."""

    uow: UnitOfWork
    rule: SyncRule
    window_start: datetime
    destination: _Destination
    events: EventPlanner
    projector: EventProjector
    _decided: dict[EventRef, SyncDecision] = field(default_factory=dict, init=False)
    _live: dict[tuple[EventRef, datetime | None], bool] = field(default_factory=dict, init=False)

    def plan(self, event: CalendarEvent, series: CalendarEvent | None) -> tuple[PreviewItem, bool]:
        """The event's item, and whether the destination will hold it or, for an occurrence,
        its series."""
        kind: PreviewItemKind
        if event.occurrence is not None and series is not None:
            series_decision = self._decide(series)
            decision = self._decide_occurrence(event, series, series_decision)
            kind, projects = "occurrence", _projects(series_decision)
        else:
            if event.occurrence is not None:
                event, decision = self._decide_lone(event)
            else:
                decision = self._decide(event)
            kind = "series" if event.recurrence is not None else "single"
            projects = _projects(decision)
        projection = self._projection(event, decision) if projects else None
        return PreviewItem(event, kind, decision.action, decision.reason, projection), projects

    def decides_first(
        self, series: CalendarEvent, *, listed: Mapping[EventRef, CalendarEvent]
    ) -> bool:
        """Whether the run decides an unlisted series before an occurrence of it."""
        return series.reference not in listed and decided_before_its_occurrences(
            series, self.destination.mapping(series.reference)
        )

    def _decide(self, event: CalendarEvent) -> SyncDecision:
        """An event's decision, made once though it is also the series of its occurrences."""
        if event.reference not in self._decided:
            mapping = self.destination.mapping(event.reference)
            actual = self.destination.get(mapping.destination) if mapping else None
            _found, self._decided[event.reference] = self.events.decide(
                self.rule,
                event,
                mapping,
                actual,
                window_start=self.window_start,
                live=self._has_live_occurrences,
            )
        return self._decided[event.reference]

    def _decide_lone(self, event: CalendarEvent) -> tuple[CalendarEvent, SyncDecision]:
        """An occurrence whose series its calendar does not show projects on its own, as a
        single event; one of a series the rule projected cannot be verified."""
        assert event.occurrence is not None
        single = event.as_single()
        series = EventRef(self.rule.source, event.occurrence.series_event_id)
        if self.destination.mapping(series) is not None:
            return single, SyncDecision(SyncAction.CONFLICT, SyncReason.SOURCE_UNVERIFIABLE)
        return single, self._decide(single)

    def _decide_occurrence(
        self, event: CalendarEvent, series: CalendarEvent, series_decision: SyncDecision
    ) -> SyncDecision:
        assert event.occurrence is not None
        start = event.occurrence.original_start
        mapping = self.destination.mapping(series.reference)
        recorded = self.uow.occurrences.get(mapping.id, start) if mapping else None
        lone = self.destination.mapping(event.reference)
        if (
            lone is not None
            and lone.occurrence is not None
            and _retires_lone_projections(series_decision, mapping)
        ):
            removal = self._lone_removal(lone, series, event.as_single())
            if removal is not None:
                return removal[0]
        if series_decision.action is SyncAction.CREATE:
            # The run writes the series, or writes it again, then decides the occurrence in it.
            return self.events.decisions.decide_occurrence_in_new_series(
                self.rule, series, event, recorded
            )
        if series_decision.action is SyncAction.DELETE:
            # Removing the series removes its mappings, and every occurrence, with it.
            mapping = recorded = None
        destination_series = self.destination.get(mapping.destination) if mapping else None
        situation = OccurrenceSituation(
            series,
            mapping,
            start,
            event,
            recorded,
            destination_series,
            self.events.provider.get_occurrence(destination_series.reference, start)
            if destination_series is not None
            else None,
        )
        decision = self.events.decisions.decide_occurrence(
            self.rule, situation, window_start=self.window_start
        )
        if decision.reason is SyncReason.DESTINATION_OCCURRENCE_MISSING and not (
            self._has_live_occurrences(series.reference)
        ):
            # As in a Sync Run, a dormant series has no projection to repair.
            decision = self.events.decisions.decide_occurrence(
                self.rule,
                replace(situation, has_live_occurrences=False),
                window_start=self.window_start,
            )
        return decision

    def lone_removals(
        self, series: CalendarEvent, *, listed: AbstractSet[EventRef]
    ) -> list[tuple[PreviewItem, bool]]:
        """Removals of single projections of the series' occurrences that the listing left out,
        which a run makes once it decides the series deleted or excluded."""
        if series.occurrence is not None or (
            series.recurrence is None and series.status is not EventStatus.CANCELLED
        ):
            return []
        mapping = self.destination.mapping(series.reference)
        if not _retires_lone_projections(self._decide(series), mapping):
            return []
        planned = []
        for lone in self.uow.mappings.lone_occurrences(self.rule.id, series.reference):
            if lone.source in listed or lone.occurrence is None:
                continue
            # Gone with its series, the occurrence has no title or time of its own left.
            gone = CalendarEvent(
                lone.source, None, series.revision, EventStatus.CANCELLED, recurrence=None
            )
            removal = self._lone_removal(lone, series, gone)
            if removal is not None:
                decision, read = removal
                source = read.as_single() if read is not None else gone
                item = PreviewItem(source, "single", decision.action, decision.reason, None)
                planned.append((item, False))
        return planned

    def _lone_removal(
        self, lone: EventMapping, series: CalendarEvent, source: CalendarEvent
    ) -> tuple[SyncDecision, CalendarEvent | None] | None:
        """The removal of the occurrence's single projection, projected while its series was not
        shown, by a series the rule does not project, with the occurrence the series answered.

        As a run, it reads the occurrence from that series, and blocks a projection it cannot
        prove the rule's.
        """
        assert lone.occurrence is not None
        decisions = self.events.decisions
        occurrence = (
            None
            if series.status is EventStatus.CANCELLED
            else self.events.provider.get_occurrence(
                series.reference, lone.occurrence.original_start
            )
        )
        reason = decisions.lone_projection_removal(self.rule, series, occurrence)
        if reason is None:
            return None
        conflict = decisions.ownership_conflict(
            self.rule, source, lone, self.destination.get(lone.destination)
        )
        if conflict is not None:
            return SyncDecision(SyncAction.CONFLICT, conflict), occurrence
        return SyncDecision(SyncAction.DELETE, reason), occurrence

    def _has_live_occurrences(
        self, series: EventRef, *, not_ended_before: datetime | None = None
    ) -> bool:
        key = (series, not_ended_before)
        if key not in self._live:
            self._live[key] = self.events.provider.has_live_occurrences(
                series, self.rule.transformation, not_ended_before
            )
        return self._live[key]

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


def _retires_lone_projections(decision: SyncDecision, mapping: EventMapping | None) -> bool:
    """Whether deciding a series leads a run to remove the single projections of occurrences
    of a series it does not project, as it does for one it never projected or removes now."""
    return decision.action is not SyncAction.CREATE and (
        mapping is None or decision.action is SyncAction.DELETE
    )


def _projects(decision: SyncDecision) -> bool:
    """Whether the destination holds the event's projection once the run decides it, or keeps
    the one a Conflict leaves in place."""
    return decision.action in _HELD or decision.reason is SyncReason.PROJECTION_CURRENT
