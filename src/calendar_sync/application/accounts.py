from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass

from calendar_sync.application.errors import (
    ConnectedAccountMustBeDisconnected,
    ConnectedAccountNotFound,
)
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    ConnectedAccount,
    ConnectedAccountRepository,
    ConnectedAccountState,
    UnitOfWorkFactory,
)
from calendar_sync.domain.model import ConnectedAccountId, SyncRule, SyncRuleId, SyncRuleState

# States that could still write, or be enabled, without the account's authorization.
_DEGRADED_ON_DISCONNECT = frozenset({SyncRuleState.DRY_RUN_VALIDATED, SyncRuleState.ENABLED})


@dataclass(frozen=True, slots=True)
class ConnectedAccountSummary:
    account: ConnectedAccount
    rule_count: int
    """How many rules use the account as their source or destination."""


@dataclass(slots=True)
class ListConnectedAccounts:
    unit_of_work: UnitOfWorkFactory
    accounts: ConnectedAccountRepository

    def execute(self) -> tuple[ConnectedAccountSummary, ...]:
        with self.unit_of_work() as uow:
            rules = tuple(uow.rules.list())
        return tuple(_summary(account, rules) for account in self.accounts.list())


@dataclass(slots=True)
class DisconnectConnectedAccount:
    """Discard an account's credentials after degrading every rule that could still write."""

    unit_of_work: UnitOfWorkFactory
    accounts: ConnectedAccountRepository
    locks: RuleLocks

    def execute(self, account_id: ConnectedAccountId) -> ConnectedAccountSummary:
        if not any(account.id == account_id for account in self.accounts.list()):
            raise ConnectedAccountNotFound(f"connected account {account_id.value} does not exist")
        for rule_id in _affected_rules(self.unit_of_work, account_id):
            # Waiting for an in-flight write means none happens with the account once degraded.
            with self.locks.for_writes(rule_id), self.unit_of_work() as uow:
                rule = uow.rules.get(rule_id)
                if rule is not None and rule.state in _DEGRADED_ON_DISCONNECT:
                    uow.rules.save(rule.degrade())
                    uow.commit()
        account = self.accounts.disconnect(account_id)
        with self.unit_of_work() as uow:
            rules = tuple(uow.rules.list())
        return _summary(account, rules)


@dataclass(slots=True)
class DeleteConnectedAccount:
    """Permanently delete a Disconnected Account with every rule that uses it.

    The rules go with their mappings, cursors, incidents, and audit activity. Their Managed
    Projections stay in Google, no longer managed. Every affected rule is locked first, as Rule
    Removal locks its rule, so no run, write, or lifecycle change of those rules is in flight
    while their records are deleted.
    """

    unit_of_work: UnitOfWorkFactory
    accounts: ConnectedAccountRepository
    locks: RuleLocks

    def execute(self, account_id: ConnectedAccountId) -> int:
        self._require_disconnected(account_id)
        affected = _affected_rules(self.unit_of_work, account_id)
        while True:
            with ExitStack() as held:
                # One order for every caller, whole-run locks before write locks, as RuleLocks
                # requires, so two deletions cannot wait on each other.
                for rule_id in affected:
                    held.enter_context(self.locks.for_rule(rule_id))
                for rule_id in affected:
                    held.enter_context(self.locks.for_writes(rule_id))
                # The account may have been reauthorized, or a rule created for it, while waiting.
                self._require_disconnected(account_id)
                current = _affected_rules(self.unit_of_work, account_id)
                if set(current) <= set(affected):
                    return self._delete(account_id, current)
            affected = _ordered({*affected, *current})

    def _require_disconnected(self, account_id: ConnectedAccountId) -> None:
        account = self.accounts.get(account_id)
        if account is None:
            raise ConnectedAccountNotFound(f"connected account {account_id.value} does not exist")
        if account.state is not ConnectedAccountState.DISCONNECTED:
            raise ConnectedAccountMustBeDisconnected(
                "disconnect this Google account before deleting it permanently"
            )

    def _delete(self, account_id: ConnectedAccountId, rules: Sequence[SyncRuleId]) -> int:
        with self.unit_of_work() as uow:
            for rule_id in rules:
                uow.rules.purge(rule_id)
            uow.commit()
        # Last, so an interrupted deletion leaves a Disconnected Account to delete again.
        self.accounts.delete(account_id)
        return len(rules)


def _affected_rules(
    unit_of_work: UnitOfWorkFactory, account_id: ConnectedAccountId
) -> tuple[SyncRuleId, ...]:
    with unit_of_work() as uow:
        rules = uow.rules.list()
    return _ordered(rule.id for rule in rules if _uses_account(rule, account_id))


def _ordered(rule_ids: Iterable[SyncRuleId]) -> tuple[SyncRuleId, ...]:
    return tuple(sorted(rule_ids, key=lambda rule_id: rule_id.value))


def _summary(account: ConnectedAccount, rules: Sequence[SyncRule]) -> ConnectedAccountSummary:
    return ConnectedAccountSummary(
        account, sum(1 for rule in rules if _uses_account(rule, account.id))
    )


def _uses_account(rule: SyncRule, account_id: ConnectedAccountId) -> bool:
    return account_id in {rule.source.connected_account_id, rule.destination.connected_account_id}
