from __future__ import annotations

from collections.abc import Callable, Collection, Iterator, Sequence
from copy import deepcopy
from dataclasses import dataclass, field, fields, replace
from datetime import date, datetime
from types import TracebackType
from typing import TYPE_CHECKING, Self

from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.errors import (
    DuplicateDirectionalRelationship,
    IdentityCollision,
    MissingReference,
)
from calendar_sync.application.sync.ports import (
    AuditRepository,
    CalendarNameRepository,
    ConnectedAccountRecords,
    DiscoveredCalendar,
    EventMappingRepository,
    ExceptionReplayRepository,
    OccurrenceMappingRepository,
    ProviderCallCounts,
    ProviderCallRepository,
    RulePreviewRepository,
    RulePreviewSummary,
    RuleRunOutcomeRepository,
    SourceObservationRepository,
    SyncCursorRepository,
    SyncRuleRepository,
    UnitOfWork,
)
from calendar_sync.application.sync.watch_ports import (
    CalendarWatchRepository,
    InstantSyncRequestRepository,
    PendingRequest,
    Receipt,
)
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ConnectedAccountState, ProviderKind
from calendar_sync.domain.audit import AuditEntry, RecordedDecision
from calendar_sync.domain.causes import WITHOUT_CAUSE, Cause
from calendar_sync.domain.changes import SourceObservation
from calendar_sync.domain.incidents import IncidentReport, IncidentResolution
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
)
from calendar_sync.domain.runs import RuleRunOutcome, RunKind
from calendar_sync.domain.watches import (
    CalendarWatch,
    CalendarWatchId,
    DeliveryEvidence,
    RegistrationState,
    WatchRegistration,
    WatchRegistrationId,
)
from calendar_sync.infrastructure.clock import SystemClock

if TYPE_CHECKING:
    from calendar_sync.infrastructure.persistence.memory_installation import (
        InMemoryInstallationUnitOfWorkFactory,
    )


@dataclass(slots=True)
class MemoryState:
    accounts: dict[ConnectedAccountId, ConnectedAccountState] = field(default_factory=dict)
    providers: dict[ConnectedAccountId, ProviderKind] = field(default_factory=dict)
    """Each account's Provider Kind, where a test recorded one."""
    lapsed: dict[ConnectedAccountId, datetime] = field(default_factory=dict)
    authorized_at: dict[ConnectedAccountId, datetime] = field(default_factory=dict)
    """When each account was last authorized; one missing was authorized before any request."""
    rules: dict[SyncRuleId, SyncRule] = field(default_factory=dict)
    rule_order: dict[SyncRuleId, int] = field(default_factory=dict)
    """Each rule's creation order, as SQLite's `creation_order` keeps it. A rule a test seeded
    into `rules` directly has none and ranks as 0."""
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
    watches: dict[CalendarWatchId, CalendarWatch] = field(default_factory=dict)
    registrations: dict[WatchRegistrationId, WatchRegistration] = field(default_factory=dict)
    instant_requests: dict[SyncRuleId, PendingRequest] = field(default_factory=dict)
    """Raised by the Watch Notice inbox outside any unit of work, as SQLite's are. A unit copies
    its partition when it opens and commits, so a test raises requests only between units."""


def _require_rule(state: MemoryState, rule_id: SyncRuleId) -> None:
    # Mirror SQLite's foreign keys to sync_rules.
    if rule_id not in state.rules:
        raise MissingReference(f"sync rule {rule_id.value} does not exist")


def _require_rule_accounts(state: MemoryState) -> None:
    # Mirror SQLite's deferred references from a rule to its own User's accounts, checked when
    # the unit commits, so an account and the rules that use it go in either order.
    for rule in state.rules.values():
        for endpoint in (rule.source, rule.destination):
            if endpoint.connected_account_id not in state.accounts:
                raise MissingReference(
                    f"sync rule {rule.id.value} names an account its User does not have"
                )


def _duplicate_relationship() -> DuplicateDirectionalRelationship:
    return DuplicateDirectionalRelationship("a rule already exists for this source and destination")


