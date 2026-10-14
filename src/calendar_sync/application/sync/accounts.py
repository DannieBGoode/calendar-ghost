from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime

from calendar_sync.application.sync.errors import (
    AccountAccessCheckFailed,
    ConnectedAccountMustBeDisconnected,
    ConnectedAccountNotFound,
    ProviderFailure,
)
from calendar_sync.application.sync.lapsed_authorization import LapsedAuthorizations
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.ports import (
    AccountAccess,
    AccountCalendars,
    ConnectedAccountRepository,
    DiscoveredCalendar,
    IncidentRepository,
    UnitOfWorkFactory,
)
from calendar_sync.domain.accounts import ConnectedAccount, ConnectedAccountState
from calendar_sync.domain.causes import ADMINISTRATOR_CAUSES
from calendar_sync.domain.model import ConnectedAccountId, SyncRule, SyncRuleId
from calendar_sync.domain.providers import AUTHORIZATION_FAILURES

logger = logging.getLogger(__name__)


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
class DiscoverCalendars:
    """List an account's calendars in its provider, remembering their names for its rules."""

    calendars: AccountCalendars
    unit_of_work: UnitOfWorkFactory
    accounts: ConnectedAccountRepository
    lapses: LapsedAuthorizations

    def execute(self, account_id: ConnectedAccountId) -> tuple[DiscoveredCalendar, ...]:
        # The provider answers for any account, so only the User's own may be asked about.
        with self.unit_of_work() as uow:
            if uow.accounts.state(account_id) is None:
                raise ConnectedAccountNotFound(
                    f"connected account {account_id.value} does not exist"
                )
        started = self.lapses.clock.now()
        try:
            discovered = tuple(self.calendars.calendars(account_id))
        except AccountAccessCheckFailed as error:
            _lapse_if_refused(self.accounts, self.lapses, account_id, error, started)
            raise
        # Recorded after the provider answered, so no write lock is held across the request.
        with self.unit_of_work() as uow:
            uow.calendar_names.remember(account_id, discovered)
            uow.commit()
        return discovered


@dataclass(frozen=True, slots=True)
class AccessCheck:
    access: AccountAccess
    rules_resumed: int
    """Rules that Lapsed Authorization alone had stopped, resumed because the check passed."""


@dataclass(slots=True)
class CheckAccountAccess:
    """Ask the provider whether it accepts the account, recording what it answered (ADR 0027).

    A refusal for authentication or authorization lapses the account; a passing check clears a
    lapse, as Reauthorization does, and resumes the rules the lapse alone stopped.
    """

    calendars: AccountCalendars
    accounts: ConnectedAccountRepository
    lapses: LapsedAuthorizations

    def execute(self, account_id: ConnectedAccountId) -> AccessCheck:
        # The provider answers for any account, so only the User's own may be asked about.
        if self.accounts.get(account_id) is None:
            raise ConnectedAccountNotFound(f"connected account {account_id.value} does not exist")
        started = self.lapses.clock.now()
        try:
            access = self.calendars.verify_access(account_id)
        except AccountAccessCheckFailed as error:
            _lapse_if_refused(self.accounts, self.lapses, account_id, error, started)
            raise
        return AccessCheck(access, self.lapses.restored(account_id, accepted_at=started))


@dataclass(slots=True)
class RecheckAdministratorLapses:
    """Check again each account an administrator's Cause stopped, such as an expired client
    secret or a provider API turned off (ADR 0031).

    Its owner cannot fix that Cause, so once the administrator has, the check passes and every
    rule the lapse alone stopped restarts, without each owner choosing Check access. A check
    that still fails changes nothing: the account stays lapsed and its open Incident notifies
    nobody again. A lapse with a Cause the owner fixes is left for them.
    """

    check: CheckAccountAccess
    incidents: IncidentRepository

    def execute(self) -> int:
        """How many rules restarted."""
        resumed = 0
        accounts = self.incidents.accounts_lapsed_by(ADMINISTRATOR_CAUSES)
        for account_id in sorted(accounts, key=lambda account: account.value):
            try:
                resumed += self.check.execute(account_id).rules_resumed
            except (AccountAccessCheckFailed, ConnectedAccountNotFound):
                continue
        return resumed


def _lapse_if_refused(
    accounts: ConnectedAccountRepository,
    lapses: LapsedAuthorizations,
    account_id: ConnectedAccountId,
    error: AccountAccessCheckFailed,
    started: datetime,
) -> None:
    """Lapse an account its provider refused for authentication or authorization (ADR 0027)."""
    if error.kind not in AUTHORIZATION_FAILURES:
        return
    account = accounts.get(account_id)
    failure = ProviderFailure(
        error.kind,
        str(error),
        account_id=account_id,
        provider=account.provider if account is not None else None,
        cause=error.cause,
    )
    lapses.lapsed(account_id, failure, attempted_at=started)


