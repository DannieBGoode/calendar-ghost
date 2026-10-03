from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

from calendar_sync.application.ports import Clock, SchedulerProgress
from calendar_sync.domain.model import (
    AllDayRange,
    CalendarEndpoint,
    CalendarEvent,
    CalendarId,
    ConnectedAccountId,
    EventId,
    EventRef,
    EventStatus,
    ManagedOrigin,
    OccurrenceIdentity,
    OccurrenceStart,
    Recurrence,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TimedInterval,
)

NOW = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class RecentSchedulerHeartbeat:
    """A `SchedulerHeartbeat` that always reports a pass completed moments ago, so a test's
    Installation Status verdict reflects its seeded rules and incidents instead of "stalled": a
    `None` scheduler (the common case for a container built without a master key) means no
    scheduler can run at all, which is correctly "stalled", but these tests are not about that."""

    clock: Clock

    def progress(self) -> SchedulerProgress:
        now = self.clock.now()
        return SchedulerProgress(running_since=now, pass_started_at=None, last_completed_at=now)


def endpoint(account: str, calendar: str) -> CalendarEndpoint:
    return CalendarEndpoint(ConnectedAccountId(account), CalendarId(calendar))


def rule(*, state: SyncRuleState = SyncRuleState.ENABLED) -> SyncRule:
    return SyncRule(
        id=SyncRuleId("rule-1"),
        source=endpoint("personal-account", "personal-calendar"),
        destination=endpoint("work-account", "work-calendar"),
        state=state,
    )


def event(
    event_id: str = "source-event",
    *,
    calendar: CalendarEndpoint | None = None,
    revision: str = "revision-1",
    title: str = "Private appointment",
) -> CalendarEvent:
    return CalendarEvent(
        reference=EventRef(calendar or rule().source, EventId(event_id)),
        time=TimedInterval(NOW, NOW + timedelta(hours=1)),
        revision=revision,
        title=title,
        description="Sensitive description",
        location="Sensitive location",
    )


def rescheduled(source: CalendarEvent, revision: str, *, hours: int = 1) -> CalendarEvent:
    """The timed source event at a later time, as a new revision, so its projection changes."""
    assert isinstance(source.time, TimedInterval)
    later = timedelta(hours=hours)
    time = TimedInterval(source.time.starts_at + later, source.time.ends_at + later)
    return replace(source, revision=revision, time=time)


def all_day_event() -> CalendarEvent:
    return CalendarEvent(
        reference=EventRef(rule().source, EventId("all-day")),
        time=AllDayRange(date(2026, 8, 30), date(2026, 8, 31)),
        revision="all-day-revision",
        title="Day off",
    )


SERIES_START = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


def week_start(week: int) -> datetime:
    return SERIES_START + timedelta(weeks=week)


def instance_id(series_id: str, start: OccurrenceStart) -> str:
    token = (
        start.strftime("%Y%m%dT%H%M%SZ")
        if isinstance(start, datetime)
        else start.strftime("%Y%m%d")
    )
    return f"{series_id}_{token}"


def series(
    event_id: str = "source-series",
    *,
    calendar: CalendarEndpoint | None = None,
    revision: str = "series-revision-1",
    title: str = "Weekly private sync",
    all_day: bool = False,
    managed_origin: ManagedOrigin | None = None,
    status: EventStatus = EventStatus.CONFIRMED,
) -> CalendarEvent:
    time = (
        AllDayRange(SERIES_START.date(), SERIES_START.date() + timedelta(days=1))
        if all_day
        else TimedInterval(SERIES_START, SERIES_START + timedelta(hours=1), "Europe/Madrid")
    )
    return CalendarEvent(
        reference=EventRef(calendar or rule().source, EventId(event_id)),
        time=None if status is EventStatus.CANCELLED else time,
        revision=revision,
        status=status,
        title=title,
        description="Sensitive description",
        location="Sensitive location",
        recurrence=Recurrence(("RRULE:FREQ=WEEKLY;COUNT=10",)),
        managed_origin=managed_origin,
    )


def occurrence(
    parent: CalendarEvent,
    week: int = 1,
    *,
    moved_by: timedelta = timedelta(0),
    revision: str = "occurrence-revision-1",
    title: str | None = None,
    status: EventStatus = EventStatus.CONFIRMED,
    all_day: bool = False,
    managed_origin: ManagedOrigin | None = None,
) -> CalendarEvent:
    start = week_start(week)
    time: TimedInterval | AllDayRange | None
    if status is EventStatus.CANCELLED:
        time = None
    elif all_day:
        time = AllDayRange(start.date(), start.date() + timedelta(days=1))
    else:
        time = TimedInterval(start + moved_by, start + moved_by + timedelta(hours=1))
    return CalendarEvent(
        reference=EventRef(
            parent.reference.calendar,
            EventId(instance_id(parent.reference.event_id.value, start)),
        ),
        time=time,
        revision=revision,
        status=status,
        title="" if status is EventStatus.CANCELLED else (title or parent.title),
        description="" if status is EventStatus.CANCELLED else parent.description,
        location="" if status is EventStatus.CANCELLED else parent.location,
        occurrence=OccurrenceIdentity(parent.reference.event_id, start),
        managed_origin=managed_origin,
    )
