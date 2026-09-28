from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from types import TracebackType
from typing import Self

from calendar_sync.application.ports import (
    AuditEntry,
    AuditRepository,
    EventMappingRepository,
    OccurrenceMappingRepository,
    RulePreviewRepository,
    RulePreviewSummary,
    RuleRunOutcome,
    RuleRunOutcomeRepository,
    RunKind,
    SyncCursorRepository,
    SyncRuleRepository,
    UnitOfWork,
)
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


@dataclass(slots=True)
class MemoryState:
    rules: dict[SyncRuleId, SyncRule] = field(default_factory=dict)
    mappings: dict[tuple[SyncRuleId, EventRef], EventMapping] = field(default_factory=dict)
    occurrences: dict[tuple[EventMappingId, OccurrenceStart], OccurrenceMapping] = field(
        default_factory=dict
    )
    cursors: dict[SyncRuleId, str] = field(default_factory=dict)
    destination_cursors: dict[SyncRuleId, str] = field(default_factory=dict)
    audit: list[AuditEntry] = field(default_factory=list)
    outcomes: dict[tuple[SyncRuleId, RunKind], RuleRunOutcome] = field(default_factory=dict)
    previews: dict[SyncRuleId, RulePreviewSummary] = field(default_factory=dict)


class InMemorySyncRuleRepository:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def get(self, rule_id: SyncRuleId) -> SyncRule | None:
        return self._state.rules.get(rule_id)

    def list(self) -> tuple[SyncRule, ...]:
        return tuple(self._state.rules.values())

    def add(self, rule: SyncRule) -> None:
        if rule.id in self._state.rules:
            raise KeyError(rule.id)
        self._state.rules[rule.id] = rule

    def save(self, rule: SyncRule) -> None:
        if rule.id not in self._state.rules:
            raise KeyError(rule.id)
        self._state.rules[rule.id] = rule

    def remove(self, rule_id: SyncRuleId) -> None:
        self._state.rules.pop(rule_id, None)
        removed = {m.id for key, m in self._state.mappings.items() if key[0] == rule_id}
        self._state.occurrences = {
            key: occurrence
            for key, occurrence in self._state.occurrences.items()
            if key[0] not in removed
        }
        self._state.mappings = {
            key: mapping for key, mapping in self._state.mappings.items() if key[0] != rule_id
        }
        self._state.cursors.pop(rule_id, None)
        self._state.destination_cursors.pop(rule_id, None)
        self._state.outcomes = {
            key: outcome for key, outcome in self._state.outcomes.items() if key[0] != rule_id
        }

    def relationship_exists(self, source: CalendarEndpoint, destination: CalendarEndpoint) -> bool:
        return any(
            rule.source == source and rule.destination == destination
            for rule in self._state.rules.values()
        )


class InMemoryEventMappingRepository:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def for_source(self, rule_id: SyncRuleId, source: EventRef) -> EventMapping | None:
        return self._state.mappings.get((rule_id, source))

    def for_destination(self, rule_id: SyncRuleId, destination: EventRef) -> EventMapping | None:
        return next(
            (
                mapping
                for mapping in self._state.mappings.values()
                if mapping.rule_id == rule_id and mapping.destination == destination
            ),
            None,
        )

    def for_rule(self, rule_id: SyncRuleId) -> tuple[EventMapping, ...]:
        return tuple(
            mapping for mapping in self._state.mappings.values() if mapping.rule_id == rule_id
        )

    def save(self, mapping: EventMapping) -> None:
        for existing in self._state.mappings.values():
            if (
                existing.rule_id == mapping.rule_id
                and existing.destination == mapping.destination
                and existing.source != mapping.source
            ):
                raise ValueError("managed destination is already mapped to another source")
        self._state.mappings[(mapping.rule_id, mapping.source)] = mapping

    def delete(self, mapping: EventMapping) -> None:
        self._state.mappings.pop((mapping.rule_id, mapping.source), None)
        self._state.occurrences = {
            key: occurrence
            for key, occurrence in self._state.occurrences.items()
            if key[0] != mapping.id
        }

    def count_for_rule(self, rule_id: SyncRuleId) -> int:
        return sum(1 for key in self._state.mappings if key[0] == rule_id)


