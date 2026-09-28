from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
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
    Recurrence,
    SyncRuleId,
    TimedInterval,
)

RULE_PROPERTY = "gcs_rule_id"
SOURCE_ACCOUNT_PROPERTY = "gcs_source_account_id"
SOURCE_CALENDAR_PROPERTY = "gcs_source_calendar_id"
SOURCE_EVENT_PROPERTY = "gcs_source_event_id"
OPERATION_PROPERTY = "gcs_operation_key"


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
        original_value = original_start.get("dateTime") or original_start.get("date")
        if isinstance(original_value, str):
            occurrence = OccurrenceIdentity(EventId(recurring_event_id), original_value)
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
    )


def projection_payload(
    projection: EventProjection,
    rule_id: SyncRuleId,
    source: EventRef,
    operation_key: str,
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
        return TimedInterval(_parse_datetime(start_time), _parse_datetime(end_time))
    raise GoogleEventTranslationError("Google event has incompatible start and end values")


def _time_payload(projection: EventProjection) -> tuple[dict[str, str], dict[str, str]]:
    if isinstance(projection.time, AllDayRange):
        return (
            {"date": projection.time.starts_on.isoformat()},
            {"date": projection.time.ends_before.isoformat()},
        )
    return (
        {"dateTime": projection.time.starts_at.isoformat()},
        {"dateTime": projection.time.ends_at.isoformat()},
    )


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


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise GoogleEventTranslationError(f"Google event is missing {key}")
    return value


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
