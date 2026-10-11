"""Graph events translated to Calendar Events, and Event Projections to Graph bodies, as pure
functions on synthetic dictionaries shaped as Graph documents them (ADR 0032)."""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from calendar_sync.application.errors import UnsupportedProjection
from calendar_sync.domain.model import (
    AllDayRange,
    EventId,
    EventProjection,
    EventRef,
    EventStatus,
    InvitationResponse,
    ManagedOrigin,
    OccurrenceIdentity,
    Recurrence,
    SyncRuleId,
    TimedInterval,
)
from calendar_sync.infrastructure.microsoft.translation import (
    OPERATION_PROPERTY,
    ORIGIN_PROPERTY,
    RULE_PROPERTY,
    cancelled_occurrence,
    cancelled_occurrence_reference,
    occurrence_body,
    projection_body,
    removed_event,
    series_of,
    to_domain_event,
)
from tests.helpers import endpoint

CALENDAR = endpoint("work-account", "work-calendar")
SOURCE = EventRef(endpoint("personal-account", "personal-calendar"), EventId("source-event"))
RULE = SyncRuleId("rule-1")
NINE_UTC = datetime(2026, 10, 12, 7, 0, tzinfo=UTC)


def item(**fields: Any) -> dict[str, Any]:
    """A Graph event as it reads with UTC times and text bodies."""
    return {
        "id": "event-1",
        "changeKey": "change-1",
        "type": "singleInstance",
        "subject": "Dentist",
        "body": {"contentType": "text", "content": "Bring\r\nthe card"},
        "location": {"displayName": "Clinic"},
        "isAllDay": False,
        "isCancelled": False,
        "start": {"dateTime": "2026-10-12T07:00:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-10-12T08:00:00.0000000", "timeZone": "UTC"},
        "originalStartTimeZone": "Romance Standard Time",
        "responseStatus": {"response": "organizer", "time": "0001-01-01T00:00:00Z"},
        "attendees": [],
        **fields,
    }


def weekly(**range_: Any) -> dict[str, Any]:
    return {
        "pattern": {
            "type": "weekly",
            "interval": 1,
            "daysOfWeek": ["monday"],
            "firstDayOfWeek": "sunday",
        },
        "range": {
            "type": "noEnd",
            "startDate": "2026-10-12",
            "recurrenceTimeZone": "Romance Standard Time",
            **range_,
        },
    }


def test_a_single_event_reads_with_its_content_and_utc_times() -> None:
    event = to_domain_event(item(), CALENDAR)

    assert event.reference == EventRef(CALENDAR, EventId("event-1"))
    assert event.revision == "change-1"
    assert event.time == TimedInterval(NINE_UTC, NINE_UTC + timedelta(hours=1))
    assert (event.title, event.description, event.location) == (
        "Dentist",
        "Bring\nthe card",
        "Clinic",
    )
    assert event.status is EventStatus.CONFIRMED
    assert (event.recurrence, event.occurrence, event.managed_origin) == (None, None, None)
    assert event.response is InvitationResponse.ACCEPTED


def test_an_all_day_event_reads_by_its_dates() -> None:
    event = to_domain_event(
        item(
            isAllDay=True,
            start={"dateTime": "2026-10-12T00:00:00.0000000", "timeZone": "UTC"},
            end={"dateTime": "2026-10-14T00:00:00.0000000", "timeZone": "UTC"},
        ),
        CALENDAR,
    )

    assert event.time == AllDayRange(date(2026, 10, 12), date(2026, 10, 14))


def test_a_series_master_keeps_its_zone_and_reads_as_one_rrule() -> None:
    event = to_domain_event(item(type="seriesMaster", recurrence=weekly()), CALENDAR)

    assert event.recurrence == Recurrence(("RRULE:FREQ=WEEKLY;BYDAY=MO",))
    assert isinstance(event.time, TimedInterval)
    assert event.time.time_zone == "Europe/Paris"
    assert event.time.starts_at == NINE_UTC


