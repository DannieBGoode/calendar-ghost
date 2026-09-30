from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from calendar_sync.domain.model import (
    AllDayRange,
    CalendarEndpoint,
    CalendarEvent,
    EventId,
    EventProjection,
    EventRef,
    EventStatus,
    ManagedOrigin,
    OccurrenceIdentity,
    OccurrenceStart,
    Recurrence,
    SyncRuleId,
    TimedInterval,
    occurrence_start,
)

RULE_PROPERTY = "gcs_rule_id"
SOURCE_ACCOUNT_PROPERTY = "gcs_source_account_id"
SOURCE_CALENDAR_PROPERTY = "gcs_source_calendar_id"
SOURCE_EVENT_PROPERTY = "gcs_source_event_id"
OPERATION_PROPERTY = "gcs_operation_key"
ORIGINAL_START_PROPERTY = "gcs_source_original_start"


class GoogleEventTranslationError(ValueError):
    pass


def to_domain_event(payload: Mapping[str, Any], endpoint: CalendarEndpoint) -> CalendarEvent:
    event_id = _required_string(payload, "id")
    revision = str(payload.get("etag") or payload.get("updated") or event_id)
    status = (
        EventStatus.CANCELLED if payload.get("status") == "cancelled" else EventStatus.CONFIRMED
    )
    time = _parse_time(payload, allow_missing=status is EventStatus.CANCELLED)
    recurrence_lines = payload.get("recurrence")
    recurrence = (
        Recurrence(tuple(str(line) for line in recurrence_lines))
        if isinstance(recurrence_lines, list) and recurrence_lines
        else None
    )
    recurring_event_id = payload.get("recurringEventId")
    original_start = payload.get("originalStartTime")
    occurrence = None
    if isinstance(recurring_event_id, str) and isinstance(original_start, Mapping):
        parsed_start = _parse_original_start(original_start)
        if parsed_start is not None:
            occurrence = OccurrenceIdentity(EventId(recurring_event_id), parsed_start)
    html_link = payload.get("htmlLink")

    return CalendarEvent(
        reference=EventRef(endpoint, EventId(event_id)),
        time=time,
        revision=revision,
        status=status,
        title=str(payload.get("summary") or ""),
        description=str(payload.get("description") or ""),
        location=str(payload.get("location") or ""),
        recurrence=recurrence,
        occurrence=occurrence,
        managed_origin=_managed_origin(payload),
        web_link=(
            html_link if isinstance(html_link, str) and html_link.startswith("https://") else None
        ),
        guests=None if status is EventStatus.CANCELLED else _guests(payload),
        conferencing=None if status is EventStatus.CANCELLED else _conferencing(payload),
    )


def _guests(payload: Mapping[str, Any]) -> tuple[str, ...] | None:
    """Attendee addresses; responses are not tracked, and a shortened list is unknown."""
    if payload.get("attendeesOmitted") is True:
        return None
    attendees = payload.get("attendees")
    if not isinstance(attendees, list):
        return ()
    addresses = {
        attendee["email"].strip().lower()
        for attendee in attendees
        if isinstance(attendee, Mapping)
        and isinstance(attendee.get("email"), str)
        and attendee["email"].strip()
    }
    return tuple(sorted(addresses))


