"""The in-memory installation-wide unit of work: what reaches across Users (ADR 0029)."""

from __future__ import annotations

from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from types import TracebackType
from typing import Self

from calendar_sync.application.operations.ports import (
    AccountStanding,
    CauseSighting,
    InboxBusy,
    IncidentSummary,
    InstallationUnitOfWork,
    InstantSyncOwner,
    OpenBlock,
    OperationsOverview,
    PendingInstantRun,
    ProviderCallUse,
    RecordedRule,
    ResourceUse,
    StatusRecords,
    UserPlanStanding,
)
from calendar_sync.application.sync.ports import ProviderCallCounts, ScheduledRule
from calendar_sync.application.sync.watch_ports import NoticeKind, WatchNotice
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ConnectedAccountState, ProviderKind
from calendar_sync.domain.audit import AuditAction, AuditEntry
from calendar_sync.domain.causes import WITHOUT_CAUSE
from calendar_sync.domain.incidents import AccountAuthorization
from calendar_sync.domain.model import (
    ConnectedAccountId,
    SyncReason,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.domain.plan_hold import RulePlace, RuleStanding
from calendar_sync.domain.plans import PlanUse
from calendar_sync.domain.runs import RunKind
from calendar_sync.domain.watches import (
    CalendarWatchId,
    DeliveryEvidence,
    RegistrationState,
    WatchRegistration,
)
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryIncidentRepository,
    MemoryDatabase,
    MemoryIncident,
    MemoryState,
    raise_instant_request,
)
from calendar_sync.infrastructure.persistence.watch_inbox import EVIDENCE_REFRESH, presents
from calendar_sync.infrastructure.persistence.watches import upkeep_due


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

    def plan_standings(self) -> Sequence[UserPlanStanding]:
        result = []
        for owner, state in sorted(
            self._database.partitions.items(), key=lambda item: item[0].value
        ):
            standings = tuple(
                sorted(
                    (
                        RuleStanding(
                            rule.id,
                            RulePlace.HELD
                            if rule.stopped_by_plan_hold
                            else RulePlace.RESERVED
                            if rule.keeps_place
                            else RulePlace.COUNTED,
                            state.rule_order.get(rule.id, 0),
                            rule.id in state.rule_kept,
                        )
                        for rule in state.rules.values()
                        if rule.counts_toward_plan or rule.stopped_by_plan_hold
                    ),
                    key=lambda each: each.rank,
                )
            )
            if standings or state.plan_grace is not None:
                result.append(
                    UserPlanStanding(
                        owner,
                        owner not in self._database.disabled,
                        standings,
                        state.plan_grace,
                        state.plan_admissions,
                    )
                )
        return tuple(result)

    def scheduled_rules(self) -> tuple[ScheduledRule, ...]:
        return tuple(
            _scheduled(owner, state, rule)
            for owner, state in sorted(
                self._database.partitions.items(), key=lambda item: item[0].value
            )
            if owner not in self._database.disabled
            for rule in sorted(state.rules.values(), key=lambda rule: rule.id.value)
            if rule.state is SyncRuleState.ENABLED
        )

    def users_with_unfinished_lapses(self) -> tuple[UserId, ...]:
        return tuple(
            owner
            for owner, state in sorted(
                self._database.partitions.items(), key=lambda item: item[0].value
            )
            if owner not in self._database.disabled and _unfinished(self._database, owner, state)
        )

    def forget_change_values(self, before: datetime) -> None:
        for state in self._database.partitions.values():
            state.change_values_forgotten_before = before

    def resource_use(self, users: Collection[UserId], since: date) -> dict[UserId, ResourceUse]:
        return {user: _resource_use(self._database.partitions.get(user), since) for user in users}

    def plan_use(self, users: Collection[UserId]) -> dict[UserId, PlanUse]:
        return {user: _plan_use(self._database, user) for user in users}

    def forget_provider_calls(self, before: date) -> None:
        for state in self._database.partitions.values():
            state.provider_calls = {
                key: counts for key, counts in state.provider_calls.items() if key[1] >= before
            }

    def failure_causes(self, since: datetime) -> list[CauseSighting]:
        runs = (
            CauseSighting(
                owner,
                outcome.failure_cause,
                outcome.completed_at,
                False,
                provider=outcome.failure_provider,
            )
            for owner, state in self._database.partitions.items()
            for outcome in state.outcomes.values()
            if not outcome.succeeded
            and outcome.failure_cause is not None
            and outcome.completed_at >= since
        )
        incidents = (
            _incident_sighting(owner, incident, self._database.state_of(owner))
            for owner, kept in self._database.incidents.items()
            for incident in kept.values()
            if incident.report.cause is not None
            and incident.report.category not in WITHOUT_CAUSE
            and (incident.open or incident.updated_at >= since)
        )
        return sorted((*runs, *incidents), key=lambda seen: (seen.user.value, seen.at))

    def status_records(self, users: Collection[UserId]) -> dict[UserId, StatusRecords]:
        return {user: _status_records(self._database, user) for user in users}

    def instant_sync_owners(self) -> tuple[InstantSyncOwner, ...]:
        database = self._database
        return tuple(
            InstantSyncOwner(
                owner,
                wanted=owner not in database.instant_sync_off,
                disabled=owner in database.disabled,
                next_due=upkeep_due(state.watches.values(), state.registrations.values()),
            )
            for owner, state in sorted(database.partitions.items(), key=lambda item: item[0].value)
            if state.watches
            or any(rule.state is SyncRuleState.ENABLED for rule in state.rules.values())
        )

    def pending_instant_runs(self) -> tuple[PendingInstantRun, ...]:
        return tuple(
            run
            for owner, state in sorted(
                self._database.partitions.items(), key=lambda item: item[0].value
            )
            if owner not in self._database.disabled
            for run in _pending_runs(owner, state)
        )


