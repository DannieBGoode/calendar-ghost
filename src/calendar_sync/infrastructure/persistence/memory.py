from __future__ import annotations

from collections.abc import Collection, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import TracebackType
from typing import Self

from calendar_sync.application.ports import (
    AuditEntry,
    AuditRepository,
    CalendarNameRepository,
    ConnectedAccountRecords,
    ConnectedAccountState,
    DiscoveredCalendar,
    EventMappingRepository,
    ExceptionReplayRepository,
    OccurrenceMappingRepository,
    RulePreviewRepository,
    RulePreviewSummary,
    RuleRunOutcome,
    RuleRunOutcomeRepository,
    RunKind,
    SourceObservationRepository,
    SyncCursorRepository,
    SyncRuleRepository,
    UnitOfWork,
)
from calendar_sync.domain.changes import SourceObservation
from calendar_sync.domain.model import (
    AllDayRange,
    CalendarEndpoint,
    CalendarId,
    ConnectedAccountId,
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
    accounts: dict[ConnectedAccountId, ConnectedAccountState] = field(default_factory=dict)
    rules: dict[SyncRuleId, SyncRule] = field(default_factory=dict)
    mappings: dict[tuple[SyncRuleId, EventRef], EventMapping] = field(default_factory=dict)
    occurrences: dict[tuple[EventMappingId, OccurrenceStart], OccurrenceMapping] = field(
        default_factory=dict
    )
    pending_replays: set[EventMappingId] = field(default_factory=set)
    cursors: dict[SyncRuleId, str] = field(default_factory=dict)
    destination_cursors: dict[SyncRuleId, str] = field(default_factory=dict)
    audit: list[AuditEntry] = field(default_factory=list)
    outcomes: dict[tuple[SyncRuleId, RunKind], RuleRunOutcome] = field(default_factory=dict)
    previews: dict[SyncRuleId, RulePreviewSummary] = field(default_factory=dict)
    calendar_names: dict[CalendarEndpoint, str] = field(default_factory=dict)
    observations: dict[tuple[SyncRuleId, EventRef], tuple[SourceObservation, datetime]] = field(
        default_factory=dict
    )
    change_values_forgotten_before: datetime | None = None
    """Entries keep their changes in memory; this records the cutoff SQLite would apply."""


class InMemoryConnectedAccountRecords:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def state(self, account_id: ConnectedAccountId) -> ConnectedAccountState | None:
        return self._state.accounts.get(account_id)

    def delete_disconnected(self, account_id: ConnectedAccountId) -> bool:
        if self._state.accounts.get(account_id) is not ConnectedAccountState.DISCONNECTED:
            return False
        del self._state.accounts[account_id]
        self._state.calendar_names = {
            endpoint: name
            for endpoint, name in self._state.calendar_names.items()
            if endpoint.connected_account_id != account_id
        }
        return True


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
        self._state.pending_replays -= removed
        self._state.cursors.pop(rule_id, None)
        self._state.destination_cursors.pop(rule_id, None)
        self._state.outcomes = {
            key: outcome for key, outcome in self._state.outcomes.items() if key[0] != rule_id
        }
        self._state.previews.pop(rule_id, None)
        self._state.observations = {
            key: value for key, value in self._state.observations.items() if key[0] != rule_id
        }

    def purge(self, rule_id: SyncRuleId) -> None:
        self.remove(rule_id)
        self._state.audit = [entry for entry in self._state.audit if entry.rule_id != rule_id]

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
        self._state.pending_replays.discard(mapping.id)
        self._state.occurrences = {
            key: occurrence
            for key, occurrence in self._state.occurrences.items()
            if key[0] != mapping.id
        }

    def count_for_rule(self, rule_id: SyncRuleId) -> int:
        return sum(1 for key in self._state.mappings if key[0] == rule_id)


class InMemoryExceptionReplayRepository:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def pending(self, rule_id: SyncRuleId) -> tuple[EventMapping, ...]:
        return tuple(
            sorted(
                (
                    mapping
                    for key, mapping in self._state.mappings.items()
                    if key[0] == rule_id and mapping.id in self._state.pending_replays
                ),
                key=lambda mapping: mapping.id.value,
            )
        )

    def add(self, series_mapping_id: EventMappingId) -> None:
        # Mirror the SQLite foreign key to event_mappings.
        if not any(m.id == series_mapping_id for m in self._state.mappings.values()):
            raise KeyError(series_mapping_id)
        self._state.pending_replays.add(series_mapping_id)

    def remove(self, series_mapping_id: EventMappingId) -> None:
        self._state.pending_replays.discard(series_mapping_id)


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

    def forget_change_values(self, before: datetime) -> None:
        self._state.change_values_forgotten_before = before


class InMemorySourceObservationRepository:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def get(self, rule_id: SyncRuleId, source: EventRef) -> SourceObservation | None:
        found = self._state.observations.get((rule_id, source))
        return found[0] if found is not None else None

    def save(
        self,
        rule_id: SyncRuleId,
        source: EventRef,
        observation: SourceObservation,
        observed_at: datetime,
    ) -> None:
        self._state.observations[(rule_id, source)] = (observation, observed_at)

    def forget_stale(
        self, rule_id: SyncRuleId, source: CalendarEndpoint, ended_before: datetime
    ) -> None:
        self._state.observations = {
            (rule, reference): value
            for (rule, reference), value in self._state.observations.items()
            if rule != rule_id
            or (reference.calendar == source and not _ended(value[0], ended_before))
        }


def _ended(observation: SourceObservation, before: datetime) -> bool:
    if observation.recurrence:
        return False
    if isinstance(observation.time, AllDayRange):
        return observation.time.ends_before <= before.date()
    return observation.time.ends_at < before


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
        full_at = (
            outcome.completed_at
            if outcome.succeeded and outcome.full_run
            else previous.last_full_succeeded_at
            if previous
            else None
        )
        self._state.outcomes[(outcome.rule_id, outcome.kind)] = replace(
            outcome, last_succeeded_at=succeeded_at, last_full_succeeded_at=full_at
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


class InMemoryCalendarNameRepository:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def remember(
        self, account_id: ConnectedAccountId, calendars: Sequence[DiscoveredCalendar]
    ) -> None:
        if account_id not in self._state.accounts:
            return
        for calendar in calendars:
            endpoint = CalendarEndpoint(account_id, CalendarId(calendar.id))
            self._state.calendar_names[endpoint] = calendar.summary

    def names(self, endpoints: Collection[CalendarEndpoint]) -> dict[CalendarEndpoint, str]:
        return {
            endpoint: self._state.calendar_names[endpoint]
            for endpoint in endpoints
            if endpoint in self._state.calendar_names
        }


class InMemoryUnitOfWork:
    accounts: ConnectedAccountRecords
    rules: SyncRuleRepository
    mappings: EventMappingRepository
    occurrences: OccurrenceMappingRepository
    replays: ExceptionReplayRepository
    cursors: SyncCursorRepository
    destination_cursors: SyncCursorRepository
    audit: AuditRepository
    observations: SourceObservationRepository
    run_outcomes: RuleRunOutcomeRepository
    previews: RulePreviewRepository
    calendar_names: CalendarNameRepository

    def __init__(self, target: MemoryState) -> None:
        self._target = target
        self._working: MemoryState | None = None
        self._committed = False

    def __enter__(self) -> Self:
        self._working = deepcopy(self._target)
        self.accounts = InMemoryConnectedAccountRecords(self._working)
        self.rules = InMemorySyncRuleRepository(self._working)
        self.mappings = InMemoryEventMappingRepository(self._working)
        self.occurrences = InMemoryOccurrenceMappingRepository(self._working)
        self.replays = InMemoryExceptionReplayRepository(self._working)
        self.cursors = InMemorySyncCursorRepository(self._working.cursors)
        self.destination_cursors = InMemorySyncCursorRepository(self._working.destination_cursors)
        self.audit = InMemoryAuditRepository(self._working)
        self.observations = InMemorySourceObservationRepository(self._working)
        self.run_outcomes = InMemoryRuleRunOutcomeRepository(self._working)
        self.previews = InMemoryRulePreviewRepository(self._working)
        self.calendar_names = InMemoryCalendarNameRepository(self._working)
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
        self._target.accounts = self._working.accounts
        self._target.rules = self._working.rules
        self._target.mappings = self._working.mappings
        self._target.occurrences = self._working.occurrences
        self._target.pending_replays = self._working.pending_replays
        self._target.cursors = self._working.cursors
        self._target.destination_cursors = self._working.destination_cursors
        self._target.audit = self._working.audit
        self._target.outcomes = self._working.outcomes
        self._target.previews = self._working.previews
        self._target.calendar_names = self._working.calendar_names
        self._target.observations = self._working.observations
        self._target.change_values_forgotten_before = self._working.change_values_forgotten_before
        self._committed = True


class InMemoryUnitOfWorkFactory:
    def __init__(self, state: MemoryState | None = None) -> None:
        self.state = state or MemoryState()

    def __call__(self) -> UnitOfWork:
        return InMemoryUnitOfWork(self.state)
