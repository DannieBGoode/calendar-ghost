from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from calendar_sync.application.errors import ProviderFailure, ProviderFailureKind, RuleNotExecutable
from calendar_sync.application.ports import ProviderChangeSet, RecordedEvent
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    CalendarEndpoint,
    CalendarEvent,
    EventRef,
    EventStatus,
    ManagedOrigin,
    OccurrenceStart,
    OccurrenceState,
    ProjectionContent,
    ProjectionFingerprint,
    Recurrence,
    SyncAction,
    SyncReason,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TimedInterval,
    TransformationPolicy,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import occurrence, rule, series, week_start

STARTS = tuple(week_start(week) for week in range(4))


def _synced() -> tuple[FakeCalendars, InMemoryUnitOfWorkFactory, EventRef]:
    calendars = FakeCalendars()
    calendars.put(series(), starts=STARTS)
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    mapping = factory.state.mappings[(rule().id, series().reference)]
    return calendars, factory, mapping.destination


def _occurrence_states(
    factory: InMemoryUnitOfWorkFactory,
) -> dict[OccurrenceStart, OccurrenceState]:
    return {key[1]: mapping.state for key, mapping in factory.state.occurrences.items()}


def test_first_run_creates_one_busy_destination_series_with_its_time_zone() -> None:
    calendars, _factory, destination = _synced()

    projected = calendars.events[destination]
    assert projected.recurrence == series().recurrence
    assert projected.title == "Busy"
    assert isinstance(projected.time, TimedInterval)
    assert projected.time.time_zone == "Europe/Madrid"
    assert calendars.writes == [("create", destination.event_id.value)]


def test_exception_listed_before_its_series_is_applied_after_the_series_is_created() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS)
    moved = occurrence(master, 1, moved_by=timedelta(hours=2), title="Secret offsite")
    factory = enabled_rule_factory()
    calendars.put(moved)
    # A full listing may return the exception first; the run must still create the series first.
    calendars.events = {moved.reference: moved, master.reference: master}

    result = sync_use_case(factory, calendars).execute(rule().id)

    destination = factory.state.mappings[(rule().id, master.reference)].destination
    written = calendars.get_occurrence(destination, week_start(1))
    assert written is not None
    assert written.title == "Busy"
    assert written.time == moved.time
    assert [kind for kind, _ in calendars.writes] == ["create", "write_occurrence"]
    assert _occurrence_states(factory) == {week_start(1): OccurrenceState.MODIFIED}
    assert result.conflicts == 0


def test_exception_without_its_series_in_the_batch_uses_the_existing_series_mapping() -> None:
    calendars, factory, destination = _synced()
    moved = calendars.put(occurrence(series(), 2, moved_by=timedelta(minutes=30)))
    calendars.report(moved)

    sync_use_case(factory, calendars).execute(rule().id)

    written = calendars.get_occurrence(destination, week_start(2))
    assert written is not None
    assert written.time == moved.time


def test_exception_of_an_unmapped_series_creates_the_series_first() -> None:
    calendars = FakeCalendars()
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    master = calendars.put(series(), starts=STARTS)
    moved = calendars.put(occurrence(master, 1, moved_by=timedelta(hours=1)))
    calendars.report(moved)

    sync_use_case(factory, calendars).execute(rule().id)

    assert (rule().id, master.reference) in factory.state.mappings
    assert [kind for kind, _ in calendars.writes] == ["create", "write_occurrence"]


def test_cancelled_source_occurrence_cancels_only_that_destination_occurrence() -> None:
    calendars, factory, destination = _synced()
    cancelled = calendars.put(occurrence(series(), 1, status=EventStatus.CANCELLED))
    calendars.report(cancelled)

    sync_use_case(factory, calendars).execute(rule().id)

    assert calendars.get_occurrence(destination, week_start(1)).status is EventStatus.CANCELLED  # type: ignore[union-attr]
    assert calendars.events[destination].status is EventStatus.CONFIRMED
    assert calendars.writes[-1][0] == "cancel_occurrence"
    assert _occurrence_states(factory) == {week_start(1): OccurrenceState.CANCELLED}


def test_cancelled_series_deletes_the_destination_series_and_its_occurrence_mappings() -> None:
    calendars, factory, destination = _synced()
    calendars.report(calendars.put(occurrence(series(), 1, status=EventStatus.CANCELLED)))
    sync_use_case(factory, calendars).execute(rule().id)
    cancelled_master = calendars.put(
        replace(series(), status=EventStatus.CANCELLED, time=None, recurrence=None)
    )
    calendars.report(cancelled_master)

    sync_use_case(factory, calendars).execute(rule().id)

    assert destination not in calendars.events
    assert factory.state.mappings == {}
    assert factory.state.occurrences == {}
    assert ("delete", destination.event_id.value) in calendars.writes
    assert not any(kind == "delete" and "_" in ref for kind, ref in calendars.writes)