def _unfinished(database: MemoryDatabase, owner: UserId, state: MemoryState) -> bool:
    """Whether a lapse or restoration of the owner's may have been left partly done."""
    if any(
        rule.state is SyncRuleState.DEGRADED and rule.awaiting_reauthorization
        for rule in state.rules.values()
    ):
        return True
    incidents = InMemoryIncidentRepository(database, owner).accounts_with_open_incidents()
    for account, standing in state.accounts.items():
        if standing is not ConnectedAccountState.CONNECTED:
            continue
        if account not in state.lapsed:
            # Authorized again while its Incident is open: a restoration.
            if account in incidents:
                return True
        # Lapsed with no Incident open, or a rule still enabled: a lapse.
        elif account not in incidents or any(
            rule.state is SyncRuleState.ENABLED and rule.uses_account(account)
            for rule in state.rules.values()
        ):
            return True
    return False


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


def _plan_use(database: MemoryDatabase, user: UserId) -> PlanUse:
    state = database.partitions.get(user) or MemoryState()
    return PlanUse(
        rules=sum(rule.counts_toward_plan for rule in state.rules.values()),
        connected_accounts=len(state.accounts),
        integration_tokens=database.unrevoked_tokens.get(user, 0),
    )


def _incident_sighting(
    owner: UserId, incident: MemoryIncident, state: MemoryState
) -> CauseSighting:
    """A provider failure's Incident, as SQLite reads it; for a lapsed account's own one still
    open, with how long after the account was last authorized it opened."""
    report = incident.report
    assert report.cause is not None
    account = report.account_id if report.rule_id is None else None
    authorized = (
        state.authorized_at.get(account)
        if account is not None
        and state.accounts.get(account) is ConnectedAccountState.CONNECTED
        and account in state.lapsed
        else None
    )
    lived = incident.opened_at - authorized if incident.open and authorized else None
    return CauseSighting(
        owner, report.cause, incident.updated_at, incident.open, lived, provider=report.provider
    )


def _status_records(database: MemoryDatabase, user: UserId) -> StatusRecords:
    """A User's records as Installation Status reads them. This store keeps no daily block
    checks, so every block still the latest decision about its event is open. It knows an
    account's provider only when a test recorded one, so an account without one counts but has no
    standing."""
    state = database.partitions.get(user) or MemoryState()
    incidents = sorted(
        (
            _incident_summary(key, incident, state)
            for key, incident in database.incidents.get(user, {}).items()
            if incident.open
        ),
        key=lambda summary: (summary.updated_at, summary.id),
        reverse=True,
    )
    accounts = tuple(
        AccountStanding(
            account.value,
            standing,
            state.providers[account],
            lapsed=standing is ConnectedAccountState.CONNECTED and account in state.lapsed,
        )
        for account, standing in sorted(state.accounts.items(), key=lambda item: item[0].value)
        if account in state.providers
    )
    standings = state.accounts.values()
    succeeded = [
        outcome.last_succeeded_at
        for (_, kind), outcome in state.outcomes.items()
        if kind is RunKind.SYNC and outcome.last_succeeded_at is not None
    ]
    return StatusRecords(
        # Rules in the order they were created, then by identifier, as SQLite lists them.
        rules=tuple(
            RecordedRule(
                rule, state.outcomes.get((rule.id, RunKind.SYNC)), state.previews.get(rule.id)
            )
            for rule in sorted(
                state.rules.values(),
                key=lambda rule: (state.rule_order.get(rule.id, 0), rule.id.value),
            )
        ),
        overview=OperationsOverview(
            connected_accounts=sum(s is ConnectedAccountState.CONNECTED for s in standings),
            disconnected_accounts=sum(s is ConnectedAccountState.DISCONNECTED for s in standings),
            open_incidents=len(incidents),
            last_synced_at=max(succeeded) if succeeded else None,
            open_blocks=_open_blocks(state),
            accounts=accounts,
        ),
        incidents=tuple(incidents),
    )