def _conferencing(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Every conferencing entry point, including the Google Meet link."""
    uris: set[str] = set()
    link = payload.get("hangoutLink")
    if isinstance(link, str) and link:
        uris.add(link)
    conference = payload.get("conferenceData")
    entry_points = conference.get("entryPoints") if isinstance(conference, Mapping) else None
    if isinstance(entry_points, list):
        uris.update(
            point["uri"]
            for point in entry_points
            if isinstance(point, Mapping) and isinstance(point.get("uri"), str) and point["uri"]
        )
    return tuple(sorted(uris))


def projection_payload(
    projection: EventProjection,
    rule_id: SyncRuleId,
    source: EventRef,
    operation_key: str,
    *,
    original_start: OccurrenceStart | None = None,
) -> dict[str, Any]:
    start, end = _time_payload(projection)
    body: dict[str, Any] = {
        "summary": projection.title,
        "description": projection.description,
        "location": projection.location,
        "start": start,
        "end": end,
        "extendedProperties": {
            "private": {
                RULE_PROPERTY: rule_id.value,
                SOURCE_ACCOUNT_PROPERTY: source.calendar.connected_account_id.value,
                SOURCE_CALENDAR_PROPERTY: source.calendar.calendar_id.value,
                SOURCE_EVENT_PROPERTY: source.event_id.value,
                OPERATION_PROPERTY: operation_key,
            }
        },
    }
    if original_start is not None:
        body["extendedProperties"]["private"][ORIGINAL_START_PROPERTY] = format_occurrence_start(
            original_start
        )
    if projection.recurrence is not None:
        body["recurrence"] = list(projection.recurrence.lines)
    return body


def private_properties(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return Google private metadata without exposing provider dictionaries inward."""
    extended = payload.get("extendedProperties", {})
    return extended.get("private", {}) if isinstance(extended, Mapping) else {}


def _parse_time(
    payload: Mapping[str, Any], *, allow_missing: bool = False
) -> TimedInterval | AllDayRange | None:
    start = payload.get("start")
    end = payload.get("end")
    if not isinstance(start, Mapping) or not isinstance(end, Mapping):
        if allow_missing:
            return None
        raise GoogleEventTranslationError("Google event is missing start or end")

    start_date = start.get("date")
    end_date = end.get("date")
    if isinstance(start_date, str) and isinstance(end_date, str):
        return AllDayRange(date.fromisoformat(start_date), date.fromisoformat(end_date))

    start_time = start.get("dateTime")
    end_time = end.get("dateTime")
    if isinstance(start_time, str) and isinstance(end_time, str):
        return TimedInterval(
            _parse_datetime(start_time), _parse_datetime(end_time), _time_zone(start)
        )
    raise GoogleEventTranslationError("Google event has incompatible start and end values")


def _time_payload(projection: EventProjection) -> tuple[dict[str, str], dict[str, str]]:
    if isinstance(projection.time, AllDayRange):
        return (
            {"date": projection.time.starts_on.isoformat()},
            {"date": projection.time.ends_before.isoformat()},
        )
    start = {"dateTime": projection.time.starts_at.isoformat()}
    end = {"dateTime": projection.time.ends_at.isoformat()}
    # Google expands a series in its zone; without it, daylight-saving changes shift occurrences.
    if projection.recurrence is not None and projection.time.time_zone is not None:
        start["timeZone"] = projection.time.time_zone
        end["timeZone"] = projection.time.time_zone
    return start, end


def _managed_origin(payload: Mapping[str, Any]) -> ManagedOrigin | None:
    extended = payload.get("extendedProperties")
    if not isinstance(extended, Mapping):
        return None
    private = extended.get("private")
    if not isinstance(private, Mapping):
        return None
    values = (
        private.get(RULE_PROPERTY),
        private.get(SOURCE_ACCOUNT_PROPERTY),
        private.get(SOURCE_CALENDAR_PROPERTY),
        private.get(SOURCE_EVENT_PROPERTY),
    )
    if not all(isinstance(value, str) and value for value in values):
        return None
    rule, account, calendar, event = values
    assert isinstance(rule, str)
    assert isinstance(account, str)
    assert isinstance(calendar, str)
    assert isinstance(event, str)
    from calendar_sync.domain.model import CalendarId, ConnectedAccountId

    source_endpoint = CalendarEndpoint(ConnectedAccountId(account), CalendarId(calendar))
    return ManagedOrigin(SyncRuleId(rule), EventRef(source_endpoint, EventId(event)))


def _time_zone(value: Mapping[str, Any]) -> str | None:
    zone = value.get("timeZone")
    return zone if isinstance(zone, str) and zone.strip() else None


def format_occurrence_start(value: OccurrenceStart) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return value.isoformat()


def _parse_original_start(value: Mapping[str, Any]) -> OccurrenceStart | None:
    timed = value.get("dateTime")
    if isinstance(timed, str):
        return occurrence_start(_parse_datetime(timed))
    all_day = value.get("date")
    if isinstance(all_day, str):
        return date.fromisoformat(all_day)
    return None


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise GoogleEventTranslationError(f"Google event is missing {key}")
    return value


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
