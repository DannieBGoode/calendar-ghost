from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from calendar_sync.application.errors import RuleNotExecutable
from calendar_sync.application.locking import RuleWork
from calendar_sync.application.ports import (
    AuditEntry,
    CalendarReader,
    Clock,
    ProviderCallTally,
    UnitOfWork,
)
from calendar_sync.application.run_log import call_summary, duration
from calendar_sync.domain.changes import SourceChange, SourceObservation
from calendar_sync.domain.model import (
    CalendarEvent,
    EventRef,
    OccurrenceStart,
    SyncAction,
    SyncReason,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
)

logger = logging.getLogger(__name__)

# A long run says how far it got this often, so a quiet log means a stuck run, not a slow one.
PROGRESS_INTERVAL = timedelta(seconds=30)

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
class SyncRunLog:
    """The service log lines of one Sync Run, from its start to how it ended."""

    rule_id: SyncRuleId
    clock: Clock
    calls: ProviderCallTally
    started_at: datetime
    run_id: str | None = None
    """Known once the run began; a rule found not enabled never begins one."""
    _next_progress: datetime | None = None

    def begin(self, run_id: str, mode: str, reason: str) -> None:
        self.run_id = run_id
        self._next_progress = self.started_at + PROGRESS_INTERVAL
        logger.info("run started %s mode=%s reason=%s", self._names(), mode, reason)

    def listed(self, source_events: int, destination_events: int) -> None:
        logger.info(
            "listing done %s source events=%d destination events=%d",
            self._names(),
            source_events,
            destination_events,
        )

    def cursor_rejected(self, feed: str) -> None:
        logger.info("cursor rejected %s feed=%s; listed in full", self._names(), feed)

    def reprojecting(self, mappings: int) -> None:
        logger.info("reprojecting remaining %s mappings=%d", self._names(), mappings)

    def replaying(self, pending: int) -> None:
        logger.info("pending replays %s series=%d", self._names(), pending)

    def progress(
        self, counts: Mapping[SyncAction, int], *, handled: int, total: int | None
    ) -> None:
        """Say how far the run got, at most once every PROGRESS_INTERVAL."""
        now = self.clock.now()
        if self._next_progress is None or now < self._next_progress:
            return
        self._next_progress = now + PROGRESS_INTERVAL
        logger.info(
            "run progress %s decided=%d handled=%s %s elapsed=%s provider_calls=%d",
            self._names(),
            sum(counts.values()),
            handled if total is None else f"{handled}/{total}",
            _decisions(counts),
            duration(now - self.started_at),
            self.calls.calls,
        )

    def finished(self, counts: Mapping[SyncAction, int]) -> None:
        logger.info(
            "run finished %s in %s %s %s",
            self._names(),
            self._elapsed(),
            _decisions(counts),
            call_summary(self.calls),
        )

    def failed(self, kind: str) -> None:
        logger.warning(
            "run failed %s kind=%s after %s %s",
            self._names(),
            kind,
            self._elapsed(),
            call_summary(self.calls),
        )

    def stopped(self) -> None:
        if self.run_id is None:
            logger.info("run not started rule=%s: rule is not enabled", self.rule_id.value)
        else:
            logger.info("run stopped %s after %s: rule changed", self._names(), self._elapsed())

    def _names(self) -> str:
        return f"rule={self.rule_id.value} run={self.run_id}"

    def _elapsed(self) -> str:
        return duration(self.clock.now() - self.started_at)


def _decisions(counts: Mapping[SyncAction, int]) -> str:
    return (
        f"created={counts[SyncAction.CREATE]} updated={counts[SyncAction.UPDATE]} "
        f"deleted={counts[SyncAction.DELETE]} ignored={counts[SyncAction.IGNORE]} "
        f"conflicts={counts[SyncAction.CONFLICT]}"
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
    handled_occurrences: set[tuple[EventRef, OccurrenceStart]] = field(default_factory=set)
    """Source occurrences decided this run, by source series and original start.

    A destination occurrence reported later is skipped by these without looking its source up.
    """
    repaired: set[EventRef] = field(default_factory=set)
    """Source series already repaired this run, so a repair never recurses."""
    live_series: dict[EventRef, bool] = field(default_factory=dict)
    """Whether each source series looked up this run still has an occurrence this rule projects."""
    blocked: set[EventRef] = field(default_factory=set)
    """Source events and occurrences this run blocked as a Conflict."""
    listed_occurrences: dict[EventRef, dict[OccurrenceStart, CalendarEvent]] = field(
        default_factory=dict
    )
    """Occurrences a series listing found while their series is re-verified, each usable once."""
    destination_series: dict[EventRef, CalendarEvent | None] = field(default_factory=dict)
    """Destination series read this run, shared by their occurrences until this run writes one.

    Occurrence writes verify the series' ownership with a fresh read of their own.
    """
    log: SyncRunLog | None = None
    work: RuleWork | None = None
    """What the rule reports while this run is in progress, including how much it handled."""

    def count(self, action: SyncAction, source: EventRef) -> None:
        """Count one decision about `source`, remembering it when it is a block.

        Every decision of a run is counted here, so this is also where a long run reports progress.
        """
        self.counts[action] += 1
        if action is SyncAction.CONFLICT:
            self.blocked.add(source)
        self._report_progress()

    def expect(self, items: int) -> None:
        """Add `items` the run will handle to its reported total, before handling any of them."""
        if self.work is not None:
            self.work.total = (self.work.total or 0) + items

    def handled_one(self) -> None:
        """One expected item is handled, whatever was decided about it."""
        if self.work is not None:
            self.work.done += 1
        self._report_progress()

    def _report_progress(self) -> None:
        if self.log is not None:
            work = self.work
            self.log.progress(
                self.counts,
                handled=work.done if work else 0,
                total=work.total if work else None,
            )


def has_live_occurrences(run: SyncRunContext, provider: CalendarReader, series: EventRef) -> bool:
    """Ask once per run whether a source series still has an occurrence this rule projects."""
    if series not in run.live_series:
        run.live_series[series] = provider.has_live_occurrences(series, run.rule.transformation)
    return run.live_series[series]


def read_destination_series(
    run: SyncRunContext, provider: CalendarReader, series: EventRef
) -> CalendarEvent | None:
    """Read a destination series once per run, however many of its occurrences are decided."""
    if series not in run.destination_series:
        run.destination_series[series] = provider.get_event(series)
    return run.destination_series[series]


def read_occurrence(
    run: SyncRunContext, provider: CalendarReader, series: EventRef, original_start: OccurrenceStart
) -> CalendarEvent | None:
    """An occurrence from its series' listing if it found it, otherwise from its own lookup."""
    listed = run.listed_occurrences.get(series, {}).pop(original_start, None)
    return listed if listed is not None else provider.get_occurrence(series, original_start)


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