def _open_blocks(state: MemoryState) -> tuple[OpenBlock, ...]:
    """Events of existing rules whose latest decision was a block, newest first. An entry's place
    in its User's Activity, from 1, stands for the identifier SQLite gives it."""
    latest: dict[tuple[SyncRuleId, str], tuple[int, AuditEntry]] = {}
    for number, entry in enumerate(state.audit, start=1):
        if entry.source_event_id is not None:
            latest[(entry.rule_id, entry.source_event_id)] = (number, entry)
    return tuple(
        OpenBlock(number, entry.rule_id.value)
        for number, entry in sorted(latest.values(), key=lambda item: item[0], reverse=True)
        if entry.rule_id in state.rules and _blocks(entry)
    )


def _blocks(entry: AuditEntry) -> bool:
    """A synchronization block. Recurring exclusions were recorded as conflicts before reason
    codes existed; they are skips."""
    return entry.action is AuditAction.CONFLICT and entry.reason != SyncReason.RECURRING_UNSUPPORTED


def _incident_summary(key: str, incident: MemoryIncident, state: MemoryState) -> IncidentSummary:
    """An Incident with its rule and the rule's accounts as they are now. This store names an
    Incident by its key."""
    report = incident.report
    rule = state.rules.get(report.rule_id) if report.rule_id is not None else None
    ends = (rule.source, rule.destination) if rule is not None else ()
    return IncidentSummary(
        id=key,
        rule_id=report.rule_id.value if report.rule_id else None,
        category=report.category,
        state="open" if incident.open else "resolved",
        summary=report.summary,
        opened_at=incident.opened_at,
        updated_at=incident.updated_at,
        resolved_at=incident.resolved_at,
        resolution=incident.resolution.value if incident.resolution else None,
        account_id=report.account_id.value if report.account_id else None,
        message=report.message,
        cause=None if report.category in WITHOUT_CAUSE else report.cause,
        provider=None
        if report.category in WITHOUT_CAUSE or report.cause is None
        else report.provider,
        rule_exists=rule is not None,
        rule_accounts=tuple(
            _authorization(state, end.connected_account_id)
            for end in ends
            if end.connected_account_id in state.accounts
        ),
    )


def _authorization(state: MemoryState, account: ConnectedAccountId) -> AccountAuthorization:
    connected = state.accounts.get(account) is ConnectedAccountState.CONNECTED
    return AccountAuthorization(
        account, connected, state.authorized_at.get(account) if connected else None
    )


def _scheduled(owner: UserId, state: MemoryState, rule: SyncRule) -> ScheduledRule:
    """The rule as the scheduler reads it. This store keeps no failure streaks, so a rule is
    failing only while its last sync failed."""
    outcome = state.outcomes.get((rule.id, RunKind.SYNC))
    preview = state.previews.get(rule.id)
    return ScheduledRule(
        owner,
        rule,
        None if outcome is None else outcome.last_full_succeeded_at,
        last_run_at=None if outcome is None else outcome.completed_at,
        failing=outcome is not None and not outcome.succeeded,
        previewed_at=None if preview is None else preview.completed_at,
    )


def _pending_runs(owner: UserId, state: MemoryState) -> Iterator[PendingInstantRun]:
    for rule_id, request in sorted(state.instant_requests.items(), key=lambda item: item[0].value):
        rule = state.rules.get(rule_id)
        if rule is None or rule.state is not SyncRuleState.ENABLED:
            continue
        if request.requested_seq <= request.handled_seq:
            continue
        outcome = state.outcomes.get((rule_id, RunKind.SYNC))
        yield PendingInstantRun(
            _scheduled(owner, state, rule),
            request,
            last_run_failed=outcome is not None and not outcome.succeeded,
        )


