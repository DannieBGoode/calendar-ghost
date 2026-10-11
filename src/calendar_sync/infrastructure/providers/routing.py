"""Sends each calendar request to the adapter of the provider its Connected Account belongs to.

A rule's source and destination may belong to different providers, so every request is routed
by the account its endpoint names (ADR 0022). An account's provider never changes, so the answer
is kept after the first lookup; an account not found is looked up again next time.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from threading import Lock
from typing import Protocol

from calendar_sync.application.errors import (
    AuthorizationNotConfigured,
    ConnectedAccountNotFound,
    ProviderFailure,
    ProviderFailureKind,
)
from calendar_sync.application.ports import (
    AccountAccess,
    AccountCalendars,
    CalendarProvider,
    CreatedProjection,
    DiscoveredCalendar,
    ProviderChangeSet,
)
from calendar_sync.application.provider_descriptors import ProviderDirectory
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarEvent,
    ConnectedAccountId,
    EventProjection,
    EventRef,
    OccurrenceStart,
    SyncRuleId,
    TransformationPolicy,
)


class ProviderKinds(Protocol):
    def provider_of(self, account_id: ConnectedAccountId) -> ProviderKind | None: ...


class _KnownKinds:
    def __init__(self, kinds: ProviderKinds) -> None:
        self._kinds = kinds
        self._known: dict[ConnectedAccountId, ProviderKind] = {}
        # Runs for different rules route on different worker threads.
        self._guard = Lock()

    def of(self, account_id: ConnectedAccountId) -> ProviderKind | None:
        with self._guard:
            known = self._known.get(account_id)
        if known is not None:
            return known
        found = self._kinds.provider_of(account_id)
        if found is not None:
            with self._guard:
                self._known[account_id] = found
        return found


def _not_configured(label: str | None) -> str:
    return f"{label or 'The calendar provider'} is not configured on this installation"


class RoutingCalendarProvider:
    """Every calendar role, answered by the adapter of each request's Connected Account."""

    def __init__(
        self,
        kinds: ProviderKinds,
        adapters: Mapping[ProviderKind, CalendarProvider],
        labels: Mapping[ProviderKind, str] | None = None,
    ) -> None:
        self._kinds = _KnownKinds(kinds)
        self._adapters = dict(adapters)
        # How messages name each provider, even one this installation has not configured.
        self._labels = dict(labels or {})

    @classmethod
    def of(cls, kinds: ProviderKinds, providers: ProviderDirectory) -> RoutingCalendarProvider:
        """A router to the calendar adapter each provider's descriptor offers."""
        return cls(
            kinds,
            {d.kind: d.provider for d in providers.descriptors if d.provider is not None},
            {guide.kind: guide.calendar_name for guide in providers.guides},
        )

    def _for(self, calendar: CalendarEndpoint) -> CalendarProvider:
        account = calendar.connected_account_id
        kind = self._kinds.of(account)
        if kind is None:
            # As an adapter reports an account it cannot find: the rule stops.
            raise ProviderFailure(
                ProviderFailureKind.PERMANENT,
                f"connected account {account.value} does not exist",
                account_id=account,
            )
        adapter = self._adapters.get(kind)
        if adapter is None:
            label = self._labels.get(kind)
            raise ProviderFailure(
                ProviderFailureKind.PERMANENT,
                _not_configured(label),
                account_id=account,
                provider=kind,
                provider_label=label,
            )
        return adapter

    def changes(
        self, source: CalendarEndpoint, cursor: str | None, not_ended_before: datetime
    ) -> ProviderChangeSet:
        return self._for(source).changes(source, cursor, not_ended_before)

    def get_event(self, reference: EventRef) -> CalendarEvent | None:
        return self._for(reference.calendar).get_event(reference)

    def find_projection(
        self, destination: CalendarEndpoint, operation_key: str
    ) -> CalendarEvent | None:
        return self._for(destination).find_projection(destination, operation_key)

    def list_events(
        self, calendar: CalendarEndpoint, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        return self._for(calendar).list_events(calendar, not_ended_before)

    def managed_events(
        self, destination: CalendarEndpoint, rule_id: SyncRuleId, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        return self._for(destination).managed_events(destination, rule_id, not_ended_before)

    def get_occurrence(
        self, series: EventRef, original_start: OccurrenceStart
    ) -> CalendarEvent | None:
        return self._for(series.calendar).get_occurrence(series, original_start)

    def list_occurrences(
        self, series: EventRef, original_starts: Collection[OccurrenceStart]
    ) -> Mapping[OccurrenceStart, CalendarEvent]:
        return self._for(series.calendar).list_occurrences(series, original_starts)

    def has_live_occurrences(self, series: EventRef, policy: TransformationPolicy) -> bool:
        return self._for(series.calendar).has_live_occurrences(series, policy)

    def occurrence_exceptions(
        self, series: EventRef, not_ended_before: datetime
    ) -> Sequence[CalendarEvent]:
        return self._for(series.calendar).occurrence_exceptions(series, not_ended_before)

    def create_projection(
        self,
        destination: CalendarEndpoint,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CreatedProjection:
        return self._for(destination).create_projection(
            destination, source, rule_id, projection, operation_key
        )

    def update_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent:
        return self._for(destination.calendar).update_projection(
            destination, source, rule_id, projection, operation_key
        )

    def delete_projection(
        self, destination: EventRef, source: EventRef, rule_id: SyncRuleId, operation_key: str
    ) -> None:
        self._for(destination.calendar).delete_projection(
            destination, source, rule_id, operation_key
        )

    def write_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent:
        return self._for(destination_series.calendar).write_occurrence(
            destination_series, original_start, source_series, rule_id, projection, operation_key
        )

    def cancel_occurrence(
        self,
        destination_series: EventRef,
        original_start: OccurrenceStart,
        source_series: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None:
        self._for(destination_series.calendar).cancel_occurrence(
            destination_series, original_start, source_series, rule_id, operation_key
        )


class RoutingAccountCalendars:
    """Calendar discovery and access checks, answered by each account's provider."""

    def __init__(
        self,
        kinds: ProviderKinds,
        adapters: Mapping[ProviderKind, AccountCalendars],
        labels: Mapping[ProviderKind, str] | None = None,
    ) -> None:
        self._kinds = _KnownKinds(kinds)
        self._adapters = dict(adapters)
        self._labels = dict(labels or {})

    @classmethod
    def of(cls, kinds: ProviderKinds, providers: ProviderDirectory) -> RoutingAccountCalendars:
        """A router to the calendar discovery each provider's descriptor offers."""
        return cls(
            kinds,
            {d.kind: d.calendars for d in providers.descriptors if d.calendars is not None},
            {guide.kind: guide.calendar_name for guide in providers.guides},
        )

    def _for(self, account_id: ConnectedAccountId) -> AccountCalendars:
        kind = self._kinds.of(account_id)
        if kind is None:
            raise ConnectedAccountNotFound(f"connected account {account_id.value} does not exist")
        adapter = self._adapters.get(kind)
        if adapter is None:
            raise AuthorizationNotConfigured(_not_configured(self._labels.get(kind)))
        return adapter

    def calendars(self, account_id: ConnectedAccountId) -> Sequence[DiscoveredCalendar]:
        return self._for(account_id).calendars(account_id)

    def verify_access(self, account_id: ConnectedAccountId) -> AccountAccess:
        return self._for(account_id).verify_access(account_id)
