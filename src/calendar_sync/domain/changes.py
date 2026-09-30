"""What a source event's tracked details were, and how a later revision changed them (ADR 0016)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from calendar_sync.domain.model import (
    AllDayRange,
    CalendarEvent,
    EventStatus,
    EventTime,
    TimedInterval,
)


class SourceField(StrEnum):
    """A tracked detail of a source event, in the order Activity lists them.

    Responses to invitations, reminders, and colours are not tracked.
    """

    TITLE = "title"
    TIME = "time"
    DESCRIPTION = "description"
    LOCATION = "location"
    GUESTS = "guests"
    RECURRENCE = "recurrence"
    CONFERENCING = "conferencing"


@dataclass(frozen=True, slots=True)
class SourceObservation:
    """The tracked details of a source event as a rule last saw them."""

    revision: str
    title: str
    time: EventTime
    description: str = ""
    location: str = ""
    recurrence: tuple[str, ...] = ()
    guests: tuple[str, ...] | None = None
    """Guest email addresses; None when the provider did not list every guest."""
    conferencing: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        # Sets, so neither order nor the case of an address reads as a change.
        if self.guests is not None:
            guests = {guest.strip().lower() for guest in self.guests if guest.strip()}
            object.__setattr__(self, "guests", tuple(sorted(guests)))
        if self.conferencing is not None:
            object.__setattr__(self, "conferencing", tuple(sorted(set(self.conferencing))))

    @classmethod
    def of(cls, event: CalendarEvent) -> SourceObservation | None:
        """The event's tracked details; None for a cancellation or a Managed Projection."""
        if (
            event.status is EventStatus.CANCELLED
            or event.time is None
            or event.managed_origin is not None
        ):
            return None
        return cls(
            revision=event.revision,
            title=event.title,
            time=event.time,
            description=event.description,
            location=event.location,
            recurrence=event.recurrence.lines if event.recurrence is not None else (),
            guests=event.guests,
            conferencing=event.conferencing,
        )


@dataclass(frozen=True, slots=True)
class SourceChange:
    """The tracked fields a later revision of a source event changed, with both observations."""

    before: SourceObservation
    after: SourceObservation
    fields: tuple[SourceField, ...]

    @classmethod
    def between(cls, before: SourceObservation, after: SourceObservation) -> SourceChange | None:
        """The change from `before` to `after`; None when no tracked field differs."""
        fields = tuple(field for field in SourceField if _differs(field, before, after))
        return cls(before, after, fields) if fields else None


def _differs(field: SourceField, before: SourceObservation, after: SourceObservation) -> bool:
    if field is SourceField.TIME:
        return _instants(before.time) != _instants(after.time)
    if field is SourceField.GUESTS:
        return _known_differ(before.guests, after.guests)
    if field is SourceField.CONFERENCING:
        return _known_differ(before.conferencing, after.conferencing)
    return bool(getattr(before, field.value) != getattr(after, field.value))


def _known_differ(before: tuple[str, ...] | None, after: tuple[str, ...] | None) -> bool:
    """Only two complete lists can show a difference; an unknown one proves nothing."""
    return before is not None and after is not None and before != after


def _instants(time: EventTime) -> tuple[object, ...]:
    if isinstance(time, TimedInterval):
        # Datetimes compare as instants, so a new offset for the same moment is no change.
        return ("timed", time.starts_at, time.ends_at)
    assert isinstance(time, AllDayRange)
    return ("all_day", time.starts_on, time.ends_before)
