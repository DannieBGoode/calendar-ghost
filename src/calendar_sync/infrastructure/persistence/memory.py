from __future__ import annotations

from collections.abc import Collection, Iterator, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, fields, replace
from datetime import date, datetime
from types import TracebackType
from typing import Self

from calendar_sync.application.causes import WITHOUT_CAUSE
from calendar_sync.application.errors import DuplicateDirectionalRelationship
from calendar_sync.application.ports import (
    AccountStanding,
    AuditEntry,
    AuditRepository,
    CalendarNameRepository,
    CauseSighting,
    ConnectedAccountRecords,
    ConnectedAccountState,
    DiscoveredCalendar,
    EventMappingRepository,
    ExceptionReplayRepository,
    InstallationUnitOfWork,
    OccurrenceMappingRepository,
    OperationsOverview,
    ProviderCallCounts,
    ProviderCallRepository,
    ProviderCallUse,
    RecordedRule,
    ResourceUse,
    RulePreviewRepository,
    RulePreviewSummary,
    RuleRunOutcome,
    RuleRunOutcomeRepository,
    RunKind,
    ScheduledRule,
    SourceObservationRepository,
    StatusRecords,
    SyncCursorRepository,
    SyncRuleRepository,
    UnitOfWork,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.access import UserId
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
    OccurrenceMappingId,
    OccurrenceStart,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
)


@dataclass(slots=True)
class MemoryState:
    accounts: dict[ConnectedAccountId, ConnectedAccountState] = field(default_factory=dict)
    lapsed: dict[ConnectedAccountId, datetime] = field(default_factory=dict)
    authorized_at: dict[ConnectedAccountId, datetime] = field(default_factory=dict)
    """When each account was last authorized; one missing was authorized before any request."""
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
    provider_calls: dict[tuple[ProviderKind, date], ProviderCallCounts] = field(
        default_factory=dict
    )


def _require_rule(state: MemoryState, rule_id: SyncRuleId) -> None:
    # Mirror SQLite's foreign keys to sync_rules.
    if rule_id not in state.rules:
        raise KeyError(rule_id)


def _duplicate_relationship() -> DuplicateDirectionalRelationship:
    return DuplicateDirectionalRelationship("a rule already exists for this source and destination")


class InMemoryConnectedAccountRecords:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def state(self, account_id: ConnectedAccountId) -> ConnectedAccountState | None:
        return self._state.accounts.get(account_id)

    def lapse(self, account_id: ConnectedAccountId, *, attempted_at: datetime) -> bool:
        if self._state.accounts.get(account_id) is not ConnectedAccountState.CONNECTED:
            return False
        authorized = self._state.authorized_at.get(account_id)
        if authorized is not None and authorized > attempted_at:
            return False
        latest = self._state.lapsed.get(account_id)
        self._state.lapsed[account_id] = max(latest, attempted_at) if latest else attempted_at
        return True

    def clear_lapse(self, account_id: ConnectedAccountId, *, requested_before: datetime) -> bool:
        lapsed = self._state.lapsed.get(account_id)
        if lapsed is None or lapsed > requested_before:
            return False
        del self._state.lapsed[account_id]
        return True

    def authorized(self, account_id: ConnectedAccountId) -> bool:
        return (
            self._state.accounts.get(account_id) is ConnectedAccountState.CONNECTED
            and account_id not in self._state.lapsed
        )

    def delete_disconnected(self, account_id: ConnectedAccountId) -> bool:
        if self._state.accounts.get(account_id) is not ConnectedAccountState.DISCONNECTED:
            return False
        del self._state.accounts[account_id]
        self._state.lapsed.pop(account_id, None)
        self._state.authorized_at.pop(account_id, None)
        self._state.calendar_names = {
            endpoint: name
            for endpoint, name in self._state.calendar_names.items()
            if endpoint.connected_account_id != account_id
        }
        return True


