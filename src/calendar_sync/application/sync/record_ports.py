"""Synchronization rule, mapping, cursor, audit, and run record ports."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from calendar_sync.application.sync.run_ports import ProviderCallCounts
from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.audit import AuditEntry, RecordedDecision
from calendar_sync.domain.changes import SourceObservation
from calendar_sync.domain.model import (
    CalendarEndpoint,
    EventMapping,
    EventMappingId,
    EventRef,
    OccurrenceMapping,
    OccurrenceStart,
    SyncRule,
    SyncRuleId,
)
from calendar_sync.domain.plan_hold import RuleStanding
from calendar_sync.domain.runs import RuleRunOutcome, RunKind


class SyncRuleRepository(Protocol):
    def get(self, rule_id: SyncRuleId) -> SyncRule | None: ...

    def list(self) -> Sequence[SyncRule]: ...

    def standings(self) -> Sequence[RuleStanding]:
        """Counted, reserved, and held rules, ranked by keep choice, creation order, and ID."""
        ...

    def keep(self, chosen: Collection[SyncRuleId]) -> None:
        """Replace this User's whole kept set; foreign IDs never change their owner's rules."""
        ...

    def add(self, rule: SyncRule) -> None: ...

    def save(self, rule: SyncRule) -> None: ...

    def relationship_exists(
        self, source: CalendarEndpoint, destination: CalendarEndpoint
    ) -> bool: ...

    def remove(self, rule_id: SyncRuleId) -> None:
        """Delete the rule with its mappings, cursors, and outcomes; resolve its incidents."""

    def purge(self, rule_id: SyncRuleId) -> None:
        """Delete the rule like `remove`, and its audit entries and incidents with it."""

    def inherit_place(self, rule: SyncRuleId, of: SyncRuleId) -> None:
        """Give `rule` the creation order and keep mark of `of`; both are this User's.
        Called only in the transaction that moves a Rule Replacement's place."""


class EventMappingRepository(Protocol):
    def for_source(self, rule_id: SyncRuleId, source: EventRef) -> EventMapping | None: ...

    def for_destination(
        self, rule_id: SyncRuleId, destination: EventRef
    ) -> EventMapping | None: ...

    def for_rule(self, rule_id: SyncRuleId) -> Sequence[EventMapping]: ...

    def lone_occurrences(self, rule_id: SyncRuleId, series: EventRef) -> Sequence[EventMapping]:
        """Mappings of occurrences of `series` projected on their own (ADR 0011)."""
        ...

    def save(self, mapping: EventMapping) -> None: ...

    def delete(self, mapping: EventMapping) -> None: ...

    def count_for_rule(self, rule_id: SyncRuleId) -> int: ...


class OccurrenceMappingRepository(Protocol):
    def for_series(self, series_mapping_id: EventMappingId) -> Sequence[OccurrenceMapping]: ...

    def get(
        self, series_mapping_id: EventMappingId, original_start: OccurrenceStart
    ) -> OccurrenceMapping | None: ...

    def save(self, mapping: OccurrenceMapping) -> None: ...

    def delete(self, mapping: OccurrenceMapping) -> None: ...


class ExceptionReplayRepository(Protocol):
    """Series projections whose source exceptions have not all been applied yet."""

    def pending(self, rule_id: SyncRuleId) -> Sequence[EventMapping]: ...

    def add(self, series_mapping_id: EventMappingId) -> None: ...

    def remove(self, series_mapping_id: EventMappingId) -> None: ...


class SyncCursorRepository(Protocol):
    def get(self, rule_id: SyncRuleId) -> str | None: ...

    def save(self, rule_id: SyncRuleId, cursor: str) -> None: ...


class AuditRepository(Protocol):
    def append(self, entry: AuditEntry) -> None: ...

    def latest_for(self, rule_id: SyncRuleId, source_event_id: str) -> RecordedDecision | None:
        """The decision of the latest entry, by id, for this rule and source event."""
        ...

    def forget_change_values(self, before: datetime) -> None:
        """Discard the values of every Source Change recorded before `before`.

        Every rule's, including paused and removed rules'. The changed fields and titles stay, so
        Activity still says what changed.
        """
        ...


class SourceObservationRepository(Protocol):
    """The tracked details of each source event a rule last observed (ADR 0017)."""

    def get(self, rule_id: SyncRuleId, source: EventRef) -> SourceObservation | None: ...

    def save(
        self,
        rule_id: SyncRuleId,
        source: EventRef,
        observation: SourceObservation,
        observed_at: datetime,
    ) -> None: ...

    def forget_stale(
        self, rule_id: SyncRuleId, source: CalendarEndpoint, ended_before: datetime
    ) -> None:
        """Forget single events that ended before `ended_before`, and other calendars' events."""
        ...


class RuleRunOutcomeRepository(Protocol):
    def record(self, outcome: RuleRunOutcome) -> None: ...

    def latest(self, rule_id: SyncRuleId, kind: RunKind) -> RuleRunOutcome | None: ...


@dataclass(frozen=True, slots=True)
class RulePreviewSummary:
    """Counts from the latest Rule Preview, kept so enabling can restate them; never content."""

    rule_id: SyncRuleId
    completed_at: datetime
    eligible_events: int
    excluded_events: int
    recurring_series: int = 0
    occurrence_changes: int = 0


class RulePreviewRepository(Protocol):
    def record(self, summary: RulePreviewSummary) -> None: ...

    def latest(self, rule_id: SyncRuleId) -> RulePreviewSummary | None: ...


class ProviderCallRepository(Protocol):
    """How many calls a User's runs made to each provider, per UTC day (ADR 0030)."""

    def add(self, day: date, provider: ProviderKind, counts: ProviderCallCounts) -> None:
        """Add one run's calls to the User's counts for that provider and day."""
        ...
