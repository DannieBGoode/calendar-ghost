"""Runs spend provider reads and Audit Entries only where something could have changed."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta

from calendar_sync.application.ports import AuditEntry, RunKind
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    EventRef,
    EventStatus,
    ManagedOrigin,
    SyncReason,
    SyncRuleId,
    TransformationPolicy,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import NOW, all_day_event, event, occurrence, rule, series, week_start

STARTS = tuple(week_start(week) for week in range(4))


def _reasons(entries: Sequence[AuditEntry]) -> list[str | None]:
    return [entry.reason for entry in entries]


def test_managed_projection_in_the_source_feed_is_counted_but_not_recorded() -> None:
    calendars = FakeCalendars()
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    managed = replace(
        event("managed"), managed_origin=ManagedOrigin(SyncRuleId("rule-2"), event("x").reference)
    )
    calendars.report(calendars.put(managed))

    result = sync.execute(rule().id)

    assert result.ignored == 1
    assert factory.state.audit == []


def test_cancelled_event_that_was_never_projected_is_not_recorded() -> None:
    calendars = FakeCalendars()
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    cancelled = replace(event("gone"), status=EventStatus.CANCELLED, time=None)
    calendars.report(calendars.put(cancelled))

    result = sync.execute(rule().id)

    assert result.ignored == 1
    assert factory.state.audit == []


def test_excluded_all_day_event_is_explained_once_not_on_every_daily_pass() -> None:
    calendars = FakeCalendars()
    calendars.put(all_day_event())
    excluding = replace(
        rule(), transformation=TransformationPolicy(all_day=AllDaySyncPolicy.EXCLUDE)
    )
    factory = enabled_rule_factory(excluding)
    sync = sync_use_case(factory, calendars)

    sync.execute(rule().id)
    sync.execute(rule().id, full=True)

    assert _reasons(factory.state.audit) == [SyncReason.ALL_DAY_EXCLUDED.value]


def test_series_without_live_occurrences_is_explained_once_not_on_every_daily_pass() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS[:1])
    calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED))
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)

    sync.execute(rule().id)
    first_run = _reasons(factory.state.audit)
    sync.execute(rule().id, full=True)

    assert SyncReason.SERIES_WITHOUT_OCCURRENCES.value in first_run
    assert _reasons(factory.state.audit) == first_run


def test_projection_echoed_by_the_destination_feed_needs_no_reads_or_entries() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    destination = factory.state.mappings[(rule().id, event().reference)].destination
    calendars.report(calendars.events[destination])
    recorded = len(factory.state.audit)
    calendars.reads.clear()

    result = sync.execute(rule().id)

    assert calendars.reads == []
    assert len(factory.state.audit) == recorded
    assert result.ignored == 1


def test_edited_projection_reported_by_the_destination_feed_is_still_repaired() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    destination = factory.state.mappings[(rule().id, event().reference)].destination
    edited = replace(calendars.events[destination], title="Renamed in the destination")
    calendars.report(calendars.put(edited))

    result = sync.execute(rule().id)

    assert result.updated == 1
    assert factory.state.audit[-1].reason == SyncReason.DESTINATION_DRIFT_REPAIRED.value
    assert calendars.events[destination].title == "Busy"


def test_projection_reported_by_both_feeds_in_one_run_is_decided_once() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    destination = factory.state.mappings[(rule().id, event().reference)].destination
    changed = calendars.put(replace(event(), revision="revision-2", title="Moved"))
    edited = calendars.put(replace(calendars.events[destination], title="Edited"))
    calendars.report(changed, edited)
    first_run = len(factory.state.audit)

    result = sync.execute(rule().id)

    assert result.updated == 1
    assert _reasons(factory.state.audit[first_run:]) == [SyncReason.SOURCE_CHANGED.value]


def test_daily_pass_reuses_the_destination_listing_and_checks_each_projection_once() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    calendars.put(event("second"))
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    first_run = len(factory.state.audit)
    calendars.reads.clear()

    result = sync.execute(rule().id, full=True)

    assert calendars.reads == []
    assert result.ignored == 2
    assert _reasons(factory.state.audit[first_run:]) == [SyncReason.PROJECTION_CURRENT.value] * 2


def test_daily_pass_reads_a_projection_the_listing_did_not_include() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    destination = factory.state.mappings[(rule().id, event().reference)].destination
    # The projection ended before the listing window; only a direct read can prove it exists.
    calendars.events[destination] = replace(
        calendars.events[destination],
        time=replace(
            calendars.events[destination].time,  # type: ignore[type-var]
            starts_at=NOW - timedelta(days=60),
            ends_at=NOW - timedelta(days=60, hours=-1),
        ),
    )
    calendars.reads.clear()

    result = sync.execute(rule().id, full=True)

    assert destination in calendars.reads
    assert result.updated == 1
    assert result.created == 0


def test_occurrence_echoed_by_the_destination_feed_needs_no_reads_or_entries() -> None:
    calendars = FakeCalendars()
    calendars.put(series(), starts=STARTS)
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    destination = factory.state.mappings[(rule().id, series().reference)].destination
    calendars.report(calendars.put(occurrence(series(), 1, moved_by=timedelta(hours=1))))
    sync.execute(rule().id)
    written = calendars.get_occurrence(destination, week_start(1))
    assert written is not None
    calendars.report(written)
    recorded = len(factory.state.audit)
    calendars.reads.clear()

    sync.execute(rule().id)

    assert calendars.reads == []
    assert len(factory.state.audit) == recorded


def test_cancelled_occurrence_echoed_by_the_destination_feed_needs_no_reads() -> None:
    calendars = FakeCalendars()
    calendars.put(series(), starts=STARTS)
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    destination = factory.state.mappings[(rule().id, series().reference)].destination
    calendars.report(calendars.put(occurrence(series(), 1, status=EventStatus.CANCELLED)))
    sync.execute(rule().id)
    cancelled = calendars.get_occurrence(destination, week_start(1))
    assert cancelled is not None and cancelled.status is EventStatus.CANCELLED
    calendars.report(cancelled)
    calendars.reads.clear()

    sync.execute(rule().id)

    assert calendars.reads == []


def test_restored_occurrence_reported_by_the_destination_feed_is_cancelled_again() -> None:
    calendars = FakeCalendars()
    calendars.put(series(), starts=STARTS)
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    destination = factory.state.mappings[(rule().id, series().reference)].destination
    calendars.report(calendars.put(occurrence(series(), 1, status=EventStatus.CANCELLED)))
    sync.execute(rule().id)
    cancelled = calendars.get_occurrence(destination, week_start(1))
    assert cancelled is not None
    restored = calendars.put(
        replace(
            calendars._expand(calendars.events[destination], week_start(1), cancelled.reference),
            revision="restored-by-hand",
        )
    )
    calendars.report(restored)

    sync.execute(rule().id)

    again = calendars.get_occurrence(destination, week_start(1))
    assert again is not None and again.status is EventStatus.CANCELLED


def test_retiring_an_occurrence_record_is_bookkeeping_not_activity() -> None:
    calendars = FakeCalendars()
    calendars.put(series(), starts=STARTS)
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    calendars.report(calendars.put(occurrence(series(), 1, moved_by=timedelta(hours=1))))
    sync.execute(rule().id)
    shortened = replace(series(), revision="series-revision-2")
    calendars.put(shortened, starts=(week_start(0),))
    del calendars.events[occurrence(series(), 1).reference]
    calendars.report(shortened)

    sync.execute(rule().id)

    assert factory.state.occurrences == {}
    assert SyncReason.OCCURRENCE_RETIRED.value not in _reasons(factory.state.audit)


def test_full_pass_verifies_an_unedited_projection_whose_source_was_not_listed() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    destination = factory.state.mappings[(rule().id, event().reference)].destination
    # The source moved before the window without its feed reporting it; only the destination
    # listing reports the mapping, and the projection still matches what this rule wrote.
    calendars.events[event().reference] = replace(
        event(),
        time=replace(
            event().time,  # type: ignore[type-var]
            starts_at=NOW - timedelta(days=60),
            ends_at=NOW - timedelta(days=60, hours=-1),
        ),
    )
    calendars.reads.clear()

    sync.execute(rule().id, full=True)

    assert event().reference in calendars.reads
    assert factory.state.audit[-1].reason == SyncReason.DESTINATION_DRIFT_REPAIRED.value
    assert calendars.events[destination].time == calendars.events[event().reference].time


def _projection_matching_a_source_moved_out_of_the_window() -> tuple[
    FakeCalendars, InMemoryUnitOfWorkFactory, EventRef
]:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    destination = factory.state.mappings[(rule().id, event().reference)].destination
    # The source moved before the window without its feed reporting it, while the projection
    # still matches what this rule wrote; only a source read reveals the Drift.
    calendars.events[event().reference] = replace(
        event(),
        time=replace(
            event().time,  # type: ignore[type-var]
            starts_at=NOW - timedelta(days=60),
            ends_at=NOW - timedelta(days=60, hours=-1),
        ),
    )
    return calendars, factory, destination


def test_expired_cursors_relist_without_trusting_projections_as_echoes() -> None:
    calendars, factory, destination = _projection_matching_a_source_moved_out_of_the_window()
    calendars.expired = {rule().source, rule().destination}

    sync_use_case(factory, calendars).execute(rule().id)

    assert factory.state.audit[-1].reason == SyncReason.DESTINATION_DRIFT_REPAIRED.value
    assert calendars.events[destination].time == calendars.events[event().reference].time


def test_missing_cursors_relist_without_trusting_projections_as_echoes() -> None:
    calendars, factory, destination = _projection_matching_a_source_moved_out_of_the_window()
    factory.state.cursors.clear()
    factory.state.destination_cursors.clear()

    sync_use_case(factory, calendars).execute(rule().id)

    assert factory.state.audit[-1].reason == SyncReason.DESTINATION_DRIFT_REPAIRED.value
    assert calendars.events[destination].time == calendars.events[event().reference].time


def test_first_run_lists_everything_so_it_counts_as_the_days_full_pass() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()

    sync_use_case(factory, calendars).execute(rule().id)

    with factory() as uow:
        latest = uow.run_outcomes.latest(rule().id, RunKind.SYNC)
    assert latest is not None and latest.full_run
    assert latest.last_full_succeeded_at == NOW
