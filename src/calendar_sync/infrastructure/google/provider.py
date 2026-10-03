from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

from google.auth.exceptions import RefreshError, TransportError

from calendar_sync.application.errors import (
    ProjectionOwnershipMismatch,
    ProviderFailure,
    ProviderFailureKind,
)
from calendar_sync.application.ports import Clock, CreatedProjection, ProviderChangeSet
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarEvent,
    ConnectedAccountId,
    EventProjection,
    EventRef,
    EventStatus,
    ManagedOrigin,
    OccurrenceStart,
    SyncRuleId,
    TransformationPolicy,
)
from calendar_sync.infrastructure.google.translation import (
    OPERATION_PROPERTY,
    RULE_PROPERTY,
    format_occurrence_start,
    projection_payload,
    to_domain_event,
)
from calendar_sync.infrastructure.provider_calls import record_call
from calendar_sync.infrastructure.scheduling import SystemClock

GoogleServiceFactory = Callable[[ConnectedAccountId], Any]


class GoogleCalendarProvider:
    """Google Calendar implementation of every application calendar role (CalendarProvider)."""

    def __init__(
        self,
        service_for: GoogleServiceFactory,
        clock: Clock | None = None,
        timer: Callable[[], float] = time.monotonic,
    ) -> None:
        self._service_for = service_for
        self._clock = clock or SystemClock()
        # Seconds from an arbitrary start, for timing calls; the clock tells wall time.
        self._timer = timer

    def _call(self, operation: str, request: Any) -> Any:
        """Send one Google request, tallying and logging it by its operation name alone."""
        started = self._timer()
        status: int | None = 200
        rate_limited = False
        try:
            return request.execute()
        except Exception as error:
            status = _status_code(error)
            rate_limited = status == 429 or (status == 403 and _is_rate_limit_error(error))
            raise
        finally:
            record_call(
                ProviderKind.GOOGLE,
                operation,
                status,
                self._timer() - started,
                rate_limited=rate_limited,
            )

    def changes(
        self,
        source: CalendarEndpoint,
        cursor: str | None,
        not_ended_before: datetime,
    ) -> ProviderChangeSet:
        parameters: dict[str, Any] = {
            "calendarId": source.calendar_id.value,
            "showDeleted": True,
            "singleEvents": False,
            "maxResults": 2500,
        }
        if cursor:
            parameters["syncToken"] = cursor
        else:
            parameters["timeMin"] = not_ended_before.isoformat()

        items: list[CalendarEvent] = []
        try:
            events_api = self._service_for(source.connected_account_id).events()
            while True:
                response = self._call("events.list", events_api.list(**parameters))
                items.extend(to_domain_event(item, source) for item in response.get("items", []))
                page_token = response.get("nextPageToken")
                if not page_token:
                    next_cursor = response.get("nextSyncToken")
                    if not isinstance(next_cursor, str):
                        raise ProviderFailure(
                            ProviderFailureKind.PERMANENT,
                            "Google response did not include a synchronization token",
                            provider=ProviderKind.GOOGLE,
                        )
                    return ProviderChangeSet(tuple(items), next_cursor, complete=not cursor)
                parameters["pageToken"] = page_token
        except ProviderFailure:
            raise
        except Exception as error:
            if cursor is not None and _status_code(error) == 410:
                return self.changes(source, None, not_ended_before)
            raise self._failure(error, source.connected_account_id) from error

    def get_event(self, reference: EventRef) -> CalendarEvent | None:
        try:
            payload = self._call(
                "events.get",
                self._service_for(reference.calendar.connected_account_id)
                .events()
                .get(
                    calendarId=reference.calendar.calendar_id.value,
                    eventId=reference.event_id.value,
                ),
            )
            return to_domain_event(payload, reference.calendar)
        except Exception as error:
            if _status_code(error) == 404:
                return None
            raise self._failure(error, reference.calendar.connected_account_id) from error

    def find_projection(
        self, destination: CalendarEndpoint, operation_key: str
    ) -> CalendarEvent | None:
        try:
            existing = self._call(
                "events.list",
                self._service_for(destination.connected_account_id)
                .events()
                .list(
                    calendarId=destination.calendar_id.value,
                    privateExtendedProperty=f"{OPERATION_PROPERTY}={operation_key}",
                    showDeleted=False,
                    maxResults=2,
                ),
            ).get("items", [])
        except Exception as error:
            raise self._failure(error, destination.connected_account_id) from error
        return to_domain_event(existing[0], destination) if existing else None

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
        try:
            payload = self._call(
                "events.insert",
                self._service_for(destination.connected_account_id)
                .events()
                .insert(
                    calendarId=destination.calendar_id.value,
                    body=projection_payload(projection, rule_id, source, operation_key),
                    sendUpdates="none",
                ),
            )
            return CreatedProjection(to_domain_event(payload, destination))
        except Exception as error:
            raise self._failure(error, destination.connected_account_id) from error

    def update_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent:
        existing = self.get_event(destination)
        if (
            existing is None
            or existing.managed_origin is None
            or existing.managed_origin.rule_id != rule_id
            or existing.managed_origin.source != source
        ):
            raise ProviderFailure(
                ProviderFailureKind.PERMANENT,
                "Google event does not carry compatible ownership metadata",
                provider=ProviderKind.GOOGLE,
            )
        try:
            payload = self._call(
                "events.update",
                self._service_for(destination.calendar.connected_account_id)
                .events()
                .update(
                    calendarId=destination.calendar.calendar_id.value,
                    eventId=destination.event_id.value,
                    body=projection_payload(projection, rule_id, source, operation_key),
                    sendUpdates="none",
                ),
            )
            return to_domain_event(payload, destination.calendar)
        except Exception as error:
            raise self._failure(error, destination.calendar.connected_account_id) from error

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
        if (
            existing.managed_origin is None
            or existing.managed_origin.rule_id != rule_id
            or existing.managed_origin.source != source
        ):
            raise ProjectionOwnershipMismatch(
                "Google event does not carry compatible ownership metadata"
            )
        try:
            self._call(
                "events.delete",
                self._service_for(destination.calendar.connected_account_id)
                .events()
                .delete(
                    calendarId=destination.calendar.calendar_id.value,
                    eventId=destination.event_id.value,
                    sendUpdates="none",
                ),
            )
        except Exception as error:
            if _status_code(error) not in {404, 410}:
                raise self._failure(error, destination.calendar.connected_account_id) from error

    def list_events(
        self, calendar: CalendarEndpoint, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        return self._list(
            calendar,
            {
                "calendarId": calendar.calendar_id.value,
                "showDeleted": True,
                "singleEvents": False,
                "timeMin": not_ended_before.isoformat(),
                "maxResults": 2500,
            },
        )

    def managed_events(
        self, destination: CalendarEndpoint, rule_id: SyncRuleId, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        return self._list(
            destination,
            {
                "calendarId": destination.calendar_id.value,
                "privateExtendedProperty": f"{RULE_PROPERTY}={rule_id.value}",
                "showDeleted": False,
                "singleEvents": False,
                "timeMin": not_ended_before.isoformat(),
                "maxResults": 2500,
            },
        )

    def _list(
        self, calendar: CalendarEndpoint, parameters: dict[str, Any]
    ) -> Sequence[CalendarEvent]:
        """Every page of one events.list request, without asking for a synchronization token."""
        try:
            events_api = self._service_for(calendar.connected_account_id).events()
            items: list[CalendarEvent] = []
            while True:
                response = self._call("events.list", events_api.list(**parameters))
                items.extend(to_domain_event(item, calendar) for item in response.get("items", []))
                page_token = response.get("nextPageToken")
                if not page_token:
                    return tuple(items)
                parameters["pageToken"] = page_token
        except Exception as error:
            raise self._failure(error, calendar.connected_account_id) from error

    def get_occurrence(
        self, series: EventRef, original_start: OccurrenceStart
    ) -> CalendarEvent | None:
        # No maxResults: Google pages before it filters by originalStart, so a one-result page
        # comes back empty for an occurrence that was moved and absence would be reported.
        parameters: dict[str, Any] = {
            "calendarId": series.calendar.calendar_id.value,
            "eventId": series.event_id.value,
            "originalStart": format_occurrence_start(original_start),
            "showDeleted": True,
        }
        try:
            events_api = self._service_for(series.calendar.connected_account_id).events()
            for _ in range(OCCURRENCE_PAGE_LIMIT):
                response = self._call("events.instances", events_api.instances(**parameters))
                for item in response.get("items", []):
                    candidate = to_domain_event(item, series.calendar)
                    # Never trust a positional result: the instance must name the requested start.
                    if (
                        candidate.occurrence is not None
                        and candidate.occurrence.series_event_id == series.event_id
                        and candidate.occurrence.original_start == original_start
                    ):
                        return candidate
                page_token = response.get("nextPageToken")
                if not page_token:
                    return None
                parameters["pageToken"] = page_token
        except Exception as error:
            # A missing series proves nothing about its occurrences; only an answered lookup may
            # report absence, because absence can authorize cancelling a destination occurrence.
            if _status_code(error) in {404, 410}:
                raise ProviderFailure(
                    ProviderFailureKind.TEMPORARY,
                    "Google series could not be read while resolving an occurrence",
                    provider=ProviderKind.GOOGLE,
                ) from error
            raise self._failure(error, series.calendar.connected_account_id) from error
        # Pages beyond the limit were not read, so the occurrence is not proven absent.
        raise ProviderFailure(
            ProviderFailureKind.TEMPORARY,
            "Google did not finish resolving an occurrence within the page limit",
            provider=ProviderKind.GOOGLE,
        )

    def list_occurrences(
        self, series: EventRef, original_starts: Collection[OccurrenceStart]
    ) -> Mapping[OccurrenceStart, CalendarEvent]:
        wanted = set(original_starts)
        if not wanted:
            return {}
        parameters: dict[str, Any] = {
            "calendarId": series.calendar.calendar_id.value,
            "eventId": series.event_id.value,
            "showDeleted": True,
            "maxResults": 2500,
            "fields": OCCURRENCE_EXCEPTION_FIELDS,
            # No timeMin: it filters by where an instance is now, not by its original start. The
            # bound only keeps an endless series from paging on; anything past it is looked up.
            "timeMax": (max(map(_as_instant, wanted)) + OCCURRENCE_LISTING_MARGIN).isoformat(),
        }
        found: dict[OccurrenceStart, CalendarEvent] = {}
        try:
            events_api = self._service_for(series.calendar.connected_account_id).events()
            for _ in range(OCCURRENCE_PAGE_LIMIT):
                response = self._call("events.instances", events_api.instances(**parameters))
                for item in response.get("items", []):
                    candidate = to_domain_event(item, series.calendar)
                    identity = candidate.occurrence
                    # Never trust a positional result: the instance must name its series and start.
                    if (
                        identity is not None
                        and identity.series_event_id == series.event_id
                        and identity.original_start in wanted
                    ):
                        found[identity.original_start] = candidate
                page_token = response.get("nextPageToken")
                if not page_token or len(found) == len(wanted):
                    break
                parameters["pageToken"] = page_token
        except Exception as error:
            # A series Google cannot expand answers nothing; each lookup then decides on its own.
            if _status_code(error) in UNLISTABLE_SERIES_STATUSES:
                return {}
            raise self._failure(error, series.calendar.connected_account_id) from error
        return found

    def has_live_occurrences(self, series: EventRef, policy: TransformationPolicy) -> bool:
        parameters: dict[str, Any] = {
            "calendarId": series.calendar.calendar_id.value,
            "eventId": series.event_id.value,
            "showDeleted": False,
            "maxResults": LIVE_OCCURRENCE_PAGE_SIZE,
            "fields": LIVE_OCCURRENCE_FIELDS,
        }
        try:
            events_api = self._service_for(series.calendar.connected_account_id).events()
            for _ in range(OCCURRENCE_PAGE_LIMIT):
                response = self._call("events.instances", events_api.instances(**parameters))
                # showDeleted=False should omit cancelled instances; the status is checked anyway,
                # because counting one as live would recreate a series that can only be cancelled.
                if any(
                    policy.projects(to_domain_event(item, series.calendar))
                    for item in response.get("items", [])
                ):
                    return True
                # A filtered page may be empty while later pages still hold live instances.
                page_token = response.get("nextPageToken")
                if not page_token:
                    return False
                parameters["pageToken"] = page_token
        except Exception as error:
            # Only an answered lookup may report that none remain. A series Google cannot expand
            # counts as live, so it synchronizes as before instead of failing the whole rule.
            if _status_code(error) in UNLISTABLE_SERIES_STATUSES:
                return True
            raise self._failure(error, series.calendar.connected_account_id) from error
        # Pages beyond the limit were not read, so the series is not proven empty.
        return True

    def occurrence_exceptions(
        self, series: EventRef, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        parameters: dict[str, Any] = {
            "calendarId": series.calendar.calendar_id.value,
            "eventId": series.event_id.value,
            "showDeleted": True,
            # timeMin filters by where an instance is now, which would drop an occurrence moved
            # out of the window whose original slot is still in it; the window is applied below.
            "maxResults": 2500,
            "fields": OCCURRENCE_EXCEPTION_FIELDS,
        }
        # The master is the regular occurrence every unmodified instance repeats.
        master = self.get_event(series)
        if master is None or master.status is EventStatus.CANCELLED:
            return ()
        exceptions: list[CalendarEvent] = []
        try:
            events_api = self._service_for(series.calendar.connected_account_id).events()
            for _ in range(OCCURRENCE_PAGE_LIMIT):
                response = self._call("events.instances", events_api.instances(**parameters))
                for item in response.get("items", []):
                    instance = to_domain_event(item, series.calendar)
                    if instance.is_exception_of(master) and instance.occurrence_reaches(
                        not_ended_before
                    ):
                        exceptions.append(instance)
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
                parameters["pageToken"] = page_token
        except Exception as error:
            if _status_code(error) in UNLISTABLE_SERIES_STATUSES:
                return ()
            raise self._failure(error, series.calendar.connected_account_id) from error
        return tuple(exceptions)

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
                "Google occurrence could not be resolved",
                provider=ProviderKind.GOOGLE,
            )
        body = projection_payload(
            projection, rule_id, source_series, operation_key, original_start=original_start
        )
        body["status"] = "confirmed"
        try:
            payload = self._call(
                "events.patch",
                self._service_for(destination_series.calendar.connected_account_id)
                .events()
                .patch(
                    calendarId=destination_series.calendar.calendar_id.value,
                    eventId=instance.reference.event_id.value,
                    body=body,
                    sendUpdates="none",
                ),
            )
            return to_domain_event(payload, destination_series.calendar)
        except Exception as error:
            raise self._failure(error, destination_series.calendar.connected_account_id) from error

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
        try:
            self._call(
                "events.delete",
                self._service_for(destination_series.calendar.connected_account_id)
                .events()
                .delete(
                    calendarId=destination_series.calendar.calendar_id.value,
                    eventId=instance.reference.event_id.value,
                    sendUpdates="none",
                ),
            )
        except Exception as error:
            if _status_code(error) not in {404, 410}:
                raise self._failure(
                    error, destination_series.calendar.connected_account_id
                ) from error

    def _failure(self, error: Exception, account: ConnectedAccountId) -> ProviderFailure:
        # The clock turns a Retry-After date into the seconds the retry helper waits. The account
        # names whose access to renew when Google rejected its credentials.
        return replace(
            _provider_failure(error, self._clock.now()),
            account_id=account,
            provider=ProviderKind.GOOGLE,
        )

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
                "Google occurrence does not carry compatible ownership metadata",
                provider=ProviderKind.GOOGLE,
            )
        return instance


def _as_instant(start: OccurrenceStart) -> datetime:
    if isinstance(start, datetime):
        return start.astimezone(UTC)
    return datetime(start.year, start.month, start.day, tzinfo=UTC)


def _owned(origin: ManagedOrigin | None, rule_id: SyncRuleId, source: EventRef) -> bool:
    return origin is not None and origin.rule_id == rule_id and origin.source == source


def _provider_failure(error: Exception, now: datetime) -> ProviderFailure:
    # Refreshing the access token fails before any request is sent, so it carries no status. A
    # revoked or expired grant needs reauthorization; google-auth marks token-endpoint outages
    # retryable. Their text can quote the token endpoint's response, so it is not kept.
    if isinstance(error, RefreshError):
        if error.retryable:
            return ProviderFailure(
                ProviderFailureKind.TEMPORARY, "Google could not refresh access right now"
            )
        return ProviderFailure(
            ProviderFailureKind.AUTHENTICATION, "Google no longer accepts this account's access"
        )
    if isinstance(error, TransportError):
        return ProviderFailure(
            ProviderFailureKind.TEMPORARY, "Google could not be reached to refresh access"
        )
    status = _status_code(error)
    detail = str(error) or error.__class__.__name__
    if status == 401:
        kind = ProviderFailureKind.AUTHENTICATION
    elif status == 403 and _is_rate_limit_error(error):
        kind = ProviderFailureKind.RATE_LIMIT
    elif status == 403:
        kind = ProviderFailureKind.AUTHORIZATION
    elif status == 429:
        kind = ProviderFailureKind.RATE_LIMIT
    elif status is not None and status >= 500:
        kind = ProviderFailureKind.TEMPORARY
    else:
        kind = ProviderFailureKind.PERMANENT
    return ProviderFailure(kind, detail, _retry_after_seconds(error, now))


# Instances are read only for their status and start, so one page covers most series.
LIVE_OCCURRENCE_PAGE_SIZE = 250
# Instance listings run under the rule's write lock, so a long expansion is read only this far.
OCCURRENCE_PAGE_LIMIT = 20
# Only what translation reads. Guests and conferencing are never projected; they are read so a
# Source Change can be described (ADR 0017), and an omitted field would read as removed. The
# calendar's own attendee entry carries its Invitation Response (ADR 0018).
OCCURRENCE_EXCEPTION_FIELDS = (
    "items(id,etag,updated,status,start,end,summary,description,location,recurringEventId,"
    "originalStartTime,extendedProperties,htmlLink,attendees(email,self,responseStatus),"
    "attendeesOmitted,conferenceData(entryPoints(uri)),hangoutLink),nextPageToken"
)
# What deciding whether a rule projects an instance reads: its time and its own answer (ADR 0018).
LIVE_OCCURRENCE_FIELDS = "items(id,status,start,end,attendees(self,responseStatus)),nextPageToken"
# How far past the latest requested start a series listing reaches, for occurrences moved later.
OCCURRENCE_LISTING_MARGIN = timedelta(days=31)
# Answers meaning Google cannot expand this series, rather than that the request failed.
UNLISTABLE_SERIES_STATUSES = frozenset({400, 404, 410})


# Retries wait in-process while holding the rule lock, so a longer provider hint is bounded; the
# attempt then fails again and the rule's normal failure handling takes over.
MAX_RETRY_AFTER_SECONDS = 60


def _retry_after_seconds(error: Exception, now: datetime) -> int | None:
    """Read Google's Retry-After header, given either as seconds or as an HTTP date."""
    response = getattr(error, "resp", None)
    value = response.get("retry-after") if isinstance(response, Mapping) else None
    if not isinstance(value, str):
        return None
    if value.strip().isdigit():
        seconds = int(value.strip())
    else:
        try:
            moment = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        seconds = max(0, math.ceil((moment - now).total_seconds()))
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


def _status_code(error: Exception) -> int | None:
    response = getattr(error, "resp", None)
    status = getattr(response, "status", None)
    return int(status) if isinstance(status, int) else None


def _is_rate_limit_error(error: Exception) -> bool:
    content = getattr(error, "content", b"")
    if isinstance(content, bytes):
        try:
            payload = json.loads(content.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
    elif isinstance(content, str):
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return False
    else:
        return False
    reasons = {
        item.get("reason")
        for item in payload.get("error", {}).get("errors", [])
        if isinstance(item, dict)
    }
    return bool(
        reasons
        & {
            "rateLimitExceeded",
            "userRateLimitExceeded",
            "quotaExceeded",
        }
    )
