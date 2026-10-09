import pytest

from calendar_sync.application.activity import (
    ActivityCategory,
    Dashboard,
    EntryEvents,
    InspectActivityEvent,
    activity_category,
)
from calendar_sync.application.errors import (
    ActivityEventNotFound,
    ActivityRuleRemoved,
    EventInspectionUnavailable,
)
from calendar_sync.application.ports import OpenBlock, OperationsOverview
from calendar_sync.domain.model import EventId, EventRef, SyncReason, SyncRuleState
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryUnitOfWorkFactory,
)
from tests.fake_calendar import FakeCalendars
from tests.helpers import event, rule
from tests.users import USER


@pytest.mark.parametrize(
    ("action", "reason", "category"),
    [
        ("create", "source_created", "changed"),
        ("update", "source_changed", "changed"),
        ("delete", "source_cancelled", "changed"),
        ("policy_changed", None, "changed"),
        ("rule_removed", None, "changed"),
        ("remove_projection", None, "changed"),
        ("detach_projection", None, "changed"),
        ("ignore", "projection_current", "unchanged"),
        ("ignore", "occurrence_current", "unchanged"),
        ("ignore", "occurrence_already_cancelled", "unchanged"),
        ("ignore", "all_day_excluded", "skipped"),
        ("ignore", None, "skipped"),
        ("conflict", "destination_occurrence_missing", "blocked"),
        ("conflict", None, "blocked"),
        ("removal_conflict", None, "blocked"),
    ],
)
def test_activity_category_groups_each_decision(
    action: str, reason: str | None, category: ActivityCategory
) -> None:
    assert activity_category(action, reason) == category


def test_recurring_exclusions_recorded_as_conflicts_are_skips() -> None:
    # Recorded before reason codes existed; the event was never synchronized, not blocked.
    assert activity_category("conflict", SyncReason.RECURRING_UNSUPPORTED.value) == "skipped"
    assert activity_category("ignore", SyncReason.RECURRING_UNSUPPORTED.value) == "skipped"


def _overview(*blocks: OpenBlock, incidents: int = 0) -> OperationsOverview:
    return OperationsOverview(1, 0, incidents, "2026-09-01T00:00:00+00:00", blocks)


def test_dashboard_counts_rules_by_state() -> None:
    dashboard = Dashboard.of(
        [SyncRuleState.ENABLED, SyncRuleState.PAUSED, SyncRuleState.DEGRADED], _overview()
    )

    assert (dashboard.sync_rules, dashboard.enabled_rules, dashboard.stopped_rules) == (3, 1, 1)
    assert dashboard.blocked_rule_id is None


@pytest.mark.parametrize("state", [SyncRuleState.DEGRADED, SyncRuleState.REMOVING])
def test_dashboard_counts_degraded_and_removing_rules_as_stopped(state: SyncRuleState) -> None:
    assert Dashboard.of([state], _overview(incidents=1)).stopped_rules == 1


def test_dashboard_names_the_blocked_rule_only_when_every_block_is_its_own() -> None:
    one_rule = Dashboard.of([], _overview(OpenBlock(9, "a"), OpenBlock(4, "a")))
    two_rules = Dashboard.of([], _overview(OpenBlock(9, "a"), OpenBlock(4, "b")))

    assert (one_rule.blocked_events, one_rule.blocked_entry_id, one_rule.blocked_rule_id) == (
        2,
        9,
        "a",
    )
    assert (two_rules.blocked_entry_id, two_rules.blocked_rule_id) == (9, None)


class Entries:
    def __init__(self, events: EntryEvents | None) -> None:
        self.events = events

    def entry_events(self, entry_id: int) -> EntryEvents | None:
        return self.events


def _inspection(
    events: EntryEvents | None, calendars: FakeCalendars | None
) -> InspectActivityEvent:
    unit_of_work = InMemoryUnitOfWorkFactory().for_user(USER)
    unit_of_work.state.rules[rule().id] = rule()
    return InspectActivityEvent(Entries(events), unit_of_work, calendars)


def test_inspection_reads_the_entry_events_live() -> None:
    calendars = FakeCalendars()
    source = calendars.put(event())

    inspected = _inspection(
        EntryEvents(rule().id.value, "source-event", "missing-projection"), calendars
    ).execute(1)

    assert inspected.source == source
    assert inspected.destination_recorded
    assert inspected.destination is None
    assert calendars.reads == [
        source.reference,
        EventRef(rule().destination, EventId("missing-projection")),
    ]


def test_inspection_skips_a_destination_the_entry_never_named() -> None:
    calendars = FakeCalendars()
    calendars.put(event())

    inspected = _inspection(EntryEvents(rule().id.value, "source-event", None), calendars).execute(
        1
    )

    assert not inspected.destination_recorded
    assert len(calendars.reads) == 1


def test_inspection_is_blocked_without_a_source_event_rule_or_provider() -> None:
    calendars = FakeCalendars()
    with pytest.raises(ActivityEventNotFound):
        _inspection(None, calendars).execute(1)
    with pytest.raises(ActivityEventNotFound):
        _inspection(EntryEvents(rule().id.value, None, None), calendars).execute(1)
    with pytest.raises(ActivityRuleRemoved):
        _inspection(EntryEvents("removed-rule", "source-event", None), calendars).execute(1)
    with pytest.raises(EventInspectionUnavailable):
        _inspection(EntryEvents(rule().id.value, "source-event", None), None).execute(1)
    assert calendars.reads == []