def _forget_watches(state: MemoryState, account_id: ConnectedAccountId) -> None:
    """Mirror SQLite's cascade from an account to its watches and their registrations."""
    gone = {key for key, watch in state.watches.items() if watch.account == account_id}
    state.watches = {key: watch for key, watch in state.watches.items() if key not in gone}
    state.registrations = {
        key: registration
        for key, registration in state.registrations.items()
        if registration.watch_id not in gone
    }


def raise_instant_request(state: MemoryState, rule_id: SyncRuleId, at: datetime) -> None:
    """Raise a rule's Instant Sync Request as SQLite's inbox does: a request already handled
    starts waiting again from `at`, and a pending one keeps the earliest time it waits since and
    the latest time it was raised, whatever order notices arrive in."""
    current = state.instant_requests.get(rule_id)
    if current is None:
        state.instant_requests[rule_id] = PendingRequest(rule_id, 1, 0, at, at, None)
        return
    waiting = current.requested_seq > current.handled_seq
    state.instant_requests[rule_id] = replace(
        current,
        requested_seq=current.requested_seq + 1,
        first_requested_at=min(current.first_requested_at, at) if waiting else at,
        last_requested_at=max(current.last_requested_at, at),
    )


class InMemoryConnectedAccountRecords:
    def __init__(self, state: MemoryState, incidents: IncidentWrites | None = None) -> None:
        self._state = state
        self._incidents = incidents or IncidentWrites()

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

    def lapsed(self) -> dict[ConnectedAccountId, ProviderKind]:
        # This store knows an account's provider only when a test recorded it.
        return {
            account: self._state.providers[account]
            for account in sorted(self._state.lapsed, key=lambda account: account.value)
            if self._state.accounts.get(account) is ConnectedAccountState.CONNECTED
            and account in self._state.providers
        }

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
        _forget_watches(self._state, account_id)
        # The account's own Incidents, such as its Lapsed Authorization, go with it.
        self._incidents.delete_account(account_id)
        return True


