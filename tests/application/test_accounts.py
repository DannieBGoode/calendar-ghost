from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from threading import Lock, Thread
from typing import cast

import pytest

from calendar_sync.application.accounts import (
    CheckAccountAccess,
    DeleteConnectedAccount,
    DisconnectConnectedAccount,
    DiscoverCalendars,
    ListConnectedAccounts,
)
from calendar_sync.application.errors import (
    ConnectedAccountMustBeDisconnected,
    ConnectedAccountNotFound,
)
from calendar_sync.application.lapsed_authorization import LapsedAuthorizations
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    AccountAccess,
    AuditAction,
    AuditEntry,
    AuditOutcome,
    CalendarAccess,
    ConnectedAccount,
    ConnectedAccountState,
    DiscoveredCalendar,
    IncidentRepository,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId, SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryUnitOfWorkFactory,
    InMemoryUserUnitOfWorkFactory,
)
from tests.fake_calendar import FixedClock
from tests.helpers import NOW, endpoint
from tests.users import OTHER_USER, USER

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


def _with_rules(*rules: SyncRule) -> InMemoryUserUnitOfWorkFactory:
    unit_of_work = InMemoryUnitOfWorkFactory().for_user(USER)
    with unit_of_work() as uow:
        for rule in rules:
            uow.rules.add(rule)
        uow.commit()
    return unit_of_work


def _deletion(
    *rules: SyncRule, state: ConnectedAccountState | None = ConnectedAccountState.DISCONNECTED
) -> tuple[DeleteConnectedAccount, InMemoryUserUnitOfWorkFactory, RuleLocks]:
    unit_of_work = _with_rules(*rules)
    if state is not None:
        unit_of_work.state.accounts[ACCOUNT] = state
    locks = RuleLocks()
    return DeleteConnectedAccount(unit_of_work, locks), unit_of_work, locks


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
    delete, unit_of_work, locks = _deletion(affected)

    blocked = _blocked_while_held(locks.for_rule(affected.id), lambda: delete.execute(ACCOUNT))

    assert blocked
    assert ACCOUNT not in unit_of_work.state.accounts


def test_deletion_waits_for_an_in_flight_write_of_an_affected_rule() -> None:
    affected = _rule("affected", "other")
    affected = SyncRule(
        affected.id, affected.source, endpoint(ACCOUNT.value, "destination"), state=affected.state
    )
    delete, unit_of_work, locks = _deletion(affected)

    blocked = _blocked_while_held(locks.for_writes(affected.id), lambda: delete.execute(ACCOUNT))

    assert blocked
    assert ACCOUNT not in unit_of_work.state.accounts


def test_deletion_does_not_wait_for_rules_of_other_accounts() -> None:
    unrelated = _rule("unrelated", "other")
    delete, unit_of_work, locks = _deletion(unrelated)

    blocked = _blocked_while_held(locks.for_rule(unrelated.id), lambda: delete.execute(ACCOUNT))

    assert not blocked
    assert ACCOUNT not in unit_of_work.state.accounts


