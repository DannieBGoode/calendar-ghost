from dataclasses import replace
from datetime import datetime, timedelta
from typing import cast

import pytest

from calendar_sync.application.sync.errors import ProviderFailure, RuleNotExecutable
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.ports import CalendarReader, UnitOfWorkFactory
from calendar_sync.application.sync.preview import PreviewProjection, PreviewSyncRule
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    ConnectedAccountId,
    EventStatus,
    InvitationResponse,
    ManagedOrigin,
    ProjectionContent,
    SyncAction,
    SyncReason,
    SyncRuleId,
    SyncRuleState,
    TentativeEventPolicy,
    TimedInterval,
    TransformationPolicy,
    UnansweredInvitationPolicy,
)
from calendar_sync.domain.providers import ProviderFailureKind
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from tests.application.test_execute_sync_rule import FakeCalendarProvider
from tests.fake_calendar import (
    WRITE_OPERATIONS,
    FakeCalendars,
    ReaderOnlyCalendar,
    enabled_rule_factory,
    sync_use_case,
)
from tests.helpers import NOW, event, occurrence, rule, series, week_start
from tests.users import memory_units


class FixedClock:
    def now(self) -> datetime:
        return NOW


def _preview(unit_of_work: UnitOfWorkFactory, provider: CalendarReader) -> PreviewSyncRule:
    return PreviewSyncRule(
        unit_of_work,
        provider,
        EventProjector(),
        FixedClock(),
        SyncDecisionService(EventProjector(), ProjectionFingerprinter()),
        locks=RuleLocks(),
    )


def test_preview_is_side_effect_free_and_unlocks_enablement() -> None:
    draft = rule(state=SyncRuleState.DRAFT)
    unit_of_work = memory_units()
    unit_of_work.state.rules[draft.id] = draft
    provider = FakeCalendarProvider(event())
    use_case = _preview(unit_of_work, provider)

    preview = use_case.execute(draft.id)

    assert preview.eligible_events == 1
    [item] = preview.items
    assert item.projection is not None
    assert item.projection.title == "Busy"
    assert provider.destination is None
    assert unit_of_work.state.rules[draft.id].state is SyncRuleState.PREVIEWED
    # Counts are kept so enabling can restate them after a reload; content never is.
    summary = unit_of_work.state.previews[draft.id]
    assert (summary.eligible_events, summary.excluded_events, summary.completed_at) == (1, 0, NOW)


def test_preview_revalidates_a_degraded_rule_after_reauthorization() -> None:
    degraded = rule(state=SyncRuleState.DEGRADED)
    unit_of_work = memory_units()
    unit_of_work.state.rules[degraded.id] = degraded
    provider = FakeCalendarProvider(event())
    use_case = _preview(unit_of_work, provider)

    use_case.execute(degraded.id)

    assert unit_of_work.state.rules[degraded.id].state is SyncRuleState.PREVIEWED


class DeniedReader:
    """A reader whose account Google no longer accepts."""

    def __init__(self, failure: ProviderFailure) -> None:
        self.failure = failure

    def changes(self, *_args: object) -> None:
        raise self.failure


class RecoveryIncidents:
    def __init__(self) -> None:
        self.blocked: list[tuple[SyncRuleId, ProviderFailure]] = []

    def recovery_blocked(
        self, rule_id: SyncRuleId, failure: ProviderFailure, *, attempted_at: datetime
    ) -> None:
        self.blocked.append((rule_id, failure))


def _denied_preview(
    state: SyncRuleState, kind: ProviderFailureKind
) -> tuple[PreviewSyncRule, RecoveryIncidents, ProviderFailure]:
    stopped = rule(state=state)
    unit_of_work = memory_units()
    unit_of_work.state.rules[stopped.id] = stopped
    failure = ProviderFailure(kind, "synthetic", account_id=ConnectedAccountId("work-account"))
    incidents = RecoveryIncidents()
    use_case = replace(
        _preview(unit_of_work, cast(CalendarReader, DeniedReader(failure))), incidents=incidents
    )
    return use_case, incidents, failure