def _report_destination(calendars: FakeCalendars) -> None:
    calendars.report(
        *(
            event
            for event in calendars.events.values()
            if event.reference.calendar == rule().destination
        )
    )


def test_series_whose_only_occurrence_is_cancelled_is_never_projected() -> None:
    # A "this and following" split can leave a series whose single occurrence is cancelled.
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS[:1])
    calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED))
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)

    use_case.execute(rule().id)
    use_case.execute(rule().id, full=True)

    assert calendars.writes == []
    assert factory.state.mappings == {}


def test_series_whose_last_occurrence_is_cancelled_stays_dormant_without_rewrites() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS[:1])
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    calendars.report(calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED)))
    use_case.execute(rule().id)
    writes = list(calendars.writes)

    # Google cancels a series once its last instance is cancelled and reports that back.
    results = []
    for _ in range(3):
        _report_destination(calendars)
        results.append(use_case.execute(rule().id))
    results.append(use_case.execute(rule().id, full=True))

    assert [kind for kind, _ in writes] == ["create", "cancel_occurrence"]
    assert calendars.writes == writes
    assert all(result.conflicts == 0 for result in results)
    assert (rule().id, master.reference) in factory.state.mappings
    assert _occurrence_states(factory) == {week_start(0): OccurrenceState.CANCELLED}


def test_restoring_one_occurrence_of_a_dormant_series_keeps_the_others_cancelled() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS[:2])
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    calendars.report(
        calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED)),
        calendars.put(occurrence(master, 1, status=EventStatus.CANCELLED)),
    )
    use_case.execute(rule().id)
    _report_destination(calendars)
    use_case.execute(rule().id)

    restored = calendars.put(occurrence(master, 1, revision="occurrence-revision-2"))
    calendars.report(restored)
    result = use_case.execute(rule().id)

    destination = factory.state.mappings[(rule().id, master.reference)].destination
    assert calendars.events[destination].status is EventStatus.CONFIRMED
    kept = calendars.get_occurrence(destination, week_start(0))
    back = calendars.get_occurrence(destination, week_start(1))
    assert kept is not None
    assert kept.status is EventStatus.CANCELLED
    assert back is not None
    assert back.status is EventStatus.CONFIRMED
    assert result.conflicts == 0


def test_acknowledged_create_of_a_series_that_lost_every_occurrence_is_removed() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS[:1])
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    orphan = factory.state.mappings.pop((rule().id, master.reference)).destination
    # The create's response was lost; then the source cancelled its only occurrence.
    calendars.report(calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED)))

    use_case.execute(rule().id, full=True)

    assert orphan not in calendars.events
    assert calendars.writes[-1] == ("delete", orphan.event_id.value)
    assert factory.state.mappings == {}
    removed = [
        (entry.action, entry.destination_event_id)
        for entry in factory.state.audit
        if entry.reason == SyncReason.SERIES_WITHOUT_OCCURRENCES_REMOVED.value
    ]
    assert removed == [("delete", orphan.event_id.value)]


@dataclass
class _LiveLookupCalendars(FakeCalendars):
    live_lookups: list[EventRef] = field(default_factory=list)

    def has_live_occurrences(self, series: EventRef, *, include_all_day: bool) -> bool:
        self.live_lookups.append(series)
        return super().has_live_occurrences(series, include_all_day=include_all_day)


def _dormant(
    calendars: FakeCalendars,
) -> tuple[CalendarEvent, InMemoryUnitOfWorkFactory]:
    """Project a one-occurrence series, then cancel that occurrence in the source."""
    master = calendars.put(series(), starts=STARTS[:1])
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    calendars.report(calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED)))
    use_case.execute(rule().id)
    _report_destination(calendars)
    use_case.execute(rule().id)
    return master, factory


def test_live_occurrences_of_a_series_are_looked_up_once_per_run() -> None:
    calendars = _LiveLookupCalendars()
    master, factory = _dormant(calendars)
    calendars.live_lookups.clear()

    # The master, its repair, and its exception each ask; the run asks Google only once.
    sync_use_case(factory, calendars).execute(rule().id, full=True)

    assert calendars.live_lookups == [master.reference]


def test_policy_change_leaves_a_dormant_series_without_writes_or_conflicts() -> None:
    calendars = FakeCalendars()
    master, factory = _dormant(calendars)
    writes = list(calendars.writes)

    _change_policy(factory, TransformationPolicy(content=ProjectionContent.DETAILS))
    result = sync_use_case(factory, calendars).execute(rule().id)

    assert calendars.writes == writes
    assert result.conflicts == 0
    assert (rule().id, master.reference) in factory.state.mappings
    assert _occurrence_states(factory) == {week_start(0): OccurrenceState.CANCELLED}
    assert factory.state.rules[rule().id].reprojection_required is False