def _account(
    account_id: str = ACCOUNT.value, state: ConnectedAccountState = ConnectedAccountState.CONNECTED
) -> ConnectedAccount:
    return ConnectedAccount(
        ConnectedAccountId(account_id),
        "Personal",
        f"{account_id}@example.test",
        state,
        provider=ProviderKind.GOOGLE,
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
        "validated": SyncRuleState.PREVIEWED,
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


def test_disconnecting_makes_a_rule_awaiting_reauthorization_need_a_preview() -> None:
    enabled = replace(_rule("stopped", ACCOUNT.value), state=SyncRuleState.ENABLED)
    stopped = enabled.degrade(awaiting_reauthorization=True)
    unit_of_work = _with_rules(stopped)

    DisconnectConnectedAccount(unit_of_work, RecordingAccounts(_account()), RuleLocks()).execute(
        ACCOUNT
    )

    kept = unit_of_work.state.rules[stopped.id]
    assert (kept.state, kept.awaiting_reauthorization) == (SyncRuleState.DEGRADED, False)


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
    delete, unit_of_work, _ = _deletion(affected, unrelated)
    with unit_of_work() as uow:
        for recorded in (affected, unrelated):
            uow.audit.append(
                AuditEntry(NOW, recorded.id, AuditAction.CREATE, AuditOutcome.COMPLETED)
            )
        uow.commit()

    deleted = delete.execute(ACCOUNT)

    assert deleted == 1
    assert ACCOUNT not in unit_of_work.state.accounts
    assert list(unit_of_work.state.rules) == [unrelated.id]
    assert [entry.rule_id for entry in unit_of_work.state.audit] == [unrelated.id]


def test_deletion_is_refused_for_a_connected_or_unknown_account() -> None:
    affected = _rule("affected", ACCOUNT.value)
    connected, unit_of_work, _ = _deletion(affected, state=ConnectedAccountState.CONNECTED)
    unknown, _, _ = _deletion(affected, state=None)

    with pytest.raises(ConnectedAccountMustBeDisconnected):
        connected.execute(ACCOUNT)
    with pytest.raises(ConnectedAccountNotFound):
        unknown.execute(ACCOUNT)

    assert unit_of_work.state.accounts == {ACCOUNT: ConnectedAccountState.CONNECTED}
    assert list(unit_of_work.state.rules) == [affected.id]


def test_deletion_also_locks_and_purges_a_rule_created_while_it_waited() -> None:
    affected = _rule("affected", ACCOUNT.value)
    late = _rule("late", ACCOUNT.value)
    delete, unit_of_work, locks = _deletion(affected)
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
    assert ACCOUNT not in unit_of_work.state.accounts


def test_deletion_is_refused_when_the_account_is_reauthorized_while_it_waited() -> None:
    affected = _rule("affected", ACCOUNT.value)
    deletion, unit_of_work, locks = _deletion(affected)
    errors: list[Exception] = []

    def delete() -> None:
        try:
            deletion.execute(ACCOUNT)
        except ConnectedAccountMustBeDisconnected as error:
            errors.append(error)

    running = locks.for_rule(affected.id)
    running.acquire()
    worker = Thread(target=delete)
    worker.start()
    worker.join(0.1)
    unit_of_work.state.accounts[ACCOUNT] = ConnectedAccountState.CONNECTED
    running.release()
    worker.join(2)

    assert len(errors) == 1
    assert unit_of_work.state.accounts == {ACCOUNT: ConnectedAccountState.CONNECTED}
    assert list(unit_of_work.state.rules) == [affected.id]


class CountingCalendars:
    """A provider that answers for any account, so only the use case can refuse one."""

    def __init__(self) -> None:
        self.asked: list[ConnectedAccountId] = []

    def calendars(self, account_id: ConnectedAccountId) -> tuple[DiscoveredCalendar, ...]:
        self.asked.append(account_id)
        return (DiscoveredCalendar("primary", "Family", CalendarAccess.OWNER, primary=True),)

    def verify_access(self, account_id: ConnectedAccountId) -> AccountAccess:
        self.asked.append(account_id)
        return AccountAccess(calendars_visible=1, writable_calendars=1)


def test_discovering_calendars_of_another_users_account_asks_no_provider() -> None:
    database = InMemoryUnitOfWorkFactory()
    database.for_user(OTHER_USER).state.accounts[ACCOUNT] = ConnectedAccountState.CONNECTED
    calendars = CountingCalendars()
    discover = DiscoverCalendars(calendars, database.for_user(USER))

    with pytest.raises(ConnectedAccountNotFound):
        discover.execute(ACCOUNT)

    assert calendars.asked == []
    assert database.for_user(OTHER_USER).state.calendar_names == {}


def test_checking_access_of_another_users_account_asks_no_provider() -> None:
    units = InMemoryUnitOfWorkFactory().for_user(USER)
    calendars = CountingCalendars()
    check = CheckAccountAccess(
        calendars,
        RecordingAccounts(),
        LapsedAuthorizations(units, cast(IncidentRepository, None), FixedClock()),
    )

    with pytest.raises(ConnectedAccountNotFound):
        check.execute(ACCOUNT)

    assert calendars.asked == []