class InMemorySyncRuleRepository:
    def __init__(
        self, state: MemoryState, others: _OtherUsers, incidents: IncidentWrites, clock: Clock
    ) -> None:
        self._state = state
        self._others = others
        self._incidents = incidents
        self._clock = clock

    def get(self, rule_id: SyncRuleId) -> SyncRule | None:
        return self._state.rules.get(rule_id)

    def list(self) -> tuple[SyncRule, ...]:
        return tuple(sorted(self._state.rules.values(), key=lambda rule: rule.id.value))

    def add(self, rule: SyncRule) -> None:
        # Mirror SQLite's primary key and its unique source-and-destination constraint.
        if rule.id in self._state.rules or self._others.hold_rule(rule.id):
            raise IdentityCollision(f"sync rule {rule.id.value} already exists")
        if self.relationship_exists(rule.source, rule.destination):
            raise _duplicate_relationship()
        self._state.rules[rule.id] = rule
        self._state.rule_order[rule.id] = max(self._state.rule_order.values(), default=0) + 1

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
        self._state.rules[rule.id] = rule

    def remove(self, rule_id: SyncRuleId) -> None:
        self._incidents.resolve_rule(rule_id, self._clock.now())
        self._state.rules.pop(rule_id, None)
        self._state.rule_order.pop(rule_id, None)
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
        self._state.instant_requests.pop(rule_id, None)
        self._state.observations = {
            key: value for key, value in self._state.observations.items() if key[0] != rule_id
        }

    def purge(self, rule_id: SyncRuleId) -> None:
        self.remove(rule_id)
        self._state.audit = [entry for entry in self._state.audit if entry.rule_id != rule_id]
        self._incidents.delete_rule(rule_id)

    def inherit_place(self, rule: SyncRuleId, of: SyncRuleId) -> None:
        # Both must be this User's, as SQLite's update requires.
        if rule in self._state.rules and of in self._state.rules:
            self._state.rule_order[rule] = self._state.rule_order.get(of, 0)

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

    def lone_occurrences(self, rule_id: SyncRuleId, series: EventRef) -> tuple[EventMapping, ...]:
        return tuple(
            mapping
            for mapping in self.for_rule(rule_id)
            if mapping.occurrence is not None
            and mapping.source.calendar == series.calendar
            and mapping.occurrence.series_event_id == series.event_id
        )

    def save(self, mapping: EventMapping) -> None:
        if self._others.hold_mapping(mapping.id):
            # Mirror SQLite's primary key: another User's mapping is neither replaced nor changed,
            # whichever rule this one names.
            raise IdentityCollision(f"event mapping {mapping.id.value} is another User's")
        _require_rule(self._state, mapping.rule_id)
        same_id = next((m for m in self._state.mappings.values() if m.id == mapping.id), None)
        if same_id is not None:
            # Mirror SQLite's upsert by id: a mapping keeps its rule, source, and occurrence.
            mapping = replace(
                mapping,
                rule_id=same_id.rule_id,
                source=same_id.source,
                occurrence=same_id.occurrence,
            )
        at_source = self._state.mappings.get((mapping.rule_id, mapping.source))
        if at_source is not None and at_source.id != mapping.id:
            raise IdentityCollision("the source is already mapped by another mapping")
        for existing in self._state.mappings.values():
            if (
                existing.rule_id == mapping.rule_id
                and existing.destination == mapping.destination
                and existing.source != mapping.source
            ):
                raise IdentityCollision("managed destination is already mapped to another source")
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
            raise MissingReference(f"series mapping {series_mapping_id.value} does not exist")
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
            raise MissingReference(
                f"series mapping {mapping.series_mapping_id.value} does not exist"
            )
        key = (mapping.series_mapping_id, mapping.original_start)
        existing = self._state.occurrences.get(key)
        if existing is not None:
            # Mirror SQLite's upsert by series and start: the occurrence keeps its id.
            mapping = replace(mapping, id=existing.id)
        elif self._others.hold_occurrence(mapping.id) or any(
            other.id == mapping.id for other in self._state.occurrences.values()
        ):
            # Mirror SQLite's primary key: one id names one occurrence.
            raise IdentityCollision("the occurrence id already names another occurrence")
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

    def latest_for(self, rule_id: SyncRuleId, source_event_id: str) -> RecordedDecision | None:
        for entry in reversed(self._state.audit):
            if entry.rule_id == rule_id and entry.source_event_id == source_event_id:
                return RecordedDecision.of(entry)
        return None

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
            failure_provider=None
            if outcome.succeeded or outcome.failure_kind in WITHOUT_CAUSE
            else outcome.failure_provider,
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
            self._state.calendar_names[endpoint] = calendar.name

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


