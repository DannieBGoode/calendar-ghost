"""Outlook calendars through Microsoft Graph v1.0: every calendar role (ADR 0032).

Graph v1.0 lists one calendar's changes only through `calendarView/delta`, which expands series
into occurrences and never returns their masters. The adapter keeps series as series: a delta
round reports what changed or was removed, a listing of what was modified since the last run
reports single events and masters, and each master's instances, with the master's own pattern,
give its exceptions, including occurrences Outlook cancelled, which it no longer lists.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any, Protocol

from calendar_sync.application.errors import (
    ProjectionOwnershipMismatch,
    ProviderFailure,
    ProviderFailureKind,
    UnsupportedProjection,
)
from calendar_sync.application.ports import Clock, CreatedProjection, ProviderChangeSet
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import (
    AllDayRange,
    CalendarEndpoint,
    CalendarEvent,
    ConnectedAccountId,
    EventProjection,
    EventRef,
    EventStatus,
    ManagedOrigin,
    OccurrenceStart,
    SyncRuleId,
    TimedInterval,
    TransformationPolicy,
)
from calendar_sync.infrastructure.microsoft.causes import cause_of
from calendar_sync.infrastructure.microsoft.graph import GraphHttp, GraphRefusal, TokenRefusal
from calendar_sync.infrastructure.microsoft.guide import MICROSOFT
from calendar_sync.infrastructure.microsoft.recurrence import occurrence_dates
from calendar_sync.infrastructure.microsoft.translation import (
    EXPAND,
    OCCURRENCE_TYPES,
    OPERATION_PROPERTY,
    RULE_PROPERTY,
    SELECT,
    GraphTranslationError,
    Series,
    cancelled_occurrence,
    cancelled_occurrence_reference,
    instances_window,
    items_of,
    occurrence_body,
    projection_body,
    property_filter,
    removed_event,
    series_of,
    to_domain_event,
)
from calendar_sync.infrastructure.retry_after import retry_after_seconds

# A delta round only tells what changed; its window is kept small, since changes outside it still
# arrive, as removals the adapter reads again (ADR 0032).
DELTA_WINDOW = timedelta(days=1)
# How far before the last run a modified-since listing reaches, for clocks that disagree.
MODIFIED_MARGIN = timedelta(minutes=10)
# Exceptions are listed this far past the sync window's start, as Google's listing stops at a
# page limit.
EXCEPTION_HORIZON = timedelta(days=730)
# Listings run under the rule's write lock, so a long one is read only this far.
PAGE_LIMIT = 20
PAGE_SIZE = "250"
# Answers meaning Graph cannot expand this series, rather than that the request failed.
UNLISTABLE = frozenset({400, 404, 410})
NOT_FOUND = frozenset({404, 410})
# Delta tokens Graph no longer accepts; a full listing starts a new round.
RESYNC_CODES = frozenset({"syncStateNotFound", "resyncRequired"})
CROSSING_NEIGHBOURS = "ErrorOccurrenceCrossingBoundary"

Json = dict[str, Any]


class AccessTokens(Protocol):
    def access_token(self, account_id: ConnectedAccountId) -> str:
        """A usable access token; raises TokenRefusal when Microsoft refuses."""
        ...


@dataclass(frozen=True, slots=True)
class _Cursor:
    delta: str
    since: datetime

    def encode(self) -> str:
        return json.dumps({"delta": self.delta, "since": self.since.isoformat()})

    @classmethod
    def decode(cls, value: str) -> _Cursor | None:
        try:
            raw = json.loads(value)
            return cls(str(raw["delta"]), datetime.fromisoformat(str(raw["since"])))
        except (ValueError, KeyError, TypeError):
            return None


class _Resync(Exception):
    """Graph no longer accepts the delta link, so a full listing starts a new round."""


class OutlookCalendarProvider:
    """Microsoft Graph implementation of every application calendar role (CalendarProvider)."""

    def __init__(
        self,
        tokens: AccessTokens,
        graph: GraphHttp,
        clock: Clock,
        timer: Callable[[], float] = time.monotonic,
    ) -> None:
        self._tokens = tokens
        self._graph = replace(graph, timer=timer)
        self._clock = clock
        # When this thread last read each account's credentials, for the failures they meet.
        self._credentials_read = threading.local()

    # Change feeds ---------------------------------------------------------------------------

    def changes(
        self, source: CalendarEndpoint, cursor: str | None, not_ended_before: datetime
    ) -> ProviderChangeSet:
        parsed = _Cursor.decode(cursor) if cursor else None
        with self._refusals(source.connected_account_id):
            if parsed is not None:
                try:
                    return self._incremental(source, parsed, not_ended_before)
                except _Resync:
                    pass
            started = self._clock.now()
            delta = self._begin_delta(source, not_ended_before)
            events = self._listing(source, not_ended_before)
            return ProviderChangeSet(tuple(events), _Cursor(delta, started).encode(), complete=True)

    def list_events(
        self, calendar: CalendarEndpoint, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        with self._refusals(calendar.connected_account_id):
            return tuple(self._listing(calendar, not_ended_before))

    def managed_events(
        self, destination: CalendarEndpoint, rule_id: SyncRuleId, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        with self._refusals(destination.connected_account_id):
            items = self._events(
                destination, {"$filter": property_filter(RULE_PROPERTY, rule_id.value)}
            )
            return tuple(
                _translate(item, destination)
                for item in items
                if item.get("isCancelled") is not True and _reaches(item, not_ended_before)
            )

    def _begin_delta(self, calendar: CalendarEndpoint, not_ended_before: datetime) -> str:
        """Start a delta round and follow it to its delta link; its events were listed apart."""
        _, link = self._follow(
            calendar,
            f"{_calendar_path(calendar)}/calendarView/delta",
            instances_window(not_ended_before, not_ended_before + DELTA_WINDOW),
        )
        return link

    def _follow(
        self, calendar: CalendarEndpoint, url: str, params: Mapping[str, str] | None = None
    ) -> tuple[list[Mapping[str, Any]], str]:
        """Every entry of a delta round, and the delta link it ends with."""
        entries: list[Mapping[str, Any]] = []
        token = self._token(calendar.connected_account_id)
        try:
            page = self._graph.request("calendarView.delta", "GET", url, token, params=params)
            while True:
                entries.extend(items_of(page))
                if isinstance(link := page.get("@odata.deltaLink"), str):
                    return entries, link
                if not isinstance(following := page.get("@odata.nextLink"), str):
                    raise ProviderFailure(
                        ProviderFailureKind.PERMANENT,
                        "Graph did not end its changes with a delta link",
                        provider=ProviderKind.OUTLOOK,
                        provider_label=MICROSOFT.calendar_name,
                    )
                page = self._graph.request("calendarView.delta", "GET", following, token)
        except GraphRefusal as error:
            if error.status == 410 or RESYNC_CODES & set(error.codes):
                raise _Resync from error
            raise

    def _incremental(
        self, calendar: CalendarEndpoint, cursor: _Cursor, not_ended_before: datetime
    ) -> ProviderChangeSet:
        started = self._clock.now()
        since = (cursor.since - MODIFIED_MARGIN).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        reported: dict[str, CalendarEvent] = {}
        masters: dict[str, Mapping[str, Any]] = {}
        for item in self._events(calendar, {"$filter": f"lastModifiedDateTime ge {since}"}):
            self._sort(calendar, item, reported, masters)
        entries, link = self._follow(calendar, cursor.delta)
        unread_masters: set[str] = set()
        for entry in entries:
            event_id = str(entry.get("id") or "")
            if not event_id or event_id in reported or event_id in masters:
                continue
            if "@removed" not in entry and entry.get("type") in OCCURRENCE_TYPES:
                # An occurrence changed within the window: its series is read again.
                unread_masters.add(str(entry.get("seriesMasterId") or ""))
                continue
            read = self._read(calendar, event_id)
            if read is None:
                reported[event_id] = removed_event(calendar, event_id)
            elif read.get("type") in OCCURRENCE_TYPES:
                unread_masters.add(str(read.get("seriesMasterId") or ""))
            else:
                self._sort(calendar, read, reported, masters)
        for master_id in sorted(unread_masters - masters.keys() - {""}):
            master = self._read(calendar, master_id)
            if master is None:
                reported[master_id] = removed_event(calendar, master_id)
            else:
                masters[master_id] = master
        events = list(reported.values())
        for item in masters.values():
            events.extend(self._series_events(calendar, item, not_ended_before))
        return ProviderChangeSet(tuple(events), _Cursor(link, started).encode())

    def _sort(
        self,
        calendar: CalendarEndpoint,
        item: Mapping[str, Any],
        reported: dict[str, CalendarEvent],
        masters: dict[str, Mapping[str, Any]],
    ) -> None:
        if item.get("type") == "seriesMaster":
            masters[str(item["id"])] = item
        elif item.get("type") not in OCCURRENCE_TYPES:
            event = _translate(item, calendar)
            reported[event.reference.event_id.value] = event

    def _listing(
        self, calendar: CalendarEndpoint, not_ended_before: datetime
    ) -> list[CalendarEvent]:
        """Every single event and series that reaches the window, with each series' exceptions."""
        events: list[CalendarEvent] = []
        for item in self._events(calendar, {}):
            if not _reaches(item, not_ended_before):
                continue
            if item.get("type") == "seriesMaster":
                events.extend(self._series_events(calendar, item, not_ended_before))
            elif item.get("type") not in OCCURRENCE_TYPES:
                events.append(_translate(item, calendar))
        return events

    def _series_events(
        self, calendar: CalendarEndpoint, item: Mapping[str, Any], not_ended_before: datetime
    ) -> list[CalendarEvent]:
        master = _translate(item, calendar)
        if master.status is EventStatus.CANCELLED:
            return [master]
        return [master, *self._exceptions(item, master, not_ended_before)]

    def _events(
        self, calendar: CalendarEndpoint, params: Mapping[str, str]
    ) -> Iterator[Mapping[str, Any]]:
        token = self._token(calendar.connected_account_id)
        query = {"$select": SELECT, "$expand": EXPAND, "$top": PAGE_SIZE, **params}
        for page in self._graph.pages(
            "events.list", f"{_calendar_path(calendar)}/events", token, params=query
        ):
            yield from items_of(page)

    # Single events ---------------------------------------------------------------------------

    def get_event(self, reference: EventRef) -> CalendarEvent | None:
        cancelled = cancelled_occurrence_reference(reference)
        if cancelled is not None:
            return self.get_occurrence(*cancelled)
        with self._refusals(reference.calendar.connected_account_id):
            item = self._read(reference.calendar, reference.event_id.value)
            return _translate(item, reference.calendar) if item is not None else None

    def _read(self, calendar: CalendarEndpoint, event_id: str) -> Mapping[str, Any] | None:
        token = self._token(calendar.connected_account_id)
        try:
            return self._graph.request(
                "events.get",
                "GET",
                f"{_calendar_path(calendar)}/events/{event_id}",
                token,
                params={"$select": SELECT, "$expand": EXPAND},
            )
        except GraphRefusal as error:
            if error.status in NOT_FOUND:
                return None
            raise

    def find_projection(
        self, destination: CalendarEndpoint, operation_key: str
    ) -> CalendarEvent | None:
        with self._refusals(destination.connected_account_id):
            query = {"$filter": property_filter(OPERATION_PROPERTY, operation_key), "$top": "2"}
            token = self._token(destination.connected_account_id)
            page = self._graph.request(
                "events.list",
                "GET",
                f"{_calendar_path(destination)}/events",
                token,
                params={"$select": SELECT, "$expand": EXPAND, **query},
            )
            found = [item for item in items_of(page) if item.get("isCancelled") is not True]
            return _translate(found[0], destination) if found else None

    def create_projection(
        self,
        destination: CalendarEndpoint,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CreatedProjection:
        existing = self.find_projection(destination, operation_key)
        if existing is not None:
            return CreatedProjection(existing)
        body = projection_body(projection, rule_id, source, operation_key)
        with self._refusals(destination.connected_account_id):
            created = self._graph.request(
                "events.create",
                "POST",
                f"{_calendar_path(destination)}/events",
                self._token(destination.connected_account_id),
                body=body,
            )
            # Graph answers without the extended properties it was given; they are as written.
            return CreatedProjection(_written(created, body, destination))

    def update_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent:
        existing = self.get_event(destination)
        if existing is None or not _owned(existing.managed_origin, rule_id, source):
            raise ProjectionOwnershipMismatch(
                "Outlook event does not carry compatible ownership metadata",
                provider=ProviderKind.OUTLOOK,
                provider_label=MICROSOFT.calendar_name,
            )
        body = projection_body(projection, rule_id, source, operation_key)
        if projection.recurrence is None and existing.recurrence is not None:
            body["recurrence"] = None
        account = destination.calendar.connected_account_id
        with self._refusals(account, event_scoped=True):
            updated = self._graph.request(
                "events.update",
                "PATCH",
                _event_path(destination),
                self._token(account),
                body=body,
            )
            return _written(updated, body, destination.calendar)

    def delete_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        # Deleting is idempotent, so it needs no Operation Key.
        operation_key: str,  # noqa: ARG002
    ) -> None:
        existing = self.get_event(destination)
        if existing is None or existing.status is EventStatus.CANCELLED:
            return
        if not _owned(existing.managed_origin, rule_id, source):
            raise ProjectionOwnershipMismatch(
                "Outlook event does not carry compatible ownership metadata",
                provider=ProviderKind.OUTLOOK,
                provider_label=MICROSOFT.calendar_name,
            )
        self._delete(destination.calendar, destination.event_id.value)

    def _delete(self, calendar: CalendarEndpoint, event_id: str) -> None:
        """DELETE, which notifies nobody about an event without attendees, as projections are;
        never `/cancel`, which always would (ADR 0032)."""
        with self._refusals(calendar.connected_account_id):
            try:
                self._graph.request(
                    "events.delete",
                    "DELETE",
                    f"{_calendar_path(calendar)}/events/{event_id}",
                    self._token(calendar.connected_account_id),
                )
            except GraphRefusal as error:
                if error.status not in NOT_FOUND:
                    raise

    # Occurrences -----------------------------------------------------------------------------

    def get_occurrence(
        self, series: EventRef, original_start: OccurrenceStart
    ) -> CalendarEvent | None:
        account = series.calendar.connected_account_id
        with self._refusals(account):
            item = self._read(series.calendar, series.event_id.value)
            if item is None:
                # Only an answered lookup may report absence, which can authorize cancelling.
                raise self._unproven(
                    "Outlook series could not be read while resolving an occurrence"
                )
            master = _translate(item, series.calendar)
            shape = series_of(item)
            after, before, is_slot = _around(shape, original_start)
            found, complete = self._instances(series, item, after, before)
            for candidate in found:
                identity = candidate.occurrence
                if (
                    identity is not None
                    and identity.series_event_id == series.event_id
                    and identity.original_start == original_start
                ):
                    return candidate
            if shape is None or not complete:
                raise self._unproven("Outlook did not finish resolving an occurrence")
            # A slot the pattern defines that Outlook no longer lists was cancelled.
            return cancelled_occurrence(master, original_start) if is_slot else None

    def list_occurrences(
        self, series: EventRef, original_starts: Collection[OccurrenceStart]
    ) -> Mapping[OccurrenceStart, CalendarEvent]:
        wanted = set(original_starts)
        if not wanted:
            return {}
        with self._refusals(series.calendar.connected_account_id):
            item = self._read(series.calendar, series.event_id.value)
            if item is None:
                return {}
            shape = series_of(item)
            margin = shape.period + shape.duration if shape else timedelta(days=367)
            instants = [Series._instant(start) for start in wanted]
            try:
                found, _ = self._instances(
                    series, item, min(instants) - margin, max(instants) + margin
                )
            except GraphRefusal as error:
                if error.status in UNLISTABLE:
                    return {}
                raise
            return {
                event.occurrence.original_start: event
                for event in found
                if event.occurrence is not None and event.occurrence.original_start in wanted
            }

    def has_live_occurrences(self, series: EventRef, policy: TransformationPolicy) -> bool:
        with self._refusals(series.calendar.connected_account_id):
            item = self._read(series.calendar, series.event_id.value)
            if item is None:
                # A series Graph cannot read counts as live, so it synchronizes as before.
                return True
            shape = series_of(item)
            first = (
                shape.first
                if shape is not None
                else _event_start(_translate(item, series.calendar))
            )
            last = _last_end(shape) if shape is not None else None
            before = last or self._clock.now() + EXCEPTION_HORIZON
            try:
                found, complete = self._instances(series, item, first, before)
            except GraphRefusal as error:
                if error.status in UNLISTABLE:
                    return True
                raise
            if any(policy.projects(event) for event in found):
                return True
            # Only an answered lookup of the whole series may report that none remain.
            return not (complete and last is not None)

    def occurrence_exceptions(
        self, series: EventRef, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        with self._refusals(series.calendar.connected_account_id):
            item = self._read(series.calendar, series.event_id.value)
            if item is None:
                return ()
            master = _translate(item, series.calendar)
            if master.status is EventStatus.CANCELLED:
                return ()
            try:
                return tuple(self._exceptions(item, master, not_ended_before))
            except GraphRefusal as error:
                if error.status in UNLISTABLE:
                    return ()
                raise

    def _exceptions(
        self,
        item: Mapping[str, Any],
        master: CalendarEvent,
        not_ended_before: datetime,
    ) -> list[CalendarEvent]:
        """The series' occurrences that reach the window and are cancelled or differ from its
        regular one, up to the horizon."""
        shape = series_of(item)
        margin = shape.period + shape.duration if shape else timedelta(days=367)
        before = not_ended_before + EXCEPTION_HORIZON
        found, complete = self._instances(
            master.reference, item, not_ended_before - margin, before + margin
        )
        exceptions = [
            event
            for event in found
            if event.is_exception_of(master) and event.occurrence_reaches(not_ended_before)
        ]
        if shape is None or not complete:
            # Cancellations are inferred only from an answered listing of an expandable series.
            return exceptions
        listed = {event.occurrence.original_start for event in found if event.occurrence}
        exceptions.extend(
            cancelled_occurrence(master, start)
            for start in shape.original_starts(not_ended_before, before)
            if start not in listed
        )
        return exceptions

    def _instances(
        self,
        series: EventRef,
        master: Mapping[str, Any],
        after: datetime,
        before: datetime,
    ) -> tuple[list[CalendarEvent], bool]:
        """A series' occurrences and exceptions from `after` to `before`, cancelled ones never
        among them, and whether the listing was answered in full."""
        token = self._token(series.calendar.connected_account_id)
        zone = _series_zone(master)
        params = {"$select": SELECT, "$expand": EXPAND, **instances_window(after, before)}
        found: list[CalendarEvent] = []
        pages = self._graph.pages(
            "events.instances", f"{_event_path(series)}/instances", token, params=params
        )
        for count, page in enumerate(pages, start=1):
            found.extend(
                _translate(each, series.calendar, series_zone=zone) for each in items_of(page)
            )
            if count >= PAGE_LIMIT and "@odata.nextLink" in page:
                # Pages beyond the limit were not read, so the listing proves nothing absent.
                return found, False
        return found, True

    def write_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent:
        instance = self._owned_occurrence(
            destination_series, original_start, source_series, rule_id
        )
        if instance is None:
            raise ProviderFailure(
                ProviderFailureKind.PERMANENT,
                "Outlook occurrence could not be resolved",
                provider=ProviderKind.OUTLOOK,
                provider_label=MICROSOFT.calendar_name,
            )
        if instance.status is EventStatus.CANCELLED:
            raise UnsupportedProjection("Outlook cannot restore a cancelled occurrence")
        body = occurrence_body(projection, rule_id, source_series, operation_key, original_start)
        calendar = destination_series.calendar
        with self._refusals(calendar.connected_account_id, event_scoped=True):
            try:
                written = self._graph.request(
                    "events.update",
                    "PATCH",
                    _event_path(instance.reference),
                    self._token(calendar.connected_account_id),
                    body=body,
                )
            except GraphRefusal as error:
                if CROSSING_NEIGHBOURS in error.codes:
                    raise UnsupportedProjection(
                        "Outlook cannot move an occurrence past its neighbours"
                    ) from error
                raise
            return _written(written, body, calendar)

    def cancel_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        # Cancelling is idempotent, so it needs no Operation Key.
        operation_key: str,  # noqa: ARG002
    ) -> None:
        instance = self._owned_occurrence(
            destination_series, original_start, source_series, rule_id
        )
        if instance is None or instance.status is EventStatus.CANCELLED:
            return
        self._delete(destination_series.calendar, instance.reference.event_id.value)

    def _owned_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
    ) -> CalendarEvent | None:
        instance = self.get_occurrence(destination_series, original_start)
        if instance is None:
            return None
        master = self.get_event(destination_series)
        if not (
            master is not None
            and _owned(master.managed_origin, rule_id, source_series)
            and (
                instance.managed_origin is None
                or _owned(instance.managed_origin, rule_id, source_series)
            )
        ):
            raise ProviderFailure(
                ProviderFailureKind.PERMANENT,
                "Outlook occurrence does not carry compatible ownership metadata",
                provider=ProviderKind.OUTLOOK,
                provider_label=MICROSOFT.calendar_name,
            )
        return instance

    # Failures --------------------------------------------------------------------------------

    def _token(self, account: ConnectedAccountId) -> str:
        """The account's access token, as it is now; when it was read names which credentials
        a refusal refused."""
        read: dict[ConnectedAccountId, datetime] = self._credentials_read.__dict__.setdefault(
            "at", {}
        )
        read[account] = self._clock.now()
        return self._tokens.access_token(account)

    def _refusals(self, account: ConnectedAccountId, *, event_scoped: bool = False) -> _Refusals:
        """Translate Microsoft's refusals into provider failures, keeping no message text."""
        return _Refusals(self, account, event_scoped)

    def _failure(
        self,
        error: GraphRefusal | TokenRefusal,
        account: ConnectedAccountId,
        *,
        event_scoped: bool,
    ) -> ProviderFailure:
        now = self._clock.now()
        read: dict[ConnectedAccountId, datetime] = self._credentials_read.__dict__.get("at", {})
        return ProviderFailure(
            _kind(error),
            str(error),
            retry_after_seconds(error.retry_after, now)
            if isinstance(error, GraphRefusal)
            else None,
            account_id=account,
            provider=ProviderKind.OUTLOOK,
            attempted_at=read.get(account, now),
            cause=cause_of(error, event_scoped=event_scoped),
            provider_label=MICROSOFT.calendar_name,
        )

    @staticmethod
    def _unproven(detail: str) -> ProviderFailure:
        return ProviderFailure(
            ProviderFailureKind.TEMPORARY,
            detail,
            provider=ProviderKind.OUTLOOK,
            provider_label=MICROSOFT.calendar_name,
        )