def test_acknowledged_lookup_that_finds_an_occurrence_never_deletes_it() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS[:1])
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    destination = factory.state.mappings.pop((rule().id, master.reference)).destination
    instance = calendars.get_occurrence(destination, week_start(0))
    assert instance is not None
    calendars.put(instance)
    key = ExecuteSyncRule._operation_key(
        rule().id, master.reference, master.revision, SyncAction.CREATE
    )
    # Only a series may be removed as an acknowledged series create, never a single instance.
    calendars.operations[key] = instance.reference
    calendars.report(calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED)))
    before = list(calendars.writes)

    result = use_case.execute(rule().id, full=True)

    assert calendars.writes == before
    assert result.deleted == 0
    assert factory.state.mappings == {}


@dataclass
class _UnfilteredLookupCalendars(FakeCalendars):
    """Returns cancelled projections from Operation Key lookups, unlike Google's default."""

    def find_projection(
        self, destination: CalendarEndpoint, operation_key: str
    ) -> CalendarEvent | None:
        reference = self.operations.get(operation_key)
        return None if reference is None else self.events.get(reference)


def test_acknowledged_lookup_that_finds_a_cancelled_series_never_deletes_it() -> None:
    calendars = _UnfilteredLookupCalendars()
    master = calendars.put(series(), starts=STARTS[:1])
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    destination = factory.state.mappings.pop((rule().id, master.reference)).destination
    calendars.events[destination] = replace(
        calendars.events[destination], status=EventStatus.CANCELLED
    )
    calendars.report(calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED)))
    before = list(calendars.writes)

    result = use_case.execute(rule().id, full=True)

    assert calendars.writes == before
    assert result.deleted == 0
    assert factory.state.mappings == {}


def test_acknowledged_lookup_that_finds_another_rules_series_is_blocked_not_deleted() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS[:1])
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    destination = factory.state.mappings.pop((rule().id, master.reference)).destination
    # The projection found under the create Operation Key names a different rule.
    calendars.events[destination] = replace(
        calendars.events[destination],
        managed_origin=ManagedOrigin(SyncRuleId("other-rule"), master.reference),
    )
    calendars.report(calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED)))
    before = list(calendars.writes)

    result = use_case.execute(rule().id, full=True)

    assert calendars.writes == before
    assert destination in calendars.events
    assert result.deleted == 0
    assert any(
        entry.reason == SyncReason.DESTINATION_OWNERSHIP_INCONSISTENT.value
        for entry in factory.state.audit
    )


def test_this_and_following_split_truncates_the_old_series_and_creates_the_new_one() -> None:
    calendars, factory, destination = _synced()
    calendars.report(calendars.put(occurrence(series(), 3, moved_by=timedelta(hours=1))))
    sync_use_case(factory, calendars).execute(rule().id)
    truncated = calendars.put(
        replace(
            series(),
            revision="series-revision-2",
            recurrence=Recurrence(("RRULE:FREQ=WEEKLY;UNTIL=20260915T080000Z",)),
        ),
        starts=STARTS[:2],
    )
    del calendars.events[occurrence(series(), 3).reference]
    following = calendars.put(series("source-series-2"), starts=STARTS[2:])
    calendars.report(truncated, following)

    sync_use_case(factory, calendars).execute(rule().id)

    assert calendars.events[destination].recurrence == truncated.recurrence
    assert (rule().id, following.reference) in factory.state.mappings
    assert factory.state.occurrences == {}
    assert not any(
        kind in {"write_occurrence", "cancel_occurrence"} for kind, _ in calendars.writes[-2:]
    )


def test_destination_edit_of_an_unmodified_occurrence_is_repaired() -> None:
    calendars, factory, destination = _synced()
    edited = calendars.get_occurrence(destination, week_start(2))
    assert edited is not None
    edited = calendars.put(replace(edited, title="Edited in destination"))
    calendars.report(edited)

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert calendars.get_occurrence(destination, week_start(2)).title == "Busy"  # type: ignore[union-attr]
    assert result.conflicts == 0
    assert factory.state.audit[-1].reason == SyncReason.OCCURRENCE_DRIFT_REPAIRED.value


def test_destination_cancellation_of_a_confirmed_occurrence_is_restored() -> None:
    calendars, factory, destination = _synced()
    calendars.cancel_occurrence(destination, week_start(2), series().reference, rule().id, "user")
    calendars.report(calendars.get_occurrence(destination, week_start(2)))  # type: ignore[arg-type]

    sync_use_case(factory, calendars).execute(rule().id)

    assert calendars.get_occurrence(destination, week_start(2)).status is EventStatus.CONFIRMED  # type: ignore[union-attr]