class InMemoryCalendarWatchRepository:
    def __init__(self, state: MemoryState, others: _OtherUsers) -> None:
        self._state = state
        self._others = others

    def list(self) -> tuple[CalendarWatch, ...]:
        return tuple(sorted(self._state.watches.values(), key=lambda watch: watch.id.value))

    def registrations(self) -> tuple[WatchRegistration, ...]:
        return tuple(
            sorted(
                self._state.registrations.values(),
                key=lambda each: (each.watch_id.value, each.created_at, each.id.value),
            )
        )

    def add(self, watch: CalendarWatch) -> None:
        # Mirror SQLite's primary key, its one watch per account and scope, and its reference to
        # the User's own account.
        if (
            watch.id in self._state.watches
            or self._others.hold_watch(watch.id)
            or any(
                other.account == watch.account and other.scope == watch.scope
                for other in self._state.watches.values()
            )
        ):
            raise IdentityCollision(f"calendar watch {watch.id.value} already exists")
        if watch.account not in self._state.accounts:
            raise MissingReference(f"connected account {watch.account.value} does not exist")
        self._state.watches[watch.id] = watch

    def set_coverage(self, watch_id: CalendarWatchId, coverage: frozenset[CalendarId]) -> None:
        watch = self._state.watches.get(watch_id)
        if watch is not None:
            self._state.watches[watch_id] = replace(watch, coverage=frozenset(coverage))

    def set_retry(
        self, watch_id: CalendarWatchId, retry_at: datetime | None, failures: int
    ) -> None:
        watch = self._state.watches.get(watch_id)
        if watch is not None:
            self._state.watches[watch_id] = replace(watch, retry_at=retry_at, failures=failures)

    def remove(self, watch_id: CalendarWatchId) -> None:
        self._state.watches.pop(watch_id, None)
        self._state.registrations = {
            key: registration
            for key, registration in self._state.registrations.items()
            if registration.watch_id != watch_id
        }

    def add_registration(self, registration: WatchRegistration) -> None:
        # Mirror SQLite's primary key, its unique token hash, and its reference to the watch.
        if self._others.hold_registration(registration) or any(
            other.id == registration.id or other.token_hash == registration.token_hash
            for other in self._state.registrations.values()
        ):
            raise IdentityCollision(f"watch registration {registration.id.value} already exists")
        if registration.watch_id not in self._state.watches:
            raise MissingReference(f"calendar watch {registration.watch_id.value} does not exist")
        self._state.registrations[registration.id] = registration

    def record_receipt(
        self,
        registration_id: WatchRegistrationId,
        receipt: Receipt,
        renew_at: datetime,
        at: datetime,
    ) -> bool:
        registration = self._state.registrations.get(registration_id)
        if registration is None or registration.state is not RegistrationState.CREATING:
            return False
        confirmed = registration.confirmed_at or (at if receipt.confirmed else None)
        self._state.registrations[registration_id] = replace(
            registration,
            state=RegistrationState.LIVE,
            handle=receipt.handle,
            expires_at=receipt.expires_at,
            renew_at=renew_at,
            confirmed_at=confirmed,
        )
        return True

    def record_extension(
        self,
        registration_id: WatchRegistrationId,
        expires_at: datetime,
        renew_at: datetime,
        seen_request: datetime | None,
    ) -> bool:
        registration = self._state.registrations.get(registration_id)
        if registration is None or registration.state is not RegistrationState.LIVE:
            return False
        asked = registration.renew_requested_at
        self._state.registrations[registration_id] = replace(
            registration,
            expires_at=expires_at,
            renew_at=renew_at,
            renew_requested_at=None if asked == seen_request else asked,
        )
        return True

    def retire(self, registration_id: WatchRegistrationId) -> bool:
        return self._move(registration_id, RegistrationState.RETIRING, {RegistrationState.LIVE})

    def abandon(self, registration_id: WatchRegistrationId) -> bool:
        return self._move(registration_id, RegistrationState.ABANDONED, set(RegistrationState))

    def delete_registration(self, registration_id: WatchRegistrationId) -> None:
        self._state.registrations.pop(registration_id, None)

    def _move(
        self,
        registration_id: WatchRegistrationId,
        to: RegistrationState,
        leaving: Collection[RegistrationState],
    ) -> bool:
        registration = self._state.registrations.get(registration_id)
        if registration is None or registration.state not in leaving:
            return False
        self._state.registrations[registration_id] = replace(registration, state=to)
        return True


