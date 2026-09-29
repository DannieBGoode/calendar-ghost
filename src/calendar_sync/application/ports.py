from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self

from calendar_sync.application.errors import ProviderFailure
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarEvent,
    ConnectedAccountId,
    EventMapping,
    EventMappingId,
    EventProjection,
    EventRef,
    EventStatus,
    EventTime,
    OccurrenceMapping,
    OccurrenceStart,
    SyncRule,
    SyncRuleId,
)


@dataclass(frozen=True, slots=True)
class ProviderChangeSet:
    events: tuple[CalendarEvent, ...]
    next_cursor: str
    complete: bool = False
    """Every event in the window, not only changes since a cursor, as after a rejected cursor."""


@dataclass(frozen=True, slots=True)
class CreatedProjection:
    destination_event: CalendarEvent


class CalendarProvider(Protocol):
    def changes(
        self,
        source: CalendarEndpoint,
        cursor: str | None,
        not_ended_before: datetime,
    ) -> ProviderChangeSet: ...

    def get_event(self, reference: EventRef) -> CalendarEvent | None: ...

    def find_projection(
        self, destination: CalendarEndpoint, operation_key: str
    ) -> CalendarEvent | None:
        """Return the projection an earlier write with this Operation Key created, if any."""
        ...

    def create_projection(
        self,
        destination: CalendarEndpoint,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CreatedProjection: ...

    def update_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent: ...

    def delete_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None: ...

    def managed_events(
        self, destination: CalendarEndpoint, rule_id: SyncRuleId
    ) -> Sequence[CalendarEvent]: ...

    def get_occurrence(
        self, series: EventRef, original_start: OccurrenceStart
    ) -> CalendarEvent | None:
        """Resolve one occurrence of a readable series, cancelled or not.

        `None` means the series answered and has no occurrence at that start. A series that cannot
        be read raises instead, because absence can authorize cancelling a destination occurrence.
        """
        ...

    def has_live_occurrences(self, series: EventRef, *, include_all_day: bool) -> bool:
        """Whether a series has an occurrence that is not cancelled.

        With `include_all_day` false, all-day occurrences do not count, because a rule that
        excludes them cancels them in the destination. Only an answered lookup may return
        `False`, because it stops a projection from being created or restored and can remove one
        left by an interrupted create; a series whose occurrences cannot be listed counts as live.
        """
        ...

    def occurrence_exceptions(
        self, series: EventRef, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        """Occurrences of a series that are cancelled or differ from its regular occurrence.

        Only occurrences whose original slot or current time reaches `not_ended_before` count.

        A series whose occurrences cannot be listed returns none; its exceptions are applied when
        a later full listing reports them.
        """

    def write_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent:
        """Write or restore an owned destination occurrence without notifying attendees."""

    def cancel_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None:
        """Cancel one owned destination occurrence; the rest of its series is unchanged."""


class SyncRuleRepository(Protocol):
    def get(self, rule_id: SyncRuleId) -> SyncRule | None: ...

    def list(self) -> Sequence[SyncRule]: ...

    def add(self, rule: SyncRule) -> None: ...

    def save(self, rule: SyncRule) -> None: ...

    def relationship_exists(
        self, source: CalendarEndpoint, destination: CalendarEndpoint
    ) -> bool: ...

    def remove(self, rule_id: SyncRuleId) -> None:
        """Delete the rule with its mappings, cursors, and outcomes; resolve its incidents."""


class EventMappingRepository(Protocol):
    def for_source(self, rule_id: SyncRuleId, source: EventRef) -> EventMapping | None: ...

    def for_destination(
        self, rule_id: SyncRuleId, destination: EventRef
    ) -> EventMapping | None: ...

    def for_rule(self, rule_id: SyncRuleId) -> Sequence[EventMapping]: ...

    def save(self, mapping: EventMapping) -> None: ...

    def delete(self, mapping: EventMapping) -> None: ...

    def count_for_rule(self, rule_id: SyncRuleId) -> int: ...


class OccurrenceMappingRepository(Protocol):
    def for_series(self, series_mapping_id: EventMappingId) -> Sequence[OccurrenceMapping]: ...

    def get(
        self, series_mapping_id: EventMappingId, original_start: OccurrenceStart
    ) -> OccurrenceMapping | None: ...

    def save(self, mapping: OccurrenceMapping) -> None: ...

    def delete(self, mapping: OccurrenceMapping) -> None: ...


class ExceptionReplayRepository(Protocol):
    """Series projections whose source exceptions have not all been applied yet."""

    def pending(self, rule_id: SyncRuleId) -> Sequence[EventMapping]: ...

    def add(self, series_mapping_id: EventMappingId) -> None: ...

    def remove(self, series_mapping_id: EventMappingId) -> None: ...


class SyncCursorRepository(Protocol):
    def get(self, rule_id: SyncRuleId) -> str | None: ...

    def save(self, rule_id: SyncRuleId, cursor: str) -> None: ...


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    """What Activity names an entry's source event by, as the run saw it (ADR 0014)."""

    title: str
    time: EventTime | None = None
    recurring: bool = False
    cancelled: bool = False

    @classmethod
    def of(cls, event: CalendarEvent) -> RecordedEvent:
        return cls(
            title=event.title,
            time=event.time,
            recurring=event.recurrence is not None or event.occurrence is not None,
            cancelled=event.status is EventStatus.CANCELLED,
        )


@dataclass(frozen=True, slots=True)
class AuditEntry:
    occurred_at: datetime
    rule_id: SyncRuleId
    action: str
    outcome: str
    source_event_id: str | None = None
    destination_event_id: str | None = None
    detail: str = ""
    reason: str | None = None
    run_id: str | None = None
    event: RecordedEvent | None = None
    """The source event's title and time; never its description, location, or attendees."""


class AuditRepository(Protocol):
    def append(self, entry: AuditEntry) -> None: ...


class RunKind(StrEnum):
    SYNC = "sync"
    RECONCILIATION = "reconciliation"


@dataclass(frozen=True, slots=True)
class RuleRunOutcome:
    """The latest result of one kind of run: counts and a failure category, never content."""

    rule_id: SyncRuleId
    kind: RunKind
    completed_at: datetime
    succeeded: bool
    full_run: bool = False
    created: int = 0
    updated: int = 0
    deleted: int = 0
    conflicts: int = 0
    checked_mappings: int = 0
    drift: int = 0
    failure_kind: str | None = None
    # When the most recent successful run of this kind completed. The repository keeps it across
    # later failures, so a failed run never erases evidence that calendars were once current.
    last_succeeded_at: datetime | None = None
    # When the most recent successful full run completed, kept across later incremental runs so
    # the daily full pass is due per rule and survives restarts.
    last_full_succeeded_at: datetime | None = None


class RuleRunOutcomeRepository(Protocol):
    def record(self, outcome: RuleRunOutcome) -> None: ...

    def latest(self, rule_id: SyncRuleId, kind: RunKind) -> RuleRunOutcome | None: ...


@dataclass(frozen=True, slots=True)
class RulePreviewSummary:
    """Counts from the latest Rule Preview, kept so enabling can restate them; never content."""

    rule_id: SyncRuleId
    completed_at: datetime
    eligible_events: int
    excluded_events: int
    recurring_series: int = 0
    occurrence_changes: int = 0


class RulePreviewRepository(Protocol):
    def record(self, summary: RulePreviewSummary) -> None: ...

    def latest(self, rule_id: SyncRuleId) -> RulePreviewSummary | None: ...


class UnitOfWork(Protocol):
    rules: SyncRuleRepository
    mappings: EventMappingRepository
    occurrences: OccurrenceMappingRepository
    replays: ExceptionReplayRepository
    cursors: SyncCursorRepository
    destination_cursors: SyncCursorRepository
    audit: AuditRepository
    run_outcomes: RuleRunOutcomeRepository
    previews: RulePreviewRepository

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def commit(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new(self) -> str: ...


class AccountAuthorizations(Protocol):
    def is_connected(self, account_id: ConnectedAccountId) -> bool: ...


class RemovalIncidents(Protocol):
    def removal_blocked(self, rule_id: SyncRuleId, failure: ProviderFailure) -> None:
        """Open or refresh the one Incident for a removal stopped by lost authorization."""
        ...
