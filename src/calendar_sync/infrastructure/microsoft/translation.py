"""Graph events and Calendar Events, translated both ways by pure functions (ADR 0032).

Raw Graph dictionaries never leave the Microsoft package: the adapter reads them through these
functions and writes the bodies they build. Every read asks for UTC times and text bodies.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from calendar_sync.application.errors import UnsupportedProjection
from calendar_sync.domain.model import (
    AllDayRange,
    CalendarEndpoint,
    CalendarEvent,
    CalendarId,
    ConnectedAccountId,
    EventId,
    EventProjection,
    EventRef,
    EventStatus,
    InvitationResponse,
    ManagedOrigin,
    OccurrenceIdentity,
    OccurrenceStart,
    Recurrence,
    SyncRuleId,
    TimedInterval,
    occurrence_start,
)
from calendar_sync.infrastructure.microsoft.recurrence import (
    SeriesRule,
    UnsupportedRecurrence,
    from_graph,
    from_ical,
    occurrence_dates,
    period,
    to_graph,
    to_ical,
)
from calendar_sync.infrastructure.microsoft.zones import iana_zone, windows_zone

# Calendar Ghost's own namespace for single-value extended properties (ADR 0032).
NAMESPACE = "{8EF42533-0AD0-4C67-A411-7FD5CF9F109E}"
RULE_PROPERTY = f"String {NAMESPACE} Name CalendarGhostRule"
OPERATION_PROPERTY = f"String {NAMESPACE} Name CalendarGhostOperation"
ORIGIN_PROPERTY = f"String {NAMESPACE} Name CalendarGhostOrigin"
PROPERTIES = (RULE_PROPERTY, OPERATION_PROPERTY, ORIGIN_PROPERTY)
EXPAND = (
    "singleValueExtendedProperties($filter="
    + " or ".join(f"id eq '{name}'" for name in PROPERTIES)
    + ")"
)
"""What every read expands, so a Managed Projection is known wherever it is read."""
SELECT = (
    "id,changeKey,type,seriesMasterId,originalStart,originalStartTimeZone,isCancelled,isAllDay,"
    "start,end,subject,body,location,recurrence,responseStatus,attendees,onlineMeeting,"
    "onlineMeetingUrl,webLink,lastModifiedDateTime"
)
OCCURRENCE_TYPES = frozenset({"occurrence", "exception"})
# Marks the identifier of an occurrence Outlook cancelled, which has no event of its own.
CANCELLED_MARKER = "~cancelled~"

_RESPONSES = {
    "organizer": InvitationResponse.ACCEPTED,
    "accepted": InvitationResponse.ACCEPTED,
    "tentativelyAccepted": InvitationResponse.TENTATIVE,
    "declined": InvitationResponse.DECLINED,
    "notResponded": InvitationResponse.AWAITING,
}
"""The Source Calendar's own answer (ADR 0018). `none`, sent for an event nobody was invited
to, and anything unknown count as accepted."""

logger = logging.getLogger(__name__)

Json = dict[str, Any]


class GraphTranslationError(ValueError):
    pass


def property_filter(property_id: str, value: str) -> str:
    """A `$filter` matching events whose extended property has this value (case-insensitive)."""
    return (
        f"singleValueExtendedProperties/Any(ep: ep/id eq '{property_id}' and ep/value eq '{value}')"
    )


# Reading --------------------------------------------------------------------------------------


def to_domain_event(
    item: Mapping[str, Any], endpoint: CalendarEndpoint, *, series_zone: str | None = None
) -> CalendarEvent:
    """One Graph event; `series_zone` is the IANA zone of the series an occurrence belongs to,
    when the caller read its master."""
    event_id = _required(item, "id")
    cancelled = item.get("isCancelled") is True
    recurrence, zone = _recurrence(item)
    return CalendarEvent(
        reference=EventRef(endpoint, EventId(event_id)),
        time=_time(item, zone),
        revision=str(item.get("changeKey") or item.get("lastModifiedDateTime") or event_id),
        status=EventStatus.CANCELLED if cancelled else EventStatus.CONFIRMED,
        title=str(item.get("subject") or ""),
        description=_text(item.get("body")),
        location=_location(item.get("location")),
        recurrence=recurrence,
        occurrence=_occurrence(item, series_zone),
        managed_origin=_origin(item),
        web_link=_web_link(item.get("webLink")),
        guests=None if cancelled else _guests(item.get("attendees")),
        conferencing=None if cancelled else _conferencing(item),
        response=_RESPONSES.get(_response(item), InvitationResponse.ACCEPTED),
    )


def removed_event(endpoint: CalendarEndpoint, event_id: str) -> CalendarEvent:
    """An event Graph reports removed and answers not found: cancelled, as a deleted Google event
    reads."""
    return CalendarEvent(
        reference=EventRef(endpoint, EventId(event_id)),
        time=None,
        revision="removed",
        status=EventStatus.CANCELLED,
    )


def cancelled_occurrence(series: CalendarEvent, original: OccurrenceStart) -> CalendarEvent:
    """An occurrence the series' pattern defines and Outlook no longer lists: cancelled. It has no
    event of its own, so it is named by its series and original start."""
    stamp = original.isoformat()
    reference = EventRef(
        series.reference.calendar,
        EventId(f"{series.reference.event_id.value}{CANCELLED_MARKER}{stamp}"),
    )
    return CalendarEvent(
        reference=reference,
        time=None,
        revision=f"cancelled:{stamp}",
        status=EventStatus.CANCELLED,
        occurrence=OccurrenceIdentity(series.reference.event_id, original),
    )


def cancelled_occurrence_reference(reference: EventRef) -> tuple[EventRef, OccurrenceStart] | None:
    """The series and original start a cancelled occurrence's name stands for, if it is one."""
    series_id, marker, stamp = reference.event_id.value.partition(CANCELLED_MARKER)
    if not marker:
        return None
    try:
        start: OccurrenceStart = (
            date.fromisoformat(stamp) if len(stamp) == 10 else datetime.fromisoformat(stamp)
        )
    except ValueError:
        return None
    return EventRef(reference.calendar, EventId(series_id)), start


