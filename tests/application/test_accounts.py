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
from calendar_sync.application.errors import (
    ConnectedAccountMustBeDisconnected,
    ConnectedAccountNotFound,
)
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import AuditEntry, ConnectedAccount, ConnectedAccountState
from calendar_sync.domain.model import ConnectedAccountId, SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.helpers import NOW, endpoint

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
        return account is not None and account.state is ConnectedAccountState.CONNECTED

    def disconnect(self, account_id: ConnectedAccountId) -> ConnectedAccount:
        if account_id not in self.accounts:
            raise ConnectedAccountNotFound(f"connected account {account_id.value} does not exist")
        self.accounts[account_id] = replace(
            self.accounts[account_id], state=ConnectedAccountState.DISCONNECTED
        )
        return self.accounts[account_id]

    def get(self, account_id: ConnectedAccountId) -> ConnectedAccount | None:
        return self.accounts.get(account_id)

    def delete(self, account_id: ConnectedAccountId) -> None:
        del self.accounts[account_id]
        self.deleted.append(account_id)


def _with_rules(*rules: SyncRule) -> InMemoryUnitOfWorkFactory:
    unit_of_work = InMemoryUnitOfWorkFactory()
    with unit_of_work() as uow:
        for rule in rules:
            uow.rules.add(rule)
        uow.commit()
    return unit_of_work


def _use_case(*rules: SyncRule) -> tuple[DeleteConnectedAccount, RecordingAccounts, RuleLocks]:
    accounts = RecordingAccounts(_account(state=ConnectedAccountState.DISCONNECTED))
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


def _account(
    account_id: str = ACCOUNT.value, state: ConnectedAccountState = ConnectedAccountState.CONNECTED
) -> ConnectedAccount:
    return ConnectedAccount(
        ConnectedAccountId(account_id), "Personal", f"{account_id}@example.test", state
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

    assert disconnected.account.state is ConnectedAccountState.DISCONNECTED
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


def test_deletion_purges_every_rule_using_the_account_and_then_the_account() -> None:
    affected = _rule("affected", ACCOUNT.value)
    unrelated = _rule("unrelated", "other")
    unit_of_work = _with_rules(affected, unrelated)
    with unit_of_work() as uow:
        for recorded in (affected, unrelated):
            uow.audit.append(AuditEntry(NOW, recorded.id, "create", "completed"))
        uow.commit()
    accounts = RecordingAccounts(_account(state=ConnectedAccountState.DISCONNECTED))

    deleted = DeleteConnectedAccount(unit_of_work, accounts, RuleLocks()).execute(ACCOUNT)

    assert deleted == 1
    assert accounts.deleted == [ACCOUNT]
    assert list(unit_of_work.state.rules) == [unrelated.id]
    assert [entry.rule_id for entry in unit_of_work.state.audit] == [unrelated.id]


def test_deletion_is_refused_for_a_connected_or_unknown_account() -> None:
    affected = _rule("affected", ACCOUNT.value)
    unit_of_work = _with_rules(affected)
    connected = RecordingAccounts(_account())

    with pytest.raises(ConnectedAccountMustBeDisconnected):
        DeleteConnectedAccount(unit_of_work, connected, RuleLocks()).execute(ACCOUNT)
    with pytest.raises(ConnectedAccountNotFound):
        DeleteConnectedAccount(unit_of_work, RecordingAccounts(), RuleLocks()).execute(ACCOUNT)

    assert connected.deleted == []
    assert list(unit_of_work.state.rules) == [affected.id]


def test_deletion_also_locks_and_purges_a_rule_created_while_it_waited() -> None:
    affected = _rule("affected", ACCOUNT.value)
    late = _rule("late", ACCOUNT.value)
    unit_of_work = _with_rules(affected)
    accounts = RecordingAccounts(_account(state=ConnectedAccountState.DISCONNECTED))
    locks = RuleLocks()
    delete = DeleteConnectedAccount(unit_of_work, accounts, locks)
    running = locks.for_rule(affected.id)
    running.acquire()
    worker = Thread(target=delete.execute, args=(ACCOUNT,))
    worker.start()
    worker.join(0.1)
    with unit_of_work() as uow:
        uow.rules.add(late)
        uow.commit()
    late_run = locks.for_rule(late.id)
    late_run.acquire()
    running.release()
    worker.join(0.2)
    waited_for_the_late_rule = worker.is_alive()
    late_run.release()
    worker.join(2)

    assert waited_for_the_late_rule
    assert unit_of_work.state.rules == {}
    assert accounts.deleted == [ACCOUNT]


def test_deletion_is_refused_when_the_account_is_reauthorized_while_it_waited() -> None:
    affected = _rule("affected", ACCOUNT.value)
    unit_of_work = _with_rules(affected)
    accounts = RecordingAccounts(_account(state=ConnectedAccountState.DISCONNECTED))
    locks = RuleLocks()
    errors: list[Exception] = []

    def delete() -> None:
        try:
            DeleteConnectedAccount(unit_of_work, accounts, locks).execute(ACCOUNT)
        except ConnectedAccountMustBeDisconnected as error:
            errors.append(error)

    running = locks.for_rule(affected.id)
    running.acquire()
    worker = Thread(target=delete)
    worker.start()
    worker.join(0.1)
    accounts.accounts[ACCOUNT] = _account()
    running.release()
    worker.join(2)

    assert len(errors) == 1
    assert accounts.deleted == []
    assert list(unit_of_work.state.rules) == [affected.id]