def test_an_occurrence_and_an_exception_name_their_series_and_original_start() -> None:
    occurrence = to_domain_event(
        item(type="occurrence", seriesMasterId="series-1", originalStart="2026-10-19T07:00:00Z"),
        CALENDAR,
    )
    exception = to_domain_event(
        item(
            type="exception",
            seriesMasterId="series-1",
            originalStart="2026-10-26T08:00:00Z",
            start={"dateTime": "2026-10-26T10:00:00.0000000", "timeZone": "UTC"},
            end={"dateTime": "2026-10-26T11:00:00.0000000", "timeZone": "UTC"},
        ),
        CALENDAR,
    )

    assert occurrence.occurrence == OccurrenceIdentity(
        EventId("series-1"), datetime(2026, 10, 19, 7, 0, tzinfo=UTC)
    )
    assert exception.occurrence == OccurrenceIdentity(
        EventId("series-1"), datetime(2026, 10, 26, 8, 0, tzinfo=UTC)
    )


def test_an_all_day_occurrence_starts_on_its_date_in_the_series_zone() -> None:
    # Midnight in Paris is 22:00 UTC the day before in summer.
    event = to_domain_event(
        item(
            type="occurrence",
            isAllDay=True,
            seriesMasterId="series-1",
            originalStart="2026-10-18T22:00:00Z",
            start={"dateTime": "2026-10-19T00:00:00.0000000", "timeZone": "UTC"},
            end={"dateTime": "2026-10-20T00:00:00.0000000", "timeZone": "UTC"},
        ),
        CALENDAR,
    )

    assert event.occurrence == OccurrenceIdentity(EventId("series-1"), date(2026, 10, 19))


def test_a_cancelled_meeting_and_a_removed_event_read_as_cancelled() -> None:
    cancelled = to_domain_event(item(isCancelled=True), CALENDAR)
    removed = removed_event(CALENDAR, "event-2")

    assert cancelled.status is EventStatus.CANCELLED
    assert removed.status is EventStatus.CANCELLED
    assert removed.reference == EventRef(CALENDAR, EventId("event-2"))
    assert removed.time is None


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("organizer", InvitationResponse.ACCEPTED),
        ("accepted", InvitationResponse.ACCEPTED),
        ("tentativelyAccepted", InvitationResponse.TENTATIVE),
        ("declined", InvitationResponse.DECLINED),
        ("notResponded", InvitationResponse.AWAITING),
        ("none", InvitationResponse.ACCEPTED),
        ("somethingNew", InvitationResponse.ACCEPTED),
    ],
)
def test_the_calendars_own_answer_is_its_invitation_response(
    response: str, expected: InvitationResponse
) -> None:
    event = to_domain_event(item(responseStatus={"response": response}), CALENDAR)

    assert event.response is expected


def test_guests_and_the_join_address_are_read_to_describe_changes_only() -> None:
    event = to_domain_event(
        item(
            attendees=[
                {"emailAddress": {"address": "Guest@Example.test", "name": "Guest"}},
                {"emailAddress": {"address": "other@example.test"}},
            ],
            onlineMeeting={"joinUrl": "https://meeting.example.test/join"},
            webLink="https://outlook.example.test/event",
        ),
        CALENDAR,
    )

    assert event.guests == ("guest@example.test", "other@example.test")
    assert event.conferencing == ("https://meeting.example.test/join",)
    assert event.web_link == "https://outlook.example.test/event"


def _properties(origin: dict[str, Any], rule: str = "rule-1") -> list[dict[str, str]]:
    return [
        {"id": RULE_PROPERTY, "value": rule},
        {"id": OPERATION_PROPERTY, "value": "key-1"},
        {"id": ORIGIN_PROPERTY, "value": json.dumps(origin)},
    ]


ORIGIN = {"account": "personal-account", "calendar": "personal-calendar", "event": "source-event"}


def test_an_event_carrying_calendar_ghosts_properties_is_a_managed_projection() -> None:
    event = to_domain_event(item(singleValueExtendedProperties=_properties(ORIGIN)), CALENDAR)

    assert event.managed_origin == ManagedOrigin(RULE, SOURCE)