def _recurrence(item: Mapping[str, Any]) -> tuple[Recurrence | None, str | None]:
    """A master's iCalendar lines and IANA zone. A projection reads as written, by what its own
    origin recorded, while Outlook still holds exactly that; otherwise as Outlook holds it."""
    graph_recurrence = item.get("recurrence")
    if not isinstance(graph_recurrence, Mapping) or item.get("type") != "seriesMaster":
        return None, None
    try:
        rule = from_graph(graph_recurrence)
    except UnsupportedRecurrence as error:
        raise GraphTranslationError(
            "Graph answered a recurrence this release cannot read"
        ) from error
    windows = _series_windows_zone(item, graph_recurrence)
    zone = iana_zone(windows)
    written = _written_series(item, rule, windows)
    if written is not None:
        return written
    if zone is None and not item.get("isAllDay"):
        # Legacy custom zones have no IANA name; the series reads in UTC (ADR 0032).
        logger.warning("series in an unrecognized time zone reads in UTC event=%s", item.get("id"))
    return Recurrence(to_ical(rule, _local_start(item, zone))), zone


def _series_windows_zone(item: Mapping[str, Any], recurrence: Mapping[str, Any]) -> str | None:
    range_ = recurrence.get("range")
    zone = range_.get("recurrenceTimeZone") if isinstance(range_, Mapping) else None
    return str(zone) if zone else _optional(item.get("originalStartTimeZone"))


def _written_series(
    item: Mapping[str, Any], actual: SeriesRule, windows: str | None
) -> tuple[Recurrence, str | None] | None:
    """The lines and zone a projection was written with, when Outlook holds exactly them."""
    written = _origin_record(item)
    lines = written.get("recurrence")
    if not isinstance(lines, list) or not lines or not all(isinstance(x, str) for x in lines):
        return None
    zone = written.get("zone")
    zone = zone if isinstance(zone, str) else None
    expected_windows = windows_zone(zone or "Etc/UTC") if not item.get("isAllDay") else windows
    if expected_windows != windows:
        return None
    try:
        rule = from_ical(tuple(lines), _local_start(item, zone or "Etc/UTC"))
    except UnsupportedRecurrence:
        return None
    return (Recurrence(tuple(lines)), zone) if rule == actual else None


def _local_start(item: Mapping[str, Any], zone: str | None) -> datetime | date:
    """The series' first start as its pattern counts: a date for an all-day series, else the
    local time in its zone."""
    if item.get("isAllDay"):
        return _date(item.get("start"))
    start = _instant(item.get("start"))
    return start.astimezone(ZoneInfo(zone)) if zone else start