@pytest.mark.parametrize("state", [SyncRuleState.DEGRADED, SyncRuleState.DRAFT])
def test_a_preview_reports_the_account_still_unauthorized(state: SyncRuleState) -> None:
    # Any preview that meets lost authorization lapses that account (ADR 0027).
    use_case, incidents, failure = _denied_preview(state, ProviderFailureKind.AUTHENTICATION)

    with pytest.raises(ProviderFailure):
        use_case.execute(SyncRuleId("rule-1"))

    assert incidents.blocked == [(SyncRuleId("rule-1"), failure)]


@pytest.mark.parametrize("state", [SyncRuleState.DEGRADED, SyncRuleState.DRAFT])
def test_other_preview_failures_leave_incidents_alone(state: SyncRuleState) -> None:
    # Reauthorizing would not help, so the Incident keeps pointing where it does.
    use_case, incidents, _failure = _denied_preview(state, ProviderFailureKind.TEMPORARY)

    with pytest.raises(ProviderFailure):
        use_case.execute(SyncRuleId("rule-1"))

    assert incidents.blocked == []


def test_preview_of_a_missing_rule_is_refused() -> None:
    provider = FakeCalendarProvider(event())

    with pytest.raises(RuleNotExecutable, match="does not exist"):
        _preview(memory_units(), provider).execute(rule().id)

    assert provider.requested_endpoints == []


@pytest.mark.parametrize("state", [SyncRuleState.ENABLED, SyncRuleState.REMOVING])
def test_preview_is_refused_for_an_enabled_or_removing_rule(state: SyncRuleState) -> None:
    unit_of_work = memory_units()
    unit_of_work.state.rules[rule().id] = rule(state=state)
    provider = FakeCalendarProvider(event())

    with pytest.raises(RuleNotExecutable, match="cannot preview"):
        _preview(unit_of_work, provider).execute(rule().id)

    assert provider.requested_endpoints == []
    assert unit_of_work.state.rules[rule().id].state is state


def test_preview_counts_series_and_occurrence_changes_with_planned_actions() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=tuple(week_start(w) for w in range(3)))
    calendars.put(occurrence(master, 1, moved_by=timedelta(hours=1)))
    calendars.put(occurrence(master, 2, status=EventStatus.CANCELLED))
    managed = calendars.put(
        series("managed", managed_origin=ManagedOrigin(SyncRuleId("other"), master.reference))
    )
    calendars.put(occurrence(managed, 1))
    factory = enabled_rule_factory(rule(state=SyncRuleState.DRAFT))

    preview = _preview(factory, calendars).execute(rule().id)

    assert preview.eligible_events == 1
    assert preview.recurring_series == 1
    assert preview.occurrence_changes == 2
    assert preview.excluded_events == 2
    assert [(item.kind, item.planned_action, item.reason) for item in preview.items] == [
        ("series", SyncAction.CREATE, SyncReason.SOURCE_CREATED),
        ("occurrence", SyncAction.CREATE, SyncReason.OCCURRENCE_CHANGED),
        ("occurrence", SyncAction.IGNORE, SyncReason.OCCURRENCE_CANCELLED),
        ("series", SyncAction.IGNORE, SyncReason.MANAGED_PROJECTION_SOURCE),
        ("occurrence", SyncAction.IGNORE, SyncReason.MANAGED_PROJECTION_SOURCE),
    ]
    assert [item.projection is not None for item in preview.items] == [
        True,
        True,
        False,
        False,
        False,
    ]
    assert calendars.writes == []
    assert factory.state.mappings == {}