class InMemorySyncRuleRepository:
    def __init__(self, state: MemoryState, others: _OtherUsers) -> None:
        self._state = state
        self._others = others

    def get(self, rule_id: SyncRuleId) -> SyncRule | None:
        return self._state.rules.get(rule_id)

    def list(self) -> tuple[SyncRule, ...]:
        return tuple(sorted(self._state.rules.values(), key=lambda rule: rule.id.value))

    def add(self, rule: SyncRule) -> None:
        # Mirror SQLite's primary key and its unique source-and-destination constraint.
        if (
            rule.id in self._state.rules
            or self._others.hold_rule(rule.id)
            or self.relationship_exists(rule.source, rule.destination)
        ):
            raise _duplicate_relationship()
        self._require_own_accounts(rule)
        self._state.rules[rule.id] = rule

    def save(self, rule: SyncRule) -> None:
        if rule.id not in self._state.rules:
            raise KeyError(rule.id)
        if any(
            other.id != rule.id
            and other.source == rule.source
            and other.destination == rule.destination
            for other in self._state.rules.values()
        ):
            raise _duplicate_relationship()
        self._require_own_accounts(rule)
        self._state.rules[rule.id] = rule

    def _require_own_accounts(self, rule: SyncRule) -> None:
        # Mirror SQLite's reference from a rule to its own User's accounts. Accounts this store
        # never recorded are let through, as application tests leave accounts unrecorded.
        for endpoint in (rule.source, rule.destination):
            if self._others.hold_account(endpoint.connected_account_id):
                raise KeyError(endpoint.connected_account_id)

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
    def __init__(self, state: MemoryState, others: _OtherUsers) -> None:
        self._state = state
        self._others = others

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
            sorted(
                (
                    mapping
                    for mapping in self._state.mappings.values()
                    if mapping.rule_id == rule_id
                ),
                key=lambda mapping: mapping.id.value,
            )
        )

    def save(self, mapping: EventMapping) -> None:
        _require_rule(self._state, mapping.rule_id)
        if self._others.hold_mapping(mapping.id):
            # Mirror SQLite's primary key: another User's mapping is neither replaced nor changed.
            raise ValueError("the mapping id names another User's mapping")
        same_id = next((m for m in self._state.mappings.values() if m.id == mapping.id), None)
        if same_id is not None:
            # Mirror SQLite's upsert by id: a mapping keeps its rule and source.
            mapping = replace(mapping, rule_id=same_id.rule_id, source=same_id.source)
        at_source = self._state.mappings.get((mapping.rule_id, mapping.source))
        if at_source is not None and at_source.id != mapping.id:
            raise ValueError("the source is already mapped by another mapping")
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
    def __init__(self, state: MemoryState, others: _OtherUsers) -> None:
        self._state = state
        self._others = others

    def for_series(self, series_mapping_id: EventMappingId) -> tuple[OccurrenceMapping, ...]:
        # SQLite orders by the stored ISO text; one series' starts are all dates or all instants.
        return tuple(
            sorted(
                (
                    mapping
                    for key, mapping in self._state.occurrences.items()
                    if key[0] == series_mapping_id
                ),
                key=lambda mapping: mapping.original_start.isoformat(),
            )
        )

    def get(
        self, series_mapping_id: EventMappingId, original_start: OccurrenceStart
    ) -> OccurrenceMapping | None:
        return self._state.occurrences.get((series_mapping_id, original_start))

    def save(self, mapping: OccurrenceMapping) -> None:
        # Mirror the SQLite foreign key to event_mappings.
        if not any(m.id == mapping.series_mapping_id for m in self._state.mappings.values()):
            raise KeyError(mapping.series_mapping_id)
        key = (mapping.series_mapping_id, mapping.original_start)
        existing = self._state.occurrences.get(key)
        if existing is not None:
            # Mirror SQLite's upsert by series and start: the occurrence keeps its id.
            mapping = replace(mapping, id=existing.id)
        elif self._others.hold_occurrence(mapping.id) or any(
            other.id == mapping.id for other in self._state.occurrences.values()
        ):
            # Mirror SQLite's primary key: one id names one occurrence.
            raise ValueError("the occurrence id already names another occurrence")
        self._state.occurrences[key] = mapping

    def delete(self, mapping: OccurrenceMapping) -> None:
        self._state.occurrences.pop((mapping.series_mapping_id, mapping.original_start), None)


class InMemorySyncCursorRepository:
    def __init__(self, state: MemoryState, cursors: dict[SyncRuleId, str]) -> None:
        self._state = state
        self._cursors = cursors

    def get(self, rule_id: SyncRuleId) -> str | None:
        return self._cursors.get(rule_id)

    def save(self, rule_id: SyncRuleId, cursor: str) -> None:
        _require_rule(self._state, rule_id)
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
        _require_rule(self._state, rule_id)
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
        _require_rule(self._state, outcome.rule_id)
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
            outcome,
            failure_cause=None
            if outcome.succeeded or outcome.failure_kind in WITHOUT_CAUSE
            else outcome.failure_cause,
            last_succeeded_at=succeeded_at,
            last_full_succeeded_at=full_at,
        )

    def latest(self, rule_id: SyncRuleId, kind: RunKind) -> RuleRunOutcome | None:
        return self._state.outcomes.get((rule_id, kind))


