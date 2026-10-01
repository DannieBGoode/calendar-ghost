from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from calendar_sync.application.errors import RuleNotExecutable
from calendar_sync.application.ports import AuditEntry, CalendarReader, UnitOfWork
from calendar_sync.domain.changes import SourceChange, SourceObservation
from calendar_sync.domain.model import (
    CalendarEvent,
    EventRef,
    SyncAction,
    SyncReason,
    SyncRule,
    SyncRuleState,
)

# How long the values of a Source Change are kept; which fields changed is kept with the entry.
SOURCE_CHANGE_RETENTION = timedelta(days=90)

# Skips that answer no question a person would ask: loop prevention, bookkeeping, and events
# that never were in scope. Runs count them but do not record them.
UNRECORDED_REASONS = frozenset(
    {
        SyncReason.MANAGED_PROJECTION_SOURCE,
        SyncReason.OUTSIDE_SOURCE_CALENDAR,
        SyncReason.CANCELLED_WITHOUT_PROJECTION,
        SyncReason.BEFORE_SYNC_WINDOW,
        SyncReason.OCCURRENCE_RETIRED,
    }
)
# Skips that explain a missing projection. A daily pass re-lists unchanged events, so only the
# run that first saw the event, or saw it change, records why it was skipped.
UNRECORDED_ON_DAILY_PASS = frozenset(
    {
        SyncReason.ALL_DAY_EXCLUDED,
        SyncReason.DECLINED,
        SyncReason.TENTATIVE_EXCLUDED,
        SyncReason.AWAITING_RESPONSE,
        SyncReason.SERIES_NOT_SYNCHRONIZED,
        SyncReason.SERIES_WITHOUT_OCCURRENCES,
    }
)


@dataclass(slots=True)
class SyncRunContext:
    """State shared by every decision of one Sync Run."""

    uow: UnitOfWork
    rule: SyncRule
    run_id: str
    counts: dict[SyncAction, int]
    window_start: datetime
    """Unmapped single events that ended before this instant are not projected."""
    reproject: bool = False
    incremental: bool = True
    """Both feeds report only changes since the previous run."""
    daily_pass: bool = False
    """A full re-listing of a rule whose calendars already synchronized incrementally."""
    source_listed: bool = False
    """The source feed listed every event in the window, including every occurrence exception."""
    listed_destinations: dict[EventRef, CalendarEvent] = field(default_factory=dict)
    """Destination events from this run's full listing, each usable once instead of a read."""
    handled: set[EventRef] = field(default_factory=set)
    repaired: set[EventRef] = field(default_factory=set)
    """Source series already repaired this run, so a repair never recurses."""
    live_series: dict[EventRef, bool] = field(default_factory=dict)
    """Whether each source series looked up this run still has an occurrence this rule projects."""
    blocked: set[EventRef] = field(default_factory=set)
    """Source events and occurrences this run blocked as a Conflict."""

    def count(self, action: SyncAction, source: EventRef) -> None:
        """Count one decision about `source`, remembering it when it is a block."""
        self.counts[action] += 1
        if action is SyncAction.CONFLICT:
            self.blocked.add(source)


def has_live_occurrences(run: SyncRunContext, provider: CalendarReader, series: EventRef) -> bool:
    """Ask once per run whether a source series still has an occurrence this rule projects."""
    if series not in run.live_series:
        run.live_series[series] = provider.has_live_occurrences(
            series, include_all_day=run.rule.transformation.includes_all_day
        )
    return run.live_series[series]


def require_unchanged(run: SyncRunContext) -> None:
    """Stop before writing if the rule was paused, edited, or removed during this run."""
    current = run.uow.rules.get(run.rule.id)
    if (
        current is None
        or current.state is not SyncRuleState.ENABLED
        or current.material_signature != run.rule.material_signature
    ):
        raise RuleNotExecutable("sync rule changed during synchronization; run stopped")


def record(run: SyncRunContext, entry: AuditEntry, observed: CalendarEvent | None = None) -> None:
    """Append an Audit Entry unless its decision is one Activity deliberately leaves out.

    An entry about `observed` also records what changed in it since the rule last observed it.
    Only recorded decisions observe, so no change is absorbed by a decision Activity never shows.
    """
    reason = entry.reason
    if reason in UNRECORDED_REASONS or (run.daily_pass and reason in UNRECORDED_ON_DAILY_PASS):
        return
    if observed is not None:
        entry = replace(entry, change=_observe(run, observed, entry.occurred_at))
    run.uow.audit.append(entry)


def _observe(run: SyncRunContext, event: CalendarEvent, at: datetime) -> SourceChange | None:
    """Remember the event's tracked details; how they changed, if the rule saw it before."""
    current = SourceObservation.of(event)
    if current is None:
        # A cancellation keeps the last observation, so a restored event compares with it.
        return None
    observations = run.uow.observations
    previous = observations.get(run.rule.id, event.reference)
    if previous is not None and previous.revision == current.revision:
        return None
    if previous is not None:
        # A list Google did not return in full keeps the last complete one, so a guest removed
        # before the next complete list is still reported.
        current = replace(
            current,
            guests=previous.guests if current.guests is None else current.guests,
            conferencing=(
                previous.conferencing if current.conferencing is None else current.conferencing
            ),
        )
    observations.save(run.rule.id, event.reference, current, at)
    return SourceChange.between(previous, current) if previous is not None else None