def test_preview_of_an_occurrence_whose_destination_series_was_deleted_does_not_fail() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=(week_start(0), week_start(1)))
    calendars.put(occurrence(master, 1, moved_by=timedelta(hours=1)))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    destination = factory.state.mappings[(rule().id, master.reference)].destination
    for instance in calendars.instances_of(destination):
        del calendars.events[instance.reference]
    del calendars.events[destination]
    with factory() as uow:
        current = uow.rules.get(rule().id)
        assert current is not None
        uow.rules.save(current.pause())
        uow.commit()

    preview = _preview(factory, calendars).execute(rule().id)

    assert preview.occurrence_changes == 1
    # The run writes the series again with the change in it, so nothing is blocked.
    assert [(item.kind, item.planned_action, item.reason) for item in preview.items] == [
        ("series", SyncAction.CREATE, SyncReason.PROJECTION_MISSING),
        ("occurrence", SyncAction.CREATE, SyncReason.OCCURRENCE_CHANGED),
    ]


def test_preview_excludes_a_series_whose_every_occurrence_is_cancelled() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=(week_start(0),))
    calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED))
    factory = enabled_rule_factory(rule(state=SyncRuleState.DRAFT))

    preview = _preview(factory, calendars).execute(rule().id)

    assert preview.eligible_events == 0
    assert preview.recurring_series == 0
    assert preview.occurrence_changes == 0
    assert preview.excluded_events == 2
    assert [(item.kind, item.reason, item.projection) for item in preview.items] == [
        ("series", SyncReason.SERIES_WITHOUT_OCCURRENCES, None),
        ("occurrence", SyncReason.SERIES_WITHOUT_OCCURRENCES, None),
    ]


def test_preview_under_an_all_day_exclusion_skips_a_series_left_with_only_all_day_occurrences() -> (
    None
):
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=(week_start(0), week_start(1)))
    calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED))
    calendars.put(occurrence(master, 1, all_day=True))
    excluding = replace(
        rule(state=SyncRuleState.DRAFT),
        transformation=TransformationPolicy(all_day=AllDaySyncPolicy.EXCLUDE),
    )

    excluded = _preview(enabled_rule_factory(excluding), calendars).execute(rule().id)
    included = _preview(enabled_rule_factory(rule(state=SyncRuleState.DRAFT)), calendars).execute(
        rule().id
    )

    assert excluded.recurring_series == 0
    assert included.recurring_series == 1


def test_preview_excludes_a_series_whose_every_occurrence_is_declined() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=(week_start(0), week_start(1)))
    calendars.put(occurrence(master, 0, status=EventStatus.CANCELLED))
    calendars.put(replace(occurrence(master, 1), response=InvitationResponse.DECLINED))
    factory = enabled_rule_factory(rule(state=SyncRuleState.DRAFT))

    preview = _preview(factory, calendars).execute(rule().id)

    assert preview.recurring_series == 0
    assert all(item.projection is None for item in preview.items)


def test_preview_excludes_declined_events_and_follows_the_rules_response_choices() -> None:
    calendars = FakeCalendars()
    responses = {
        "declined": InvitationResponse.DECLINED,
        "maybe": InvitationResponse.TENTATIVE,
        "unanswered": InvitationResponse.AWAITING,
        "accepted": InvitationResponse.ACCEPTED,
    }
    for event_id, response in responses.items():
        calendars.put(replace(event(event_id), response=response))
    strict = replace(
        rule(state=SyncRuleState.DRAFT),
        transformation=TransformationPolicy(
            tentative=TentativeEventPolicy.SKIP, unanswered=UnansweredInvitationPolicy.WAIT
        ),
    )

    marking = _preview(enabled_rule_factory(rule(state=SyncRuleState.DRAFT)), calendars).execute(
        rule().id
    )
    skipping = _preview(enabled_rule_factory(strict), calendars).execute(rule().id)

    assert (marking.eligible_events, marking.excluded_events) == (3, 1)
    assert sorted(
        (item.source.reference.event_id.value, item.projection and item.projection.title)
        for item in marking.items
    ) == [
        ("accepted", "Busy"),
        ("declined", None),
        ("maybe", "Busy (tentative)"),
        ("unanswered", "Busy (tentative)"),
    ]
    assert {
        item.source.reference.event_id.value: item.reason
        for item in skipping.items
        if item.projection is None
    } == {
        "declined": SyncReason.DECLINED,
        "maybe": SyncReason.TENTATIVE_EXCLUDED,
        "unanswered": SyncReason.AWAITING_RESPONSE,
    }
    assert (skipping.eligible_events, skipping.excluded_events) == (1, 3)


