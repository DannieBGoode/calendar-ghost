"""Audit Entries: what a run or rule change did, as Activity reads it (ADR 0014)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from calendar_sync.domain.changes import SourceChange
from calendar_sync.domain.model import (
    CalendarEvent,
    EventStatus,
    EventTime,
    SyncAction,
    SyncReason,
    SyncRuleId,
)


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    """What Activity names an entry's source event by, as the run saw it (ADR 0014)."""

    title: str
    time: EventTime | None = None
    recurring: bool = False
    cancelled: bool = False

    @classmethod
    def of(cls, event: CalendarEvent) -> RecordedEvent:
        return cls(
            title=event.title,
            time=event.time,
            recurring=event.recurrence is not None or event.occurrence is not None,
            cancelled=event.status is EventStatus.CANCELLED,
        )


class AuditAction(StrEnum):
    """What an Audit Entry records; the stored values are a compatibility surface."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    IGNORE = "ignore"
    CONFLICT = "conflict"
    POLICY_CHANGED = "policy_changed"
    REMOVE_PROJECTION = "remove_projection"
    DETACH_PROJECTION = "detach_projection"
    REMOVAL_CONFLICT = "removal_conflict"
    RULE_REMOVED = "rule_removed"

    @classmethod
    def of(cls, action: SyncAction) -> AuditAction:
        return cls(action.value)


class AuditOutcome(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"

    @classmethod
    def of(cls, action: SyncAction) -> AuditOutcome:
        if action is SyncAction.IGNORE:
            return cls.SKIPPED
        if action is SyncAction.CONFLICT:
            return cls.BLOCKED
        return cls.COMPLETED


@dataclass(frozen=True, slots=True)
class AuditEntry:
    occurred_at: datetime
    rule_id: SyncRuleId
    action: AuditAction
    outcome: AuditOutcome
    source_event_id: str | None = None
    destination_event_id: str | None = None
    detail: str = ""
    reason: SyncReason | None = None
    run_id: str | None = None
    event: RecordedEvent | None = None
    """The source event's title and time, as ADR 0014 records them."""
    change: SourceChange | None = None
    """What the source event's new revision changed since the rule last observed it (ADR 0017)."""
