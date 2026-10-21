from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import pytest

from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.provider_ports import CreatedProjection
from calendar_sync.application.sync.synchronization import ExecuteSyncRule
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarEvent,
    EventId,
    EventProjection,
    EventRef,
    EventStatus,
    OccurrenceIdentity,
    Recurrence,
    SyncReason,
    SyncRuleId,
    TimedInterval,
    TransformationPolicy,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from calendar_sync.infrastructure.identifiers import UuidRunIdGenerator
from calendar_sync.infrastructure.persistence.memory import InMemoryUserUnitOfWorkFactory
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import NOW, event, instance_id, rescheduled, rule, series

LONG_AGO = datetime(2023, 5, 10, 9, 0, tzinfo=UTC)


def _ended_long_ago(event_id: str = "old-event", revision: str = "revision-2") -> CalendarEvent:
    return replace(
        event(event_id, revision=revision),
        time=TimedInterval(LONG_AGO, LONG_AGO + timedelta(hours=1)),
    )


def test_incremental_change_to_an_event_that_ended_before_the_window_is_not_projected() -> None:
    calendars = FakeCalendars()
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    # Google's incremental feed is not bounded by the initial timeMin.
    calendars.report(calendars.put(_ended_long_ago()))

    result = sync.execute(rule().id)

    assert result.created == 0
    assert calendars.writes == []
    assert factory.state.mappings == {}
    assert result.ignored == 1
    # An event outside the rule's scope is counted, not explained in Activity.
    assert factory.state.audit == []


def test_incremental_change_to_an_event_inside_the_window_is_projected() -> None:
    calendars = FakeCalendars()
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    recent = replace(
        event("recent-event"),
        time=TimedInterval(NOW - timedelta(days=29), NOW - timedelta(days=29, hours=-1)),
    )
    calendars.report(calendars.put(recent))

    result = sync.execute(rule().id)

    assert result.created == 1


def test_mapped_event_moved_before_the_window_is_still_updated() -> None:
    calendars = FakeCalendars()
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    calendars.put(event("moved-event"))
    sync.execute(rule().id)
    calendars.report(calendars.put(_ended_long_ago("moved-event")))

    result = sync.execute(rule().id)

    assert result.updated == 1
    destination = factory.state.mappings[(rule().id, event("moved-event").reference)].destination
    moved = calendars.events[destination].time
    assert isinstance(moved, TimedInterval)
    assert moved.starts_at == LONG_AGO


@dataclass
class MovingClock:
    current: datetime = NOW

    def now(self) -> datetime:
        return self.current