class _Refusals(AbstractContextManager[None]):
    """Not @contextmanager: its exit sets the traceback of the provider failures raised inside,
    which frozen slotted dataclass errors reject."""

    def __init__(
        self, provider: OutlookCalendarProvider, account: ConnectedAccountId, event_scoped: bool
    ) -> None:
        self._provider = provider
        self._account = account
        self._event_scoped = event_scoped

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if isinstance(error, GraphRefusal | TokenRefusal):
            raise self._provider._failure(
                error, self._account, event_scoped=self._event_scoped
            ) from error
        if isinstance(error, GraphTranslationError):
            raise replace(
                self._provider._unproven("Outlook answered an event this release cannot read"),
                kind=ProviderFailureKind.PERMANENT,
                account_id=self._account,
            ) from error


def _kind(error: GraphRefusal | TokenRefusal) -> ProviderFailureKind:
    """What Calendar Ghost does about a refusal: retry, stop the rule, or lapse the account."""
    if isinstance(error, TokenRefusal):
        temporary = error.status is None or error.status >= 500
        if temporary or error.error == "temporarily_unavailable":
            return ProviderFailureKind.TEMPORARY
        return ProviderFailureKind.AUTHENTICATION
    status = error.status
    if status is None or status >= 500:
        return ProviderFailureKind.TEMPORARY
    if status == 429:
        return ProviderFailureKind.RATE_LIMIT
    if status == 401:
        return ProviderFailureKind.AUTHENTICATION
    if status == 403 and "ErrorAccessDenied" not in error.codes:
        return ProviderFailureKind.AUTHORIZATION
    # One calendar the account may not change, or one that is gone: its rule stops alone.
    return ProviderFailureKind.PERMANENT


