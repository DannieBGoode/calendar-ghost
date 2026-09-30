"""Runs record what changed in a source event on the decision's Audit Entry (ADR 0017)."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from calendar_sync.application.sync_run import SOURCE_CHANGE_RETENTION
from calendar_sync.domain.changes import SourceField, SourceObservation
from calendar_sync.domain.model import (
    CalendarEvent,
    EventStatus,
    ProjectionContent,
    SyncReason,
    SyncRule,
    TimedInterval,
    TransformationPolicy,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import NOW, event, rule

DETAILS = replace(rule(), transformation=TransformationPolicy(content=ProjectionContent.DETAILS))
GUESTS = ("ana@example.com", "ben@example.com")


def _synced(sync_rule: SyncRule | None = None) -> tuple[FakeCalendars, InMemoryUnitOfWorkFactory]:
    calendars = FakeCalendars()
    calendars.put(replace(event(), guests=GUESTS, conferencing=()))
    factory = enabled_rule_factory(sync_rule)
    sync_use_case(factory, calendars).execute(rule().id)
    return calendars, factory


def _run_with(
    calendars: FakeCalendars, factory: InMemoryUnitOfWorkFactory, *reported: CalendarEvent
) -> None:
    calendars.report(*(calendars.put(item) for item in reported))
    sync_use_case(factory, calendars).execute(rule().id)


def _source(**changes: object) -> CalendarEvent:
    details: dict[str, object] = {"guests": GUESTS, "conferencing": (), **changes}
    return replace(event(), **details)  # type: ignore[arg-type]


def test_the_first_observation_of_an_event_records_no_change() -> None:
    _calendars, factory = _synced()

    assert [entry.change for entry in factory.state.audit] == [None]
    assert (rule().id, event().reference) in factory.state.observations


def test_a_changed_description_is_recorded_with_its_values_on_the_update() -> None:
    calendars, factory = _synced(DETAILS)

    _run_with(calendars, factory, _source(revision="revision-2", description="New agenda"))

    entry = factory.state.audit[-1]
    assert entry.reason == SyncReason.SOURCE_CHANGED
    assert entry.change is not None
    assert entry.change.fields == (SourceField.DESCRIPTION,)
    assert entry.change.before.description == "Sensitive description"
    assert entry.change.after.description == "New agenda"


def test_a_rename_a_busy_only_rule_does_not_show_is_recorded_without_a_write() -> None:
    calendars, factory = _synced()
    writes = len(calendars.writes)

    _run_with(calendars, factory, _source(revision="revision-2", title="Renamed"))

    entry = factory.state.audit[-1]
    assert calendars.writes[writes:] == []
    assert entry.reason == SyncReason.PROJECTION_CURRENT
    assert entry.change is not None
    assert entry.change.fields == (SourceField.TITLE,)


def test_a_reply_to_the_invitation_records_no_change() -> None:
    calendars, factory = _synced()

    # Google gives the event a new revision; its guests and details are the same.
    _run_with(calendars, factory, _source(revision="revision-2"))

    assert factory.state.audit[-1].reason == SyncReason.PROJECTION_CURRENT
    assert factory.state.audit[-1].change is None


def test_a_revision_decided_twice_in_one_run_records_its_change_once() -> None:
    calendars, factory = _synced(DETAILS)
    changed = calendars.put(_source(revision="revision-2", location="Room 2"))
    calendars.report(changed, changed)
    recorded = len(factory.state.audit)

    sync_use_case(factory, calendars).execute(rule().id)

    changes = [entry.change for entry in factory.state.audit[recorded:] if entry.change]
    assert [change.fields for change in changes] == [(SourceField.LOCATION,)]


def test_a_restored_event_is_compared_with_how_it_was_before_it_was_cancelled() -> None:
    calendars, factory = _synced(DETAILS)
    cancelled = replace(event(), revision="revision-2", status=EventStatus.CANCELLED, time=None)
    _run_with(calendars, factory, cancelled)

    _run_with(calendars, factory, _source(revision="revision-3", location="Room 2"))

    entry = factory.state.audit[-1]
    assert entry.reason == SyncReason.SOURCE_CREATED
    assert entry.change is not None
    assert entry.change.fields == (SourceField.LOCATION,)


def test_a_decision_activity_leaves_out_does_not_observe_the_event() -> None:
    calendars, factory = _synced()
    ended = replace(
        event("long-ago"),
        time=TimedInterval(NOW - timedelta(days=60), NOW - timedelta(days=60, hours=-1)),
    )

    _run_with(calendars, factory, ended)

    assert factory.state.audit[-1].reason != SyncReason.BEFORE_SYNC_WINDOW
    assert (rule().id, ended.reference) not in factory.state.observations


def test_a_full_listing_forgets_old_change_values_and_ended_events() -> None:
    calendars, factory = _synced()
    ended = replace(
        event("ended"),
        time=TimedInterval(NOW - timedelta(days=100), NOW - timedelta(days=100, hours=-1)),
    )
    observation = SourceObservation.of(ended)
    assert observation is not None
    factory.state.observations[(rule().id, ended.reference)] = (observation, NOW)

    sync_use_case(factory, calendars).execute(rule().id, full=True)

    assert factory.state.change_values_forgotten_before == NOW - SOURCE_CHANGE_RETENTION
    assert (rule().id, ended.reference) not in factory.state.observations
    assert (rule().id, event().reference) in factory.state.observations


def test_a_revision_both_feeds_report_in_one_run_records_its_change_once() -> None:
    calendars, factory = _synced(DETAILS)
    destination = factory.state.mappings[(rule().id, event().reference)].destination
    changed = calendars.put(_source(revision="revision-2", location="Room 2"))
    edited = calendars.put(replace(calendars.events[destination], title="Edited"))
    calendars.report(changed, edited)
    recorded = len(factory.state.audit)

    sync_use_case(factory, calendars).execute(rule().id)

    changes = [entry.change for entry in factory.state.audit[recorded:] if entry.change]
    assert [change.fields for change in changes] == [(SourceField.LOCATION,)]


def test_a_shortened_guest_list_keeps_the_last_complete_one() -> None:
    calendars, factory = _synced()
    # Google shortened the guest list, so this revision cannot say who was removed.
    _run_with(calendars, factory, _source(revision="revision-2", guests=None))

    _run_with(calendars, factory, _source(revision="revision-3", guests=("ana@example.com",)))

    change = factory.state.audit[-1].change
    assert change is not None
    assert change.fields == (SourceField.GUESTS,)
    assert change.before.guests == GUESTS