def test_recreated_destination_series_keeps_source_cancellations() -> None:
    calendars, factory, destination = _synced()
    calendars.report(calendars.put(occurrence(series(), 1, status=EventStatus.CANCELLED)))
    sync_use_case(factory, calendars).execute(rule().id)
    deleted = replace(calendars.events.pop(destination), status=EventStatus.CANCELLED, time=None)
    for instance in calendars.instances_of(destination):
        del calendars.events[instance.reference]
    calendars.report(deleted)

    sync_use_case(factory, calendars).execute(rule().id)

    recreated = factory.state.mappings[(rule().id, series().reference)].destination
    assert recreated != destination
    assert calendars.get_occurrence(recreated, week_start(1)).status is EventStatus.CANCELLED  # type: ignore[union-attr]
    assert _occurrence_states(factory) == {week_start(1): OccurrenceState.CANCELLED}


def test_reverse_rule_ignores_managed_series_and_their_metadata_less_cancellations() -> None:
    calendars, _factory, destination = _synced()
    calendars.cancel_occurrence(destination, week_start(1), series().reference, rule().id, "k")
    reverse = SyncRule(SyncRuleId("reverse"), rule().destination, rule().source, state=rule().state)
    reverse_factory = enabled_rule_factory(reverse)
    before = list(calendars.writes)

    result = sync_use_case(reverse_factory, calendars).execute(reverse.id)

    assert calendars.writes == before
    assert result.created == 0
    assert result.updated == 0
    assert result.deleted == 0
    assert reverse_factory.state.mappings == {}


def test_destination_series_owned_by_another_rule_blocks_occurrence_writes() -> None:
    calendars, factory, destination = _synced()
    master = calendars.events[destination]
    calendars.events[destination] = replace(
        master, managed_origin=ManagedOrigin(SyncRuleId("other"), series().reference)
    )
    calendars.report(calendars.put(occurrence(series(), 1, moved_by=timedelta(hours=1))))
    before = list(calendars.writes)

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert result.conflicts >= 1
    assert [write for write in calendars.writes if write not in before] == []


def test_unverifiable_source_series_blocks_without_deleting() -> None:
    calendars, factory, destination = _synced()
    calendars.unreadable.add(series().reference)
    edited = calendars.get_occurrence(destination, week_start(2))
    assert edited is not None
    calendars.report(calendars.put(replace(edited, title="Edited")))
    before = list(calendars.writes)

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert result.conflicts == 1
    assert calendars.writes == before
    assert factory.state.audit[-1].reason == SyncReason.SOURCE_UNVERIFIABLE.value


def test_missing_destination_occurrence_after_repair_is_a_conflict() -> None:
    calendars, factory, destination = _synced()
    # The destination series has drifted: it no longer expands to the source's occurrences.
    calendars.expansions[destination] = ()
    calendars.report(calendars.put(occurrence(series(), 2, moved_by=timedelta(hours=1))))
    before = list(calendars.writes)

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert result.conflicts == 1
    assert factory.state.audit[-1].reason == SyncReason.DESTINATION_OCCURRENCE_MISSING.value
    assert [kind for kind, _ in calendars.writes[len(before) :]] == []


def test_missing_occurrence_block_is_one_entry_recording_the_series_check() -> None:
    calendars, factory, destination = _synced()
    calendars.expansions[destination] = ()
    calendars.report(calendars.put(occurrence(series(), 2, moved_by=timedelta(hours=1))))
    recorded = len(factory.state.audit)

    sync_use_case(factory, calendars).execute(rule().id)

    # The series check made only to repair this occurrence is evidence for the block, not an
    # "already up to date" entry of its own beside it.
    entries = factory.state.audit[recorded:]
    assert [entry.reason for entry in entries] == [SyncReason.DESTINATION_OCCURRENCE_MISSING.value]
    assert entries[0].detail == (
        "Series check before blocking: projection_current. "
        f"No destination occurrence originally starts at {week_start(2).isoformat()}."
    )


def test_series_repair_that_rewrites_the_series_is_still_recorded() -> None:
    calendars, factory, destination = _synced()
    calendars.events[destination] = replace(calendars.events[destination], title="Edited")
    calendars.expansions[destination] = ()
    calendars.report(calendars.put(occurrence(series(), 2, moved_by=timedelta(hours=1))))
    recorded = len(factory.state.audit)

    sync_use_case(factory, calendars).execute(rule().id)

    reasons = [entry.reason for entry in factory.state.audit[recorded:]]
    assert SyncReason.DESTINATION_DRIFT_REPAIRED.value in reasons


