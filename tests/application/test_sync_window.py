from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from calendar_sync.domain.model import CalendarEvent, SyncReason, TimedInterval
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import NOW, event, rule

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
    assert factory.state.audit[-1].reason == SyncReason.BEFORE_SYNC_WINDOW.value


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
