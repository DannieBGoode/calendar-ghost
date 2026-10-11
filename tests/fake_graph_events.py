"""Events in fake Graph mailboxes, served as Graph v1.0 documents them (ADR 0032).

Single events and series masters are stored as written. A series expands, in its own zone, into
occurrences; an occurrence patched becomes an exception, and one deleted is cancelled and is no
longer listed, as Graph lists no cancelled instance. `calendarView/delta` reports what changed
since a round's token, and removals as `@removed`. Every read answers in UTC. Only the patterns the
tests use are expanded: daily, weekly, and absolute monthly.

Anything that would send mail (attendees, `/cancel`, `/forward`, responses) is recorded in
`mail`, which tests keep empty.
"""

from __future__ import annotations

import calendar as months
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"
Json = dict[str, Any]

ZONES = {
    "UTC": "UTC",
    "W. Europe Standard Time": "Europe/Berlin",
    "Romance Standard Time": "Europe/Paris",
    "Pacific Standard Time": "America/Los_Angeles",
}
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
PROPERTY_FILTER = re.compile(
    r"singleValueExtendedProperties/Any\(ep: ep/id eq '(?P<id>[^']+)' and ep/value eq "
    r"'(?P<value>[^']*)'\)"
)
MODIFIED_FILTER = re.compile(r"lastModifiedDateTime ge (?P<since>\S+)")
MAILING = ("cancel", "forward", "accept", "decline", "tentativelyAccept")
PAGE = 50


@dataclass
class StoredEvent:
    id: str
    mailbox: str
    calendar: str
    fields: Json
    change: int = 1
    modified: datetime = field(default_factory=lambda: datetime.now(UTC))
    cancelled: set[date] = field(default_factory=set)
    """The local dates of occurrences deleted from this series."""
    exceptions: dict[date, Json] = field(default_factory=dict)
    """What each patched occurrence changed, by its local date."""

    @property
    def is_series(self) -> bool:
        return bool(self.fields.get("recurrence"))


@dataclass(frozen=True)
class Change:
    version: int
    place: tuple[str, str]
    id: str
    removed: bool
    series: str | None = None