def test_rule_change_during_a_run_stops_occurrence_writes(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    with factory() as uow:
        uow.rules.add(rule())
        uow.commit()
    calendars = FakeCalendars()
    calendars.put(series(), starts=STARTS)
    sync_use_case(factory, calendars).execute(rule().id)
    calendars.report(calendars.put(occurrence(series(), 1, moved_by=timedelta(hours=1))))

    class EditingCalendars(FakeCalendars):
        def changes(
            self, source: CalendarEndpoint, cursor: str | None, not_ended_before: datetime
        ) -> ProviderChangeSet:
            with factory() as concurrent:
                current = concurrent.rules.get(rule().id)
                assert current is not None
                if current.state is SyncRuleState.ENABLED:
                    concurrent.rules.save(current.pause())
                    concurrent.commit()
            return super().changes(source, cursor, not_ended_before)

    editing = EditingCalendars(calendars.events, calendars.expansions, calendars.feeds)
    with factory() as uow:
        cursor_before = uow.cursors.get(rule().id)

    with pytest.raises(RuleNotExecutable):
        sync_use_case(factory, editing).execute(rule().id)

    assert editing.writes == []
    with factory() as uow:
        assert uow.cursors.get(rule().id) == cursor_before


def test_every_occurrence_audit_entry_names_its_event_but_keeps_no_other_content() -> None:
    calendars, factory, _destination = _synced()
    moved = occurrence(series(), 1, title="Secret offsite", moved_by=timedelta(hours=1))
    calendars.report(calendars.put(moved))

    sync_use_case(factory, calendars).execute(rule().id)

    assert all(entry.run_id and entry.reason for entry in factory.state.audit)
    written = factory.state.audit[-1]
    assert written.source_event_id == moved.reference.event_id.value
    assert written.event == RecordedEvent(title="Secret offsite", time=moved.time, recurring=True)
    assert all("Sensitive" not in repr(entry) for entry in factory.state.audit)


def _change_policy(factory: InMemoryUnitOfWorkFactory, policy: TransformationPolicy) -> None:
    with factory() as uow:
        current = uow.rules.get(rule().id)
        assert current is not None
        uow.rules.save(current.change_policy(policy).mark_previewed().enable())
        uow.commit()


def test_occurrence_removed_from_its_series_records_no_title_of_its_own() -> None:
    calendars, factory, destination = _synced()
    moved = occurrence(series(), 3, title="Secret offsite", moved_by=timedelta(hours=1))
    calendars.report(calendars.put(moved))
    sync_use_case(factory, calendars).execute(rule().id)
    edited = calendars.get_occurrence(destination, week_start(3))
    assert edited is not None
    calendars.report(calendars.put(replace(edited, title="Edited")))

    class RemovedFromSeries(FakeCalendars):
        def get_occurrence(
            self, series: EventRef, original_start: OccurrenceStart
        ) -> CalendarEvent | None:
            if series.calendar == rule().source and original_start == week_start(3):
                return None
            return super().get_occurrence(series, original_start)

    removed_source = RemovedFromSeries(calendars.events, calendars.expansions, calendars.feeds)
    sync_use_case(factory, removed_source).execute(rule().id)

    removed = [
        entry
        for entry in factory.state.audit
        if entry.reason == SyncReason.OCCURRENCE_REMOVED_FROM_SERIES
    ]
    # The series title is not the occurrence's; Activity names it from its earlier entry.
    assert [(entry.source_event_id, entry.event) for entry in removed] == [
        (moved.reference.event_id.value, RecordedEvent(title="", recurring=True, cancelled=True))
    ]


def test_details_to_busy_change_rewrites_the_master_and_exceptions_outside_the_window() -> None:
    details = TransformationPolicy(content=ProjectionContent.DETAILS)
    calendars = FakeCalendars()
    master = calendars.put(replace(series(), title="Weekly private sync"), starts=STARTS)
    factory = enabled_rule_factory(replace(rule(), transformation=details))
    sync_use_case(factory, calendars).execute(rule().id)
    early = week_start(-10)
    calendars.expansions[master.reference] = (early, *STARTS)
    destination = factory.state.mappings[(rule().id, master.reference)].destination
    calendars.expansions[destination] = (early, *STARTS)
    old_exception = calendars.put(
        replace(occurrence(master, -10, title="Old secret"), revision="old-r1")
    )
    calendars.report(old_exception)
    sync_use_case(factory, calendars).execute(rule().id)
    assert calendars.get_occurrence(destination, early).title == "Old secret"  # type: ignore[union-attr]

    _change_policy(factory, TransformationPolicy(content=ProjectionContent.BUSY_ONLY))
    sync_use_case(factory, calendars).execute(rule().id)

    assert calendars.events[destination].title == "Busy"
    rewritten = calendars.get_occurrence(destination, early)
    assert rewritten is not None
    assert (rewritten.title, rewritten.description, rewritten.location) == ("Busy", "", "")
    assert factory.state.rules[rule().id].reprojection_required is False
    occurrence_writes = [ref for kind, ref in calendars.writes if kind == "write_occurrence"]
    assert occurrence_writes.count(rewritten.reference.event_id.value) == 2


def test_all_day_exclusion_deletes_all_day_series_and_cancels_all_day_exceptions() -> None:
    calendars = FakeCalendars()
    all_day_master = calendars.put(
        series("all-day-series", all_day=True), starts=(STARTS[0].date(),)
    )
    timed_master = calendars.put(series(), starts=STARTS)
    calendars.put(occurrence(timed_master, 1, all_day=True))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    timed_destination = factory.state.mappings[(rule().id, timed_master.reference)].destination
    all_day_destination = factory.state.mappings[(rule().id, all_day_master.reference)].destination

    _change_policy(factory, TransformationPolicy(all_day=AllDaySyncPolicy.EXCLUDE))
    sync_use_case(factory, calendars).execute(rule().id)

    assert all_day_destination not in calendars.events
    excluded = calendars.get_occurrence(timed_destination, week_start(1))
    assert excluded is not None
    assert excluded.status is EventStatus.CANCELLED
    assert factory.state.rules[rule().id].reprojection_required is False


def test_unchanged_series_still_reverifies_exceptions_outside_the_window_on_policy_change() -> None:
    calendars = FakeCalendars()
    early = week_start(-10)
    master = calendars.put(series(), starts=(early, *STARTS))
    calendars.put(occurrence(master, -10, all_day=True))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    destination = factory.state.mappings[(rule().id, master.reference)].destination
    calendars.report(calendars.events[occurrence(master, -10).reference])
    sync_use_case(factory, calendars).execute(rule().id)
    assert calendars.get_occurrence(destination, early).is_all_day  # type: ignore[union-attr]

    _change_policy(factory, TransformationPolicy(all_day=AllDaySyncPolicy.EXCLUDE))
    sync_use_case(factory, calendars).execute(rule().id)

    cancelled = calendars.get_occurrence(destination, early)
    assert cancelled is not None
    assert cancelled.status is EventStatus.CANCELLED
    assert calendars.events[destination].status is EventStatus.CONFIRMED


def test_series_recreated_during_an_occurrence_repair_keeps_source_cancellations() -> None:
    calendars, factory, destination = _synced()
    calendars.report(calendars.put(occurrence(series(), 1, status=EventStatus.CANCELLED)))
    sync_use_case(factory, calendars).execute(rule().id)
    deleted = replace(calendars.events.pop(destination), status=EventStatus.CANCELLED, time=None)
    for instance in calendars.instances_of(destination):
        del calendars.events[instance.reference]
    calendars.report(deleted)
    calendars.report(calendars.put(occurrence(series(), 2, moved_by=timedelta(hours=1))))

    sync_use_case(factory, calendars).execute(rule().id)

    recreated = factory.state.mappings[(rule().id, series().reference)].destination
    assert recreated != destination
    cancelled = calendars.get_occurrence(recreated, week_start(1))
    assert cancelled is not None
    assert cancelled.status is EventStatus.CANCELLED
    moved = calendars.get_occurrence(recreated, week_start(2))
    assert moved is not None
    assert moved.time == occurrence(series(), 2, moved_by=timedelta(hours=1)).time


def test_occurrence_reverification_never_holds_the_database_write_lock(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    with factory() as uow:
        uow.rules.add(rule())
        uow.commit()
    locked: list[str] = []

    class ProbingCalendars(FakeCalendars):
        def get_occurrence(
            self, series: EventRef, original_start: OccurrenceStart
        ) -> CalendarEvent | None:
            probe = sqlite3.connect(database, timeout=0)
            try:
                probe.execute("BEGIN IMMEDIATE")
                probe.rollback()
            except sqlite3.OperationalError as error:
                locked.append(str(error))
            finally:
                probe.close()
            return super().get_occurrence(series, original_start)

    calendars = ProbingCalendars()
    calendars.put(series(), starts=STARTS)
    calendars.put(occurrence(series(), 1, moved_by=timedelta(hours=1)))
    calendars.put(occurrence(series(), 2, status=EventStatus.CANCELLED))
    sync_use_case(factory, calendars).execute(rule().id)
    calendars.report(
        calendars.put(replace(series(), revision="series-revision-2", title="Renamed"))
    )

    sync_use_case(factory, calendars).execute(rule().id)

    assert locked == []


def test_exception_of_an_unreadable_unmapped_series_is_skipped_not_blocked() -> None:
    calendars = FakeCalendars()
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    orphan = occurrence(series("elsewhere"), 1, status=EventStatus.CANCELLED)
    calendars.report(orphan)

    result = sync_use_case(factory, calendars).execute(rule().id)

    assert result.conflicts == 0
    assert factory.state.audit[-1].reason == SyncReason.SERIES_NOT_SYNCHRONIZED.value
    assert calendars.writes == []


def test_unverifiable_source_occurrence_lookup_never_cancels_the_destination() -> None:
    calendars, factory, destination = _synced()
    calendars.report(calendars.put(occurrence(series(), 1, moved_by=timedelta(hours=1))))
    sync_use_case(factory, calendars).execute(rule().id)
    edited = calendars.get_occurrence(destination, week_start(1))
    assert edited is not None
    calendars.report(calendars.put(replace(edited, title="Edited")))
    cursor_before = factory.state.cursors[rule().id]

    class UnreadableInstances(FakeCalendars):
        def get_occurrence(
            self, series: EventRef, original_start: OccurrenceStart
        ) -> CalendarEvent | None:
            if series.calendar == rule().source:
                raise ProviderFailure(ProviderFailureKind.TEMPORARY, "series lookup failed")
            return super().get_occurrence(series, original_start)

    failing = UnreadableInstances(calendars.events, calendars.expansions, calendars.feeds)

    with pytest.raises(ProviderFailure):
        sync_use_case(factory, failing).execute(rule().id)

    assert failing.writes == []
    assert factory.state.cursors[rule().id] == cursor_before


def test_fake_occurrence_lookup_of_a_missing_series_is_a_failure() -> None:
    calendars = FakeCalendars()

    with pytest.raises(ProviderFailure):
        calendars.get_occurrence(series().reference, week_start(1))


def test_series_whose_only_live_occurrence_is_all_day_is_dormant_under_an_excluding_rule() -> None:
    # A timed series whose one remaining occurrence moved to all-day would be cancelled whole.
    excluding = replace(
        rule(), transformation=TransformationPolicy(all_day=AllDaySyncPolicy.EXCLUDE)
    )
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS[:2])
    calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED))
    calendars.put(occurrence(master, 1, all_day=True))
    factory = enabled_rule_factory(excluding)
    use_case = sync_use_case(factory, calendars)

    use_case.execute(rule().id)
    use_case.execute(rule().id, full=True)

    assert calendars.writes == []


