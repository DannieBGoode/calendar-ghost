from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.errors import RuleNotExecutable
from calendar_sync.application.sync.locking import RuleWork
from calendar_sync.application.sync.ports import UnitOfWork
from calendar_sync.application.sync.provider_ports import CalendarReader
from calendar_sync.application.sync.run_log import call_summary, duration
from calendar_sync.application.sync.run_ports import ProviderCallTally
from calendar_sync.domain.audit import (
    AuditAction,
    AuditEntry,
    FoundBy,
    RunReason,
    repeats_previous,
)
from calendar_sync.domain.changes import SourceComparison
from calendar_sync.domain.model import (
    CalendarEvent,
    EventRef,
    OccurrenceStart,
    SyncAction,
    SyncReason,
    SyncRule,
    SyncRuleId,
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
        SyncReason.BIRTHDAY,
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

    def finished(self, counts: Mapping[SyncAction, int], unrecorded: int) -> None:
        logger.info(
            "run finished %s in %s %s unrecorded=%d %s",
            self._names(),
            self._elapsed(),
            _decisions(counts),
            unrecorded,
            call_summary(self.calls),
        )

    def failed(self, kind: str, site: str) -> None:
        logger.warning(
            "run failed %s kind=%s at=%s after %s %s",
            self._names(),
            kind,
            site,
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
    rebuilt: set[EventRef] = field(default_factory=set)
    """Source series whose destination series this run rebuilt, so each is rebuilt once."""
    live_series: dict[tuple[EventRef, datetime | None], bool] = field(default_factory=dict)
    """Whether each source series looked up this run still has an occurrence this rule projects,
    at all or ending at or after an instant."""
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
    unrecorded: int = 0
    """Decisions this run counted but left out of Activity as repeats (ADR 0037)."""
    log: SyncRunLog | None = None
    work: RuleWork | None = None
    """What the rule reports while this run is in progress, including how much it handled."""
    run_reason: RunReason | None = None
    """Why this run read the calendars as it did."""
    found_by: FoundBy | None = None
    """The work that led to the decisions being made now; nested work inherits it."""

    @contextmanager
    def finding(self, found_by: FoundBy) -> Iterator[None]:
        """Name the work that finds events until the block ends, then restore the earlier one."""
        outer = self.found_by
        self.found_by = found_by
        try:
            yield
        finally:
            self.found_by = outer

    def count(self, action: SyncAction, source: EventRef) -> None:
        """Count one decision about `source`, remembering it when it is a block.

        Every decision of a run is counted here, so this is also where a long run reports progress.
        """
        self.counts[action] += 1
        if action is SyncAction.CONFLICT:
            self.blocked.add(source)
        self._report_progress()

    def uncount(self, counted: SyncAction) -> None:
        """Take back a decision that will be made again, so it is counted once."""
        self.counts[counted] -= 1

    def recount(self, counted: SyncAction, action: SyncAction, source: EventRef) -> None:
        """Count a decision as `action` instead of the `counted` one its write could not make."""
        self.counts[counted] -= 1
        self.count(action, source)

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


def has_live_occurrences(
    run: SyncRunContext,
    provider: CalendarReader,
    series: EventRef,
    *,
    not_ended_before: datetime | None = None,
) -> bool:
    """Ask once per run whether a source series still has an occurrence this rule projects;
    with `not_ended_before`, one that ends at or after it."""
    key = (series, not_ended_before)
    if key not in run.live_series:
        run.live_series[key] = provider.has_live_occurrences(
            series, run.rule.transformation, not_ended_before
        )
    return run.live_series[key]


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
    """Stop before writing if the rule was paused, edited, or removed during this run, or its
    User was disabled."""
    current = run.uow.rules.get(run.rule.id)
    if (
        current is None
        or not current.synchronizes
        or current.material_signature != run.rule.material_signature
        or not run.uow.user_active()
    ):
        raise RuleNotExecutable("sync rule changed during synchronization; run stopped")


def record(
    run: SyncRunContext,
    entry: AuditEntry,
    observed: CalendarEvent | None = None,
    *,
    own_identity: bool = True,
) -> None:
    """Append an Audit Entry unless its decision is one Activity deliberately leaves out.

    An entry about `observed` also records how it compared with the rule's Source Observation.
    Outside the daily pass, a skip that repeats the event's previous entry with nothing new is
    counted but not recorded (ADR 0037). Only recorded decisions observe, so no change is
    absorbed by a decision Activity never shows. `own_identity` is false when the entry is filed
    under another event's identifier, so its previous entry may be about something else.
    """
    reason = entry.reason
    if reason in UNRECORDED_REASONS or (run.daily_pass and reason in UNRECORDED_ON_DAILY_PASS):
        return
    comparison = _compare(run, observed) if observed is not None else None
    if comparison is not None and own_identity and _repeats(run, entry, comparison):
        run.unrecorded += 1
        return
    entry = replace(entry, run_reason=run.run_reason, found_by=run.found_by)
    if comparison is not None:
        assert observed is not None
        if comparison.observation is not None:
            run.uow.observations.save(
                run.rule.id, observed.reference, comparison.observation, entry.occurred_at
            )
        entry = replace(entry, change=comparison.change, source_comparison=comparison.kind)
    run.uow.audit.append(entry)


def _compare(run: SyncRunContext, event: CalendarEvent) -> SourceComparison:
    return SourceComparison.of(run.uow.observations.get(run.rule.id, event.reference), event)


def _repeats(run: SyncRunContext, entry: AuditEntry, comparison: SourceComparison) -> bool:
    if run.daily_pass or entry.action is not AuditAction.IGNORE or entry.source_event_id is None:
        return False
    previous = run.uow.audit.latest_for(run.rule.id, entry.source_event_id)
    return repeats_previous(previous, entry, comparison)
