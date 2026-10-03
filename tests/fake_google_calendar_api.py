"""An in-memory Google Calendar v3 service for driving the real `GoogleCalendarProvider`.

It keeps Google-shaped event JSON per calendar and answers only the `events()` requests the
adapter sends for the Calendar Provider contract. Every write must ask Google to notify nobody and
carry no guests, conferencing, or attachments; each one is recorded for inspection.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from calendar_sync.domain.model import CalendarEndpoint, ConnectedAccountId

EventJson = dict[str, Any]

PAGE_SIZE = 2
"""Small, so a listing of more than two events is answered in pages."""

FORBIDDEN_WRITE_FIELDS = ("attendees", "conferenceData", "attachments")
_FIRST_UPDATE = datetime(2026, 8, 1, tzinfo=UTC)


class GoogleResponse(dict[str, str]):
    """Mirrors httplib2.Response: lower-cased headers plus an integer status."""

    def __init__(self, status: int, headers: dict[str, str]) -> None:
        super().__init__({key.lower(): value for key, value in headers.items()})
        self.status = status


class GoogleApiError(Exception):
    """Shaped like googleapiclient's HttpError, as far as the adapter reads it."""

    def __init__(
        self,
        status: int,
        *,
        reason: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(f"synthetic Google status {status}")
        self.resp = GoogleResponse(status, headers or {})
        self.content = (
            b""
            if reason is None
            else ('{"error":{"errors":[{"reason":"' + reason + '"}]}}').encode()
        )


class UnsafeGoogleWrite(BaseException):
    """A write that could notify guests or carry their data.

    A BaseException, so the adapter's `except Exception` cannot turn it into a ProviderFailure.
    """


@dataclass(frozen=True, slots=True)
class RecordedWrite:
    method: str
    calendar_id: str
    event_id: str | None
    body: EventJson | None
    send_updates: str | None


@dataclass(frozen=True, slots=True)
class FakeRequest:
    """What `events().<method>(...)` returns: nothing happens until `execute()`."""

    run: Callable[[], Any]

    def execute(self) -> Any:
        return self.run()


@dataclass
class FakeGoogleCalendarApi:
    calendars: dict[tuple[str, str], dict[str, EventJson]] = field(default_factory=dict)
    """Event JSON by event id, per (Connected Account, calendarId)."""
    changed_at: dict[tuple[str, str, str], int] = field(default_factory=dict)
    """The version at which each event last changed, for incremental listings."""
    writes: list[RecordedWrite] = field(default_factory=list)
    version: int = 0
    inserted: int = 0

    def service_for(self, account_id: ConnectedAccountId) -> FakeService:
        return FakeService(self, account_id.value)

    def seed(self, endpoint: CalendarEndpoint, event_json: EventJson) -> EventJson:
        """Place a Native Event as the calendar's owner would, without the adapter's help."""
        key = (endpoint.connected_account_id.value, endpoint.calendar_id.value)
        stored = self._store(key, {"status": "confirmed", **copy.deepcopy(event_json)})
        return copy.deepcopy(stored)

    def stored(self, endpoint: CalendarEndpoint, event_id: str) -> EventJson:
        key = (endpoint.connected_account_id.value, endpoint.calendar_id.value)
        return copy.deepcopy(self.calendars[key][event_id])

    def _store(self, key: tuple[str, str], event_json: EventJson) -> EventJson:
        self.version += 1
        event_json["etag"] = f'"etag-{self.version}"'
        event_json["updated"] = (_FIRST_UPDATE + timedelta(seconds=self.version)).isoformat()
        self.calendars.setdefault(key, {})[event_json["id"]] = event_json
        self.changed_at[(*key, event_json["id"])] = self.version
        return event_json

    def _existing(self, key: tuple[str, str], event_id: str) -> EventJson:
        found = self.calendars.get(key, {}).get(event_id)
        if found is None:
            raise GoogleApiError(404, reason="notFound")
        return found

    def _write(
        self,
        method: str,
        key: tuple[str, str],
        event_id: str | None,
        body: EventJson | None,
        send_updates: str | None,
    ) -> None:
        if send_updates != "none":
            raise UnsafeGoogleWrite(f"events.{method} sent sendUpdates={send_updates!r}")
        carried = [name for name in FORBIDDEN_WRITE_FIELDS if body is not None and name in body]
        if carried:
            raise UnsafeGoogleWrite(f"events.{method} body carried {carried}")
        self.writes.append(
            RecordedWrite(method, key[1], event_id, copy.deepcopy(body), send_updates)
        )

    def get(self, key: tuple[str, str], event_id: str) -> EventJson:
        return copy.deepcopy(self._existing(key, event_id))

    def insert(self, key: tuple[str, str], body: EventJson, send_updates: str | None) -> EventJson:
        self._write("insert", key, None, body, send_updates)
        self.inserted += 1
        created = {"status": "confirmed", **copy.deepcopy(body), "id": f"fake{self.inserted:04d}"}
        return copy.deepcopy(self._store(key, created))

    def update(
        self, key: tuple[str, str], event_id: str, body: EventJson, send_updates: str | None
    ) -> EventJson:
        self._existing(key, event_id)
        self._write("update", key, event_id, body, send_updates)
        replaced = {"status": "confirmed", **copy.deepcopy(body), "id": event_id}
        return copy.deepcopy(self._store(key, replaced))

    def delete(self, key: tuple[str, str], event_id: str, send_updates: str | None) -> str:
        existing = self._existing(key, event_id)
        if existing["status"] == "cancelled":
            raise GoogleApiError(410, reason="deleted")
        self._write("delete", key, event_id, None, send_updates)
        # Google keeps a deleted event, cancelled, so later reads and listings can report it.
        self._store(key, {**existing, "status": "cancelled"})
        return ""

    def listing(self, key: tuple[str, str], query: EventQuery) -> EventJson:
        matching = [
            event_json
            for event_id, event_json in self.calendars.get(key, {}).items()
            if query.matches(event_json, self.changed_at[(*key, event_id)])
        ]
        offset = int(query.page_token or 0)
        end = offset + min(query.max_results, PAGE_SIZE)
        response: EventJson = {"items": copy.deepcopy(matching[offset:end])}
        if end < len(matching):
            response["nextPageToken"] = str(end)
        else:
            response["nextSyncToken"] = f"sync-{self.version}"
        return response


@dataclass(frozen=True, slots=True)
class EventQuery:
    show_deleted: bool
    max_results: int
    time_min: str | None
    sync_token: str | None
    private_property: str | None
    page_token: str | None

    def matches(self, event_json: EventJson, changed_at: int) -> bool:
        if self.sync_token is not None:
            # An incremental listing reports every change since the token, cancellations included.
            return changed_at > int(self.sync_token.removeprefix("sync-"))
        if event_json["status"] == "cancelled" and not self.show_deleted:
            return False
        if self.private_property is not None:
            name, _, value = self.private_property.partition("=")
            private = event_json.get("extendedProperties", {}).get("private", {})
            if private.get(name) != value:
                return False
        return self.time_min is None or _ends_after(event_json, _instant(self.time_min))


def _ends_after(event_json: EventJson, moment: datetime) -> bool:
    end = event_json.get("end")
    if not isinstance(end, dict):
        return True
    if "dateTime" in end:
        return _instant(end["dateTime"]) > moment
    return datetime.combine(date.fromisoformat(end["date"]), time(), UTC) > moment


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True, slots=True)
class FakeService:
    api: FakeGoogleCalendarApi
    account_id: str

    def events(self) -> FakeEvents:
        return FakeEvents(self.api, self.account_id)


