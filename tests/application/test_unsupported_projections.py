"""A projection the destination's provider cannot hold exactly is a Conflict for that one event,
never an approximation, and the rest of the rule keeps synchronizing (ADR 0032)."""

from dataclasses import replace
from datetime import timedelta

from calendar_sync.domain.model import OccurrenceState, Recurrence, SyncReason
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import event, occurrence, rule, series, week_start

STARTS = tuple(week_start(week) for week in range(4))


def test_an_event_the_destination_cannot_hold_is_blocked_and_the_rest_syncs() -> None:
    calendars = FakeCalendars()
    odd = calendars.put(series("odd-series"), starts=STARTS)
    plain = calendars.put(event("plain-event"))
    calendars.unsupported.add(odd.reference)
    factory = enabled_rule_factory()

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert (rule().id, odd.reference) not in factory.state.mappings
    assert (rule().id, plain.reference) in factory.state.mappings
    assert result.conflicts == 1
    (blocked,) = [entry for entry in factory.state.audit if entry.outcome == "blocked"]
    assert (blocked.action, blocked.reason) == ("conflict", SyncReason.PROJECTION_UNSUPPORTED)
    assert blocked.source_event_id == "odd-series"
    assert blocked.destination_event_id is None


def test_a_series_change_the_destination_cannot_hold_leaves_its_projection_and_mapping() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS)
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    mapping = factory.state.mappings[(rule().id, master.reference)]
    written = calendars.events[mapping.destination]
    changed = calendars.put(
        replace(
            master, revision="series-revision-2", recurrence=Recurrence(("RRULE:FREQ=HOURLY",))
        ),
        starts=STARTS,
    )
    calendars.unsupported.add(changed.reference)
    calendars.report(changed)

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert calendars.events[mapping.destination] == written
    assert factory.state.mappings[(rule().id, master.reference)] == mapping
    assert result.conflicts == 1
    assert factory.state.audit[-1].reason == SyncReason.PROJECTION_UNSUPPORTED


def test_an_occurrence_the_destination_cannot_write_is_blocked_alone() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS)
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    moved = calendars.put(occurrence(master, 1, moved_by=timedelta(hours=1)))
    other = calendars.put(occurrence(master, 2, moved_by=timedelta(hours=2)))
    calendars.unsupported_occurrences.add(week_start(1))
    calendars.report(moved, other)

    result = sync_use_case(factory, calendars).execute(rule().id)

    states = {key[1]: value.state for key, value in factory.state.occurrences.items()}
    assert states == {week_start(2): OccurrenceState.MODIFIED}
    assert result.conflicts == 1
    blocked = [entry for entry in factory.state.audit if entry.outcome == "blocked"]
    assert [entry.reason for entry in blocked] == [SyncReason.PROJECTION_UNSUPPORTED]
