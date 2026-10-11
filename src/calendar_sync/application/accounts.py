from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass

from calendar_sync.application.errors import (
    AUTHORIZATION_FAILURES,
    AccountAccessCheckFailed,
    ConnectedAccountMustBeDisconnected,
    ConnectedAccountNotFound,
    ProviderFailure,
)
from calendar_sync.application.lapsed_authorization import LapsedAuthorizations
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    AccountAccess,
    AccountCalendars,
    ConnectedAccount,
    ConnectedAccountRepository,
    ConnectedAccountState,
    DiscoveredCalendar,
    UnitOfWorkFactory,
)
from calendar_sync.domain.model import ConnectedAccountId, SyncRule, SyncRuleId, SyncRuleState

# States that could still write, or be enabled, without the account's authorization.
_DEGRADED_ON_DISCONNECT = frozenset({SyncRuleState.PREVIEWED, SyncRuleState.ENABLED})


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

    def execute(self, account_id: ConnectedAccountId) -> tuple[DiscoveredCalendar, ...]:
        # The provider answers for any account, so only the User's own may be asked about.
        with self.unit_of_work() as uow:
            if uow.accounts.state(account_id) is None:
                raise ConnectedAccountNotFound(
                    f"connected account {account_id.value} does not exist"
                )
        discovered = tuple(self.calendars.calendars(account_id))
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
            if error.kind in AUTHORIZATION_FAILURES:
                account = self.accounts.get(account_id)
                provider = account.provider if account is not None else None
                failure = ProviderFailure(
                    error.kind,
                    str(error),
                    account_id=account_id,
                    provider=provider,
                    cause=error.cause,
                )
                self.lapses.lapsed(account_id, failure, attempted_at=started)
            raise
        return AccessCheck(access, self.lapses.restored(account_id, accepted_at=started))


@dataclass(slots=True)
class DisconnectConnectedAccount:
    """Discard an account's credentials after degrading every rule that could still write."""

    unit_of_work: UnitOfWorkFactory
    accounts: ConnectedAccountRepository
    locks: RuleLocks

    def execute(self, account_id: ConnectedAccountId) -> ConnectedAccountSummary:
        if not any(account.id == account_id for account in self.accounts.list()):
            raise ConnectedAccountNotFound(f"connected account {account_id.value} does not exist")
        with self.unit_of_work() as uow:
            affected = _affected_rules(uow.rules.list(), account_id)
        for rule_id in affected:
            # Waiting for an in-flight write means none happens with the account once degraded.
            with self.locks.for_writes(rule_id), self.unit_of_work() as uow:
                rule = uow.rules.get(rule_id)
                if rule is not None and rule.state in _DEGRADED_ON_DISCONNECT:
                    uow.rules.save(rule.degrade())
                    uow.commit()
                elif rule is not None and rule.awaiting_reauthorization:
                    # Disconnecting is a deliberate stop, so recovering needs a preview.
                    uow.rules.save(rule.require_preview())
                    uow.commit()
        account = self.accounts.disconnect(account_id)
        with self.unit_of_work() as uow:
            rules = tuple(uow.rules.list())
        return _summary(account, rules)


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