def _time(item: Mapping[str, Any], zone: str | None) -> TimedInterval | AllDayRange | None:
    start, end = item.get("start"), item.get("end")
    if not isinstance(start, Mapping) or not isinstance(end, Mapping):
        if item.get("isCancelled") is True:
            return None
        raise GraphTranslationError("Graph event is missing its start or end")
    if item.get("isAllDay"):
        return AllDayRange(_date(start), _date(end))
    return TimedInterval(_instant(start), _instant(end), zone)


def _instant(value: object) -> datetime:
    """A Graph dateTimeTimeZone as an aware instant; reads ask for UTC."""
    if not isinstance(value, Mapping) or not isinstance(value.get("dateTime"), str):
        raise GraphTranslationError("Graph time is missing")
    text = str(value["dateTime"]).removesuffix("Z")
    whole, _, fraction = text.partition(".")
    moment = datetime.fromisoformat(whole + ("." + fraction[:6] if fraction else ""))
    zone = iana_zone(_optional(value.get("timeZone")))
    return moment.replace(tzinfo=ZoneInfo(zone) if zone else UTC).astimezone(UTC)


def _date(value: object) -> date:
    if not isinstance(value, Mapping) or not isinstance(value.get("dateTime"), str):
        raise GraphTranslationError("Graph date is missing")
    return date.fromisoformat(str(value["dateTime"])[:10])


