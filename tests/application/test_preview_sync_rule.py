from dataclasses import replace
from datetime import datetime, timedelta

from calendar_sync.application.ports import CalendarReader, UnitOfWorkFactory
from calendar_sync.application.preview import PreviewSyncRule
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    EventStatus,
    ManagedOrigin,
    SyncAction,
    SyncRuleId,
    SyncRuleState,
    TransformationPolicy,
)
from calendar_sync.domain.services import (
    EventProjector,
    ProjectionFingerprinter,
    SyncDecisionService,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.application.test_execute_sync_rule import FakeCalendarProvider
from tests.fake_calendar import (
    WRITE_OPERATIONS,
    FakeCalendars,
    ReaderOnlyCalendar,
    enabled_rule_factory,
    sync_use_case,
)
from tests.helpers import NOW, event, occurrence, rule, series, week_start


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
    )


def test_preview_is_side_effect_free_and_unlocks_enablement() -> None:
    draft = rule(state=SyncRuleState.DRAFT)
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[draft.id] = draft
    provider = FakeCalendarProvider(event())
    use_case = _preview(unit_of_work, provider)

    preview = use_case.execute(draft.id)

    assert preview.eligible_events == 1
    assert preview.sample[0].projected_title == "Busy"
    assert provider.destination is None
    assert unit_of_work.state.rules[draft.id].state is SyncRuleState.DRY_RUN_VALIDATED
    # Counts are kept so enabling can restate them after a reload; content never is.
    summary = unit_of_work.state.previews[draft.id]
    assert (summary.eligible_events, summary.excluded_events, summary.completed_at) == (1, 0, NOW)


def test_preview_revalidates_a_degraded_rule_after_reauthorization() -> None:
    degraded = rule(state=SyncRuleState.DEGRADED)
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[degraded.id] = degraded
    provider = FakeCalendarProvider(event())
    use_case = _preview(unit_of_work, provider)

    use_case.execute(degraded.id)

    assert unit_of_work.state.rules[degraded.id].state is SyncRuleState.DRY_RUN_VALIDATED


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
    assert [(item.kind, item.planned_action) for item in preview.sample] == [
        ("series", SyncAction.CREATE),
        ("occurrence", SyncAction.UPDATE),
        ("occurrence", SyncAction.DELETE),
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
    assert preview.sample == ()


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