def _translate(
    item: Mapping[str, Any], calendar: CalendarEndpoint, *, series_zone: str | None = None
) -> CalendarEvent:
    return to_domain_event(item, calendar, series_zone=series_zone)


def _written(
    answer: Mapping[str, Any], body: Mapping[str, Any], calendar: CalendarEndpoint
) -> CalendarEvent:
    return _translate(
        {**answer, "singleValueExtendedProperties": body["singleValueExtendedProperties"]},
        calendar,
    )


def _owned(origin: ManagedOrigin | None, rule_id: SyncRuleId, source: EventRef) -> bool:
    return origin is not None and origin.rule_id == rule_id and origin.source == source


def _calendar_path(calendar: CalendarEndpoint) -> str:
    return f"/me/calendars/{calendar.calendar_id.value}"


def _event_path(reference: EventRef) -> str:
    return f"{_calendar_path(reference.calendar)}/events/{reference.event_id.value}"


def _series_zone(item: Mapping[str, Any]) -> str | None:
    shape = series_of(item)
    if shape is None or not isinstance(shape.start, datetime):
        return "Etc/UTC" if item.get("isAllDay") else None
    return str(shape.start.tzinfo)


def _event_start(event: CalendarEvent) -> datetime:
    if isinstance(event.time, TimedInterval):
        return event.time.starts_at
    if isinstance(event.time, AllDayRange):
        return datetime.combine(event.time.starts_on, datetime.min.time(), tzinfo=UTC)
    return datetime.min.replace(tzinfo=UTC)


