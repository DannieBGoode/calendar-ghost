"""Calendar provider read and projection write ports of Synchronization."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarEvent,
    EventProjection,
    EventRef,
    OccurrenceStart,
    SyncRuleId,
    TransformationPolicy,
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


class CalendarReader(Protocol):
    """Provider reads. Preview and reconciliation receive only this role, so they cannot write."""

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

    def list_events(
        self, calendar: CalendarEndpoint, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        """Every event, cancelled ones included, that ends at or after `not_ended_before`.

        Unlike `changes`, it reads no incremental position and yields none.
        """
        ...

    def managed_events(
        self, destination: CalendarEndpoint, rule_id: SyncRuleId, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        """This rule's live Managed Projections that end at or after `not_ended_before`."""
        ...

    def get_occurrence(
        self, series: EventRef, original_start: OccurrenceStart
    ) -> CalendarEvent | None:
        """Resolve one occurrence of a readable series, cancelled or not.

        `None` means the series answered and has no occurrence at that start. A series that cannot
        be read raises instead, because absence can authorize cancelling a destination occurrence.
        """
        ...

    def list_occurrences(
        self, series: EventRef, original_starts: Collection[OccurrenceStart]
    ) -> Mapping[OccurrenceStart, CalendarEvent]:
        """Occurrences of a series one listing found, cancelled or not, by original start.

        A requested start the answer lacks proves nothing: resolve it with `get_occurrence`.
        """
        ...

    def has_live_occurrences(
        self,
        series: EventRef,
        policy: TransformationPolicy,
        not_ended_before: datetime | None = None,
    ) -> bool:
        """Whether a series has an occurrence that is not cancelled and that `policy` projects.

        An occurrence the policy excludes, such as an all-day one or one the Source Calendar
        declined, does not count, because the rule cancels it in the destination. Only an answered
        lookup may return `False`, because it stops a projection from being created or restored
        and can remove one left by an interrupted create; a series whose occurrences cannot be
        listed counts as live.

        With `not_ended_before`, only an occurrence that ends at or after it counts, wherever it
        has moved to: a series the rule never projected is created only while one reaches the
        sync window.
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


class ProjectionDeleter(Protocol):
    """Deletes an owned projection; Rule Removal needs no other provider operation."""

    def delete_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None: ...


class ProjectionWriter(ProjectionDeleter, Protocol):
    """Creates, updates, and deletes owned projections."""

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


class OccurrenceWriter(Protocol):
    """Writes and cancels single occurrences of owned destination series."""

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


class CalendarProvider(CalendarReader, ProjectionWriter, OccurrenceWriter, Protocol):
    """Every provider role. Only a Sync Run needs them all."""
