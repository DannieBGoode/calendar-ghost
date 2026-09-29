from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from threading import Lock, Thread

import pytest

from calendar_sync.application.accounts import (
    DeleteConnectedAccount,
    DisconnectConnectedAccount,
    ListConnectedAccounts,
)
from calendar_sync.application.errors import ConnectedAccountNotFound
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import ConnectedAccount
from calendar_sync.domain.model import ConnectedAccountId, SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.helpers import endpoint

ACCOUNT = ConnectedAccountId("personal")


def _rule(rule_id: str, account: str) -> SyncRule:
    return SyncRule(
        SyncRuleId(rule_id),
        endpoint(account, f"{rule_id}-source"),
        endpoint("work", f"{rule_id}-destination"),
        state=SyncRuleState.DEGRADED,
    )


class RecordingAccounts:
    def __init__(self, *accounts: ConnectedAccount) -> None:
        self.accounts = {account.id: account for account in accounts}
        self.deleted: list[ConnectedAccountId] = []

    def list(self) -> tuple[ConnectedAccount, ...]:
        return tuple(self.accounts.values())

    def is_connected(self, account_id: ConnectedAccountId) -> bool:
        account = self.accounts.get(account_id)
        return account is not None and account.state == "connected"

    def disconnect(self, account_id: ConnectedAccountId) -> ConnectedAccount:
        if account_id not in self.accounts:
            raise ConnectedAccountNotFound(f"connected account {account_id.value} does not exist")
        self.accounts[account_id] = replace(self.accounts[account_id], state="disconnected")
        return self.accounts[account_id]

    def delete(self, account_id: ConnectedAccountId) -> int:
        self.deleted.append(account_id)
        return 1


def _with_rules(*rules: SyncRule) -> InMemoryUnitOfWorkFactory:
    unit_of_work = InMemoryUnitOfWorkFactory()
    with unit_of_work() as uow:
        for rule in rules:
            uow.rules.add(rule)
        uow.commit()
    return unit_of_work


def _use_case(*rules: SyncRule) -> tuple[DeleteConnectedAccount, RecordingAccounts, RuleLocks]:
    accounts = RecordingAccounts()
    locks = RuleLocks()
    return DeleteConnectedAccount(_with_rules(*rules), accounts, locks), accounts, locks


def _blocked_while_held(lock: Lock, delete: Callable[[], object]) -> bool:
    lock.acquire()
    worker = Thread(target=delete)
    worker.start()
    worker.join(0.2)
    blocked = worker.is_alive()
    lock.release()
    worker.join(2)
    assert not worker.is_alive()
    return blocked


def test_deletion_waits_for_an_in_flight_run_of_an_affected_rule() -> None:
    affected = _rule("affected", ACCOUNT.value)
    delete, accounts, locks = _use_case(affected)

    blocked = _blocked_while_held(locks.for_rule(affected.id), lambda: delete.execute(ACCOUNT))

    assert blocked
    assert accounts.deleted == [ACCOUNT]


def test_deletion_waits_for_an_in_flight_write_of_an_affected_rule() -> None:
    affected = _rule("affected", "other")
    affected = SyncRule(
        affected.id, affected.source, endpoint(ACCOUNT.value, "destination"), state=affected.state
    )
    delete, accounts, locks = _use_case(affected)

    blocked = _blocked_while_held(locks.for_writes(affected.id), lambda: delete.execute(ACCOUNT))

    assert blocked
    assert accounts.deleted == [ACCOUNT]


def test_deletion_does_not_wait_for_rules_of_other_accounts() -> None:
    unrelated = _rule("unrelated", "other")
    delete, accounts, locks = _use_case(unrelated)

    blocked = _blocked_while_held(locks.for_rule(unrelated.id), lambda: delete.execute(ACCOUNT))

    assert not blocked
    assert accounts.deleted == [ACCOUNT]


def _account(account_id: str = ACCOUNT.value) -> ConnectedAccount:
    return ConnectedAccount(
        ConnectedAccountId(account_id), "Personal", f"{account_id}@example.test", "connected"
    )


def test_accounts_are_listed_with_the_number_of_rules_using_them() -> None:
    both_ends = SyncRule(
        SyncRuleId("both"), endpoint(ACCOUNT.value, "a"), endpoint(ACCOUNT.value, "b")
    )
    unit_of_work = _with_rules(_rule("affected", ACCOUNT.value), both_ends, _rule("other", "x"))
    accounts = RecordingAccounts(_account(), _account("unused"))

    listed = ListConnectedAccounts(unit_of_work, accounts).execute()

    assert [(item.account.id.value, item.rule_count) for item in listed] == [
        ("personal", 2),
        ("unused", 0),
    ]


def test_disconnecting_degrades_validated_and_enabled_rules_only() -> None:
    states = {
        "enabled": SyncRuleState.ENABLED,
        "validated": SyncRuleState.DRY_RUN_VALIDATED,
        "paused": SyncRuleState.PAUSED,
        "draft": SyncRuleState.DRAFT,
    }
    rules = [replace(_rule(name, ACCOUNT.value), state=state) for name, state in states.items()]
    unrelated = replace(_rule("unrelated", "other"), state=SyncRuleState.ENABLED)
    unit_of_work = _with_rules(*rules, unrelated)
    accounts = RecordingAccounts(_account())

    disconnected = DisconnectConnectedAccount(unit_of_work, accounts, RuleLocks()).execute(ACCOUNT)

    assert disconnected.account.state == "disconnected"
    assert disconnected.rule_count == 4
    assert {rule_id.value: rule.state for rule_id, rule in unit_of_work.state.rules.items()} == {
        "enabled": SyncRuleState.DEGRADED,
        "validated": SyncRuleState.DEGRADED,
        "paused": SyncRuleState.PAUSED,
        "draft": SyncRuleState.DRAFT,
        "unrelated": SyncRuleState.ENABLED,
    }


def test_disconnecting_an_unknown_account_changes_no_rule() -> None:
    affected = replace(_rule("affected", ACCOUNT.value), state=SyncRuleState.ENABLED)
    unit_of_work = _with_rules(affected)

    with pytest.raises(ConnectedAccountNotFound):
        DisconnectConnectedAccount(unit_of_work, RecordingAccounts(), RuleLocks()).execute(ACCOUNT)

    assert unit_of_work.state.rules[affected.id].state is SyncRuleState.ENABLED


def test_disconnecting_waits_for_an_in_flight_write_of_an_affected_rule() -> None:
    affected = replace(_rule("affected", ACCOUNT.value), state=SyncRuleState.ENABLED)
    unit_of_work = _with_rules(affected)
    locks = RuleLocks()
    disconnect = DisconnectConnectedAccount(unit_of_work, RecordingAccounts(_account()), locks)

    blocked = _blocked_while_held(
        locks.for_writes(affected.id), lambda: disconnect.execute(ACCOUNT)
    )

    assert blocked
    assert unit_of_work.state.rules[affected.id].state is SyncRuleState.DEGRADED
