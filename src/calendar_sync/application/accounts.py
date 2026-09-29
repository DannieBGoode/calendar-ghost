from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass

from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import ConnectedAccountDeletion, UnitOfWorkFactory
from calendar_sync.domain.model import ConnectedAccountId, SyncRule, SyncRuleId


@dataclass(slots=True)
class DeleteConnectedAccount:
    """Permanently delete a Disconnected Account with every rule that uses it.

    Every affected rule is locked first, as Rule Removal locks its rule, so no run, write, or
    lifecycle change of those rules is in flight while their records are deleted.
    """

    unit_of_work: UnitOfWorkFactory
    accounts: ConnectedAccountDeletion
    locks: RuleLocks

    def execute(self, account_id: ConnectedAccountId) -> int:
        affected = self._affected_rules(account_id)
        while True:
            with ExitStack() as held:
                # One order for every caller, whole-run locks before write locks, as RuleLocks
                # requires, so two deletions cannot wait on each other.
                for rule_id in affected:
                    held.enter_context(self.locks.for_rule(rule_id))
                for rule_id in affected:
                    held.enter_context(self.locks.for_writes(rule_id))
                current = self._affected_rules(account_id)
                # A rule created for the account while waiting must be locked as well.
                if set(current) <= set(affected):
                    return self.accounts.delete(account_id)
            affected = tuple(sorted({*affected, *current}, key=lambda rule_id: rule_id.value))

    def _affected_rules(self, account_id: ConnectedAccountId) -> tuple[SyncRuleId, ...]:
        with self.unit_of_work() as uow:
            rules = uow.rules.list()
        return tuple(
            sorted(
                (rule.id for rule in rules if _uses_account(rule, account_id)),
                key=lambda rule_id: rule_id.value,
            )
        )


def _uses_account(rule: SyncRule, account_id: ConnectedAccountId) -> bool:
    return account_id in {rule.source.connected_account_id, rule.destination.connected_account_id}
