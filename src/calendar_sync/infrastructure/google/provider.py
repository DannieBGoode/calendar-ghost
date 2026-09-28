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
    SyncRuleId,
)
from calendar_sync.infrastructure.google.translation import (
    OPERATION_PROPERTY,
    RULE_PROPERTY,
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