def test_daily_pass_of_a_projected_live_series_asks_for_no_live_lookup() -> None:
    calendars = _LiveLookupCalendars()
    calendars.put(series(), starts=STARTS)
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    calendars.live_lookups.clear()

    use_case.execute(rule().id, full=True)

    assert calendars.live_lookups == []


def _states(calendars: FakeCalendars, destination: EventRef) -> list[EventStatus | None]:
    return [
        found.status if (found := calendars.get_occurrence(destination, start)) else None
        for start in STARTS[:3]
    ]


def test_restoring_one_occurrence_of_a_never_projected_series_keeps_the_others_cancelled() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS[:3])
    for week in range(3):
        calendars.put(occurrence(master, week, status=EventStatus.CANCELLED))
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    assert factory.state.mappings == {}

    calendars.report(calendars.put(occurrence(master, 1, revision="occurrence-revision-2")))
    result = use_case.execute(rule().id)

    destination = factory.state.mappings[(rule().id, master.reference)].destination
    cancelled, confirmed = EventStatus.CANCELLED, EventStatus.CONFIRMED
    assert _states(calendars, destination) == [cancelled, confirmed, cancelled]
    assert result.conflicts == 0


@dataclass
class _LostCancellationCalendars(FakeCalendars):
    """Google applies the next occurrence cancellation, but its response never arrives."""

    lose_next_cancellation: bool = False

    def cancel_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None:
        super().cancel_occurrence(
            destination_series, original_start, source_series, rule_id, operation_key
        )
        if self.lose_next_cancellation:
            self.lose_next_cancellation = False
            raise ProviderFailure(ProviderFailureKind.TEMPORARY, "response lost")