class FakeGraphEvents:
    def __init__(self) -> None:
        self.stored: dict[str, StoredEvent] = {}
        self.log: list[Change] = []
        self.version = 0
        self.mail: list[str] = []
        self.writes: list[tuple[str, str, Json]] = []
        """Every write: its method, the event it named, and its body."""
        self.expired = False
        """Whether every delta token is refused, as Graph does once its cache drops them."""
        self.created = 0
        self._last = datetime.now(UTC)

    # Test helpers -------------------------------------------------------------------------

    def seed(self, mailbox: str, calendar: str, item: Json) -> str:
        """Place an event as its owner would create it in Outlook; its id."""
        event_id = str(item.get("id") or self._new_id())
        fields = {key: value for key, value in item.items() if key != "id"}
        self.stored[event_id] = StoredEvent(
            event_id, mailbox, calendar, fields, modified=self._now()
        )
        self._changed(mailbox, calendar, event_id)
        return event_id

    def in_calendar(self, mailbox: str, calendar: str) -> list[StoredEvent]:
        return [
            event
            for event in self.stored.values()
            if (event.mailbox, event.calendar) == (mailbox, calendar)
        ]

    # Serving ------------------------------------------------------------------------------

    def serve(
        self, request: httpx.Request, mailbox: str, calendar: str, path: str
    ) -> httpx.Response:
        rest = path.removeprefix(f"/me/calendars/{calendar}")
        params = dict(request.url.params)
        method = request.method
        if rest == "/events":
            if method == "POST":
                return self._create(mailbox, calendar, _json(request))
            return self._list(mailbox, calendar, params)
        if rest == "/calendarView/delta":
            return self._delta(mailbox, calendar, params)
        match = re.fullmatch(r"/events/(?P<id>[^/]+)(?P<tail>/[A-Za-z]+)?", rest)
        if match is None:
            return _error(404, "ErrorInvalidUrl")
        return self._serve_event(request, mailbox, calendar, match["id"], match["tail"] or "")

    def _serve_event(
        self, request: httpx.Request, mailbox: str, calendar: str, event_id: str, tail: str
    ) -> httpx.Response:
        params, method = dict(request.url.params), request.method
        if tail.removeprefix("/") in MAILING:
            self.mail.append(f"{tail.removeprefix('/')} {event_id}")
            return httpx.Response(202)
        if tail == "/instances":
            return self._instances(mailbox, calendar, event_id, params)
        if tail:
            return _error(404, "ErrorInvalidUrl")
        if method == "GET":
            return self._get(mailbox, calendar, event_id, params)
        if method == "PATCH":
            return self._patch(mailbox, calendar, event_id, _json(request))
        if method == "DELETE":
            return self._delete(mailbox, calendar, event_id)
        return _error(405, "ErrorInvalidRequest")

    def _create(self, mailbox: str, calendar: str, body: Json) -> httpx.Response:
        self._mail_check("create", body)
        event_id = self._new_id()
        event = StoredEvent(event_id, mailbox, calendar, dict(body), modified=self._now())
        self.stored[event_id] = event
        self.writes.append(("POST", event_id, body))
        self._changed(mailbox, calendar, event_id)
        # Graph answers without the extended properties it was given.
        return httpx.Response(201, json=self._serve(event, expand=False))

    def _list(self, mailbox: str, calendar: str, params: Mapping[str, str]) -> httpx.Response:
        query = params.get("$filter", "")
        events = [event for event in self.in_calendar(mailbox, calendar) if _matches(event, query)]
        return self._page(
            events,
            params,
            f"{GRAPH}/me/calendars/{calendar}/events",
            lambda event: self._serve(event, expand="$expand" in params),
        )

    def _page(
        self,
        items: list[Any],
        params: Mapping[str, str],
        url: str,
        serve: Any,
    ) -> httpx.Response:
        size = int(params.get("$top", PAGE))
        skip = int(params.get("$skip", "0"))
        body: Json = {"value": [serve(item) for item in items[skip : skip + size]]}
        if skip + size < len(items):
            following = httpx.URL(url, params={**params, "$skip": str(skip + size)})
            body["@odata.nextLink"] = str(following)
        return httpx.Response(200, json=body)

    def _get(
        self, mailbox: str, calendar: str, event_id: str, params: Mapping[str, str]
    ) -> httpx.Response:
        expand = "$expand" in params
        event = self._event(mailbox, calendar, event_id)
        if event is not None:
            return httpx.Response(200, json=self._serve(event, expand=expand))
        found = self._occurrence(mailbox, calendar, event_id)
        if found is None:
            return _error(404, "ErrorItemNotFound")
        series, day = found
        return httpx.Response(200, json=self._instance(series, day, expand=expand))

    def _patch(self, mailbox: str, calendar: str, event_id: str, body: Json) -> httpx.Response:
        self._mail_check("update", body)
        self.writes.append(("PATCH", event_id, body))
        event = self._event(mailbox, calendar, event_id)
        if event is not None:
            for key, value in body.items():
                if value is None:
                    event.fields.pop(key, None)
                else:
                    event.fields[key] = value
            self._touch(event)
            self._changed(mailbox, calendar, event_id)
            return httpx.Response(200, json=self._serve(event, expand=False))
        found = self._occurrence(mailbox, calendar, event_id)
        if found is None:
            return _error(404, "ErrorItemNotFound")
        series, day = found
        if "start" in body and not self._between_neighbours(series, day, _utc(body["start"])):
            return _error(400, "ErrorOccurrenceCrossingBoundary")
        series.exceptions[day] = {**series.exceptions.get(day, {}), **body}
        # Outlook changes the master when one of its occurrences changes (ADR 0032, item 2).
        self._touch(series)
        self._changed(mailbox, calendar, event_id, series=series.id)
        return httpx.Response(200, json=self._instance(series, day, expand=False))

    def _delete(self, mailbox: str, calendar: str, event_id: str) -> httpx.Response:
        event = self._event(mailbox, calendar, event_id)
        self.writes.append(("DELETE", event_id, {}))
        if event is not None:
            if event.fields.get("attendees"):
                self.mail.append(f"cancellation {event_id}")
            del self.stored[event_id]
            self._changed(mailbox, calendar, event_id, removed=True)
            return httpx.Response(204)
        found = self._occurrence(mailbox, calendar, event_id)
        if found is None:
            return _error(404, "ErrorItemNotFound")
        series, day = found
        series.cancelled.add(day)
        series.exceptions.pop(day, None)
        self._touch(series)
        self._changed(mailbox, calendar, event_id, removed=True, series=series.id)
        return httpx.Response(204)

    def _delta(self, mailbox: str, calendar: str, params: Mapping[str, str]) -> httpx.Response:
        if self.expired and "$deltatoken" in params:
            return _error(410, "syncStateNotFound")
        url = f"{GRAPH}/me/calendars/{calendar}/calendarView/delta"
        if "$deltatoken" not in params and "$skiptoken" not in params:
            # A new round reports the window's events; the adapter listed them apart.
            changes = [
                Change(self.version, (mailbox, calendar), event.id, removed=False)
                for event in self.in_calendar(mailbox, calendar)
            ]
        else:
            since = int(params.get("$deltatoken", params.get("$skiptoken", "0").split(":")[0]))
            changes = [
                change
                for change in self.log
                if change.version > since and change.place == (mailbox, calendar)
            ]
        skip = int(params["$skiptoken"].split(":")[1]) if "$skiptoken" in params else 0
        page = changes[skip : skip + PAGE]
        body: Json = {"value": [_delta_entry(change, self.stored) for change in page]}
        if skip + PAGE < len(changes):
            token = params.get("$deltatoken", params.get("$skiptoken", "0").split(":")[0])
            body["@odata.nextLink"] = f"{url}?$skiptoken={token}:{skip + PAGE}"
        else:
            body["@odata.deltaLink"] = f"{url}?$deltatoken={self.version}"
        return httpx.Response(200, json=body)

    def _instances(
        self, mailbox: str, calendar: str, event_id: str, params: Mapping[str, str]
    ) -> httpx.Response:
        series = self._event(mailbox, calendar, event_id)
        if series is None or not series.is_series:
            return _error(404, "ErrorItemNotFound")
        after = datetime.fromisoformat(params["startDateTime"].replace("Z", "+00:00"))
        before = datetime.fromisoformat(params["endDateTime"].replace("Z", "+00:00"))
        listed = [
            day
            for day in _slots(series, before + timedelta(days=400))
            if day not in series.cancelled and self._overlaps(series, day, after, before)
        ]
        url = f"{GRAPH}/me/calendars/{calendar}/events/{event_id}/instances"
        return self._page(
            listed,
            params,
            url,
            lambda day: self._instance(series, day, expand="$expand" in params),
        )

    # Shaping answers ---------------------------------------------------------------------

    def _serve(self, event: StoredEvent, *, expand: bool) -> Json:
        fields = {**event.fields}
        properties = fields.pop("singleValueExtendedProperties", None)
        answer: Json = {
            "id": event.id,
            "changeKey": f"ck-{event.id}-{event.change}",
            "lastModifiedDateTime": event.modified.isoformat().replace("+00:00", "Z"),
            "type": "seriesMaster" if event.is_series else "singleInstance",
            "isCancelled": False,
            "isAllDay": False,
            "originalStartTimeZone": fields.get("start", {}).get("timeZone", "UTC"),
            **fields,
            "start": _answer_time(fields.get("start"), fields.get("isAllDay")),
            "end": _answer_time(fields.get("end"), fields.get("isAllDay")),
        }
        if expand and properties:
            answer["singleValueExtendedProperties"] = properties
        return answer

    def _instance(self, series: StoredEvent, day: date, *, expand: bool) -> Json:
        override = series.exceptions.get(day, {})
        start = self._slot_start(series, day)
        length = _utc(series.fields["end"]) - _utc(series.fields["start"])
        all_day = bool(series.fields.get("isAllDay"))
        own_start = _utc(override["start"]) if "start" in override else start
        own_end = _utc(override["end"]) if "end" in override else start + length
        answer: Json = {
            "id": f"{series.id}.occ.{day.isoformat()}",
            "changeKey": f"ck-{series.id}-{day}-{len(override)}",
            "type": "exception" if override else "occurrence",
            "seriesMasterId": series.id,
            "originalStart": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "originalStartTimeZone": series.fields["start"].get("timeZone", "UTC"),
            "isAllDay": all_day,
            "isCancelled": False,
            "subject": override.get("subject", series.fields.get("subject", "")),
            "body": override.get("body", series.fields.get("body")),
            "location": override.get("location", series.fields.get("location")),
            "responseStatus": series.fields.get("responseStatus"),
            "start": _answer_instant(own_start, False),
            "end": _answer_instant(own_end, False),
        }
        if all_day:
            # An all-day occurrence reads by its own dates, wherever its series' zone is.
            span = date.fromisoformat(series.fields["end"]["dateTime"][:10]) - date.fromisoformat(
                series.fields["start"]["dateTime"][:10]
            )
            own = (
                date.fromisoformat(str(override["start"]["dateTime"])[:10])
                if "start" in override
                else day
            )
            answer["start"] = {"dateTime": f"{own}T00:00:00.0000000", "timeZone": "UTC"}
            answer["end"] = {"dateTime": f"{own + span}T00:00:00.0000000", "timeZone": "UTC"}
        properties = override.get("singleValueExtendedProperties")
        if expand and properties:
            answer["singleValueExtendedProperties"] = properties
        return answer

    # Series --------------------------------------------------------------------------------

    def _slot_start(self, series: StoredEvent, day: date) -> datetime:
        local = _local(series.fields["start"])
        if series.fields.get("isAllDay"):
            return datetime.combine(day, datetime.min.time(), tzinfo=local.tzinfo).astimezone(UTC)
        return datetime.combine(day, local.timetz()).astimezone(UTC)

    def _overlaps(self, series: StoredEvent, day: date, after: datetime, before: datetime) -> bool:
        instance = self._instance(series, day, expand=False)
        starts = _utc(instance["start"])
        ends = _utc(instance["end"])
        return starts < before and ends > after

    def _between_neighbours(self, series: StoredEvent, day: date, moved: datetime) -> bool:
        """Outlook refuses to move an occurrence to or past a neighbouring occurrence's day."""
        slots = list(_slots(series, moved + timedelta(days=400)))
        index = slots.index(day) if day in slots else -1
        zone = _local(series.fields["start"]).tzinfo
        moved_day = moved.astimezone(zone).date()
        previous = slots[index - 1] if index > 0 else None
        following = slots[index + 1] if 0 <= index < len(slots) - 1 else None
        return (previous is None or moved_day > previous) and (
            following is None or moved_day < following
        )

    def _occurrence(
        self, mailbox: str, calendar: str, event_id: str
    ) -> tuple[StoredEvent, date] | None:
        series_id, marker, day = event_id.partition(".occ.")
        series = self._event(mailbox, calendar, series_id) if marker else None
        if series is None or not series.is_series:
            return None
        occurrence = date.fromisoformat(day)
        horizon = self._slot_start(series, occurrence) + timedelta(days=2)
        if occurrence in series.cancelled or occurrence not in set(_slots(series, horizon)):
            return None
        return series, occurrence

    # Bookkeeping ----------------------------------------------------------------------------

    def _event(self, mailbox: str, calendar: str, event_id: str) -> StoredEvent | None:
        event = self.stored.get(event_id)
        if event is None or (event.mailbox, event.calendar) != (mailbox, calendar):
            return None
        return event

    def _mail_check(self, action: str, body: Mapping[str, Any]) -> None:
        if body.get("attendees") or body.get("isOnlineMeeting"):
            self.mail.append(f"{action} with attendees or a meeting")

    def _touch(self, event: StoredEvent) -> None:
        event.change += 1
        event.modified = self._now()

    def _changed(
        self,
        mailbox: str,
        calendar: str,
        event_id: str,
        *,
        removed: bool = False,
        series: str | None = None,
    ) -> None:
        self.version += 1
        self.log.append(Change(self.version, (mailbox, calendar), event_id, removed, series))

    def _now(self) -> datetime:
        self._last = max(datetime.now(UTC), self._last + timedelta(microseconds=1))
        return self._last

    def _new_id(self) -> str:
        self.created += 1
        return f"AAMk-synthetic-{self.created}"