class InMemoryRulePreviewRepository:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def record(self, summary: RulePreviewSummary) -> None:
        _require_rule(self._state, summary.rule_id)
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


class InMemoryProviderCallRepository:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def add(self, day: date, provider: ProviderKind, counts: ProviderCallCounts) -> None:
        total = self._state.provider_calls.setdefault((provider, day), ProviderCallCounts())
        total.calls += counts.calls
        total.rate_limited += counts.rate_limited
        total.failed += counts.failed


class InMemoryUnitOfWork:
    """One User's records, like SQLite's unit of work: they live in that User's partition."""

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
    provider_calls: ProviderCallRepository

    def __init__(self, database: MemoryDatabase, user_id: UserId) -> None:
        self._database = database
        self._user = user_id
        self._working: MemoryState | None = None
        self._committed = False

    def __enter__(self) -> Self:
        working = deepcopy(self._database.state_of(self._user))
        self._working = working
        others = _OtherUsers(self._database, self._user)
        self.accounts = InMemoryConnectedAccountRecords(working)
        self.rules = InMemorySyncRuleRepository(working, others)
        self.mappings = InMemoryEventMappingRepository(working, others)
        self.occurrences = InMemoryOccurrenceMappingRepository(working, others)
        self.replays = InMemoryExceptionReplayRepository(working)
        self.cursors = InMemorySyncCursorRepository(working, working.cursors)
        self.destination_cursors = InMemorySyncCursorRepository(
            working, working.destination_cursors
        )
        self.audit = InMemoryAuditRepository(working)
        self.observations = InMemorySourceObservationRepository(working)
        self.run_outcomes = InMemoryRuleRunOutcomeRepository(working)
        self.previews = InMemoryRulePreviewRepository(working)
        self.calendar_names = InMemoryCalendarNameRepository(working)
        self.provider_calls = InMemoryProviderCallRepository(working)
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
        target = self._database.state_of(self._user)
        # Copies, so writes after this commit stay in the unit until it commits again.
        for each in fields(MemoryState):
            setattr(target, each.name, deepcopy(getattr(self._working, each.name)))
        self._committed = True

    def user_active(self) -> bool:
        return self._user not in self._database.disabled


@dataclass(slots=True)
class MemoryDatabase:
    """Every User's records, each User's in a partition of their own."""

    partitions: dict[UserId, MemoryState] = field(default_factory=dict)
    disabled: set[UserId] = field(default_factory=set)
    """Users who may not sign in; the scheduler holds their rules."""

    def state_of(self, user_id: UserId) -> MemoryState:
        return self.partitions.setdefault(user_id, MemoryState())


@dataclass(frozen=True, slots=True)
class _OtherUsers:
    """What SQLite's shared tables would refuse because another User holds it."""

    database: MemoryDatabase
    user: UserId

    def _states(self) -> Iterator[MemoryState]:
        return (state for owner, state in self.database.partitions.items() if owner != self.user)

    def hold_rule(self, rule_id: SyncRuleId) -> bool:
        return any(rule_id in state.rules for state in self._states())

    def hold_account(self, account_id: ConnectedAccountId) -> bool:
        return any(account_id in state.accounts for state in self._states())

    def hold_mapping(self, mapping_id: EventMappingId) -> bool:
        return any(
            mapping.id == mapping_id
            for state in self._states()
            for mapping in state.mappings.values()
        )

    def hold_occurrence(self, occurrence_id: OccurrenceMappingId) -> bool:
        return any(
            occurrence.id == occurrence_id
            for state in self._states()
            for occurrence in state.occurrences.values()
        )


class InMemoryUnitOfWorkFactory:
    """Units of work over one in-memory database, each for the one User `for_user` names."""

    def __init__(self, database: MemoryDatabase | None = None) -> None:
        self.database = database or MemoryDatabase()

    def for_user(self, user_id: UserId) -> InMemoryUserUnitOfWorkFactory:
        return InMemoryUserUnitOfWorkFactory(self.database, user_id)

    def installation(self) -> InMemoryInstallationUnitOfWorkFactory:
        return InMemoryInstallationUnitOfWorkFactory(self.database)


@dataclass(frozen=True, slots=True)
class InMemoryUserUnitOfWorkFactory:
    database: MemoryDatabase
    user_id: UserId

    @property
    def state(self) -> MemoryState:
        """This User's committed records, for tests to seed and inspect."""
        return self.database.state_of(self.user_id)

    def __call__(self) -> UnitOfWork:
        return InMemoryUnitOfWork(self.database, self.user_id)


