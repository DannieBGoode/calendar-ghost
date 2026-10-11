"""Read-only questions the Web API asks about recorded Activity and operational state.

Results carry identities, reason codes, and the source event's title and time (ADR 0014). An
entry's Source Change values are unsealed only when one entry's change is asked for (ADR 0017).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from calendar_sync.application.operations.errors import (
    ActivityEventNotFound,
    ActivityRuleRemoved,
    EventInspectionUnavailable,
)
from calendar_sync.application.operations.ports import IncidentSummary, OperationsOverview
from calendar_sync.application.sync.ports import CalendarReader, UnitOfWorkFactory
from calendar_sync.domain.model import (
    CalendarEvent,
    EventId,
    EventRef,
    SyncAction,
    SyncReason,
    SyncRuleId,
)

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
    changed_fields: tuple[str, ...] | None = None
    """The source fields this entry's Source Change touched; None when it recorded none."""


@dataclass(frozen=True, slots=True)
class FieldChange:
    """One changed source field: text before and after, a time, or what was added and removed."""

    field: str
    before: str | None = None
    after: str | None = None
    before_time: RecordedTime | None = None
    after_time: RecordedTime | None = None
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecordedChange:
    """An entry's Source Change. Only titles remain once its values expired or cannot open."""

    fields: tuple[str, ...]
    values_available: bool
    changes: tuple[FieldChange, ...]


@dataclass(frozen=True, slots=True)
class ActivityFilter:
    rule_id: str | None = None
    categories: frozenset[ActivityCategory] = frozenset()
    before: int | None = None
    """Only entries older than this one, for the next page."""
    limit: int = 100
    search: str | None = None
    """Matches recorded titles, ignoring case and accents."""


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

    def entry_change(self, entry_id: int) -> RecordedChange | None:
        """The entry's Source Change with its values, or None when it recorded none."""
        ...

    def recent_changes(self, limit: int) -> Sequence[RecentChange]:
        """The newest written events, each repeated repair counted on its newest write."""
        ...


class OperationsQueries(Protocol):
    def overview(self) -> OperationsOverview: ...

    def incidents(self, before: str | None = None) -> Sequence[IncidentSummary]:
        """One page of incidents: open ones first, then resolved ones, each most recently updated
        first. `before` is the `cursor` of the last one of the previous page, so a page goes on
        where that one was, though it has changed since; one that is not a cursor starts none."""
        ...

    def incident(self, incident_id: str) -> IncidentSummary | None:
        """One of the User's incidents, listed or not; None for any other."""
        ...


class EntryEventQueries(Protocol):
    def entry_events(self, entry_id: int) -> EntryEvents | None: ...


@dataclass(frozen=True, slots=True)
class InspectedEvents:
    source: CalendarEvent | None
    destination: CalendarEvent | None
    destination_recorded: bool
    """Whether the entry named a destination event at all, found or not."""


@dataclass(slots=True)
class InspectActivityEvent:
    """Read an entry's events live for display; their content is never persisted or logged."""

    entries: EntryEventQueries
    unit_of_work: UnitOfWorkFactory
    provider: CalendarReader | None

    def execute(self, entry_id: int) -> InspectedEvents:
        events = self.entries.entry_events(entry_id)
        if events is None or events.source_event_id is None:
            raise ActivityEventNotFound(f"activity entry {entry_id} has no source event")
        with self.unit_of_work() as uow:
            rule = uow.rules.get(SyncRuleId(events.rule_id))
        if rule is None:
            # Retained history of a removed rule no longer names its calendars.
            raise ActivityRuleRemoved(f"sync rule {events.rule_id} was removed")
        if self.provider is None:
            raise EventInspectionUnavailable("no calendar provider is configured")
        source = self.provider.get_event(EventRef(rule.source, EventId(events.source_event_id)))
        if events.destination_event_id is None:
            return InspectedEvents(source, None, destination_recorded=False)
        destination = self.provider.get_event(
            EventRef(rule.destination, EventId(events.destination_event_id))
        )
        return InspectedEvents(source, destination, destination_recorded=True)