def test_preview_cannot_reach_a_provider_write() -> None:
    # CalendarReader declares no write, so a reader-only calendar is all preview can be given.
    assert not any(hasattr(CalendarReader, name) for name in WRITE_OPERATIONS)
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=tuple(week_start(w) for w in range(3)))
    calendars.put(occurrence(master, 1, moved_by=timedelta(hours=1)))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    writes = list(calendars.writes)
    with factory() as uow:
        current = uow.rules.get(rule().id)
        assert current is not None
        uow.rules.save(current.pause())
        uow.commit()
    calendars.put(occurrence(master, 2, moved_by=timedelta(hours=2)))
    reader = ReaderOnlyCalendar(calendars)

    preview = _preview(factory, reader).execute(rule().id)

    assert not any(hasattr(reader, name) for name in WRITE_OPERATIONS)
    assert preview.recurring_series == 1
    assert preview.occurrence_changes == 2
    assert calendars.writes == writes


def test_preview_counts_an_occurrence_whose_series_is_not_shown_as_a_single_event() -> None:
    # One meeting of someone else's series, the series itself not in the calendar.
    calendars = FakeCalendars()
    calendars.put(occurrence(series("their-series"), 2))
    draft = rule(state=SyncRuleState.DRAFT)
    unit_of_work = memory_units()
    unit_of_work.state.rules[draft.id] = draft

    preview = _preview(unit_of_work, ReaderOnlyCalendar(calendars)).execute(draft.id)

    assert (preview.eligible_events, preview.excluded_events) == (1, 0)
    assert (preview.recurring_series, preview.occurrence_changes) == (0, 0)
    assert preview.items[0].kind == "single"


def test_preview_lists_every_source_event_with_what_the_destination_would_hold() -> None:
    calendars = FakeCalendars()
    calendars.put(event("meeting", title="Dentist"))
    calendars.put(replace(event("birthday", title="Mum"), is_birthday=True))
    details = replace(
        rule(state=SyncRuleState.DRAFT),
        transformation=TransformationPolicy(content=ProjectionContent.DETAILS),
    )

    preview = _preview(enabled_rule_factory(details), calendars).execute(rule().id)

    by_id = {item.source.reference.event_id.value: item for item in preview.items}
    assert by_id["meeting"].source.title == "Dentist"
    assert by_id["meeting"].projection == PreviewProjection("Dentist", True, None)
    assert (by_id["birthday"].planned_action, by_id["birthday"].reason) == (
        SyncAction.IGNORE,
        SyncReason.BIRTHDAY,
    )
    assert by_id["birthday"].projection is None


def test_a_repreview_reads_the_destination_once_instead_of_each_mapped_event() -> None:
    calendars = FakeCalendars()
    for index in range(3):
        calendars.put(event(f"event-{index}"))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    _pause(factory)
    calendars.put(replace(event("event-0"), response=InvitationResponse.DECLINED))
    calendars.reads.clear()

    preview = _preview(factory, calendars).execute(rule().id)

    assert calendars.reads == []
    assert calendars.managed_listings == [rule().destination]
    by_id = {item.source.reference.event_id.value: item for item in preview.items}
    assert (by_id["event-0"].planned_action, by_id["event-0"].reason) == (
        SyncAction.DELETE,
        SyncReason.DECLINED_REMOVED,
    )
    assert by_id["event-1"].reason is SyncReason.PROJECTION_CURRENT
    assert by_id["event-1"].projection is not None


def test_a_mapped_projection_missing_from_the_listing_is_read_on_its_own() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    _pause(factory)
    destination = factory.state.mappings[(rule().id, event().reference)].destination
    del calendars.events[destination]
    calendars.reads.clear()

    [item] = _preview(factory, calendars).execute(rule().id).items

    assert calendars.reads == [destination]
    assert (item.planned_action, item.reason) == (SyncAction.CREATE, SyncReason.PROJECTION_MISSING)


