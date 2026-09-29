from __future__ import annotations

from collections.abc import Callable
from threading import Lock, Thread

from calendar_sync.application.accounts import DeleteConnectedAccount
from calendar_sync.application.locking import RuleLocks
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
    def __init__(self) -> None:
        self.deleted: list[ConnectedAccountId] = []

    def delete(self, account_id: ConnectedAccountId) -> int:
        self.deleted.append(account_id)
        return 1


def _use_case(*rules: SyncRule) -> tuple[DeleteConnectedAccount, RecordingAccounts, RuleLocks]:
    unit_of_work = InMemoryUnitOfWorkFactory()
    with unit_of_work() as uow:
        for rule in rules:
            uow.rules.add(rule)
        uow.commit()
    accounts = RecordingAccounts()
    locks = RuleLocks()
    return DeleteConnectedAccount(unit_of_work, accounts, locks), accounts, locks


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
