"""A Source Cancellation matters to a rule only through its projection: a deleted event, series,
or occurrence the rule never projected is no decision of the rule, so Activity records nothing
for it, and one it projected is removed."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from calendar_sync.domain.model import (
    CalendarEvent,
    EventStatus,
    InvitationResponse,
    SyncAction,
    SyncReason,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUserUnitOfWorkFactory
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import occurrence, rule, series, week_start

STARTS = tuple(week_start(week) for week in range(4))


def _cancelled(event: CalendarEvent, revision: str = "deleted") -> CalendarEvent:
    """The event as a provider keeps it once deleted: cancelled, with its last time."""
    return replace(event, status=EventStatus.CANCELLED, revision=revision)


def _moved(master: CalendarEvent, week: int) -> CalendarEvent:
    return occurrence(master, week, moved_by=timedelta(days=2, hours=7))


def test_a_series_deleted_before_a_new_rule_runs_leaves_no_activity() -> None:
    # Projected by an earlier rule, then deleted in the source; a new rule finds its tombstones.
    calendars = FakeCalendars()
    master = calendars.put(_cancelled(series("cg-test-a")), starts=STARTS)
    calendars.put(_cancelled(_moved(master, 2)))
    factory = enabled_rule_factory()

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert factory.state.audit == []
    assert calendars.writes == []
    assert result.ignored == 2


def test_a_deleted_series_whose_tombstone_has_no_recurrence_leaves_no_activity() -> None:
    # A provider may keep only the identity and status of a deleted event.
    calendars = FakeCalendars()
    master = calendars.put(
        replace(_cancelled(series("cg-test-a")), recurrence=None, title="", description="")
    )
    calendars.put(_cancelled(_moved(series("cg-test-a"), 2)))
    factory = enabled_rule_factory()

    sync_use_case(factory, calendars).execute(rule().id)

    assert master.recurrence is None
    assert factory.state.audit == []
    assert calendars.writes == []


def test_an_occurrence_of_a_deleted_series_leaves_no_activity_though_it_reads_confirmed() -> None:
    # The series' cancellation proves every occurrence of it gone.
    calendars = FakeCalendars()
    master = calendars.put(_cancelled(series("cg-test-a")), starts=STARTS)
    calendars.put(_moved(master, 2))
    factory = enabled_rule_factory()

    sync_use_case(factory, calendars).execute(rule().id)

    assert factory.state.audit == []
    assert calendars.writes == []


def _projected_series_with_a_moved_occurrence() -> tuple[
    FakeCalendars, CalendarEvent, CalendarEvent, InMemoryUserUnitOfWorkFactory
]:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS)
    moved = calendars.put(_moved(master, 2))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    return calendars, master, moved, factory


def test_deleting_a_projected_series_records_only_its_removal() -> None:
    calendars, master, moved, factory = _projected_series_with_a_moved_occurrence()
    destination = factory.state.mappings[(rule().id, master.reference)].destination
    recorded = len(factory.state.audit)
    calendars.report(
        calendars.put(_cancelled(master)), calendars.put(_cancelled(moved, "moved-deleted"))
    )

    sync_use_case(factory, calendars).execute(rule().id)

    assert destination not in calendars.events
    entries = factory.state.audit[recorded:]
    assert [(entry.action, entry.reason) for entry in entries] == [
        ("delete", SyncReason.SOURCE_CANCELLED)
    ]


def test_an_occurrence_reported_before_its_deleted_series_still_removes_the_series() -> None:
    # Only the occurrence's change is in the feed; reading its series finds the series deleted.
    calendars, master, moved, factory = _projected_series_with_a_moved_occurrence()
    destination = factory.state.mappings[(rule().id, master.reference)].destination
    recorded = len(factory.state.audit)
    calendars.put(_cancelled(master))
    calendars.report(calendars.put(_cancelled(moved, "moved-deleted")))

    sync_use_case(factory, calendars).execute(rule().id)

    assert destination not in calendars.events
    entries = factory.state.audit[recorded:]
    assert [(entry.action, entry.reason) for entry in entries] == [
        ("delete", SyncReason.SOURCE_CANCELLED)
    ]


def test_an_edited_occurrence_of_a_series_deleted_in_the_source_removes_the_series() -> None:
    # The destination reports the edit before the source reports the deletion.
    calendars, master, _moved_occurrence, factory = _projected_series_with_a_moved_occurrence()
    destination = factory.state.mappings[(rule().id, master.reference)].destination
    [written] = [
        instance
        for instance in calendars.instances_of(destination)
        if instance.status is EventStatus.CONFIRMED
    ]
    calendars.put(_cancelled(master))
    calendars.report(calendars.put(replace(written, title="Edited", revision="edited")))

    sync_use_case(factory, calendars).execute(rule().id)

    assert destination not in calendars.events
    assert factory.state.audit[-1].reason == SyncReason.SOURCE_CANCELLED
    assert factory.state.audit[-1].action == SyncAction.DELETE.value


def _declined_series() -> tuple[FakeCalendars, CalendarEvent]:
    calendars = FakeCalendars()
    master = calendars.put(replace(series(), response=InvitationResponse.DECLINED), starts=STARTS)
    return calendars, master


def test_a_cancelled_occurrence_of_a_series_the_rule_skips_leaves_no_activity() -> None:
    calendars, master = _declined_series()
    calendars.put(_cancelled(_moved(master, 2)))
    factory = enabled_rule_factory()

    sync_use_case(factory, calendars).execute(rule().id)

    assert [(entry.source_event_id, entry.reason) for entry in factory.state.audit] == [
        (master.reference.event_id.value, SyncReason.DECLINED)
    ]


def test_a_live_occurrence_of_a_series_the_rule_skips_is_still_explained() -> None:
    calendars, master = _declined_series()
    moved = calendars.put(_moved(master, 2))
    factory = enabled_rule_factory()

    sync_use_case(factory, calendars).execute(rule().id)

    assert (moved.reference.event_id.value, SyncReason.SERIES_NOT_SYNCHRONIZED) in {
        (entry.source_event_id, entry.reason) for entry in factory.state.audit
    }


def _lone_projection() -> tuple[FakeCalendars, CalendarEvent, InMemoryUserUnitOfWorkFactory]:
    """One occurrence of a series the calendar does not show, projected on its own."""
    calendars = FakeCalendars()
    invited = calendars.put(occurrence(series("their-series"), 2, title="Planning"))
    calendars.report(invited)
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    return calendars, invited, factory


def test_a_lone_projection_is_removed_once_its_series_shows_as_deleted() -> None:
    calendars, invited, factory = _lone_projection()
    lone = factory.state.mappings[(rule().id, invited.reference)].destination
    calendars.put(_cancelled(series("their-series")), starts=STARTS)
    calendars.report(calendars.put(_cancelled(invited, "invited-deleted")))

    sync_use_case(factory, calendars).execute(rule().id)

    assert lone not in calendars.events
    assert (rule().id, invited.reference) not in factory.state.mappings
    assert factory.state.audit[-1].reason == SyncReason.SOURCE_CANCELLED


def test_a_lone_projection_is_removed_when_only_its_series_deletion_is_reported() -> None:
    calendars, invited, factory = _lone_projection()
    lone = factory.state.mappings[(rule().id, invited.reference)].destination
    calendars.report(calendars.put(_cancelled(series("their-series")), starts=STARTS))

    sync_use_case(factory, calendars).execute(rule().id)

    assert lone not in calendars.events
    assert factory.state.audit[-1].reason == SyncReason.SOURCE_CANCELLED
