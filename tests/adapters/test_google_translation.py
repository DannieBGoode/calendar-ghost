import json
from datetime import UTC, date, datetime
from pathlib import Path

from calendar_sync.domain.model import (
    AllDayRange,
    EventId,
    EventProjection,
    EventRef,
    EventStatus,
    OccurrenceIdentity,
    Recurrence,
    SyncRuleId,
    TimedInterval,
)
from calendar_sync.infrastructure.google.translation import (
    OPERATION_PROPERTY,
    ORIGINAL_START_PROPERTY,
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


FIXTURES = Path(__file__).parent.parent / "fixtures"


def _fixture(name: str) -> dict[str, object]:
    payload: dict[str, object] = json.loads((FIXTURES / name).read_text())
    return payload


def test_series_master_keeps_its_time_zone_and_recurrence_lines() -> None:
    translated = to_domain_event(_fixture("google_event_series.json"), endpoint("a", "c"))

    assert isinstance(translated.time, TimedInterval)
    assert translated.time.time_zone == "Europe/Madrid"
    assert translated.recurrence is not None
    assert translated.recurrence.lines[1].startswith("EXDATE")


def test_modified_occurrence_normalizes_its_original_start_to_utc() -> None:
    translated = to_domain_event(_fixture("google_modified_occurrence.json"), endpoint("a", "c"))

    assert translated.occurrence == OccurrenceIdentity(
        EventId("synthetic-series-001"), datetime(2026, 9, 8, 8, 0, tzinfo=UTC)
    )


def test_minimal_cancelled_occurrence_translates() -> None:
    translated = to_domain_event(_fixture("google_cancelled_occurrence.json"), endpoint("a", "c"))

    assert translated.status is EventStatus.CANCELLED
    assert translated.time is None
    assert translated.occurrence == OccurrenceIdentity(
        EventId("synthetic-series-001"), datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    )


def test_all_day_occurrence_keeps_its_original_date() -> None:
    payload = {
        "id": "series_20260908",
        "status": "cancelled",
        "recurringEventId": "series",
        "originalStartTime": {"date": "2026-09-08"},
    }

    translated = to_domain_event(payload, endpoint("a", "c"))

    assert translated.occurrence == OccurrenceIdentity(EventId("series"), date(2026, 9, 8))


def test_series_payload_writes_time_zone_and_single_payload_does_not() -> None:
    zoned = TimedInterval(
        datetime(2026, 9, 1, 8, 0, tzinfo=UTC),
        datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
        "Europe/Madrid",
    )
    series_body = projection_payload(
        EventProjection(zoned, "Busy", recurrence=Recurrence(("RRULE:FREQ=WEEKLY",))),
        SyncRuleId("rule-1"),
        event().reference,
        "key",
    )
    single_body = projection_payload(
        EventProjection(zoned, "Busy"), SyncRuleId("rule-1"), event().reference, "key"
    )

    assert series_body["start"]["timeZone"] == "Europe/Madrid"
    assert series_body["end"]["timeZone"] == "Europe/Madrid"
    assert "timeZone" not in single_body["start"]


def test_occurrence_payload_records_the_original_start() -> None:
    body = projection_payload(
        EventProjection(
            TimedInterval(
                datetime(2026, 9, 8, 8, 0, tzinfo=UTC), datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
            ),
            "Busy",
        ),
        SyncRuleId("rule-1"),
        event().reference,
        "key",
        original_start=datetime(2026, 9, 8, 8, 0, tzinfo=UTC),
    )

    assert private_properties(body)[ORIGINAL_START_PROPERTY] == "2026-09-08T08:00:00Z"
    assert "attendees" not in body
