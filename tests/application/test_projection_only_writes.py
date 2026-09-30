"""A new source revision writes to the destination only when the projection changes (ADR 0017)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

import pytest

from calendar_sync.application.errors import ProviderFailure, ProviderFailureKind
from calendar_sync.domain.model import CalendarEvent, EventRef, OccurrenceStart, SyncReason
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import event, occurrence, rule, series, week_start

STARTS = tuple(week_start(week) for week in range(4))


@dataclass
class FlakyCalendars(FakeCalendars):
    """Fails the next lookup of a source occurrence, as a lost connection would."""

    fail_next_source_occurrence: bool = False

    def get_occurrence(
        self, series: EventRef, original_start: OccurrenceStart
    ) -> CalendarEvent | None:
        if self.fail_next_source_occurrence and series.calendar == rule().source:
            self.fail_next_source_occurrence = False
            raise ProviderFailure(ProviderFailureKind.TEMPORARY, "connection lost")
        return super().get_occurrence(series, original_start)


def _series_mapping_revision(factory: InMemoryUnitOfWorkFactory) -> str:
    return factory.state.mappings[(rule().id, series().reference)].source_revision


def _synced_series_with_exception() -> tuple[FlakyCalendars, InMemoryUnitOfWorkFactory]:
    calendars = FlakyCalendars()
    calendars.put(series(), starts=STARTS)
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    calendars.report(calendars.put(occurrence(series(), 1, moved_by=timedelta(hours=1))))
    sync.execute(rule().id)
    assert factory.state.occurrences
    return calendars, factory


def test_busy_only_rename_advances_the_mapping_without_a_write() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync = sync_use_case(factory, calendars)
    sync.execute(rule().id)
    writes = len(calendars.writes)
    renamed = calendars.put(replace(event(), revision="revision-2", title="Renamed privately"))
    calendars.report(renamed)

    result = sync.execute(rule().id)

    assert calendars.writes[writes:] == []
    assert result.updated == 0
    assert factory.state.mappings[(rule().id, event().reference)].source_revision == "revision-2"
    assert factory.state.audit[-1].reason == SyncReason.PROJECTION_CURRENT


def test_busy_only_series_rename_still_rechecks_its_occurrences() -> None:
    calendars, factory = _synced_series_with_exception()
    writes = len(calendars.writes)
    recorded = len(factory.state.audit)
    renamed = calendars.put(series(revision="series-revision-2", title="Renamed"), starts=STARTS)
    calendars.report(renamed)

    sync_use_case(factory, calendars).execute(rule().id)

    assert calendars.writes[writes:] == []
    assert [entry.reason for entry in factory.state.audit[recorded:]] == [
        SyncReason.PROJECTION_CURRENT,
        SyncReason.OCCURRENCE_CURRENT,
    ]
    assert _series_mapping_revision(factory) == "series-revision-2"


def test_series_keeps_its_old_revision_until_its_occurrences_were_rechecked() -> None:
    calendars, factory = _synced_series_with_exception()
    renamed = calendars.put(series(revision="series-revision-2", title="Renamed"), starts=STARTS)
    calendars.report(renamed)
    calendars.fail_next_source_occurrence = True

    with pytest.raises(ProviderFailure):
        sync_use_case(factory, calendars).execute(rule().id)

    assert _series_mapping_revision(factory) == "series-revision-1"
    # The cursor did not advance, so Google reports the series again.
    calendars.report(renamed)
    recorded = len(factory.state.audit)

    sync_use_case(factory, calendars).execute(rule().id)

    assert SyncReason.OCCURRENCE_CURRENT in [
        entry.reason for entry in factory.state.audit[recorded:]
    ]
    assert _series_mapping_revision(factory) == "series-revision-2"


def test_a_series_repaired_during_its_recheck_finishes_its_revision_once() -> None:
    calendars, factory = _synced_series_with_exception()
    destination = factory.state.mappings[(rule().id, series().reference)].destination
    # The destination series no longer has the exception, so re-checking it repairs the series.
    calendars.expansions[destination] = ()
    renamed = calendars.put(series(revision="series-revision-2", title="Renamed"), starts=STARTS)
    calendars.report(renamed)
    recorded = len(factory.state.audit)

    sync_use_case(factory, calendars).execute(rule().id)

    assert [entry.reason for entry in factory.state.audit[recorded:]] == [
        SyncReason.PROJECTION_CURRENT,
        SyncReason.DESTINATION_OCCURRENCE_MISSING,
    ]
    assert _series_mapping_revision(factory) == "series-revision-2"
