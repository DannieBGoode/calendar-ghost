"""Read-only questions the Web API asks about recorded Activity and operational state.

Results carry identities, reason codes, and the source event's title and time (ADR 0014); never
its description, location, attendees, or conferencing data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from calendar_sync.domain.model import SyncAction, SyncReason

ActivityCategory = Literal["changed", "unchanged", "skipped", "blocked"]

# Ignored decisions that confirmed the destination already matches; other ignores are skips.
NO_CHANGE_REASONS = frozenset(
    {
        SyncReason.PROJECTION_CURRENT.value,
        SyncReason.OCCURRENCE_CURRENT.value,
        SyncReason.OCCURRENCE_ALREADY_CANCELLED.value,
    }
)
BLOCK_ACTIONS = frozenset({SyncAction.CONFLICT.value, "removal_conflict"})
# Recurring exclusions were recorded as conflicts before reason codes existed; they are skips.
LEGACY_SKIP_REASON = SyncReason.RECURRING_UNSUPPORTED.value


def activity_category(action: str, reason: str | None) -> ActivityCategory:
    """How Activity groups an entry. The SQLite adapter mirrors this order to filter by it."""
    if reason == LEGACY_SKIP_REASON:
        return "skipped"
    if action in BLOCK_ACTIONS:
        return "blocked"
    if action == SyncAction.IGNORE:
        return "unchanged" if reason in NO_CHANGE_REASONS else "skipped"
    return "changed"


@dataclass(frozen=True, slots=True)
class RecordedTime:
    all_day: bool = False
    starts: str | None = None
    ends: str | None = None


@dataclass(frozen=True, slots=True)
class ActivityEvent:
    """The source event an entry names, as a run recorded it; see ADR 0014."""

    title: str
    all_day: bool = False
    starts: str | None = None
    ends: str | None = None
    recurring: bool = False
    cancelled: bool = False
    renamed_from: str | None = None
    moved_from: RecordedTime | None = None
    """The time the previous entry for this event recorded, when this entry saw it move."""


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    id: int
    run_id: str | None
    occurred_at: str
    rule_id: str
    action: str
    outcome: str
    category: ActivityCategory
    reason: str | None
    detail: str
    source_event_id: str | None
    destination_event_id: str | None
    event: ActivityEvent | None = None
    repeated: bool = False
    """A repair that redoes the same event's previous one, recorded by an earlier run."""


@dataclass(frozen=True, slots=True)
class ActivityFilter:
    rule_id: str | None = None
    run_id: str | None = None
    categories: frozenset[ActivityCategory] = frozenset()
    before: int | None = None
    """Only entries older than this one, for the next page."""
    limit: int = 100
    search: str | None = None
    """Matches recorded titles, ignoring case and accents."""


@dataclass(frozen=True, slots=True)
class NoChangeRun:
    run_id: str
    rule_id: str
    newest_id: int
    occurred_at: str
    count: int


@dataclass(frozen=True, slots=True)
class RecentChange:
    """One written event; an identical repair repeated among recent entries is counted on it."""

    entry: ActivityEntry
    repeats: int
    first_occurred_at: str


@dataclass(frozen=True, slots=True)
class EntryEvents:
    """The events an entry was about, so they can be read live from the provider."""

    rule_id: str
    source_event_id: str | None
    destination_event_id: str | None


class ActivityQueries(Protocol):
    def entries(self, selection: ActivityFilter) -> Sequence[ActivityEntry]:
        """Recorded entries matching every given filter, newest first."""
        ...

    def entry(self, entry_id: int) -> ActivityEntry | None: ...

    def entry_events(self, entry_id: int) -> EntryEvents | None: ...

    def no_change_runs(self, rule_id: str | None, after: int) -> Sequence[NoChangeRun]:
        """Runs newer than entry `after` that made no-change checks, with how many each made."""
        ...

    def recent_changes(self, limit: int) -> Sequence[RecentChange]:
        """The newest written events, each repeated repair counted on its newest write."""
        ...


@dataclass(frozen=True, slots=True)
class OpenBlock:
    entry_id: int
    rule_id: str


@dataclass(frozen=True, slots=True)
class OperationsOverview:
    connected_accounts: int
    disconnected_accounts: int
    open_incidents: int
    last_synced_at: str | None
    open_blocks: tuple[OpenBlock, ...]
    """Events of existing rules whose latest decision was a block, newest first."""


@dataclass(frozen=True, slots=True)
class IncidentSummary:
    id: str
    rule_id: str | None
    category: str
    state: str
    summary: str
    opened_at: str
    updated_at: str


class OperationsQueries(Protocol):
    def overview(self) -> OperationsOverview: ...

    def incidents(self) -> Sequence[IncidentSummary]:
        """Open incidents first, then resolved ones, each most recently updated first."""
        ...
