"""Outside the daily pass, a skip that repeats the event's previous entry is not recorded."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from calendar_sync.domain.audit import AuditAction
from calendar_sync.domain.changes import ComparisonKind, SourceField
from calendar_sync.domain.model import (
    CalendarEvent,
    EventStatus,
    ManagedOrigin,
    SyncReason,
    SyncRuleId,
)
from calendar_sync.infrastructure.persistence.activity_queries import open_blocks
from calendar_sync.infrastructure.persistence.memory import InMemoryUserUnitOfWorkFactory
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import event, occurrence, rule, series, week_start
from tests.users import USER, sqlite_units

GUESTS = ("ana@example.com",)
STARTS = tuple(week_start(week) for week in range(4))


def _synced() -> tuple[FakeCalendars, InMemoryUserUnitOfWorkFactory]:
    calendars = FakeCalendars()
    calendars.put(replace(event(), guests=GUESTS, conferencing=()))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    return calendars, factory


def _send(
    calendars: FakeCalendars, factory: InMemoryUserUnitOfWorkFactory, *events: CalendarEvent
) -> int:
    recorded = len(factory.state.audit)
    # A series sent again keeps the occurrences it expands to.
    calendars.report(
        *(
            calendars.put(item, starts=calendars.expansions.get(item.reference, ()))
            for item in events
        )
    )
    sync_use_case(factory, calendars).execute(rule().id)
    return recorded


def _revision(name: str, **changes: object) -> CalendarEvent:
    details: dict[str, object] = {"guests": GUESTS, "conferencing": (), **changes}
    return replace(event(), revision=name, **details)  # type: ignore[arg-type]


def test_an_event_sent_again_with_nothing_tracked_changed_is_not_recorded_twice() -> None:
    calendars, factory = _synced()
    _send(calendars, factory, _revision("r2"))  # first "already current" after the create: recorded
    assert factory.state.audit[-1].reason == SyncReason.PROJECTION_CURRENT

    recorded = _send(calendars, factory, _revision("r3"))

    assert factory.state.audit[recorded:] == []
    observation = factory.state.observations[(rule().id, event().reference)][0]
    assert observation.revision == "r2"


def test_a_tracked_change_after_a_left_out_revision_compares_with_the_last_recorded_one() -> None:
    calendars, factory = _synced()
    _send(calendars, factory, _revision("r2"))
    _send(calendars, factory, _revision("r3"))

    recorded = _send(calendars, factory, _revision("r4", title="Renamed"))

    [entry] = factory.state.audit[recorded:]
    assert entry.change is not None
    assert entry.change.fields == (SourceField.TITLE,)
    assert entry.change.before.revision == "r2"


def test_a_complete_guest_list_after_a_partial_one_is_recorded_and_saved() -> None:
    calendars = FakeCalendars()
    # Google shortened the guest list, so the first observation cannot say who was invited.
    calendars.put(_revision("revision-1", guests=None))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    _send(calendars, factory, _revision("r2", guests=None))

    recorded = _send(calendars, factory, _revision("r3"))

    [entry] = factory.state.audit[recorded:]
    assert entry.reason == SyncReason.PROJECTION_CURRENT
    assert entry.change is None
    observation = factory.state.observations[(rule().id, event().reference)][0]
    assert (observation.revision, observation.guests) == ("r3", GUESTS)


def test_a_series_and_its_moved_occurrence_sent_again_unchanged_are_not_recorded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The 2026-10-14 case: the provider sends a series and its occurrence again, unchanged.
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS)
    moved = calendars.put(occurrence(master, 1, moved_by=timedelta(hours=1)))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    _send(calendars, factory, replace(master, revision="s2"), replace(moved, revision="o2"))
    assert [entry.reason for entry in factory.state.audit[-2:]] == [
        SyncReason.PROJECTION_CURRENT,
        SyncReason.OCCURRENCE_CURRENT,
    ]

    with caplog.at_level(logging.INFO, logger="calendar_sync.application.sync.sync_run"):
        recorded = _send(
            calendars, factory, replace(master, revision="s3"), replace(moved, revision="o3")
        )

    assert factory.state.audit[recorded:] == []
    assert "ignored=2 conflicts=0 unrecorded=2" in _finished(caplog)
    observed = factory.state.observations
    assert observed[(rule().id, master.reference)][0].revision == "s2"
    assert observed[(rule().id, moved.reference)][0].revision == "o2"


def test_a_skipped_series_sent_again_unchanged_is_not_recorded() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS[:1])
    calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    assert [entry.reason for entry in factory.state.audit] == [
        SyncReason.SERIES_WITHOUT_OCCURRENCES
    ]

    recorded = _send(calendars, factory, replace(master, revision="series-revision-2"))

    assert factory.state.audit[recorded:] == []


def test_a_series_that_loses_its_last_occurrence_is_recorded() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS[:1])
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    _send(calendars, factory, replace(master, revision="series-revision-2"))
    assert factory.state.audit[-1].reason == SyncReason.PROJECTION_CURRENT
    _send(calendars, factory, occurrence(master, 0, status=EventStatus.CANCELLED))

    # Nothing tracked changed in the series, but the decision about it did.
    recorded = _send(calendars, factory, replace(master, revision="series-revision-3"))

    [entry] = factory.state.audit[recorded:]
    assert entry.source_event_id == master.reference.event_id.value
    assert entry.reason == SyncReason.SERIES_WITHOUT_OCCURRENCES
    assert entry.source_comparison == ComparisonKind.UNTRACKED


def test_an_occurrence_without_its_own_source_is_recorded_every_time() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS[:1])
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    _send(calendars, factory, occurrence(master, 0, status=EventStatus.CANCELLED))
    destination = factory.state.mappings[(rule().id, master.reference)].destination
    projected = calendars.events[destination]
    calendars.put(replace(projected, status=EventStatus.CANCELLED, time=None))
    # An occurrence the source series never had: decided under the series' identity.
    stray = occurrence(projected, 1, managed_origin=projected.managed_origin)

    reasons = []
    for name in ("d1", "d2", "d3"):
        recorded = _send(calendars, factory, replace(stray, revision=name))
        reasons += [
            (entry.source_event_id, entry.reason) for entry in factory.state.audit[recorded:]
        ]

    assert reasons == [(master.reference.event_id.value, SyncReason.SERIES_WITHOUT_OCCURRENCES)] * 3


def test_a_blocked_event_decided_again_without_a_change_is_recorded_and_unblocks(
    tmp_path: Path,
) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = sqlite_units(database)
    with factory() as uow:
        uow.rules.add(rule())
        uow.commit()
    calendars = FakeCalendars()
    calendars.put(_revision("revision-1"))
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    calendars.report(calendars.put(_revision("r2")))
    sync.execute(rule().id)  # "already current", which the later skip would otherwise repeat
    with factory() as uow:
        mapping = uow.mappings.for_source(rule().id, event().reference)
    assert mapping is not None
    projection = calendars.events[mapping.destination]
    calendars.put(
        replace(projection, managed_origin=ManagedOrigin(SyncRuleId("rule-2"), event().reference))
    )
    calendars.report(calendars.put(_revision("r3")))
    assert sync.execute(rule().id).conflicts == 1
    with sqlite3.connect(database) as connection:
        assert len(open_blocks(connection, USER.value)) == 1
    calendars.put(projection)
    calendars.report(calendars.put(_revision("r4")))

    result = sync.execute(rule().id)

    assert result.ignored == 1
    with sqlite3.connect(database) as connection:
        assert open_blocks(connection, USER.value) == []
        latest = connection.execute(
            "SELECT action, reason FROM audit_entries ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert tuple(latest) == (AuditAction.IGNORE.value, SyncReason.PROJECTION_CURRENT.value)


def test_a_cancelled_series_sent_again_is_not_recorded_and_a_restored_one_is() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS)
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    cancelled = series(revision="series-revision-2", status=EventStatus.CANCELLED)
    _send(calendars, factory, cancelled)
    assert factory.state.audit[-1].reason == SyncReason.SOURCE_CANCELLED

    again = _send(calendars, factory, replace(cancelled, revision="series-revision-3"))
    restored = _send(calendars, factory, replace(master, revision="series-revision-4"))

    assert factory.state.audit[again:restored] == []
    [entry] = factory.state.audit[restored:]
    assert entry.reason == SyncReason.SOURCE_CREATED
    # Compared with the observation kept from before the cancellation, which nothing changed.
    assert entry.source_comparison == ComparisonKind.UNTRACKED
    assert entry.change is None


def test_a_cancelled_occurrence_sent_again_is_not_recorded_and_a_restored_one_is() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS)
    moved = calendars.put(occurrence(master, 1, moved_by=timedelta(hours=1)))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    _send(calendars, factory, occurrence(master, 1, status=EventStatus.CANCELLED, revision="c1"))
    _send(calendars, factory, occurrence(master, 1, status=EventStatus.CANCELLED, revision="c2"))
    assert factory.state.audit[-1].reason == SyncReason.OCCURRENCE_ALREADY_CANCELLED

    again = _send(
        calendars, factory, occurrence(master, 1, status=EventStatus.CANCELLED, revision="c3")
    )
    restored = _send(calendars, factory, replace(moved, revision="back"))

    assert factory.state.audit[again:restored] == []
    [entry] = factory.state.audit[restored:]
    assert entry.reason == SyncReason.OCCURRENCE_CHANGED
    assert entry.source_comparison == ComparisonKind.UNTRACKED
    assert entry.change is None


def test_the_daily_pass_records_what_it_recorded_before() -> None:
    calendars, factory = _synced()
    sync = sync_use_case(factory, calendars)

    sync.execute(rule().id, full=True)
    sync.execute(rule().id, full=True)

    assert [entry.reason for entry in factory.state.audit] == [
        SyncReason.SOURCE_CREATED,
        SyncReason.PROJECTION_CURRENT,
        SyncReason.PROJECTION_CURRENT,
    ]


def test_the_run_log_counts_the_entries_it_left_out(caplog: pytest.LogCaptureFixture) -> None:
    calendars, factory = _synced()
    _send(calendars, factory, _revision("r2"))

    with caplog.at_level(logging.INFO, logger="calendar_sync.application.sync.sync_run"):
        _send(calendars, factory, _revision("r3"))

    assert "ignored=1 conflicts=0 unrecorded=1" in _finished(caplog)


def _finished(caplog: pytest.LogCaptureFixture) -> str:
    [line] = [record.getMessage() for record in caplog.records if "run finished" in record.msg]
    return line