class InMemoryInstantSyncRequestRepository:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def pending(self) -> tuple[PendingRequest, ...]:
        return tuple(
            sorted(
                (
                    request
                    for request in self._state.instant_requests.values()
                    if request.requested_seq > request.handled_seq
                ),
                key=lambda request: request.rule_id.value,
            )
        )

    def acknowledge(self, rule_id: SyncRuleId, seq: int, ran_at: datetime) -> None:
        current = self._state.instant_requests.get(rule_id)
        if current is not None:
            self._state.instant_requests[rule_id] = replace(
                current, handled_seq=max(current.handled_seq, seq), last_run_at=ran_at
            )


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
    watches: CalendarWatchRepository
    instant_requests: InstantSyncRequestRepository

    def __init__(self, database: MemoryDatabase, user_id: UserId, clock: Clock) -> None:
        self._database = database
        self._user = user_id
        self._clock = clock
        self._working: MemoryState | None = None
        self._incidents = IncidentWrites()
        self._committed = False

    def __enter__(self) -> Self:
        working = deepcopy(self._database.state_of(self._user))
        self._working = working
        others = _OtherUsers(self._database, self._user)
        # Like SQLite's connection, each context starts clean: what an earlier one did not
        # commit to Incidents is gone.
        incidents = self._incidents = IncidentWrites()
        self.accounts = InMemoryConnectedAccountRecords(working, incidents)
        self.rules = InMemorySyncRuleRepository(working, others, incidents, self._clock)
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
        self.watches = InMemoryCalendarWatchRepository(working, others)
        self.instant_requests = InMemoryInstantSyncRequestRepository(working)
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
        _require_rule_accounts(self._working)
        target = self._database.state_of(self._user)
        # Copies, so writes after this commit stay in the unit until it commits again.
        for each in fields(MemoryState):
            setattr(target, each.name, deepcopy(getattr(self._working, each.name)))
        self._incidents.apply(self._database.incidents_of(self._user))
        self._committed = True

    def user_active(self) -> bool:
        return self._user not in self._database.disabled


@dataclass(slots=True)
class MemoryDatabase:
    """Every User's records, each User's in a partition of their own."""

    partitions: dict[UserId, MemoryState] = field(default_factory=dict)
    disabled: set[UserId] = field(default_factory=set)
    """Users who may not sign in; the scheduler holds their rules."""
    instant_sync_off: set[UserId] = field(default_factory=set)
    """Users who turned Instant Sync off; like `disabled`, kept as SQLite's users table keeps it."""
    incidents: dict[UserId, dict[str, MemoryIncident]] = field(default_factory=dict)
    """Each User's Incidents by key; like SQLite's, they change outside any unit of work, except
    as a unit's rule removals and account deletions change them when it commits."""
    delivery_evidence: dict[tuple[ProviderKind, str], DeliveryEvidence] = field(
        default_factory=dict
    )
    """Whether each provider reached each public address, as SQLite's installation table keeps."""

    def state_of(self, user_id: UserId) -> MemoryState:
        return self.partitions.setdefault(user_id, MemoryState())

    def incidents_of(self, user_id: UserId) -> dict[str, MemoryIncident]:
        return self.incidents.setdefault(user_id, {})


@dataclass(slots=True)
class MemoryIncident:
    """An Incident as SQLite's row keeps it: what it last reported, and when and why it opened
    and resolved."""

    report: IncidentReport
    opened_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    resolution: IncidentResolution | None = None

    @property
    def open(self) -> bool:
        return self.resolved_at is None

    def resolve(self, at: datetime, resolution: IncidentResolution) -> None:
        self.updated_at = self.resolved_at = at
        self.resolution = resolution


class IncidentWrites:
    """What a unit of work's writes do to its User's Incidents. SQLite changes them in the unit's
    own transaction, so here they wait for the unit to commit."""

    def __init__(self) -> None:
        self._writes: list[Callable[[dict[str, MemoryIncident]], None]] = []

    def resolve_rule(self, rule_id: SyncRuleId, at: datetime) -> None:
        def write(incidents: dict[str, MemoryIncident]) -> None:
            for incident in incidents.values():
                if incident.report.rule_id == rule_id and incident.open:
                    incident.resolve(at, IncidentResolution.RULE_REMOVED)

        self._writes.append(write)

    def delete_rule(self, rule_id: SyncRuleId) -> None:
        self._delete(lambda report: report.rule_id == rule_id)

    def delete_account(self, account_id: ConnectedAccountId) -> None:
        self._delete(lambda report: report.rule_id is None and report.account_id == account_id)

    def _delete(self, deleted: Callable[[IncidentReport], bool]) -> None:
        def write(incidents: dict[str, MemoryIncident]) -> None:
            for key in [key for key, each in incidents.items() if deleted(each.report)]:
                del incidents[key]

        self._writes.append(write)

    def apply(self, incidents: dict[str, MemoryIncident]) -> None:
        """Apply the writes since the last commit, so writes after it wait for the next."""
        for write in self._writes:
            write(incidents)
        self._writes.clear()