def _around(shape: Series | None, original: OccurrenceStart) -> tuple[datetime, datetime, bool]:
    """Where to look for an occurrence: between its neighbouring slots, which an exception never
    moves past, and whether the pattern defines it at all."""
    moment = Series._instant(original)
    if shape is None:
        return moment - timedelta(days=367), moment + timedelta(days=367), False
    previous, following, is_slot = shape.neighbours(original)
    after = shape.instant(previous) if previous is not None else moment - shape.period
    before = shape.instant(following) if following is not None else moment + shape.period
    return after, before + shape.duration, is_slot


def _last_end(shape: Series) -> datetime | None:
    """When the series' last occurrence ends; None for a series without an end."""
    if shape.rule.range.end is None and not shape.rule.range.count:
        return None
    final = deque(occurrence_dates(shape.rule), maxlen=1)
    if not final:
        return None
    return shape.instant(shape.start_of(final[0])) + shape.duration


def _reaches(item: Mapping[str, Any], not_ended_before: datetime) -> bool:
    """Whether a listed single event or series reaches the window; a series that cannot be
    expanded is assumed to."""
    if item.get("type") == "seriesMaster":
        shape = series_of(item)
        if shape is None:
            return True
        last = _last_end(shape)
        return last is None or last >= not_ended_before
    end = item.get("end")
    if not isinstance(end, Mapping) or not isinstance(end.get("dateTime"), str):
        return True
    text = str(end["dateTime"])[:19]
    if item.get("isAllDay"):
        return datetime.fromisoformat(text[:10]).date() >= not_ended_before.date()
    return datetime.fromisoformat(text).replace(tzinfo=UTC) >= not_ended_before