class InMemoryOccurrenceMappingRepository:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def for_series(self, series_mapping_id: EventMappingId) -> tuple[OccurrenceMapping, ...]:
        return tuple(
            mapping
            for key, mapping in self._state.occurrences.items()
            if key[0] == series_mapping_id
        )

    def get(
        self, series_mapping_id: EventMappingId, original_start: OccurrenceStart
    ) -> OccurrenceMapping | None:
        return self._state.occurrences.get((series_mapping_id, original_start))

    def save(self, mapping: OccurrenceMapping) -> None:
        # Mirror the SQLite foreign key to event_mappings.
        if not any(m.id == mapping.series_mapping_id for m in self._state.mappings.values()):
            raise KeyError(mapping.series_mapping_id)
        self._state.occurrences[(mapping.series_mapping_id, mapping.original_start)] = mapping

    def delete(self, mapping: OccurrenceMapping) -> None:
        self._state.occurrences.pop((mapping.series_mapping_id, mapping.original_start), None)


class InMemorySyncCursorRepository:
    def __init__(self, cursors: dict[SyncRuleId, str]) -> None:
        self._cursors = cursors

    def get(self, rule_id: SyncRuleId) -> str | None:
        return self._cursors.get(rule_id)

    def save(self, rule_id: SyncRuleId, cursor: str) -> None:
        self._cursors[rule_id] = cursor


class InMemoryAuditRepository:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def append(self, entry: AuditEntry) -> None:
        self._state.audit.append(entry)


class InMemoryRuleRunOutcomeRepository:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def record(self, outcome: RuleRunOutcome) -> None:
        previous = self._state.outcomes.get((outcome.rule_id, outcome.kind))
        succeeded_at = (
            outcome.completed_at
            if outcome.succeeded
            else previous.last_succeeded_at
            if previous
            else None
        )
        self._state.outcomes[(outcome.rule_id, outcome.kind)] = replace(
            outcome, last_succeeded_at=succeeded_at
        )

    def latest(self, rule_id: SyncRuleId, kind: RunKind) -> RuleRunOutcome | None:
        return self._state.outcomes.get((rule_id, kind))


class InMemoryRulePreviewRepository:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def record(self, summary: RulePreviewSummary) -> None:
        self._state.previews[summary.rule_id] = summary

    def latest(self, rule_id: SyncRuleId) -> RulePreviewSummary | None:
        return self._state.previews.get(rule_id)


class InMemoryUnitOfWork:
    rules: SyncRuleRepository
    mappings: EventMappingRepository
    occurrences: OccurrenceMappingRepository
    cursors: SyncCursorRepository
    destination_cursors: SyncCursorRepository
    audit: AuditRepository
    run_outcomes: RuleRunOutcomeRepository
    previews: RulePreviewRepository

    def __init__(self, target: MemoryState) -> None:
        self._target = target
        self._working: MemoryState | None = None
        self._committed = False

    def __enter__(self) -> Self:
        self._working = deepcopy(self._target)
        self.rules = InMemorySyncRuleRepository(self._working)
        self.mappings = InMemoryEventMappingRepository(self._working)
        self.occurrences = InMemoryOccurrenceMappingRepository(self._working)
        self.cursors = InMemorySyncCursorRepository(self._working.cursors)
        self.destination_cursors = InMemorySyncCursorRepository(self._working.destination_cursors)
        self.audit = InMemoryAuditRepository(self._working)
        self.run_outcomes = InMemoryRuleRunOutcomeRepository(self._working)
        self.previews = InMemoryRulePreviewRepository(self._working)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return None

    def commit(self) -> None:
        assert self._working is not None
        self._target.rules = self._working.rules
        self._target.mappings = self._working.mappings
        self._target.occurrences = self._working.occurrences
        self._target.cursors = self._working.cursors
        self._target.destination_cursors = self._working.destination_cursors
        self._target.audit = self._working.audit
        self._target.outcomes = self._working.outcomes
        self._target.previews = self._working.previews
        self._committed = True


class InMemoryUnitOfWorkFactory:
    def __init__(self, state: MemoryState | None = None) -> None:
        self.state = state or MemoryState()

    def __call__(self) -> UnitOfWork:
        return InMemoryUnitOfWork(self.state)