class CrashAfterCreate(FakeCalendars):
    """Google acknowledges the create, then the process dies before the mapping commits."""

    crash = True

    def create_projection(
        self,
        destination: CalendarEndpoint,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CreatedProjection:
        created = super().create_projection(destination, source, rule_id, projection, operation_key)
        if self.crash:
            self.crash = False
            raise RuntimeError("process stopped")
        return created


def test_create_acknowledged_before_a_crash_is_adopted_after_it_leaves_the_window() -> None:
    calendars = CrashAfterCreate()
    factory = enabled_rule_factory()
    clock = MovingClock()
    fingerprinter = ProjectionFingerprinter()
    sync = ExecuteSyncRule(
        factory,
        calendars,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        clock,
        UuidRunIdGenerator(),
        locks=RuleLocks(),
    )
    sync.execute(rule().id)
    edge = replace(
        event("edge-event"),
        time=TimedInterval(NOW - timedelta(days=29, hours=23), NOW - timedelta(days=29, hours=22)),
    )
    calendars.report(calendars.put(edge))
    with pytest.raises(RuntimeError):
        sync.execute(rule().id)
    assert factory.state.mappings == {}

    # The uncommitted batch is replayed after the event has crossed the rolling cutoff.
    clock.current = NOW + timedelta(days=1)
    calendars.report(edge)
    sync.execute(rule().id)

    mapping = factory.state.mappings[(rule().id, edge.reference)]
    projections = [ref for ref, item in calendars.events.items() if item.managed_origin]
    assert projections == [mapping.destination]
    assert calendars.writes == [("create", mapping.destination.event_id.value)]


# A series that ended long ago, as a listing from the window start may still report it.
OLD_STARTS = tuple(LONG_AGO + timedelta(weeks=week) for week in range(3))


def ended_series(
    event_id: str = "old-series",
    starts: tuple[datetime, ...] = OLD_STARTS,
    *,
    revision: str = "old-series-revision-1",
) -> tuple[CalendarEvent, tuple[datetime, ...]]:
    """A weekly series whose occurrences start at `starts`, all long ago unless one is given."""
    first = starts[0]
    master = replace(
        series(event_id, revision=revision),
        time=TimedInterval(first, first + timedelta(hours=1), "Europe/Madrid"),
        recurrence=Recurrence((f"RRULE:FREQ=WEEKLY;COUNT={len(starts)}",)),
    )
    return master, starts


def moved_occurrence(master: CalendarEvent, start: datetime) -> CalendarEvent:
    """The occurrence at `start`, moved three hours later and renamed."""
    moved = start + timedelta(hours=3)
    return CalendarEvent(
        reference=EventRef(
            master.reference.calendar,
            EventId(instance_id(master.reference.event_id.value, start)),
        ),
        time=TimedInterval(moved, moved + timedelta(hours=1)),
        revision="moved-revision-1",
        title="Moved",
        occurrence=OccurrenceIdentity(master.reference.event_id, start),
    )


@dataclass
class LiveLookups(FakeCalendars):
    """Records each live-occurrence lookup with the instant it asked from."""

    lookups: list[tuple[EventRef, datetime | None]] = field(default_factory=list)

    def has_live_occurrences(
        self,
        series: EventRef,
        policy: TransformationPolicy,
        not_ended_before: datetime | None = None,
    ) -> bool:
        self.lookups.append((series, not_ended_before))
        return super().has_live_occurrences(series, policy, not_ended_before)


def test_a_series_that_ended_before_the_window_is_not_projected() -> None:
    # Regression: a new rule "from the past 30 days" created series that ended years ago.
    calendars = FakeCalendars()
    master, starts = ended_series()
    calendars.put(master, starts=starts)
    factory = enabled_rule_factory()

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert (result.created, result.ignored) == (0, 1)
    assert calendars.writes == []
    assert factory.state.mappings == {}
    # Past, as a single event that ended before the window: counted, not explained in Activity.
    assert factory.state.audit == []


def test_a_change_to_a_series_and_occurrence_that_ended_before_the_window_records_nothing() -> None:
    calendars = FakeCalendars()
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    master, starts = ended_series()
    calendars.report(
        calendars.put(master, starts=starts), calendars.put(moved_occurrence(master, starts[1]))
    )

    result = sync.execute(rule().id)

    assert (result.created, result.updated, result.ignored) == (0, 0, 2)
    assert calendars.writes == []
    assert factory.state.mappings == {}
    assert factory.state.audit == []


@pytest.mark.parametrize(
    "last", [NOW - timedelta(days=10), NOW + timedelta(days=7)], ids=["in the window", "upcoming"]
)
def test_a_series_that_began_long_ago_is_projected_while_an_occurrence_reaches_the_window(
    last: datetime,
) -> None:
    calendars = LiveLookups()
    master, starts = ended_series(starts=(*OLD_STARTS, last))
    calendars.put(master, starts=starts)
    factory = enabled_rule_factory()

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert result.created == 1
    assert (rule().id, master.reference) in factory.state.mappings
    # Live in the window is live at all, so the window's lookup is the only one.
    assert calendars.lookups == [(master.reference, NOW - timedelta(days=30))]


def test_a_series_that_ended_before_the_window_costs_one_more_lookup() -> None:
    calendars = LiveLookups()
    master, starts = ended_series()
    calendars.put(master, starts=starts)

    sync_use_case(enabled_rule_factory(), calendars).execute(rule().id)

    assert calendars.lookups == [
        (master.reference, NOW - timedelta(days=30)),
        (master.reference, None),
    ]


def test_a_series_that_ended_before_the_window_with_no_live_occurrence_is_without_one() -> None:
    calendars = FakeCalendars()
    master, starts = ended_series(starts=OLD_STARTS[:1])
    calendars.put(master, starts=starts)
    calendars.put(
        replace(
            moved_occurrence(master, starts[0]),
            status=EventStatus.CANCELLED,
            time=None,
        )
    )
    factory = enabled_rule_factory()

    sync_use_case(factory, calendars).execute(rule().id)

    # Nothing to project at all is still said as it was, before the window or not.
    assert [entry.reason for entry in factory.state.audit] == [
        SyncReason.SERIES_WITHOUT_OCCURRENCES.value
    ]


def test_a_mapped_series_that_ended_before_the_window_stays_current() -> None:
    calendars = FakeCalendars()
    factory = enabled_rule_factory()
    clock = MovingClock()
    sync = _sync_with(factory, calendars, clock)
    master, starts = ended_series(starts=(NOW + timedelta(days=1), NOW + timedelta(days=8)))
    calendars.put(master, starts=starts)
    sync.execute(rule().id)
    mapping = factory.state.mappings[(rule().id, master.reference)]

    # Years later the series is past, and someone moves it an hour later.
    clock.current = NOW + timedelta(days=800)
    moved = rescheduled(master, "moved")
    calendars.report(calendars.put(moved, starts=starts))
    result = sync.execute(rule().id)

    assert result.updated == 1
    assert factory.state.mappings[(rule().id, master.reference)].source_revision == "moved"
    assert calendars.events[mapping.destination].time == moved.time


def test_a_series_create_acknowledged_before_a_crash_is_adopted_after_it_leaves_the_window() -> (
    None
):
    calendars = CrashAfterCreate()
    factory = enabled_rule_factory()
    clock = MovingClock()
    sync = _sync_with(factory, calendars, clock)
    sync.execute(rule().id)
    master, starts = ended_series(starts=(NOW - timedelta(days=29, hours=23),))
    calendars.report(calendars.put(master, starts=starts))
    with pytest.raises(RuntimeError):
        sync.execute(rule().id)
    assert factory.state.mappings == {}

    # The uncommitted batch is replayed after the series' only occurrence crossed the cutoff.
    clock.current = NOW + timedelta(days=1)
    calendars.report(master)
    sync.execute(rule().id)

    mapping = factory.state.mappings[(rule().id, master.reference)]
    projections = [ref for ref, item in calendars.events.items() if item.managed_origin]
    assert projections == [mapping.destination]
    assert calendars.writes == [("create", mapping.destination.event_id.value)]


def _sync_with(
    factory: InMemoryUserUnitOfWorkFactory, calendars: FakeCalendars, clock: MovingClock
) -> ExecuteSyncRule:
    fingerprinter = ProjectionFingerprinter()
    return ExecuteSyncRule(
        factory,
        calendars,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        clock,
        UuidRunIdGenerator(),
        locks=RuleLocks(),
    )
