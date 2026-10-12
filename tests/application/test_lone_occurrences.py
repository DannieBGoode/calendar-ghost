"""An occurrence whose series its calendar does not show, as when someone invites you to one
meeting of their recurring series, is an event of that calendar like any other. It projects as a
single event until its series appears (ADR 0011)."""

from dataclasses import replace
from datetime import timedelta

from calendar_sync.domain.model import (
    CalendarEvent,
    EventId,
    EventRef,
    EventStatus,
    InvitationResponse,
    SyncReason,
    TimedInterval,
)
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import occurrence, rule, series, week_start

STARTS = tuple(week_start(week) for week in range(4))


def _invited() -> tuple[FakeCalendars, CalendarEvent]:
    """The calendar holds one occurrence of a series it does not show."""
    calendars = FakeCalendars()
    invited = calendars.put(occurrence(series("their-series"), 2, title="Planning"))
    calendars.report(invited)
    return calendars, invited


def test_an_occurrence_whose_series_is_not_shown_projects_as_a_single_event() -> None:
    calendars, invited = _invited()
    factory = enabled_rule_factory()

    result = sync_use_case(factory, calendars).execute(rule().id)

    mapping = factory.state.mappings[(rule().id, invited.reference)]
    projected = calendars.events[mapping.destination]
    assert projected.time == invited.time
    assert projected.recurrence is None
    assert projected.occurrence is None
    assert result.created == 1
    assert factory.state.audit[-1].reason == SyncReason.SOURCE_CREATED


def test_a_lone_occurrence_cancelled_in_the_source_is_removed() -> None:
    calendars, invited = _invited()
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    destination = factory.state.mappings[(rule().id, invited.reference)].destination
    calendars.report(calendars.put(replace(invited, status=EventStatus.CANCELLED, revision="r2")))

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert result.deleted == 1
    assert destination not in calendars.events


def test_an_edit_to_a_lone_occurrences_projection_is_repaired() -> None:
    calendars, invited = _invited()
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    destination = factory.state.mappings[(rule().id, invited.reference)].destination
    edited = calendars.put(
        replace(calendars.events[destination], title="Edited in destination", revision="d2")
    )
    calendars.report(edited)

    sync_use_case(factory, calendars).execute(rule().id)

    assert calendars.events[destination].title == "Busy"


def test_a_lone_occurrence_leaves_its_single_projection_once_its_series_is_shown() -> None:
    calendars, invited = _invited()
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    lone = factory.state.mappings[(rule().id, invited.reference)].destination
    # Invited to the whole series now: the calendar shows it, and reports the occurrence again.
    master = calendars.put(series("their-series"), starts=STARTS)
    assert isinstance(invited.time, TimedInterval)
    later = timedelta(hours=1)
    moved = calendars.put(
        replace(
            invited,
            revision="r2",
            time=TimedInterval(invited.time.starts_at + later, invited.time.ends_at + later),
        )
    )
    calendars.report(master, moved)

    sync_use_case(factory, calendars).execute(rule().id)

    assert (rule().id, invited.reference) not in factory.state.mappings
    assert lone not in calendars.events
    series_mapping = factory.state.mappings[(rule().id, master.reference)]
    shown = calendars.get_occurrence(series_mapping.destination, week_start(2))
    assert shown is not None
    assert shown.time == moved.time
    assert SyncReason.OCCURRENCE_JOINED_SERIES in {entry.reason for entry in factory.state.audit}


def _series_now_shown(calendars: FakeCalendars, invited: CalendarEvent) -> CalendarEvent:
    """The calendar shows the whole series now, and reports the occurrence again."""
    master = calendars.put(series("their-series"), starts=STARTS)
    calendars.report(master, calendars.put(replace(invited, revision="r2")))
    return master


def test_a_lone_projection_stays_while_its_series_cannot_be_shown() -> None:
    # The destination cannot hold the series, so removing the single event would show nothing.
    calendars, invited = _invited()
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    lone = factory.state.mappings[(rule().id, invited.reference)].destination
    calendars.unsupported.add(EventRef(rule().source, EventId("their-series")))

    _series_now_shown(calendars, invited)
    sync_use_case(factory, calendars).execute(rule().id)

    assert (rule().id, invited.reference) in factory.state.mappings
    assert lone in calendars.events


def test_a_lone_projection_someone_invited_guests_to_is_reported_blocked() -> None:
    calendars, invited = _invited()
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    lone = factory.state.mappings[(rule().id, invited.reference)].destination
    calendars.undeletable.add(lone)

    _series_now_shown(calendars, invited)
    result = sync_use_case(factory, calendars).execute(rule().id)

    assert lone in calendars.events
    assert result.conflicts == 1
    blocked = [entry for entry in factory.state.audit if entry.outcome == "blocked"]
    assert [entry.reason for entry in blocked] == [SyncReason.PROJECTION_HAS_GUESTS]