def test_a_cancellation_whose_response_was_lost_survives_a_later_restore() -> None:
    calendars = _LostCancellationCalendars()
    master = calendars.put(series(), starts=STARTS[:2])
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    calendars.report(calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED)))
    use_case.execute(rule().id)
    # Cancelling the last occurrence cancels the destination series, but the run never hears.
    last = calendars.put(occurrence(master, 1, status=EventStatus.CANCELLED))
    calendars.lose_next_cancellation = True
    calendars.report(last)
    with pytest.raises(ProviderFailure):
        use_case.execute(rule().id)
    calendars.report(last)
    use_case.execute(rule().id)

    calendars.report(calendars.put(occurrence(master, 0, revision="occurrence-revision-2")))
    result = use_case.execute(rule().id)

    destination = factory.state.mappings[(rule().id, master.reference)].destination
    assert _states(calendars, destination)[:2] == [EventStatus.CONFIRMED, EventStatus.CANCELLED]
    assert result.conflicts == 0


def test_cancellations_made_after_the_destination_series_was_deleted_survive_a_restore() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS[:2])
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    deleted = factory.state.mappings[(rule().id, master.reference)].destination
    calendars.events[deleted] = replace(calendars.events[deleted], status=EventStatus.CANCELLED)
    calendars.report(
        calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED)),
        calendars.put(occurrence(master, 1, status=EventStatus.CANCELLED)),
    )
    use_case.execute(rule().id)

    calendars.report(calendars.put(occurrence(master, 1, revision="occurrence-revision-2")))
    result = use_case.execute(rule().id)

    destination = factory.state.mappings[(rule().id, master.reference)].destination
    assert destination != deleted
    assert _states(calendars, destination)[:2] == [EventStatus.CANCELLED, EventStatus.CONFIRMED]
    assert result.conflicts == 0


