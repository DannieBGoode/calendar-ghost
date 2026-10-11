"""Google projection writes and change listings, driven through a stateful Calendar v3 fake."""

from __future__ import annotations

from datetime import timedelta

from calendar_sync.domain.model import (
    EventProjection,
    EventStatus,
    ManagedOrigin,
    SyncRuleId,
    TimedInterval,
)
from calendar_sync.infrastructure.google.provider import GoogleCalendarProvider
from calendar_sync.infrastructure.google.translation import (
    OPERATION_PROPERTY,
    RULE_PROPERTY,
    SOURCE_ACCOUNT_PROPERTY,
    SOURCE_CALENDAR_PROPERTY,
    SOURCE_EVENT_PROPERTY,
)
from tests.fake_google_calendar_api import PAGE_SIZE, FakeGoogleCalendarApi
from tests.helpers import NOW, endpoint, event

SOURCE = endpoint("personal-account", "personal-calendar")
DESTINATION = endpoint("work-account", "work-calendar")
SOURCE_EVENT = event("source-event", calendar=SOURCE).reference
RULE_ID = SyncRuleId("rule-1")
WINDOW_START = NOW - timedelta(days=1)


def _projection(title: str = "Busy", *, hours_later: int = 0) -> EventProjection:
    starts_at = NOW + timedelta(hours=hours_later)
    return EventProjection(TimedInterval(starts_at, starts_at + timedelta(hours=1)), title)


def _ownership(operation_key: str) -> dict[str, str]:
    return {
        RULE_PROPERTY: "rule-1",
        SOURCE_ACCOUNT_PROPERTY: "personal-account",
        SOURCE_CALENDAR_PROPERTY: "personal-calendar",
        SOURCE_EVENT_PROPERTY: "source-event",
        OPERATION_PROPERTY: operation_key,
    }


def _native(event_id: str, *, hours_from_now: int = 0) -> dict[str, object]:
    starts_at = NOW + timedelta(hours=hours_from_now)
    return {
        "id": event_id,
        "summary": "Private appointment",
        "start": {"dateTime": starts_at.isoformat()},
        "end": {"dateTime": (starts_at + timedelta(hours=1)).isoformat()},
    }


def test_a_fresh_projection_is_inserted_owned_and_without_notifying_anyone() -> None:
    api = FakeGoogleCalendarApi()
    provider = GoogleCalendarProvider(api.service_for)

    created = provider.create_projection(
        DESTINATION, SOURCE_EVENT, RULE_ID, _projection(), "key-create"
    ).destination_event

    [write] = api.writes
    assert write.method == "insert"
    assert write.calendar_id == "work-calendar"
    assert write.send_updates == "none"
    assert write.body is not None
    assert write.body["summary"] == "Busy"
    assert write.body["extendedProperties"]["private"] == _ownership("key-create")
    found = provider.get_event(created.reference)
    assert found is not None
    assert found.reference == created.reference
    assert found.managed_origin == ManagedOrigin(RULE_ID, SOURCE_EVENT)


def test_an_owned_projection_is_updated_in_place_and_keeps_its_ownership() -> None:
    api = FakeGoogleCalendarApi()
    provider = GoogleCalendarProvider(api.service_for)
    created = provider.create_projection(
        DESTINATION, SOURCE_EVENT, RULE_ID, _projection(), "key-create"
    ).destination_event

    updated = provider.update_projection(
        created.reference, SOURCE_EVENT, RULE_ID, _projection(hours_later=2), "key-update"
    )

    assert [write.method for write in api.writes] == ["insert", "update"]
    assert api.writes[1].event_id == created.reference.event_id.value
    assert api.writes[1].send_updates == "none"
    assert updated.reference == created.reference
    assert updated.revision != created.revision
    assert updated.time == _projection(hours_later=2).time
    assert updated.managed_origin == ManagedOrigin(RULE_ID, SOURCE_EVENT)
    stored = api.stored(DESTINATION, created.reference.event_id.value)
    assert stored["extendedProperties"]["private"] == _ownership("key-update")


def test_a_deleted_projection_reads_back_cancelled_and_is_deleted_only_once() -> None:
    api = FakeGoogleCalendarApi()
    provider = GoogleCalendarProvider(api.service_for)
    created = provider.create_projection(
        DESTINATION, SOURCE_EVENT, RULE_ID, _projection(), "key-create"
    ).destination_event

    provider.delete_projection(created.reference, SOURCE_EVENT, RULE_ID, "key-delete")
    provider.delete_projection(created.reference, SOURCE_EVENT, RULE_ID, "key-delete")

    assert [write.method for write in api.writes] == ["insert", "delete"]
    assert api.writes[1].send_updates == "none"
    found = provider.get_event(created.reference)
    assert found is not None
    assert found.status is EventStatus.CANCELLED
    assert provider.managed_events(DESTINATION, RULE_ID, WINDOW_START) == ()
    assert provider.find_projection(DESTINATION, "key-create") is None


def test_changes_since_a_cursor_report_only_what_changed_including_cancellations() -> None:
    api = FakeGoogleCalendarApi()
    provider = GoogleCalendarProvider(api.service_for)
    native_ids = [f"native-{number}" for number in range(PAGE_SIZE + 1)]
    for number, event_id in enumerate(native_ids):
        api.seed(SOURCE, _native(event_id, hours_from_now=number))
    api.seed(SOURCE, _native("already-ended", hours_from_now=-48))

    full = provider.changes(SOURCE, None, WINDOW_START)
    api.seed(SOURCE, {**_native("native-0"), "summary": "Moved appointment"})
    api.seed(SOURCE, {"id": "native-1", "status": "cancelled"})
    since = provider.changes(SOURCE, full.next_cursor, WINDOW_START)

    assert full.complete
    assert [item.reference.event_id.value for item in full.events] == native_ids
    assert not since.complete
    assert since.next_cursor != full.next_cursor
    assert [(item.reference.event_id.value, item.status) for item in since.events] == [
        ("native-0", EventStatus.CONFIRMED),
        ("native-1", EventStatus.CANCELLED),
    ]