def test_a_lone_projection_stays_while_its_series_shows_the_occurrence_wrong() -> None:
    # The destination refuses the occurrence's move, so its series shows it at its regular time.
    calendars, invited = _invited()
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    lone = factory.state.mappings[(rule().id, invited.reference)].destination
    calendars.unsupported_occurrences.add(week_start(2))
    master = calendars.put(series("their-series"), starts=STARTS)
    moved = occurrence(
        series("their-series"), 2, title="Planning", moved_by=timedelta(hours=1), revision="r2"
    )
    calendars.report(master, calendars.put(moved))

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert result.conflicts == 1
    assert (rule().id, invited.reference) in factory.state.mappings
    assert lone in calendars.events


def test_a_lone_projection_leaves_when_only_its_series_is_reported() -> None:
    # Invited to the whole series, the occurrence is a regular one of it and is not reported.
    calendars, invited = _invited()
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    lone = factory.state.mappings[(rule().id, invited.reference)].destination
    del calendars.events[invited.reference]
    calendars.report(calendars.put(series("their-series"), starts=STARTS))

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert result.deleted == 1
    assert (rule().id, invited.reference) not in factory.state.mappings
    assert lone not in calendars.events
    assert factory.state.audit[-1].reason == SyncReason.OCCURRENCE_JOINED_SERIES


def test_a_lone_occurrence_cancelled_as_its_series_is_shown_leaves_no_projection() -> None:
    calendars, invited = _invited()
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    lone = factory.state.mappings[(rule().id, invited.reference)].destination
    master = calendars.put(series("their-series"), starts=STARTS)
    cancelled = calendars.put(replace(invited, status=EventStatus.CANCELLED, revision="r2"))
    calendars.report(master, cancelled)

    sync_use_case(factory, calendars).execute(rule().id)

    assert lone not in calendars.events
    series_mapping = factory.state.mappings[(rule().id, master.reference)]
    shown = calendars.get_occurrence(series_mapping.destination, week_start(2))
    assert shown is None or shown.status is EventStatus.CANCELLED
    assert SyncReason.SOURCE_CANCELLED in {entry.reason for entry in factory.state.audit}


def _declined_series() -> CalendarEvent:
    return replace(series("their-series"), response=InvitationResponse.DECLINED)


def test_a_lone_projection_leaves_when_its_series_is_shown_but_excluded() -> None:
    # A series the rule leaves out projects none of its occurrences, even one accepted on its own
    # (ADR 0018), so the single projection would be the only trace of it in the destination.
    calendars, invited = _invited()
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    lone = factory.state.mappings[(rule().id, invited.reference)].destination
    master = calendars.put(_declined_series(), starts=STARTS)
    calendars.report(master, calendars.put(replace(invited, revision="r2")))

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert result.deleted == 1
    assert lone not in calendars.events
    assert (rule().id, invited.reference) not in factory.state.mappings
    assert (rule().id, master.reference) not in factory.state.mappings
    assert SyncReason.DECLINED_REMOVED in {entry.reason for entry in factory.state.audit}


def test_a_lone_projection_leaves_when_only_its_excluded_series_is_reported() -> None:
    calendars, invited = _invited()
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    lone = factory.state.mappings[(rule().id, invited.reference)].destination
    calendars.report(calendars.put(_declined_series(), starts=STARTS))

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert result.deleted == 1
    assert lone not in calendars.events
    assert factory.state.audit[-1].reason == SyncReason.DECLINED_REMOVED


def test_a_lone_projection_of_an_excluded_series_someone_invited_guests_to_is_blocked() -> None:
    calendars, invited = _invited()
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    lone = factory.state.mappings[(rule().id, invited.reference)].destination
    calendars.undeletable.add(lone)
    calendars.report(calendars.put(_declined_series(), starts=STARTS))

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert lone in calendars.events
    assert result.conflicts == 1
    assert factory.state.audit[-1].reason == SyncReason.PROJECTION_HAS_GUESTS


def test_a_lone_projection_stays_while_its_excluded_series_cannot_find_the_occurrence() -> None:
    # Unread, the occurrence is decided as the single event it was projected as.
    calendars, invited = _invited()
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    lone = factory.state.mappings[(rule().id, invited.reference)].destination
    without_it = tuple(start for start in STARTS if start != week_start(2))
    calendars.report(calendars.put(_declined_series(), starts=without_it))

    sync_use_case(factory, calendars).execute(rule().id)

    assert lone in calendars.events


def test_a_full_pass_removes_a_lone_projection_whose_series_is_shown_but_excluded() -> None:
    # Reprojection after a policy change or an upgrade lists the calendar in full; nothing is
    # reported as changed.
    calendars, invited = _invited()
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    lone = factory.state.mappings[(rule().id, invited.reference)].destination
    calendars.put(_declined_series(), starts=STARTS)

    result = sync_use_case(factory, calendars).execute(rule().id, full=True)

    assert result.deleted == 1
    assert lone not in calendars.events
    assert (rule().id, invited.reference) not in factory.state.mappings