class InMemoryIncidentRepository:
    """One User's Incidents, as SQLite opens and resolves them."""

    def __init__(self, database: MemoryDatabase, user_id: UserId) -> None:
        self._database = database
        self._user = user_id

    def open(self, incident: IncidentReport, at: datetime, *, refresh: bool = True) -> bool:
        state = self._database.state_of(self._user)
        # An account's own Incident opens only while the account is lapsed.
        if incident.rule_id is None and incident.account_id not in state.lapsed:
            return False
        incidents = self._database.incidents_of(self._user)
        existing = incidents.get(incident.key)
        if existing is None or not existing.open:
            # A resolved Incident reopens as a new episode.
            incidents[incident.key] = MemoryIncident(incident, opened_at=at, updated_at=at)
            return True
        if refresh:
            existing.report, existing.updated_at = incident, at
        return False

    def resolve(
        self,
        key: str,
        at: datetime,
        resolution: IncidentResolution,
        *,
        while_authorized: ConnectedAccountId | None = None,
    ) -> None:
        state = self._database.state_of(self._user)
        incident = self._database.incidents_of(self._user).get(key)
        if incident is None or not incident.open:
            return
        if while_authorized is None or InMemoryConnectedAccountRecords(state).authorized(
            while_authorized
        ):
            incident.resolve(at, resolution)

    def accounts_lapsed_by(self, causes: Collection[Cause]) -> frozenset[ConnectedAccountId]:
        return frozenset(
            incident.report.account_id
            for incident in self._database.incidents_of(self._user).values()
            if incident.open
            and incident.report.rule_id is None
            and incident.report.account_id is not None
            and incident.report.cause in causes
        )

    def accounts_with_open_incidents(self) -> frozenset[ConnectedAccountId]:
        return frozenset(
            incident.report.account_id
            for incident in self._database.incidents_of(self._user).values()
            if incident.open
            and incident.report.rule_id is None
            and incident.report.account_id is not None
        )


@dataclass(frozen=True, slots=True)
class _OtherUsers:
    """What SQLite's shared tables would refuse because another User holds it."""

    database: MemoryDatabase
    user: UserId

    def _states(self) -> Iterator[MemoryState]:
        return (state for owner, state in self.database.partitions.items() if owner != self.user)

    def hold_rule(self, rule_id: SyncRuleId) -> bool:
        return any(rule_id in state.rules for state in self._states())

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

    def hold_watch(self, watch_id: CalendarWatchId) -> bool:
        return any(watch_id in state.watches for state in self._states())

    def hold_registration(self, registration: WatchRegistration) -> bool:
        return any(
            other.id == registration.id or other.token_hash == registration.token_hash
            for state in self._states()
            for other in state.registrations.values()
        )


class InMemoryUnitOfWorkFactory:
    """Units of work over one in-memory database, each for the one User `for_user` names."""

    def __init__(self, database: MemoryDatabase | None = None, clock: Clock | None = None) -> None:
        self.database = database or MemoryDatabase()
        self.clock = clock or SystemClock()

    def for_user(self, user_id: UserId) -> InMemoryUserUnitOfWorkFactory:
        return InMemoryUserUnitOfWorkFactory(self.database, user_id, self.clock)

    def installation(self) -> InMemoryInstallationUnitOfWorkFactory:
        # Imported here, since that module builds on this one's database.
        from calendar_sync.infrastructure.persistence.memory_installation import (
            InMemoryInstallationUnitOfWorkFactory,
        )

        return InMemoryInstallationUnitOfWorkFactory(self.database)


@dataclass(frozen=True, slots=True)
class InMemoryUserUnitOfWorkFactory:
    database: MemoryDatabase
    user_id: UserId
    clock: Clock = field(default_factory=SystemClock)

    @property
    def state(self) -> MemoryState:
        """This User's committed records, for tests to seed and inspect."""
        return self.database.state_of(self.user_id)

    def __call__(self) -> UnitOfWork:
        return InMemoryUnitOfWork(self.database, self.user_id, self.clock)
