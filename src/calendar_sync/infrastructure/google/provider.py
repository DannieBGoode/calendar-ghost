from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from calendar_sync.application.errors import ProviderFailure, ProviderFailureKind
from calendar_sync.application.ports import CreatedProjection, ProviderChangeSet
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
)
from calendar_sync.infrastructure.google.translation import (
    OPERATION_PROPERTY,
    RULE_PROPERTY,
    format_occurrence_start,
    projection_payload,
    to_domain_event,
)

GoogleServiceFactory = Callable[[ConnectedAccountId], Any]


class GoogleCalendarProvider:
    """Google Calendar implementation of the application CalendarProvider port."""

    def __init__(self, service_for: GoogleServiceFactory) -> None:
        self._service_for = service_for

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
                response = events_api.list(**parameters).execute()
                items.extend(to_domain_event(item, source) for item in response.get("items", []))
                page_token = response.get("nextPageToken")
                if not page_token:
                    next_cursor = response.get("nextSyncToken")
                    if not isinstance(next_cursor, str):
                        raise ProviderFailure(
                            ProviderFailureKind.PERMANENT,
                            "Google response did not include a synchronization token",
                        )
                    return ProviderChangeSet(tuple(items), next_cursor)
                parameters["pageToken"] = page_token
        except ProviderFailure:
            raise
        except Exception as error:
            if cursor is not None and _status_code(error) == 410:
                return self.changes(source, None, not_ended_before)
            raise _provider_failure(error) from error

    def get_event(self, reference: EventRef) -> CalendarEvent | None:
        try:
            payload = (
                self._service_for(reference.calendar.connected_account_id)
                .events()
                .get(
                    calendarId=reference.calendar.calendar_id.value,
                    eventId=reference.event_id.value,
                )
                .execute()
            )
            return to_domain_event(payload, reference.calendar)
        except Exception as error:
            if _status_code(error) == 404:
                return None
            raise _provider_failure(error) from error

    def create_projection(
        self,
        destination: CalendarEndpoint,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CreatedProjection:
        service = self._service_for(destination.connected_account_id)
        try:
            existing = (
                service.events()
                .list(
                    calendarId=destination.calendar_id.value,
                    privateExtendedProperty=f"{OPERATION_PROPERTY}={operation_key}",
                    showDeleted=False,
                    maxResults=2,
                )
                .execute()
                .get("items", [])
            )
            if existing:
                return CreatedProjection(to_domain_event(existing[0], destination))
            payload = (
                service.events()
                .insert(
                    calendarId=destination.calendar_id.value,
                    body=projection_payload(projection, rule_id, source, operation_key),
                    sendUpdates="none",
                )
                .execute()
            )
            return CreatedProjection(to_domain_event(payload, destination))
        except Exception as error:
            raise _provider_failure(error) from error

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
            )
        try:
            payload = (
                self._service_for(destination.calendar.connected_account_id)
                .events()
                .update(
                    calendarId=destination.calendar.calendar_id.value,
                    eventId=destination.event_id.value,
                    body=projection_payload(projection, rule_id, source, operation_key),
                    sendUpdates="none",
                )
                .execute()
            )
            return to_domain_event(payload, destination.calendar)
        except Exception as error:
            raise _provider_failure(error) from error

    def delete_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None:
        existing = self.get_event(destination)
        if existing is None or existing.status is EventStatus.CANCELLED:
            return
        if (
            existing.managed_origin is None
            or existing.managed_origin.rule_id != rule_id
            or existing.managed_origin.source != source
        ):
            raise ProviderFailure(
                ProviderFailureKind.PERMANENT,
                "Google event does not carry compatible ownership metadata",
            )
        try:
            (
                self._service_for(destination.calendar.connected_account_id)
                .events()
                .delete(
                    calendarId=destination.calendar.calendar_id.value,
                    eventId=destination.event_id.value,
                    sendUpdates="none",
                )
                .execute()
            )
        except Exception as error:
            if _status_code(error) not in {404, 410}:
                raise _provider_failure(error) from error

    def managed_events(
        self, destination: CalendarEndpoint, rule_id: SyncRuleId
    ) -> Sequence[CalendarEvent]:
        try:
            events_api = self._service_for(destination.connected_account_id).events()
            parameters: dict[str, Any] = {
                "calendarId": destination.calendar_id.value,
                "privateExtendedProperty": f"{RULE_PROPERTY}={rule_id.value}",
                "showDeleted": False,
                "singleEvents": False,
                "maxResults": 2500,
            }
            items: list[CalendarEvent] = []
            while True:
                response = events_api.list(**parameters).execute()
                items.extend(
                    to_domain_event(item, destination) for item in response.get("items", [])
                )
                page_token = response.get("nextPageToken")
                if not page_token:
                    return tuple(items)
                parameters["pageToken"] = page_token
        except Exception as error:
            raise _provider_failure(error) from error

    def get_occurrence(
        self, series: EventRef, original_start: OccurrenceStart
    ) -> CalendarEvent | None:
        try:
            response = (
                self._service_for(series.calendar.connected_account_id)
                .events()
                .instances(
                    calendarId=series.calendar.calendar_id.value,
                    eventId=series.event_id.value,
                    originalStart=format_occurrence_start(original_start),
                    showDeleted=True,
                    maxResults=1,
                )
                .execute()
            )
        except Exception as error:
            # A missing series proves nothing about its occurrences; only an answered lookup may
            # report absence, because absence can authorize cancelling a destination occurrence.
            if _status_code(error) in {404, 410}:
                raise ProviderFailure(
                    ProviderFailureKind.TEMPORARY,
                    "Google series could not be read while resolving an occurrence",
                ) from error
            raise _provider_failure(error) from error
        for item in response.get("items", []):
            candidate = to_domain_event(item, series.calendar)
            # Never trust a positional result: the instance must name the requested start.
            if (
                candidate.occurrence is not None
                and candidate.occurrence.series_event_id == series.event_id
                and candidate.occurrence.original_start == original_start
            ):
                return candidate
        return None

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
                ProviderFailureKind.PERMANENT, "Google occurrence could not be resolved"
            )
        body = projection_payload(
            projection, rule_id, source_series, operation_key, original_start=original_start
        )
        body["status"] = "confirmed"
        try:
            payload = (
                self._service_for(destination_series.calendar.connected_account_id)
                .events()
                .patch(
                    calendarId=destination_series.calendar.calendar_id.value,
                    eventId=instance.reference.event_id.value,
                    body=body,
                    sendUpdates="none",
                )
                .execute()
            )
            return to_domain_event(payload, destination_series.calendar)
        except Exception as error:
            raise _provider_failure(error) from error

    def cancel_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None:
        instance = self._owned_occurrence(
            destination_series, original_start, source_series, rule_id
        )
        if instance is None or instance.status is EventStatus.CANCELLED:
            return
        try:
            (
                self._service_for(destination_series.calendar.connected_account_id)
                .events()
                .delete(
                    calendarId=destination_series.calendar.calendar_id.value,
                    eventId=instance.reference.event_id.value,
                    sendUpdates="none",
                )
                .execute()
            )
        except Exception as error:
            if _status_code(error) not in {404, 410}:
                raise _provider_failure(error) from error

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
            )
        return instance


def _owned(origin: ManagedOrigin | None, rule_id: SyncRuleId, source: EventRef) -> bool:
    return origin is not None and origin.rule_id == rule_id and origin.source == source


def _provider_failure(error: Exception) -> ProviderFailure:
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
    return ProviderFailure(kind, detail)


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