def test_a_new_rule_reads_nothing_from_the_destination() -> None:
    calendars = FakeCalendars()
    calendars.put(event())

    _preview(enabled_rule_factory(rule(state=SyncRuleState.DRAFT)), calendars).execute(rule().id)

    assert calendars.managed_listings == []
    assert calendars.reads == []


def _pause(factory: UnitOfWorkFactory) -> None:
    with factory() as uow:
        current = uow.rules.get(rule().id)
        assert current is not None
        uow.rules.save(current.pause())
        uow.commit()


def test_a_declined_occurrence_of_a_new_series_is_never_written() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=tuple(week_start(w) for w in range(3)))
    calendars.put(replace(occurrence(master, 1), response=InvitationResponse.DECLINED))

    preview = _preview(enabled_rule_factory(rule(state=SyncRuleState.DRAFT)), calendars).execute(
        rule().id
    )

    declined = next(item for item in preview.items if item.kind == "occurrence")
    # Nothing is in the destination yet, so the date is left out rather than removed.
    assert (declined.planned_action, declined.reason) == (SyncAction.IGNORE, SyncReason.DECLINED)
    assert declined.projection is None


def test_a_source_event_deleted_after_a_run_shows_its_planned_removal() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    _pause(factory)
    calendars.put(replace(event(), status=EventStatus.CANCELLED, time=None, revision="gone"))

    [item] = _preview(factory, calendars).execute(rule().id).items

    assert (item.planned_action, item.reason) == (SyncAction.DELETE, SyncReason.SOURCE_CANCELLED)


def test_a_source_event_deleted_while_paused_shows_its_removal_though_the_window_omits_it() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    _pause(factory)
    # A provider's fresh listing leaves a deleted event out; only the change feed reports it.
    del calendars.events[event().reference]
    calendars.report(replace(event(), status=EventStatus.CANCELLED, time=None, revision="gone"))

    [item] = _preview(factory, calendars).execute(rule().id).items

    assert (item.planned_action, item.reason) == (SyncAction.DELETE, SyncReason.SOURCE_CANCELLED)


def test_a_source_event_moved_before_the_window_while_paused_shows_its_update() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    _pause(factory)
    starts = NOW - timedelta(days=90)
    long_ago = replace(
        event(), time=TimedInterval(starts, starts + timedelta(hours=1)), revision="moved"
    )
    calendars.events[event().reference] = long_ago
    calendars.report(long_ago)

    [item] = _preview(factory, calendars).execute(rule().id).items

    assert item.planned_action is SyncAction.UPDATE
    # Reading the feed moved nothing: the next Sync Run still reads the same change.
    assert calendars.changes(rule().source, factory.state.cursors[rule().id], NOW).events == (
        long_ago,
    )


def test_a_projection_cancelled_in_the_destination_plans_as_missing() -> None:
    calendars = FakeCalendars()
    calendars.put(event())
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    _pause(factory)
    destination = factory.state.mappings[(rule().id, event().reference)].destination
    calendars.events[destination] = replace(
        calendars.events[destination], status=EventStatus.CANCELLED, time=None
    )

    [item] = _preview(factory, calendars).execute(rule().id).items

    assert (item.planned_action, item.reason) == (SyncAction.CREATE, SyncReason.PROJECTION_MISSING)


def test_removing_an_excluded_series_counts_one_removal_not_one_per_occurrence() -> None:
    calendars = FakeCalendars()
    master = calendars.put(series(), starts=tuple(week_start(w) for w in range(3)))
    calendars.put(occurrence(master, 1, moved_by=timedelta(hours=1)))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    _pause(factory)
    calendars.put(replace(master, response=InvitationResponse.DECLINED, revision="declined"))

    preview = _preview(factory, calendars).execute(rule().id)

    assert [(item.kind, item.planned_action, item.reason) for item in preview.items] == [
        ("series", SyncAction.DELETE, SyncReason.DECLINED_REMOVED),
        ("occurrence", SyncAction.IGNORE, SyncReason.DECLINED_REMOVED),
    ]