def _slots(series: StoredEvent, until: datetime) -> Iterator[date]:
    """The local dates the series' pattern defines, up to `until`."""
    recurrence = series.fields["recurrence"]
    pattern, range_ = recurrence["pattern"], recurrence["range"]
    first = date.fromisoformat(range_["startDate"])
    end = date.fromisoformat(range_["endDate"]) if range_.get("type") == "endDate" else None
    count = int(range_.get("numberOfOccurrences") or 0) if range_.get("type") == "numbered" else 0
    stop = min(until.date(), end) if end else until.date()
    for produced, day in enumerate(_pattern_dates(pattern, first)):
        if day > stop or (count and produced >= count):
            return
        yield day


def _pattern_dates(pattern: Mapping[str, Any], first: date) -> Iterator[date]:
    interval = int(pattern.get("interval") or 1)
    kind = pattern["type"]
    if kind == "daily":
        day = first
        while True:
            yield day
            day += timedelta(days=interval)
    if kind == "weekly":
        week_start = DAYS.index(pattern.get("firstDayOfWeek", "sunday"))
        week = first - timedelta(days=(first.weekday() - week_start) % 7)
        wanted = sorted((DAYS.index(name) - week_start) % 7 for name in pattern["daysOfWeek"])
        while True:
            for offset in wanted:
                day = week + timedelta(days=offset)
                if day >= first:
                    yield day
            week += timedelta(weeks=interval)
    if kind == "absoluteMonthly":
        year, month = first.year, first.month
        while True:
            length = months.monthrange(year, month)[1]
            day = date(year, month, min(int(pattern["dayOfMonth"]), length))
            if day >= first:
                yield day
            month += interval
            year, month = year + (month - 1) // 12, (month - 1) % 12 + 1
    raise AssertionError(f"the fake does not expand {kind} patterns")


