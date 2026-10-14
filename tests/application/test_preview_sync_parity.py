"""A Rule Preview plans exactly what the next Sync Run does: for every source event the run
records, the preview lists the same action and reason, and it lists nothing the run leaves out of
Activity, such as an event deleted before the rule projected it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta

import pytest

from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.preview import PreviewSyncRule, RulePreview
from calendar_sync.domain.model import (
    CalendarEvent,
    EventStatus,
    InvitationResponse,
    SyncReason,
    SyncRuleState,
    TimedInterval,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUserUnitOfWorkFactory
from tests.fake_calendar import FakeCalendars, FixedClock, enabled_rule_factory, sync_use_case
from tests.helpers import NOW, event, occurrence, rule, series, week_start

STARTS = tuple(week_start(week) for week in range(4))
Planned = set[tuple[str, str, SyncReason]]


def _preview(factory: InMemoryUserUnitOfWorkFactory, calendars: FakeCalendars) -> RulePreview:
    fingerprinter = ProjectionFingerprinter()
    return PreviewSyncRule(
        factory,
        calendars,
        EventProjector(),
        FixedClock(),
        SyncDecisionService(EventProjector(), fingerprinter),
        locks=RuleLocks(),
    ).execute(rule().id)


def _planned(preview: RulePreview) -> Planned:
    return {
        (item.source.reference.event_id.value, item.planned_action.value, item.reason)
        for item in preview.items
    }


def _recorded(factory: InMemoryUserUnitOfWorkFactory, since: int = 0) -> Planned:
    return {
        (entry.source_event_id, entry.action, SyncReason(entry.reason))
        for entry in factory.state.audit[since:]
        if entry.source_event_id is not None and entry.reason is not None
    }


def _cancelled(source: CalendarEvent, revision: str = "deleted") -> CalendarEvent:
    return replace(source, status=EventStatus.CANCELLED, revision=revision)


def _moved(master: CalendarEvent, week: int) -> CalendarEvent:
    return occurrence(master, week, moved_by=timedelta(hours=3))


def _new_series_with_changed_occurrences(calendars: FakeCalendars) -> None:
    master = calendars.put(series(), starts=STARTS)
    calendars.put(_moved(master, 1))
    calendars.put(occurrence(master, 2, status=EventStatus.CANCELLED))
    calendars.put(replace(occurrence(master, 3), response=InvitationResponse.DECLINED))


def _deleted_series(calendars: FakeCalendars) -> None:
    master = calendars.put(_cancelled(series("cg-test-a")), starts=STARTS)
    calendars.put(_cancelled(_moved(master, 2)))
    calendars.put(_moved(master, 3))


def _declined_series(calendars: FakeCalendars) -> None:
    master = calendars.put(replace(series(), response=InvitationResponse.DECLINED), starts=STARTS)
    calendars.put(_moved(master, 1))
    calendars.put(_cancelled(_moved(master, 2)))


def _series_without_occurrences(calendars: FakeCalendars) -> None:
    master = calendars.put(series(), starts=STARTS[:1])
    calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED))


def _lone_occurrence(calendars: FakeCalendars) -> None:
    calendars.put(occurrence(series("their-series"), 2, title="Planning"))


def _single_events(calendars: FakeCalendars) -> None:
    calendars.put(event("kept"))
    calendars.put(_cancelled(event("deleted")))
    calendars.put(replace(event("declined"), response=InvitationResponse.DECLINED))


@pytest.mark.parametrize(
    "scenario",
    [
        _new_series_with_changed_occurrences,
        _deleted_series,
        _declined_series,
        _series_without_occurrences,
        _lone_occurrence,
        _single_events,
    ],
)
def test_a_new_rules_preview_lists_what_its_first_run_records(
    scenario: Callable[[FakeCalendars], None],
) -> None:
    calendars = FakeCalendars()
    scenario(calendars)

    preview = _preview(enabled_rule_factory(rule(state=SyncRuleState.DRAFT)), calendars)
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)

    assert _planned(preview) == _recorded(factory)


def test_a_preview_lists_nothing_for_a_series_deleted_before_the_rule_projected_it() -> None:
    calendars = FakeCalendars()
    _deleted_series(calendars)

    preview = _preview(enabled_rule_factory(rule(state=SyncRuleState.DRAFT)), calendars)

    assert preview.items == ()
    assert (preview.eligible_events, preview.excluded_events) == (0, 0)
    assert (preview.recurring_series, preview.occurrence_changes) == (0, 0)


def _pause(factory: InMemoryUserUnitOfWorkFactory) -> None:
    with factory() as uow:
        current = uow.rules.get(rule().id)
        assert current is not None
        uow.rules.save(current.pause())
        uow.commit()


def _resume(factory: InMemoryUserUnitOfWorkFactory) -> None:
    with factory() as uow:
        current = uow.rules.get(rule().id)
        assert current is not None
        uow.rules.save(replace(current, state=SyncRuleState.ENABLED))
        uow.commit()


def _changed_since_the_last_run(
    change: Callable[[FakeCalendars, CalendarEvent, CalendarEvent], None],
) -> tuple[Planned, Planned]:
    """What a preview plans for the events a change reported, and what the next run records."""
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS)
    moved = calendars.put(_moved(master, 2))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    recorded = len(factory.state.audit)
    reported = len(calendars.feeds.get(rule().source, []))
    change(calendars, master, moved)
    changed = {
        source.reference.event_id.value for source in calendars.feeds[rule().source][reported:]
    }
    _pause(factory)

    preview = _preview(factory, calendars)
    _resume(factory)
    sync_use_case(factory, calendars).execute(rule().id)

    planned = {item for item in _planned(preview) if item[0] in changed}
    return planned, _recorded(factory, recorded)


def _delete_the_series(
    calendars: FakeCalendars, master: CalendarEvent, moved: CalendarEvent
) -> None:
    calendars.report(
        calendars.put(_cancelled(master)), calendars.put(_cancelled(moved, "moved-deleted"))
    )


def _decline_the_series(
    calendars: FakeCalendars, master: CalendarEvent, moved: CalendarEvent
) -> None:
    calendars.report(
        calendars.put(replace(master, response=InvitationResponse.DECLINED, revision="no")),
        calendars.put(replace(moved, revision="moved-again", title="Moved again")),
    )


def _cancel_the_moved_occurrence(
    calendars: FakeCalendars, master: CalendarEvent, moved: CalendarEvent
) -> None:
    calendars.report(calendars.put(_cancelled(moved, "moved-deleted")))


@pytest.mark.parametrize(
    "change", [_delete_the_series, _decline_the_series, _cancel_the_moved_occurrence]
)
def test_a_paused_rules_preview_lists_what_its_next_run_records(
    change: Callable[[FakeCalendars, CalendarEvent, CalendarEvent], None],
) -> None:
    planned, recorded = _changed_since_the_last_run(change)

    assert planned == recorded


def _preview_then_run(factory: InMemoryUserUnitOfWorkFactory, calendars: FakeCalendars) -> Planned:
    """Preview the paused rule, then run it; what the preview planned."""
    _pause(factory)
    preview = _preview(factory, calendars)
    _resume(factory)
    sync_use_case(factory, calendars).execute(rule().id)
    return _planned(preview)


def test_a_preview_shows_the_removal_of_a_lone_projection_whose_series_shows_as_deleted() -> None:
    calendars = FakeCalendars()
    invited = calendars.put(occurrence(series("their-series"), 2, title="Planning"))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    recorded = len(factory.state.audit)
    calendars.put(_cancelled(series("their-series")), starts=STARTS)
    calendars.report(calendars.put(_cancelled(invited, "invited-deleted")))

    planned = _preview_then_run(factory, calendars)

    removal = (invited.reference.event_id.value, "delete", SyncReason.SOURCE_CANCELLED)
    assert planned == _recorded(factory, recorded) == {removal}


def test_a_preview_shows_a_series_deletion_that_only_its_occurrence_reports() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=STARTS)
    moved = calendars.put(_moved(master, 2))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    recorded = len(factory.state.audit)
    # A bare tombstone, without its recurrence, that the window's listing leaves out.
    long_ago = NOW - timedelta(days=90)
    calendars.put(
        replace(
            _cancelled(master),
            recurrence=None,
            time=TimedInterval(long_ago, long_ago + timedelta(hours=1)),
        )
    )
    calendars.report(calendars.put(_cancelled(moved, "moved-deleted")))

    planned = _preview_then_run(factory, calendars)

    removal = (master.reference.event_id.value, "delete", SyncReason.SOURCE_CANCELLED)
    assert planned == _recorded(factory, recorded) == {removal}