def test_series_created_from_a_full_listing_do_not_list_their_exceptions_again() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS)
    calendars.put(occurrence(master, 1, status=EventStatus.CANCELLED))

    sync_use_case(enabled_rule_factory(), calendars).execute(rule().id)

    assert calendars.exception_listings == []


@dataclass
class _FailingExceptionListing(FakeCalendars):
    """The next listing of a series' exceptions fails, as a temporary Google outage would."""

    fail_next_listing: bool = False

    def occurrence_exceptions(
        self, series: EventRef, not_ended_before: datetime
    ) -> tuple[CalendarEvent, ...]:
        if self.fail_next_listing:
            self.fail_next_listing = False
            raise ProviderFailure(ProviderFailureKind.TEMPORARY, "Google unavailable")
        return super().occurrence_exceptions(series, not_ended_before)


def test_a_replay_interrupted_by_a_failed_run_is_finished_by_the_retry() -> None:
    calendars = _FailingExceptionListing()
    master = calendars.put(series(), starts=STARTS[:3])
    for week in range(3):
        calendars.put(occurrence(master, week, status=EventStatus.CANCELLED))
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    restored = calendars.put(occurrence(master, 1, revision="occurrence-revision-2"))
    calendars.fail_next_listing = True
    calendars.report(restored)
    with pytest.raises(ProviderFailure):
        use_case.execute(rule().id)

    # The cursor did not advance, so the retry sees the same change.
    calendars.report(restored)
    use_case.execute(rule().id)

    destination = factory.state.mappings[(rule().id, master.reference)].destination
    cancelled, confirmed = EventStatus.CANCELLED, EventStatus.CONFIRMED
    assert _states(calendars, destination) == [cancelled, confirmed, cancelled]
    assert factory.state.pending_replays == set()


def test_exceptions_reported_with_their_new_series_are_applied_once() -> None:
    calendars = FakeCalendars()
    factory = enabled_rule_factory()
    use_case = sync_use_case(factory, calendars)
    use_case.execute(rule().id)
    master = calendars.put(series(), starts=STARTS)
    calendars.report(
        master,
        calendars.put(occurrence(master, 1, status=EventStatus.CANCELLED)),
        calendars.put(occurrence(master, 2, status=EventStatus.CANCELLED)),
    )

    result = use_case.execute(rule().id)

    assert [kind for kind, _ in calendars.writes] == [
        "create",
        "cancel_occurrence",
        "cancel_occurrence",
    ]
    assert result.ignored == 0


def test_daily_pass_decides_a_blocked_occurrence_again() -> None:
    calendars, factory, destination = _synced()
    calendars.expansions[destination] = ()
    calendars.report(calendars.put(occurrence(series(), 2, moved_by=timedelta(hours=1))))
    sync_use_case(factory, calendars).execute(rule().id)
    recorded = len(factory.state.audit)

    result = sync_use_case(factory, calendars).execute(rule().id, full=True)

    # A block that persists is recorded again, by this run, so rule health can see it persisted.
    again = [entry for entry in factory.state.audit[recorded:] if entry.run_id == result.run_id]
    assert SyncReason.DESTINATION_OCCURRENCE_MISSING.value in [entry.reason for entry in again]
    assert result.listed_in_full


def test_reverifying_an_occurrence_already_recorded_as_current_leaves_its_mapping_alone() -> None:
    calendars, factory, _destination = _synced()
    moved = calendars.put(occurrence(series(), 1, moved_by=timedelta(hours=1)))
    calendars.report(moved)
    sync_use_case(factory, calendars).execute(rule().id)
    key = next(key for key in factory.state.occurrences if key[1] == week_start(1))
    recorded = replace(
        factory.state.occurrences[key], projection_fingerprint=ProjectionFingerprint("before")
    )
    factory.state.occurrences[key] = recorded
    renamed = calendars.put(series(revision="series-revision-2", title="Renamed"), starts=STARTS)
    calendars.report(renamed)

    sync_use_case(factory, calendars).execute(rule().id)

    # The series' new revision re-verified the occurrence, found it current, and kept the record.
    assert [entry.reason for entry in factory.state.audit][-2:] == [
        SyncReason.PROJECTION_CURRENT,
        SyncReason.OCCURRENCE_CURRENT,
    ]
    assert factory.state.occurrences[key] == recorded