def _matches(event: StoredEvent, query: str) -> bool:
    if not query:
        return True
    if found := PROPERTY_FILTER.fullmatch(query):
        properties = event.fields.get("singleValueExtendedProperties") or []
        return any(
            each["id"].lower() == found["id"].lower()
            # Graph compares a property's value case-insensitively.
            and str(each["value"]).lower() == found["value"].lower()
            for each in properties
        )
    if found := MODIFIED_FILTER.fullmatch(query):
        return event.modified >= datetime.fromisoformat(found["since"].replace("Z", "+00:00"))
    raise AssertionError(f"the fake does not understand the filter {query}")


def _delta_entry(change: Change, stored: Mapping[str, StoredEvent]) -> Json:
    if change.removed:
        return {"id": change.id, "@removed": {"reason": "deleted"}}
    if change.series is not None:
        return {"id": change.id, "type": "exception", "seriesMasterId": change.series}
    event = stored.get(change.id)
    kind = "seriesMaster" if event is not None and event.is_series else "singleInstance"
    return {"id": change.id, "type": kind}


def _local(value: Mapping[str, Any]) -> datetime:
    zone = ZoneInfo(ZONES.get(value.get("timeZone", "UTC"), value.get("timeZone", "UTC")))
    text = str(value["dateTime"]).split(".")[0].removesuffix("Z")
    return datetime.fromisoformat(text).replace(tzinfo=zone)


def _utc(value: Mapping[str, Any]) -> datetime:
    return _local(value).astimezone(UTC)


def _answer_time(value: Any, all_day: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    if all_day:
        return {"dateTime": f"{str(value['dateTime'])[:10]}T00:00:00.0000000", "timeZone": "UTC"}
    return _answer_instant(_utc(value), False)


def _answer_instant(moment: datetime, all_day: bool) -> Json:
    if all_day:
        return {"dateTime": f"{moment.date().isoformat()}T00:00:00.0000000", "timeZone": "UTC"}
    return {"dateTime": moment.strftime("%Y-%m-%dT%H:%M:%S.0000000"), "timeZone": "UTC"}


def _json(request: httpx.Request) -> Json:
    import json

    body = json.loads(request.content or b"{}")
    return body if isinstance(body, dict) else {}


def _error(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": "private-marker"}})
