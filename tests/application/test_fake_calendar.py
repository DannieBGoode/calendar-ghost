from __future__ import annotations

from calendar_sync.domain.model import EventStatus, ManagedOrigin
from tests.fake_calendar import FakeCalendars
from tests.helpers import instance_id, occurrence, rule, series, week_start


def test_fake_expands_series_and_prefers_stored_exceptions() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=(week_start(0), week_start(1)))
    moved = calendars.put(occurrence(master, 1, title="Moved"))

    assert calendars.get_occurrence(master.reference, week_start(1)) == moved
    expanded = calendars.get_occurrence(master.reference, week_start(0))
    assert expanded is not None
    assert expanded.reference.event_id.value == instance_id("source-series", week_start(0))
    assert calendars.get_occurrence(master.reference, week_start(5)) is None


def test_fake_cancelled_instances_lose_their_metadata() -> None:
    calendars = FakeCalendars()
    origin = ManagedOrigin(rule().id, series().reference)
    master = calendars.put(
        series("projection-1", calendar=rule().destination, managed_origin=origin),
        starts=(week_start(1), week_start(2)),
    )

    calendars.cancel_occurrence(master.reference, week_start(1), series().reference, rule().id, "k")

    cancelled = calendars.get_occurrence(master.reference, week_start(1))
    assert cancelled is not None
    assert cancelled.status is EventStatus.CANCELLED
    assert cancelled.managed_origin is None


def test_fake_cancelling_the_last_live_instance_cancels_the_series() -> None:
    calendars = FakeCalendars()
    origin = ManagedOrigin(rule().id, series().reference)
    master = calendars.put(
        series("projection-1", calendar=rule().destination, managed_origin=origin),
        starts=(week_start(1),),
    )

    calendars.cancel_occurrence(master.reference, week_start(1), series().reference, rule().id, "k")

    assert calendars.events[master.reference].status is EventStatus.CANCELLED
