from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self

from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarEvent,
    EventMapping,
    EventProjection,
    EventRef,
    SyncRule,
    SyncRuleId,
)


@dataclass(frozen=True, slots=True)
class ProviderChangeSet:
    events: tuple[CalendarEvent, ...]
    next_cursor: str


@dataclass(frozen=True, slots=True)
class CreatedProjection:
    destination_event: CalendarEvent


class CalendarProvider(Protocol):
    def changes(
        self,
        source: CalendarEndpoint,
        cursor: str | None,
        not_ended_before: datetime,
    ) -> ProviderChangeSet: ...

    def get_event(self, reference: EventRef) -> CalendarEvent | None: ...

    def create_projection(
        self,
        destination: CalendarEndpoint,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CreatedProjection: ...

    def update_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        projection: EventProjection,
        operation_key: str,
    ) -> CalendarEvent: ...

    def delete_projection(
        self,
        destination: EventRef,
        source: EventRef,
        rule_id: SyncRuleId,
        operation_key: str,
    ) -> None: ...

    def managed_events(
        self, destination: CalendarEndpoint, rule_id: SyncRuleId
    ) -> Sequence[CalendarEvent]: ...


class SyncRuleRepository(Protocol):
    def get(self, rule_id: SyncRuleId) -> SyncRule | None: ...

    def list(self) -> Sequence[SyncRule]: ...

    def add(self, rule: SyncRule) -> None: ...

    def save(self, rule: SyncRule) -> None: ...

    def relationship_exists(
        self, source: CalendarEndpoint, destination: CalendarEndpoint
    ) -> bool: ...


class EventMappingRepository(Protocol):
    def for_source(self, rule_id: SyncRuleId, source: EventRef) -> EventMapping | None: ...

    def for_destination(
        self, rule_id: SyncRuleId, destination: EventRef
    ) -> EventMapping | None: ...

    def for_rule(self, rule_id: SyncRuleId) -> Sequence[EventMapping]: ...

    def save(self, mapping: EventMapping) -> None: ...

    def delete(self, mapping: EventMapping) -> None: ...


class SyncCursorRepository(Protocol):
    def get(self, rule_id: SyncRuleId) -> str | None: ...

    def save(self, rule_id: SyncRuleId, cursor: str) -> None: ...


@dataclass(frozen=True, slots=True)
class AuditEntry:
    occurred_at: datetime
    rule_id: SyncRuleId
    action: str
    outcome: str
    source_event_id: str | None = None
    destination_event_id: str | None = None
    detail: str = ""
    reason: str | None = None
    run_id: str | None = None


class AuditRepository(Protocol):
    def append(self, entry: AuditEntry) -> None: ...


class UnitOfWork(Protocol):
    rules: SyncRuleRepository
    mappings: EventMappingRepository
    cursors: SyncCursorRepository
    destination_cursors: SyncCursorRepository
    audit: AuditRepository

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def commit(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new(self) -> str: ...
