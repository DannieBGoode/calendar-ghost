from datetime import UTC, date, datetime

from calendar_sync.domain.model import (
    AllDayRange,
    EventProjection,
    EventRef,
    EventStatus,
    Recurrence,
    SyncRuleId,
    TimedInterval,
)
from calendar_sync.infrastructure.google.translation import (
    OPERATION_PROPERTY,
    RULE_PROPERTY,
    private_properties,
    projection_payload,
    to_domain_event,
)
from tests.helpers import endpoint, event


def test_google_all_day_series_translates_without_midnight_conversion() -> None:
    payload = {
        "id": "series-1",
        "etag": "revision-1",
        "summary": "Away",
        "start": {"date": "2026-08-30"},
        "end": {"date": "2026-09-01"},
        "recurrence": ["RRULE:FREQ=DAILY;COUNT=2"],
    }

    translated = to_domain_event(payload, endpoint("account", "calendar"))

    assert translated.time == AllDayRange(date(2026, 8, 30), date(2026, 9, 1))
    assert translated.recurrence == Recurrence(("RRULE:FREQ=DAILY;COUNT=2",))


def test_projection_payload_contains_private_identity_but_no_invitation_fields() -> None:
    source = event().reference
    projection = EventProjection(
        TimedInterval(
            datetime(2026, 8, 30, 10, tzinfo=UTC),
            datetime(2026, 8, 30, 11, tzinfo=UTC),
        ),
        "Busy",
    )

    payload = projection_payload(projection, SyncRuleId("rule-1"), source, "operation-1")
    private = private_properties(payload)

    assert private[RULE_PROPERTY] == "rule-1"
    assert private[OPERATION_PROPERTY] == "operation-1"
    assert "attendees" not in payload
    assert "conferenceData" not in payload
    assert "attachments" not in payload


def test_managed_origin_round_trips_through_google_private_properties() -> None:
    source: EventRef = event().reference
    source_time = event().time
    assert source_time is not None
    projection = EventProjection(source_time, "Busy")
    payload = projection_payload(projection, SyncRuleId("rule-1"), source, "operation-1")
    payload.update({"id": "destination", "etag": "revision"})

    translated = to_domain_event(payload, endpoint("work", "destination"))

    assert translated.managed_origin is not None
    assert translated.managed_origin.source == source


def test_cancelled_google_tombstone_without_time_translates() -> None:
    translated = to_domain_event(
        {"id": "deleted-event", "etag": "revision-2", "status": "cancelled"},
        endpoint("account", "calendar"),
    )

    assert translated.status is EventStatus.CANCELLED
    assert translated.time is None


def test_only_https_google_event_links_are_translated() -> None:
    payload = {
        "id": "event-1",
        "etag": "revision-1",
        "start": {"dateTime": "2026-08-30T10:00:00+00:00"},
        "end": {"dateTime": "2026-08-30T11:00:00+00:00"},
    }
    calendar = endpoint("account", "calendar")

    linked = to_domain_event(
        {**payload, "htmlLink": "https://www.google.com/calendar/event?eid=synthetic"}, calendar
    )
    unsafe = to_domain_event({**payload, "htmlLink": "javascript:alert(1)"}, calendar)

    assert linked.web_link == "https://www.google.com/calendar/event?eid=synthetic"
    assert unsafe.web_link is None