@pytest.mark.parametrize(
    "properties",
    [
        [{"id": "String {00000000-0000-0000-0000-000000000000} Name Other", "value": "x"}],
        [{"id": RULE_PROPERTY, "value": "rule-1"}],
        [{"id": RULE_PROPERTY, "value": "rule-1"}, {"id": ORIGIN_PROPERTY, "value": "not json"}],
    ],
)
def test_incomplete_or_foreign_properties_prove_no_origin(properties: list[dict[str, str]]) -> None:
    event = to_domain_event(item(singleValueExtendedProperties=properties), CALENDAR)

    assert event.managed_origin is None


def test_property_ids_read_in_any_case() -> None:
    properties = [{**each, "id": each["id"].lower()} for each in _properties(ORIGIN)]

    event = to_domain_event(item(singleValueExtendedProperties=properties), CALENDAR)

    assert event.managed_origin == ManagedOrigin(RULE, SOURCE)


def test_a_projection_body_can_email_nobody_and_carries_its_origin() -> None:
    projection = EventProjection(
        TimedInterval(NINE_UTC, NINE_UTC + timedelta(hours=1)), "Busy", "text", "place"
    )

    body = projection_body(projection, RULE, SOURCE, "key-1")

    assert "attendees" not in body
    assert body["responseRequested"] is False
    assert body["allowNewTimeProposals"] is False
    assert body["isOnlineMeeting"] is False
    assert (body["showAs"], body["sensitivity"], body["isReminderOn"]) == ("busy", "normal", False)
    assert body["start"] == {"dateTime": "2026-10-12T07:00:00", "timeZone": "UTC"}
    assert body["body"] == {"contentType": "text", "content": "text"}
    assert body["location"] == {"displayName": "place"}
    written = to_domain_event({**item(), **body, "id": "p-1", "changeKey": "c"}, CALENDAR)
    assert written.managed_origin == ManagedOrigin(RULE, SOURCE)
    assert written.title == "Busy"


def test_an_all_day_projection_is_written_midnight_to_midnight() -> None:
    projection = EventProjection(AllDayRange(date(2026, 10, 12), date(2026, 10, 13)), "Busy")

    body = projection_body(projection, RULE, SOURCE, "key-1")

    assert body["isAllDay"] is True
    assert body["start"] == {"dateTime": "2026-10-12T00:00:00", "timeZone": "UTC"}
    assert body["end"] == {"dateTime": "2026-10-13T00:00:00", "timeZone": "UTC"}


def _series_projection(lines: tuple[str, ...], zone: str = "Europe/Madrid") -> EventProjection:
    return EventProjection(
        TimedInterval(NINE_UTC, NINE_UTC + timedelta(hours=1), zone),
        "Busy",
        recurrence=Recurrence(lines),
    )


def test_a_series_projection_is_written_in_its_local_time_and_windows_zone() -> None:
    body = projection_body(
        _series_projection(("RRULE:FREQ=WEEKLY;WKST=SU;BYDAY=MO",)), RULE, SOURCE, "key-1"
    )

    assert body["start"] == {
        "dateTime": "2026-10-12T09:00:00",
        "timeZone": "W. Europe Standard Time",
    }
    assert body["recurrence"]["pattern"] == {
        "type": "weekly",
        "interval": 1,
        "daysOfWeek": ["monday"],
        "firstDayOfWeek": "monday",
    }
    assert body["recurrence"]["range"]["recurrenceTimeZone"] == "W. Europe Standard Time"


def test_a_series_reads_back_with_the_lines_and_zone_it_was_written_with() -> None:
    lines = ("RRULE:FREQ=WEEKLY;WKST=SU;BYDAY=MO",)
    body = projection_body(_series_projection(lines), RULE, SOURCE, "key-1")
    # Graph answers the same pattern with every field at its default, and times in UTC.
    answered = item(
        type="seriesMaster",
        recurrence={
            "pattern": {
                **body["recurrence"]["pattern"],
                "dayOfMonth": 0,
                "month": 0,
                "index": "first",
            },
            "range": {
                **body["recurrence"]["range"],
                "endDate": "0001-01-01",
                "numberOfOccurrences": 0,
            },
        },
        originalStartTimeZone="W. Europe Standard Time",
        singleValueExtendedProperties=body["singleValueExtendedProperties"],
    )

    event = to_domain_event(answered, CALENDAR)

    # Equivalent to what was written, so it reads as written and is not mistaken for drift.
    assert event.recurrence == Recurrence(lines)
    assert isinstance(event.time, TimedInterval)
    assert event.time.time_zone == "Europe/Madrid"