@dataclass(frozen=True, slots=True)
class FakeEvents:
    """The `events()` collection, taking exactly the keyword arguments the adapter sends."""

    api: FakeGoogleCalendarApi
    account_id: str

    def list(
        self,
        *,
        calendarId: str,
        showDeleted: bool = False,
        singleEvents: bool = False,
        maxResults: int = 250,
        timeMin: str | None = None,
        syncToken: str | None = None,
        privateExtendedProperty: str | None = None,
        pageToken: str | None = None,
    ) -> FakeRequest:
        query = EventQuery(
            showDeleted, maxResults, timeMin, syncToken, privateExtendedProperty, pageToken
        )
        return FakeRequest(lambda: self.api.listing((self.account_id, calendarId), query))

    def get(self, *, calendarId: str, eventId: str) -> FakeRequest:
        return FakeRequest(lambda: self.api.get((self.account_id, calendarId), eventId))

    def insert(
        self, *, calendarId: str, body: EventJson, sendUpdates: str | None = None
    ) -> FakeRequest:
        return FakeRequest(
            lambda: self.api.insert((self.account_id, calendarId), body, sendUpdates)
        )

    def update(
        self, *, calendarId: str, eventId: str, body: EventJson, sendUpdates: str | None = None
    ) -> FakeRequest:
        return FakeRequest(
            lambda: self.api.update((self.account_id, calendarId), eventId, body, sendUpdates)
        )

    def delete(
        self, *, calendarId: str, eventId: str, sendUpdates: str | None = None
    ) -> FakeRequest:
        return FakeRequest(
            lambda: self.api.delete((self.account_id, calendarId), eventId, sendUpdates)
        )