class InMemoryInstallationUnitOfWork:
    def __init__(self, database: MemoryDatabase) -> None:
        self._database = database

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return None

    def commit(self) -> None:
        return None

    def scheduled_rules(self) -> tuple[ScheduledRule, ...]:
        return tuple(
            ScheduledRule(owner, rule, _last_full_sync(state, rule.id))
            for owner, state in sorted(
                self._database.partitions.items(), key=lambda item: item[0].value
            )
            if owner not in self._database.disabled
            for rule in sorted(state.rules.values(), key=lambda rule: rule.id.value)
            if rule.state is SyncRuleState.ENABLED
        )

    def forget_change_values(self, before: datetime) -> None:
        for state in self._database.partitions.values():
            state.change_values_forgotten_before = before

    def resource_use(self, users: Collection[UserId], since: date) -> dict[UserId, ResourceUse]:
        return {user: _resource_use(self._database.partitions.get(user), since) for user in users}

    def forget_provider_calls(self, before: date) -> None:
        for state in self._database.partitions.values():
            state.provider_calls = {
                key: counts for key, counts in state.provider_calls.items() if key[1] >= before
            }

    def failure_causes(self, since: datetime) -> list[CauseSighting]:
        """Failed runs since `since`; this store keeps no Incidents."""
        return sorted(
            (
                CauseSighting(owner, outcome.failure_cause, outcome.completed_at, False)
                for owner, state in self._database.partitions.items()
                for outcome in state.outcomes.values()
                if not outcome.succeeded
                and outcome.failure_cause is not None
                and outcome.completed_at >= since
            ),
            key=lambda seen: (seen.user.value, seen.at),
        )

    def status_records(self, users: Collection[UserId]) -> dict[UserId, StatusRecords]:
        return {user: _status_records(self._database.partitions.get(user)) for user in users}


def _resource_use(state: MemoryState | None, since: date) -> ResourceUse:
    state = state or MemoryState()
    calls: dict[ProviderKind, ProviderCallCounts] = {}
    for (provider, day), counts in state.provider_calls.items():
        if day >= since:
            total = calls.setdefault(provider, ProviderCallCounts())
            total.calls += counts.calls
            total.rate_limited += counts.rate_limited
            total.failed += counts.failed
    return ResourceUse(
        rules=len(state.rules),
        connected_accounts=len(state.accounts),
        activity_entries=len(state.audit),
        provider_calls=tuple(
            ProviderCallUse(provider, total.calls, total.rate_limited, total.failed)
            for provider, total in sorted(calls.items(), key=lambda item: item[0].value)
        ),
    )


def _status_records(state: MemoryState | None) -> StatusRecords:
    """A User's records as Installation Status reads them. This store keeps no Incidents or
    Activity blocks, and every account it records is a Google account."""
    state = state or MemoryState()
    accounts = tuple(
        AccountStanding(
            account.value,
            standing.value,
            ProviderKind.GOOGLE.value,
            lapsed=standing is ConnectedAccountState.CONNECTED and account in state.lapsed,
        )
        for account, standing in sorted(state.accounts.items(), key=lambda item: item[0].value)
    )
    succeeded = [
        outcome.last_succeeded_at
        for (_, kind), outcome in state.outcomes.items()
        if kind is RunKind.SYNC and outcome.last_succeeded_at is not None
    ]
    return StatusRecords(
        # Rules keep the order they were added in, as a dictionary keeps its keys'.
        rules=tuple(
            RecordedRule(
                rule, state.outcomes.get((rule.id, RunKind.SYNC)), state.previews.get(rule.id)
            )
            for rule in state.rules.values()
        ),
        overview=OperationsOverview(
            connected_accounts=sum(a.state == "connected" for a in accounts),
            disconnected_accounts=sum(a.state == "disconnected" for a in accounts),
            open_incidents=0,
            last_synced_at=max(succeeded).isoformat() if succeeded else None,
            open_blocks=(),
            accounts=accounts,
        ),
        incidents=(),
    )


def _last_full_sync(state: MemoryState, rule_id: SyncRuleId) -> datetime | None:
    outcome = state.outcomes.get((rule_id, RunKind.SYNC))
    return outcome.last_full_succeeded_at if outcome is not None else None


@dataclass(frozen=True, slots=True)
class InMemoryInstallationUnitOfWorkFactory:
    database: MemoryDatabase

    def __call__(self) -> InstallationUnitOfWork:
        return InMemoryInstallationUnitOfWork(self.database)