def test_a_series_edited_in_outlook_reads_as_it_now_is() -> None:
    lines = ("RRULE:FREQ=WEEKLY;WKST=SU;BYDAY=MO",)
    body = projection_body(_series_projection(lines), RULE, SOURCE, "key-1")
    edited = item(
        type="seriesMaster",
        recurrence={
            **body["recurrence"],
            "pattern": {**body["recurrence"]["pattern"], "daysOfWeek": ["tuesday"]},
        },
        singleValueExtendedProperties=body["singleValueExtendedProperties"],
    )

    event = to_domain_event(edited, CALENDAR)

    assert event.recurrence == Recurrence(("RRULE:FREQ=WEEKLY;BYDAY=TU",))


@pytest.mark.parametrize(
    ("lines", "zone"),
    [
        (("RRULE:FREQ=HOURLY",), "Europe/Madrid"),
        (("RRULE:FREQ=WEEKLY", "EXDATE:20261019T070000Z"), "Europe/Madrid"),
        (("RRULE:FREQ=WEEKLY",), "Not/AZone"),
    ],
)
def test_a_projection_outlook_cannot_hold_exactly_is_refused(
    lines: tuple[str, ...], zone: str
) -> None:
    with pytest.raises(UnsupportedProjection):
        projection_body(_series_projection(lines, zone), RULE, SOURCE, "key-1")


def test_an_occurrence_body_carries_its_series_origin_and_original_start() -> None:
    start = datetime(2026, 10, 19, 7, 0, tzinfo=UTC)
    projection = EventProjection(TimedInterval(start, start + timedelta(hours=1)), "Busy")

    body = occurrence_body(projection, RULE, SOURCE, "key-2", start)

    assert "recurrence" not in body
    written = to_domain_event({**item(), **body}, CALENDAR)
    assert written.managed_origin == ManagedOrigin(RULE, SOURCE)
    origin = next(p for p in body["singleValueExtendedProperties"] if p["id"] == ORIGIN_PROPERTY)
    assert json.loads(origin["value"])["start"] == "2026-10-19T07:00:00Z"


def test_a_series_expands_in_its_zone_across_daylight_saving() -> None:
    master = item(type="seriesMaster", recurrence=weekly(type="numbered", numberOfOccurrences=3))

    series = series_of(master)

    assert series is not None
    # 09:00 in Paris is 07:00 UTC before the change on 25 October and 08:00 UTC after it.
    assert list(series.original_starts(NINE_UTC, NINE_UTC + timedelta(days=30))) == [
        NINE_UTC,
        NINE_UTC + timedelta(days=7),
        NINE_UTC + timedelta(days=14, hours=1),
    ]


def test_a_series_in_a_zone_this_release_cannot_name_cannot_be_expanded() -> None:
    master = item(
        type="seriesMaster",
        recurrence=weekly(recurrenceTimeZone="tzone://Microsoft/Custom"),
        originalStartTimeZone="tzone://Microsoft/Custom",
    )

    assert series_of(master) is None
    assert series_of(item()) is None


def test_a_cancelled_occurrence_is_named_by_its_series_and_start() -> None:
    master = to_domain_event(
        item(id="series-1", type="seriesMaster", recurrence=weekly()), CALENDAR
    )
    start = NINE_UTC + timedelta(days=7)

    cancelled = cancelled_occurrence(master, start)

    assert cancelled.status is EventStatus.CANCELLED
    assert cancelled.occurrence == OccurrenceIdentity(EventId("series-1"), start)
    assert cancelled_occurrence_reference(cancelled.reference) == (
        EventRef(CALENDAR, EventId("series-1")),
        start,
    )
    assert cancelled_occurrence_reference(master.reference) is None
