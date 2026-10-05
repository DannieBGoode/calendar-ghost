"""What every unit of work must honor, asked only through the persistence ports.

SQLite is what installations run; the in-memory unit of work stands in for it in application
tests. Both pass this suite, so the storage behavior it states holds for a use case tested in
memory; behavior it does not state may still differ. A subclass supplies a harness that records
Connected Accounts, which happens outside any unit of work.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

import pytest

from calendar_sync.application.errors import DuplicateDirectionalRelationship
from calendar_sync.application.ports import (
    CalendarAccess,
    ConnectedAccountState,
    DiscoveredCalendar,
    RulePreviewSummary,
    RuleRunOutcome,
    RunKind,
    UnitOfWork,
    UnitOfWorkFactory,
)
from calendar_sync.domain.changes import SourceObservation
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarId,
    ConnectedAccountId,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    OccurrenceMapping,
    OccurrenceMappingId,
    OccurrenceStart,
    OccurrenceState,
    ProjectionFingerprint,
    SyncRuleId,
    TimedInterval,
)
from tests.helpers import NOW, endpoint, rule, week_start

RULE = rule()
OTHER_RULE = replace(
    rule(), id=SyncRuleId("rule-0"), destination=endpoint("work-account", "other-calendar")
)
"""Sorts before RULE, so listing order is by identifier rather than by insertion."""
ACCOUNT = ConnectedAccountId("personal-account")


@dataclass(frozen=True, slots=True)
class PersistenceHarness:
    unit_of_work: UnitOfWorkFactory
    connect_account: Callable[[ConnectedAccountId], object]
    """Record a Connected Account, as authorizing it would outside any unit of work."""
    disconnect_account: Callable[[ConnectedAccountId], object]
    refused: tuple[type[Exception], ...]
    """What this storage raises for a record whose parent does not exist or is taken."""


def _mapping(name: str, rule_id: SyncRuleId = RULE.id, destination: str = "") -> EventMapping:
    return EventMapping(
        EventMappingId(name),
        rule_id,
        EventRef(RULE.source, EventId(f"source-{name}")),
        EventRef(RULE.destination, EventId(destination or f"destination-{name}")),
        "revision-1",
        ProjectionFingerprint("fingerprint"),
    )


def _occurrence(series: EventMapping, start: OccurrenceStart, name: str) -> OccurrenceMapping:
    return OccurrenceMapping(
        OccurrenceMappingId(name),
        series.id,
        start,
        EventRef(RULE.source, EventId(f"{series.source.event_id.value}_{name}")),
        EventRef(RULE.destination, EventId(f"{series.destination.event_id.value}_{name}")),
        OccurrenceState.CANCELLED,
        "revision-1",
    )


def _observation(ends_at: datetime = NOW, recurrence: tuple[str, ...] = ()) -> SourceObservation:
    return SourceObservation(
        revision="revision-1",
        title="Planning",
        time=TimedInterval(ends_at - timedelta(hours=1), ends_at),
        recurrence=recurrence,
    )


def _calendar(calendar_id: str, name: str) -> DiscoveredCalendar:
    return DiscoveredCalendar(calendar_id, name, CalendarAccess.OWNER, primary=False)


def _add_then_fail(unit_of_work: UnitOfWorkFactory) -> None:
    with unit_of_work() as uow:
        uow.rules.add(RULE)
        raise RuntimeError("stop")


def _commit_then_fail(unit_of_work: UnitOfWorkFactory) -> None:
    with unit_of_work() as uow:
        uow.rules.add(RULE)
        uow.commit()
        uow.rules.add(OTHER_RULE)
        raise RuntimeError("stop")


class PersistenceContract:
    @pytest.fixture
    def harness(self) -> PersistenceHarness:
        raise NotImplementedError

    # Units of work

    def test_writes_without_a_commit_are_discarded(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)

        with harness.unit_of_work() as uow:
            assert uow.rules.get(RULE.id) is None

    def test_a_unit_that_raises_discards_its_writes(self, harness: PersistenceHarness) -> None:
        with pytest.raises(RuntimeError):
            _add_then_fail(harness.unit_of_work)

        with harness.unit_of_work() as uow:
            assert uow.rules.get(RULE.id) is None

    def test_writes_after_a_commit_need_another_commit(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.commit()
            uow.rules.add(OTHER_RULE)

        with harness.unit_of_work() as uow:
            assert uow.rules.list() == (RULE,)

    def test_a_unit_that_raises_after_a_commit_keeps_what_it_committed(
        self, harness: PersistenceHarness
    ) -> None:
        with pytest.raises(RuntimeError):
            _commit_then_fail(harness.unit_of_work)

        with harness.unit_of_work() as uow:
            assert uow.rules.list() == (RULE,)

    def test_a_unit_reads_its_own_writes(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            assert uow.rules.get(RULE.id) == RULE

    # Directional Sync Rules

    def test_rules_round_trip_and_list_by_identifier(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            uow.commit()
        stopped = RULE.degrade(awaiting_reauthorization=True)
        with harness.unit_of_work() as uow:
            uow.rules.save(stopped)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.rules.list() == (OTHER_RULE, stopped)
            assert uow.rules.get(RULE.id) == stopped

    def test_a_second_rule_for_one_direction_is_refused(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            with pytest.raises(DuplicateDirectionalRelationship):
                uow.rules.add(replace(RULE, id=SyncRuleId("rule-2")))

    def test_moving_a_rule_onto_another_rules_direction_is_refused(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            with pytest.raises(DuplicateDirectionalRelationship):
                uow.rules.save(replace(OTHER_RULE, destination=RULE.destination))

    def test_saving_an_unknown_rule_fails(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow, pytest.raises(KeyError):
            uow.rules.save(RULE)

    def test_a_relationship_has_a_direction(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            assert uow.rules.relationship_exists(RULE.source, RULE.destination)
            assert not uow.rules.relationship_exists(RULE.destination, RULE.source)

    def test_removing_a_rule_takes_its_records_and_keeps_others(
        self, harness: PersistenceHarness
    ) -> None:
        series, other = _mapping("series"), _mapping("other", OTHER_RULE.id)
        source = EventRef(RULE.source, EventId("observed"))
        with harness.unit_of_work() as uow:
            for each, mapping in ((RULE, series), (OTHER_RULE, other)):
                uow.rules.add(each)
                uow.mappings.save(mapping)
                uow.replays.add(mapping.id)
                uow.cursors.save(each.id, "source-cursor")
                uow.destination_cursors.save(each.id, "destination-cursor")
                uow.run_outcomes.record(RuleRunOutcome(each.id, RunKind.SYNC, NOW, True))
                uow.previews.record(RulePreviewSummary(each.id, NOW, 1, 0))
                uow.observations.save(each.id, source, _observation(), NOW)
            uow.occurrences.save(_occurrence(series, week_start(1), "1"))
            uow.commit()

        with harness.unit_of_work() as uow:
            uow.rules.remove(RULE.id)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.rules.get(RULE.id) is None
            assert uow.mappings.for_rule(RULE.id) == ()
            assert uow.occurrences.for_series(series.id) == ()
            assert uow.replays.pending(RULE.id) == ()
            assert uow.cursors.get(RULE.id) is None
            assert uow.destination_cursors.get(RULE.id) is None
            assert uow.run_outcomes.latest(RULE.id, RunKind.SYNC) is None
            assert uow.previews.latest(RULE.id) is None
            assert uow.observations.get(RULE.id, source) is None
            assert uow.mappings.for_rule(OTHER_RULE.id) == (other,)
            assert uow.replays.pending(OTHER_RULE.id) == (other,)
            assert uow.cursors.get(OTHER_RULE.id) == "source-cursor"
            assert uow.previews.latest(OTHER_RULE.id) is not None
            assert uow.observations.get(OTHER_RULE.id, source) is not None

    def test_purging_a_rule_removes_it_with_its_mappings(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(_mapping("series"))
            uow.commit()
        with harness.unit_of_work() as uow:
            uow.rules.purge(RULE.id)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.rules.get(RULE.id) is None
            assert uow.mappings.count_for_rule(RULE.id) == 0

    # Event Mappings

    def test_mappings_are_found_by_source_destination_and_rule(
        self, harness: PersistenceHarness
    ) -> None:
        first, second, other = _mapping("b"), _mapping("a"), _mapping("c", OTHER_RULE.id)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            for mapping in (first, second, other):
                uow.mappings.save(mapping)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.mappings.for_source(RULE.id, first.source) == first
            assert uow.mappings.for_destination(RULE.id, first.destination) == first
            assert uow.mappings.for_destination(OTHER_RULE.id, first.destination) is None
            assert uow.mappings.for_rule(RULE.id) == (second, first)
            assert uow.mappings.count_for_rule(RULE.id) == 2

    def test_saving_a_mapping_again_updates_it(self, harness: PersistenceHarness) -> None:
        mapping = _mapping("series")
        updated = replace(
            mapping,
            source_revision="revision-2",
            projection_fingerprint=ProjectionFingerprint("new"),
        )
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(mapping)
            uow.mappings.save(updated)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.mappings.for_rule(RULE.id) == (updated,)

    def test_a_projection_mapped_to_another_source_is_refused(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(_mapping("first", destination="projection"))
            with pytest.raises(harness.refused):
                uow.mappings.save(_mapping("second", destination="projection"))

    def test_deleting_a_mapping_takes_its_occurrences_and_replay(
        self, harness: PersistenceHarness
    ) -> None:
        series = _mapping("series")
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(series)
            uow.occurrences.save(_occurrence(series, week_start(1), "1"))
            uow.replays.add(series.id)
            uow.commit()
        with harness.unit_of_work() as uow:
            uow.mappings.delete(series)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.occurrences.for_series(series.id) == ()
            assert uow.replays.pending(RULE.id) == ()

    # Occurrence Mappings and exception replays

    def test_occurrences_round_trip_in_start_order(self, harness: PersistenceHarness) -> None:
        timed, all_day = _mapping("timed"), _mapping("all-day")
        later = _occurrence(timed, week_start(2), "2")
        earlier = _occurrence(timed, week_start(1), "1")
        day = _occurrence(all_day, date(2026, 9, 1), "day")
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(timed)
            uow.mappings.save(all_day)
            for occurrence in (later, earlier, day):
                uow.occurrences.save(occurrence)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.occurrences.for_series(timed.id) == (earlier, later)
            assert uow.occurrences.get(all_day.id, date(2026, 9, 1)) == day
            assert uow.occurrences.get(all_day.id, date(2026, 9, 8)) is None

    def test_an_occurrence_needs_its_series_mapping(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            with pytest.raises(harness.refused):
                uow.occurrences.save(_occurrence(_mapping("missing"), week_start(1), "1"))

    def test_pending_replays_follow_their_series_mapping(self, harness: PersistenceHarness) -> None:
        kept, deleted = _mapping("kept"), _mapping("deleted")
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(kept)
            uow.mappings.save(deleted)
            uow.replays.add(kept.id)
            uow.replays.add(kept.id)
            uow.replays.add(deleted.id)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert [mapping.id for mapping in uow.replays.pending(RULE.id)] == [
                deleted.id,
                kept.id,
            ]
            uow.mappings.delete(deleted)
            uow.commit()
        with harness.unit_of_work() as uow:
            assert uow.replays.pending(RULE.id) == (kept,)
            uow.replays.remove(kept.id)
            uow.commit()
        with harness.unit_of_work() as uow:
            assert uow.replays.pending(RULE.id) == ()

    def test_a_replay_needs_its_series_mapping(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            with pytest.raises(harness.refused):
                uow.replays.add(EventMappingId("missing"))

    # Cursors, outcomes, previews

    def test_source_and_destination_cursors_are_kept_apart(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.cursors.save(RULE.id, "source-1")
            uow.destination_cursors.save(RULE.id, "destination-1")
            uow.cursors.save(RULE.id, "source-2")
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.cursors.get(RULE.id) == "source-2"
            assert uow.destination_cursors.get(RULE.id) == "destination-1"

    def test_run_outcomes_keep_the_last_successes_across_later_runs(
        self, harness: PersistenceHarness
    ) -> None:
        full = RuleRunOutcome(RULE.id, RunKind.SYNC, NOW, True, full_run=True)
        incremental = replace(full, completed_at=NOW + timedelta(days=1), full_run=False)
        failed = replace(full, completed_at=NOW + timedelta(days=2), succeeded=False)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.run_outcomes.record(full)
            uow.run_outcomes.record(incremental)
            # A failed full run leaves the daily pass due, so it must not count as completed.
            uow.run_outcomes.record(failed)
            uow.commit()

        with harness.unit_of_work() as uow:
            latest = uow.run_outcomes.latest(RULE.id, RunKind.SYNC)
            assert uow.run_outcomes.latest(RULE.id, RunKind.RECONCILIATION) is None
        assert latest is not None
        assert latest.completed_at == failed.completed_at
        assert not latest.succeeded
        assert latest.last_succeeded_at == incremental.completed_at
        assert latest.last_full_succeeded_at == full.completed_at

    def test_the_latest_preview_replaces_the_previous(self, harness: PersistenceHarness) -> None:
        later = RulePreviewSummary(RULE.id, NOW + timedelta(hours=1), 5, 2, 1, 3)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.previews.record(RulePreviewSummary(RULE.id, NOW, 1, 0))
            uow.previews.record(later)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.previews.latest(RULE.id) == later

    # Source Observations

    def test_stale_observations_are_forgotten_and_series_kept(
        self, harness: PersistenceHarness
    ) -> None:
        current = EventRef(RULE.source, EventId("current"))
        ended = EventRef(RULE.source, EventId("ended"))
        series = EventRef(RULE.source, EventId("series"))
        elsewhere = EventRef(endpoint("personal-account", "old-calendar"), EventId("elsewhere"))
        past = NOW - timedelta(days=100)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.observations.save(RULE.id, current, _observation(), NOW)
            uow.observations.save(RULE.id, ended, _observation(past), NOW)
            uow.observations.save(RULE.id, series, _observation(past, ("RRULE:FREQ=WEEKLY",)), NOW)
            uow.observations.save(RULE.id, elsewhere, _observation(), NOW)
            uow.commit()
        with harness.unit_of_work() as uow:
            uow.observations.forget_stale(RULE.id, RULE.source, NOW - timedelta(days=90))
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.observations.get(RULE.id, current) == _observation()
            assert uow.observations.get(RULE.id, ended) is None
            assert uow.observations.get(RULE.id, series) is not None
            assert uow.observations.get(RULE.id, elsewhere) is None

    # Connected Accounts and calendar names

    def test_only_a_disconnected_account_is_deleted(self, harness: PersistenceHarness) -> None:
        harness.connect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            assert uow.accounts.state(ACCOUNT) is ConnectedAccountState.CONNECTED
            assert not uow.accounts.delete_disconnected(ACCOUNT)
        harness.disconnect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            assert uow.accounts.state(ACCOUNT) is ConnectedAccountState.DISCONNECTED
            assert uow.accounts.delete_disconnected(ACCOUNT)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.accounts.state(ACCOUNT) is None
            assert not uow.accounts.delete_disconnected(ACCOUNT)

    def test_a_connected_account_lapses_once_until_its_lapse_clears(
        self, harness: PersistenceHarness
    ) -> None:
        harness.connect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            assert uow.accounts.authorized(ACCOUNT)
            assert uow.accounts.lapse(ACCOUNT, NOW)
            assert not uow.accounts.lapse(ACCOUNT, NOW)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert not uow.accounts.authorized(ACCOUNT)
            assert uow.accounts.clear_lapse(ACCOUNT)
            assert not uow.accounts.clear_lapse(ACCOUNT)
            uow.commit()
        with harness.unit_of_work() as uow:
            assert uow.accounts.authorized(ACCOUNT)

    def test_only_a_connected_account_lapses(self, harness: PersistenceHarness) -> None:
        missing = ConnectedAccountId("missing")
        harness.connect_account(ACCOUNT)
        harness.disconnect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            assert not uow.accounts.lapse(ACCOUNT, NOW)
            assert not uow.accounts.lapse(missing, NOW)
            assert not uow.accounts.authorized(ACCOUNT)
            assert not uow.accounts.authorized(missing)

    def test_calendar_names_belong_to_an_existing_account_and_go_with_it(
        self, harness: PersistenceHarness
    ) -> None:
        family = CalendarEndpoint(ACCOUNT, CalendarId("family"))
        work = CalendarEndpoint(ACCOUNT, CalendarId("work"))
        missing = ConnectedAccountId("missing")
        harness.connect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            uow.calendar_names.remember(ACCOUNT, [_calendar("family", "Family")])
            uow.calendar_names.remember(missing, [_calendar("other", "Other")])
            uow.calendar_names.remember(ACCOUNT, [_calendar("family", "Household")])
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.calendar_names.names([family, work]) == {family: "Household"}
            assert uow.calendar_names.names([CalendarEndpoint(missing, CalendarId("other"))]) == {}
            assert uow.calendar_names.names([]) == {}
        harness.disconnect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            assert uow.accounts.delete_disconnected(ACCOUNT)
            uow.commit()
        with harness.unit_of_work() as uow:
            assert uow.calendar_names.names([family]) == {}

    # Records need their rule, and identities stay unique

    def test_records_of_a_rule_that_does_not_exist_are_refused(
        self, harness: PersistenceHarness
    ) -> None:
        source = EventRef(RULE.source, EventId("observed"))
        writes: tuple[Callable[[UnitOfWork], object], ...] = (
            lambda uow: uow.mappings.save(_mapping("series")),
            lambda uow: uow.cursors.save(RULE.id, "cursor"),
            lambda uow: uow.destination_cursors.save(RULE.id, "cursor"),
            lambda uow: uow.run_outcomes.record(RuleRunOutcome(RULE.id, RunKind.SYNC, NOW, True)),
            lambda uow: uow.previews.record(RulePreviewSummary(RULE.id, NOW, 1, 0)),
            lambda uow: uow.observations.save(RULE.id, source, _observation(), NOW),
        )
        for write in writes:
            with harness.unit_of_work() as uow, pytest.raises(harness.refused):
                write(uow)

    def test_a_second_mapping_for_one_source_is_refused(self, harness: PersistenceHarness) -> None:
        first = _mapping("first")
        again = replace(_mapping("second"), source=first.source)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(first)
            with pytest.raises(harness.refused):
                uow.mappings.save(again)

    def test_saving_a_mapping_again_keeps_its_rule_and_source(
        self, harness: PersistenceHarness
    ) -> None:
        mapping = _mapping("series")
        moved = replace(
            mapping,
            source=EventRef(RULE.source, EventId("elsewhere")),
            destination=EventRef(RULE.destination, EventId("new-projection")),
            source_revision="revision-2",
        )
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(mapping)
            uow.mappings.save(moved)
            uow.commit()

        with harness.unit_of_work() as uow:
            # A mapping's rule and source never change; its projection and revision do.
            assert uow.mappings.for_rule(RULE.id) == (replace(moved, source=mapping.source),)
            assert uow.mappings.for_source(RULE.id, moved.source) is None

    def test_saving_an_occurrence_again_keeps_its_identifier(
        self, harness: PersistenceHarness
    ) -> None:
        series = _mapping("series")
        first = _occurrence(series, week_start(1), "1")
        renamed = replace(first, id=OccurrenceMappingId("other"), source_revision="revision-2")
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(series)
            uow.occurrences.save(first)
            uow.occurrences.save(renamed)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.occurrences.for_series(series.id) == (replace(renamed, id=first.id),)

    def test_one_occurrence_identifier_names_one_occurrence(
        self, harness: PersistenceHarness
    ) -> None:
        series = _mapping("series")
        first = _occurrence(series, week_start(1), "1")
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(series)
            uow.occurrences.save(first)
            with pytest.raises(harness.refused):
                uow.occurrences.save(replace(first, original_start=week_start(2)))