@dataclass(slots=True)
class InMemoryWatchNoticeInbox:
    """Every User's Watch Notices, as SQLite's inbox records them. Its writes reach each User's
    committed records at once. Setting `busy` stands for a store that stays locked."""

    database: MemoryDatabase
    busy: bool = False

    def record(
        self,
        notices: Sequence[WatchNotice],
        provider: ProviderKind,
        address_base: str,
        at: datetime,
    ) -> int:
        if self.busy:
            raise InboxBusy("the store stayed locked; the notice is to be sent again")
        requested, delivered = 0, False
        for notice in dict.fromkeys(notices):
            found = _authentic(self.database, notice, provider)
            if found is None:
                continue
            state, registration = found
            delivered = delivered or registration.address.startswith(f"{address_base}/")
            requested += _apply(state, registration, notice.kind, at)
        if delivered:
            _refresh_success(self.database, provider, address_base, at)
        return requested


_REMOVED_TO = {
    RegistrationState.LIVE: RegistrationState.RETIRING,
    RegistrationState.CREATING: RegistrationState.ABANDONED,
}
"""What a removal notice makes of a registration: one still being created is abandoned, so its
late receipt cannot make it live."""


def _authentic(
    database: MemoryDatabase, notice: WatchNotice, provider: ProviderKind
) -> tuple[MemoryState, WatchRegistration] | None:
    for state in database.partitions.values():
        registration = state.registrations.get(notice.registration_id)
        if registration is None:
            continue
        watch = state.watches.get(registration.watch_id)
        if (
            registration.state is RegistrationState.ABANDONED
            or watch is None
            or state.providers.get(watch.account) is not provider
            or not presents(notice, registration.token_hash, registration.handle)
        ):
            return None
        return state, registration
    return None


def _apply(
    state: MemoryState, registration: WatchRegistration, kind: NoticeKind, at: datetime
) -> int:
    key = registration.id
    # Any authentic notice proves the provider reaches the installation through it.
    registration = replace(registration, confirmed_at=registration.confirmed_at or at)
    state.registrations[key] = registration
    if kind is NoticeKind.STARTED:
        return 0
    if kind is NoticeKind.REAUTHORIZE:
        asked = registration.renew_requested_at
        state.registrations[key] = replace(
            registration, renew_requested_at=max(asked, at) if asked else at
        )
        return 0
    if kind is NoticeKind.REMOVED and registration.state in _REMOVED_TO:
        state.registrations[key] = replace(registration, state=_REMOVED_TO[registration.state])
    return _request_runs(state, registration.watch_id, at)


def _request_runs(state: MemoryState, watch_id: CalendarWatchId, at: datetime) -> int:
    watch = state.watches.get(watch_id)
    if watch is None:
        return 0
    woken = [
        rule.id
        for rule in state.rules.values()
        if rule.state is SyncRuleState.ENABLED and watch.covers(rule.source)
    ]
    for rule_id in woken:
        raise_instant_request(state, rule_id, at)
    return len(woken)


def _refresh_success(
    database: MemoryDatabase, provider: ProviderKind, address: str, at: datetime
) -> None:
    kept = database.delivery_evidence.get((provider, address))
    latest = kept.last_success_at if kept else None
    failed_since = (
        kept is not None
        and latest is not None
        and kept.last_failure_at is not None
        and kept.last_failure_at >= latest
    )
    if latest is None or latest <= at - EVIDENCE_REFRESH or failed_since:
        InMemoryDeliveryEvidenceLog(database).succeeded(provider, address, at)


@dataclass(frozen=True, slots=True)
class InMemoryDeliveryEvidenceLog:
    database: MemoryDatabase

    def succeeded(self, provider: ProviderKind, address: str, at: datetime) -> None:
        kept = self._kept(provider, address)
        latest = kept.last_success_at
        self.database.delivery_evidence[(provider, address)] = replace(
            kept, last_success_at=max(latest, at) if latest else at
        )

    def failed(self, provider: ProviderKind, address: str, at: datetime) -> None:
        kept = self._kept(provider, address)
        latest = kept.last_failure_at
        self.database.delivery_evidence[(provider, address)] = replace(
            kept, last_failure_at=max(latest, at) if latest else at
        )

    def evidence(self, address: str) -> dict[ProviderKind, DeliveryEvidence]:
        return {
            provider: kept
            for (provider, kept_address), kept in sorted(
                self.database.delivery_evidence.items(), key=lambda item: item[0][0].value
            )
            if kept_address == address
        }

    def _kept(self, provider: ProviderKind, address: str) -> DeliveryEvidence:
        return self.database.delivery_evidence.get((provider, address)) or DeliveryEvidence(
            provider, address
        )


@dataclass(frozen=True, slots=True)
class InMemoryInstallationUnitOfWorkFactory:
    database: MemoryDatabase

    def __call__(self) -> InstallationUnitOfWork:
        return InMemoryInstallationUnitOfWork(self.database)