@dataclass(slots=True)
class DisconnectConnectedAccount:
    """Discard an account's credentials after degrading every rule that could still write.

    Each rule stops in its own transaction, then the account disconnects, so an interruption can
    leave some rules stopped and the account still connected. That state is safe: a stopped rule
    writes nothing and restarts only through a preview, as it would after the disconnection the
    User asked for. The User sees the account still connected and retries, which stops the
    remaining rules and then disconnects it. So retrying completes it, and it is not made atomic
    as deletion is. The account's Calendar Watches stop just before, best effort, while the
    credentials that stopping them needs still exist.
    """

    unit_of_work: UnitOfWorkFactory
    accounts: ConnectedAccountRepository
    locks: RuleLocks
    stop_watches: Callable[[ConnectedAccountId], None] = lambda _account: None
    """Stops and removes the account's Calendar Watches, best effort."""

    def execute(self, account_id: ConnectedAccountId) -> ConnectedAccountSummary:
        if not any(account.id == account_id for account in self.accounts.list()):
            raise ConnectedAccountNotFound(f"connected account {account_id.value} does not exist")
        with self.unit_of_work() as uow:
            affected = _affected_rules(uow.rules.list(), account_id)
        for rule_id in affected:
            # Waiting for an in-flight write means none happens with the account once degraded.
            with self.locks.for_writes(rule_id), self.unit_of_work() as uow:
                rule = uow.rules.get(rule_id)
                stopped = rule.on_account_disconnected() if rule is not None else None
                if stopped is not None and stopped != rule:
                    uow.rules.save(stopped)
                    uow.commit()
        _stop_watches(self.stop_watches, account_id)
        account = self.accounts.disconnect(account_id)
        with self.unit_of_work() as uow:
            rules = tuple(uow.rules.list())
        return _summary(account, rules)


def _stop_watches(
    stop: Callable[[ConnectedAccountId], None], account_id: ConnectedAccountId
) -> None:
    try:
        stop(account_id)
    except Exception:
        logger.exception("Could not stop the watches of a disconnecting account; they expire")


@dataclass(slots=True)
class DeleteConnectedAccount:
    """Permanently delete a Disconnected Account with every rule that uses it.

    The rules go with their mappings, cursors, incidents, and audit activity. Their Managed
    Projections stay in their calendars, no longer managed. Every affected rule is locked first,
    as Rule Removal locks its rule, so no run, write, or lifecycle change of those rules is in
    flight while their records are deleted. The state check, the rules it selects, and every
    deletion commit in one transaction, so a reauthorization or a new rule cannot interleave with
    them.
    """

    unit_of_work: UnitOfWorkFactory
    locks: RuleLocks

    def execute(self, account_id: ConnectedAccountId) -> int:
        with self.unit_of_work() as uow:
            _require_disconnected(uow.accounts.state(account_id), account_id)
            affected = _affected_rules(uow.rules.list(), account_id)
        while True:
            with ExitStack() as held:
                # One order for every caller, whole-run locks before write locks, as RuleLocks
                # requires, so two deletions cannot wait on each other.
                for rule_id in affected:
                    held.enter_context(self.locks.for_rule(rule_id))
                for rule_id in affected:
                    held.enter_context(self.locks.for_writes(rule_id))
                deleted = self._delete(account_id, affected)
                if deleted is not None:
                    return deleted
            # A rule was created for the account while waiting; lock it as well and try again.
            with self.unit_of_work() as uow:
                affected = _ordered({*affected, *_affected_rules(uow.rules.list(), account_id)})

    def _delete(self, account_id: ConnectedAccountId, locked: Sequence[SyncRuleId]) -> int | None:
        """Delete everything in one transaction; `None`, with nothing deleted, to retry."""
        with self.unit_of_work() as uow:
            # Deleting first holds the database's write lock for the rest of the transaction.
            if not uow.accounts.delete_disconnected(account_id):
                # Reauthorized, or deleted by another request, while waiting for the locks.
                _require_disconnected(uow.accounts.state(account_id), account_id)
            rules = _affected_rules(uow.rules.list(), account_id)
            if not set(rules) <= set(locked):
                return None
            for rule_id in rules:
                uow.rules.purge(rule_id)
            uow.commit()
        return len(rules)


def _require_disconnected(
    state: ConnectedAccountState | None, account_id: ConnectedAccountId
) -> None:
    if state is None:
        raise ConnectedAccountNotFound(f"connected account {account_id.value} does not exist")
    if state is not ConnectedAccountState.DISCONNECTED:
        raise ConnectedAccountMustBeDisconnected(
            "disconnect this account before deleting it permanently"
        )


def _affected_rules(
    rules: Sequence[SyncRule], account_id: ConnectedAccountId
) -> tuple[SyncRuleId, ...]:
    return _ordered(rule.id for rule in rules if rule.uses_account(account_id))


def _ordered(rule_ids: Iterable[SyncRuleId]) -> tuple[SyncRuleId, ...]:
    return tuple(sorted(rule_ids, key=lambda rule_id: rule_id.value))


def _summary(account: ConnectedAccount, rules: Sequence[SyncRule]) -> ConnectedAccountSummary:
    return ConnectedAccountSummary(
        account, sum(1 for rule in rules if rule.uses_account(account.id))
    )
