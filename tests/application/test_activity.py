import pytest

from calendar_sync.application.operations.activity import (
    ActivityCategory,
    EntryEvents,
    InspectActivityEvent,
    activity_category,
)
from calendar_sync.application.operations.errors import (
    ActivityEventNotFound,
    ActivityRuleRemoved,
    EventInspectionUnavailable,
)
from calendar_sync.domain.model import EventId, EventRef, SyncReason
from tests.fake_calendar import FakeCalendars
from tests.helpers import event, rule
from tests.users import memory_units


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


class Entries:
    def __init__(self, events: EntryEvents | None) -> None:
        self.events = events

    def entry_events(self, entry_id: int) -> EntryEvents | None:
        return self.events


def _inspection(
    events: EntryEvents | None, calendars: FakeCalendars | None
) -> InspectActivityEvent:
    unit_of_work = memory_units()
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