def _occurrence(item: Mapping[str, Any], series_zone: str | None) -> OccurrenceIdentity | None:
    if item.get("type") not in OCCURRENCE_TYPES:
        return None
    series = item.get("seriesMasterId")
    original = item.get("originalStart")
    if not isinstance(series, str) or not isinstance(original, str):
        return None
    moment = datetime.fromisoformat(original.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    if item.get("isAllDay"):
        # An all-day occurrence begins at midnight in its series' zone.
        zone = series_zone or iana_zone(_optional(item.get("originalStartTimeZone"))) or "Etc/UTC"
        return OccurrenceIdentity(EventId(series), moment.astimezone(ZoneInfo(zone)).date())
    return OccurrenceIdentity(EventId(series), occurrence_start(moment))


def _origin_record(item: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = _properties(item).get(ORIGIN_PROPERTY.lower())
    try:
        record = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return record if isinstance(record, dict) else {}


def _origin(item: Mapping[str, Any]) -> ManagedOrigin | None:
    rule = _properties(item).get(RULE_PROPERTY.lower())
    record = _origin_record(item)
    values = (rule, record.get("account"), record.get("calendar"), record.get("event"))
    if not all(isinstance(value, str) and value for value in values):
        return None
    rule_id, account, calendar, event = (str(value) for value in values)
    source = CalendarEndpoint(ConnectedAccountId(account), CalendarId(calendar))
    return ManagedOrigin(SyncRuleId(rule_id), EventRef(source, EventId(event)))


def _properties(item: Mapping[str, Any]) -> dict[str, str]:
    """Calendar Ghost's extended properties by lowercase id; Graph may answer ids in any case."""
    properties = item.get("singleValueExtendedProperties")
    if not isinstance(properties, list):
        return {}
    return {
        str(each["id"]).lower(): str(each.get("value") or "")
        for each in properties
        if isinstance(each, Mapping) and isinstance(each.get("id"), str)
    }


def _response(item: Mapping[str, Any]) -> str:
    status = item.get("responseStatus")
    return str(status.get("response")) if isinstance(status, Mapping) else "none"


def _guests(attendees: object) -> tuple[str, ...]:
    """Attendee addresses, only to describe a Source Change; never projected."""
    if not isinstance(attendees, list):
        return ()
    addresses = {
        str(address["address"]).strip().lower()
        for attendee in attendees
        if isinstance(attendee, Mapping)
        and isinstance(address := attendee.get("emailAddress"), Mapping)
        and isinstance(address.get("address"), str)
        and address["address"].strip()
    }
    return tuple(sorted(addresses))


def _conferencing(item: Mapping[str, Any]) -> tuple[str, ...]:
    uris: set[str] = set()
    meeting = item.get("onlineMeeting")
    if isinstance(meeting, Mapping) and isinstance(meeting.get("joinUrl"), str):
        uris.add(meeting["joinUrl"])
    if isinstance(item.get("onlineMeetingUrl"), str) and item["onlineMeetingUrl"]:
        uris.add(item["onlineMeetingUrl"])
    return tuple(sorted(uri for uri in uris if uri))


def _text(body: object) -> str:
    content = body.get("content") if isinstance(body, Mapping) else None
    return str(content).replace("\r\n", "\n") if isinstance(content, str) else ""


def _location(location: object) -> str:
    name = location.get("displayName") if isinstance(location, Mapping) else None
    return str(name) if isinstance(name, str) else ""


def _web_link(value: object) -> str | None:
    return value if isinstance(value, str) and value.startswith("https://") else None


def _required(item: Mapping[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise GraphTranslationError(f"Graph event is missing {key}")
    return value


def _optional(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


# Series ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Series:
    """What expanding an Outlook series needs: its rule, zone, first start, and length."""

    rule: SeriesRule
    start: datetime | date
    """The first occurrence's local start, aware in the series' zone, or its date."""
    duration: timedelta

    @property
    def period(self) -> timedelta:
        """The longest time between neighbouring occurrences, which bounds how far an exception
        may move: Outlook keeps it between its neighbours."""
        return period(self.rule.pattern)

    def original_starts(self, after: datetime, before: datetime) -> Iterator[OccurrenceStart]:
        """The original start of every occurrence the pattern defines from `after` to
        `before`, both inclusive, in order."""
        for day in occurrence_dates(self.rule):
            start = self._start_of(day)
            if self._instant(start) > before:
                return
            if self._instant(start) >= after:
                yield start

    def neighbours(
        self, original: OccurrenceStart
    ) -> tuple[OccurrenceStart | None, OccurrenceStart | None, bool]:
        """The occurrences just before and after `original`, and whether it is one itself."""
        previous: OccurrenceStart | None = None
        target = self._instant(original)
        for day in occurrence_dates(self.rule):
            start = self._start_of(day)
            moment = self._instant(start)
            if moment == target:
                return previous, self._next(day), True
            if moment > target:
                return previous, start, False
            previous = start
        return previous, None, False

    @property
    def first(self) -> datetime:
        """When the series' first occurrence begins."""
        return self._instant(self._start_of(self.rule.range.start))

    def instant(self, start: OccurrenceStart) -> datetime:
        return self._instant(start)

    def start_of(self, day: date) -> OccurrenceStart:
        """The original start of the occurrence on `day`."""
        return self._start_of(day)

    def _next(self, day: date) -> OccurrenceStart | None:
        for following in occurrence_dates(self.rule):
            if following > day:
                return self._start_of(following)
        return None

    def _start_of(self, day: date) -> OccurrenceStart:
        if not isinstance(self.start, datetime):
            return day
        local = datetime.combine(day, self.start.timetz())
        return occurrence_start(local)

    @staticmethod
    def _instant(start: OccurrenceStart) -> datetime:
        if isinstance(start, datetime):
            return start
        return datetime(start.year, start.month, start.day, tzinfo=UTC)


def series_of(item: Mapping[str, Any]) -> Series | None:
    """A master's expansion; None for anything else, or a series in a zone this release cannot
    name, whose occurrences cannot be placed exactly."""
    recurrence = item.get("recurrence")
    if item.get("type") != "seriesMaster" or not isinstance(recurrence, Mapping):
        return None
    try:
        rule = from_graph(recurrence)
    except UnsupportedRecurrence:
        return None
    if item.get("isAllDay"):
        start: datetime | date = _date(item.get("start"))
        duration = timedelta(days=(_date(item.get("end")) - start).days)
        return Series(rule, start, duration)
    zone = iana_zone(_series_windows_zone(item, recurrence))
    if zone is None:
        return None
    begins, ends = _instant(item.get("start")), _instant(item.get("end"))
    return Series(rule, begins.astimezone(ZoneInfo(zone)), ends - begins)


# Writing --------------------------------------------------------------------------------------


def projection_body(
    projection: EventProjection, rule_id: SyncRuleId, source: EventRef, operation_key: str
) -> Json:
    """A Managed Projection's full body; UnsupportedProjection when Outlook cannot hold it."""
    body = _content(projection)
    origin = _origin_value(source)
    if projection.recurrence is not None:
        zone = _projection_zone(projection)
        windows = _windows(zone)
        start = _projection_start(projection, zone)
        try:
            rule = from_ical(projection.recurrence.lines, start)
        except UnsupportedRecurrence as error:
            raise UnsupportedProjection(f"Outlook cannot repeat this series: {error}") from error
        body["recurrence"] = to_graph(rule, windows)
        if isinstance(projection.time, TimedInterval):
            body["start"] = _local(projection.time.starts_at, zone, windows)
            body["end"] = _local(projection.time.ends_at, zone, windows)
        origin |= {"recurrence": list(projection.recurrence.lines), "zone": _time_zone(projection)}
    body["singleValueExtendedProperties"] = _properties_value(rule_id, operation_key, origin)
    return body


def occurrence_body(
    projection: EventProjection,
    rule_id: SyncRuleId,
    source_series: EventRef,
    operation_key: str,
    original_start: OccurrenceStart,
) -> Json:
    """One occurrence's body, naming its series' source and its own original start."""
    body = _content(projection)
    origin = _origin_value(source_series) | {"start": format_occurrence_start(original_start)}
    body["singleValueExtendedProperties"] = _properties_value(rule_id, operation_key, origin)
    return body


def format_occurrence_start(value: OccurrenceStart) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return value.isoformat()


def _content(projection: EventProjection) -> Json:
    """What a projection shows, and the settings that keep it from ever emailing anyone: no
    attendees, no online meeting, no response requested (ADR 0032)."""
    body: Json = {
        "subject": projection.title,
        "body": {"contentType": "text", "content": projection.description},
        "location": {"displayName": projection.location},
        "showAs": "busy",
        "sensitivity": "normal",
        "isReminderOn": False,
        "isOnlineMeeting": False,
        "responseRequested": False,
        "allowNewTimeProposals": False,
    }
    if isinstance(projection.time, AllDayRange):
        body["isAllDay"] = True
        body["start"] = {"dateTime": f"{projection.time.starts_on}T00:00:00", "timeZone": "UTC"}
        body["end"] = {"dateTime": f"{projection.time.ends_before}T00:00:00", "timeZone": "UTC"}
    else:
        body["isAllDay"] = False
        body["start"] = _utc(projection.time.starts_at)
        body["end"] = _utc(projection.time.ends_at)
    return body


def _origin_value(source: EventRef) -> Json:
    return {
        "account": source.calendar.connected_account_id.value,
        "calendar": source.calendar.calendar_id.value,
        "event": source.event_id.value,
    }


def _properties_value(rule_id: SyncRuleId, operation_key: str, origin: Json) -> list[Json]:
    return [
        {"id": RULE_PROPERTY, "value": rule_id.value},
        {"id": OPERATION_PROPERTY, "value": operation_key},
        {"id": ORIGIN_PROPERTY, "value": json.dumps(origin, sort_keys=True)},
    ]


def _time_zone(projection: EventProjection) -> str | None:
    return projection.time.time_zone if isinstance(projection.time, TimedInterval) else None


def _projection_zone(projection: EventProjection) -> str:
    """The IANA zone a series repeats in; a timed series without one repeats in UTC."""
    if isinstance(projection.time, AllDayRange):
        return "Etc/UTC"
    zone = projection.time.time_zone or "Etc/UTC"
    if iana_zone(zone) is None:
        raise UnsupportedProjection("Outlook cannot repeat a series in this time zone")
    return zone


def _windows(zone: str) -> str:
    windows = windows_zone(zone)
    if windows is None:
        raise UnsupportedProjection("Outlook has no time zone that repeats like this one")
    return windows


def _projection_start(projection: EventProjection, zone: str) -> datetime | date:
    if isinstance(projection.time, AllDayRange):
        return projection.time.starts_on
    return projection.time.starts_at.astimezone(ZoneInfo(zone))


def _local(moment: datetime, zone: str, windows: str) -> Json:
    local = moment.astimezone(ZoneInfo(zone))
    return {"dateTime": local.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": windows}


def _utc(moment: datetime) -> Json:
    return {"dateTime": moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"}


def instances_window(after: datetime, before: datetime) -> dict[str, str]:
    """The `instances` query parameters for a window, in UTC."""
    return {
        "startDateTime": after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDateTime": before.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def items_of(page: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    values = page.get("value")
    return (
        [item for item in values if isinstance(item, Mapping)] if isinstance(values, list) else []
    )
