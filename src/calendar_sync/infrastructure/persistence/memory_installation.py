"""The in-memory installation-wide unit of work: what reaches across Users (ADR 0029)."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime
from types import TracebackType
from typing import Self

from calendar_sync.application.operations.ports import (
    AccountStanding,
    CauseSighting,
    InstallationUnitOfWork,
    OperationsOverview,
    ProviderCallUse,
    RecordedRule,
    ResourceUse,
    StatusRecords,
)
from calendar_sync.application.sync.ports import ProviderCallCounts, ScheduledRule
from calendar_sync.domain.access import UserId
from calendar_sync.domain.accounts import ConnectedAccountState, ProviderKind
from calendar_sync.domain.model import SyncRuleId, SyncRuleState
from calendar_sync.domain.runs import RunKind
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryIncidentRepository,
    MemoryDatabase,
    MemoryState,
)


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

    def forget_provider_calls(self, before: date) -> None:
        for state in self._database.partitions.values():
            state.provider_calls = {
                key: counts for key, counts in state.provider_calls.items() if key[1] >= before
            }

    def failure_causes(self, since: datetime) -> list[CauseSighting]:
        """Failed runs since `since`; Incidents are not read here."""
        return sorted(
            (
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
            ),
            key=lambda seen: (seen.user.value, seen.at),
        )

    def status_records(self, users: Collection[UserId]) -> dict[UserId, StatusRecords]:
        return {user: _status_records(self._database.partitions.get(user)) for user in users}


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


def _status_records(state: MemoryState | None) -> StatusRecords:
    """A User's records as Installation Status reads them. This store reads no Incidents here and
    keeps no Activity blocks. It knows an account's provider only when a test recorded one, so an
    account without one counts but has no standing."""
    state = state or MemoryState()
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
        # Rules keep the order they were added in, as a dictionary keeps its keys'.
        rules=tuple(
            RecordedRule(
                rule, state.outcomes.get((rule.id, RunKind.SYNC)), state.previews.get(rule.id)
            )
            for rule in state.rules.values()
        ),
        overview=OperationsOverview(
            connected_accounts=sum(s is ConnectedAccountState.CONNECTED for s in standings),
            disconnected_accounts=sum(s is ConnectedAccountState.DISCONNECTED for s in standings),
            open_incidents=0,
            last_synced_at=max(succeeded) if succeeded else None,
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
