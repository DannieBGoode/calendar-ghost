"""Your plan: what the signed-in User's Plan allows them, and how much of it they have (ADR 0038).

A read model across sync, which counts rules and accounts, and identity, which counts tokens. The
limits themselves are checked where each resource is added, inside its own transaction; this only
shows them, and lets the Web UI disable Connect and issuing a token before the server refuses.
"""

from __future__ import annotations

from dataclasses import dataclass

from calendar_sync.application.identity.ports import IntegrationTokens
from calendar_sync.application.operations.own_plan_holds import OwnPlanGrace, grace_view
from calendar_sync.application.sync.account_ports import ConnectedAccountRepository
from calendar_sync.application.sync.plan_ports import Allowances
from calendar_sync.application.sync.ports import UnitOfWorkFactory
from calendar_sync.domain.access import UserId
from calendar_sync.domain.plan_hold import RulePlace, RuleStanding
from calendar_sync.domain.plans import Allowance, exceeds, has_room


@dataclass(frozen=True, slots=True)
class OwnPlan:
    """A User's Allowance beside what counts toward each of its limits."""

    allowance: Allowance
    rules_counted: int
    """Rules that count toward the rule limit: enabled, stopped only by Lapsed Authorization, or
    a Rule Replacement draft that keeps its place."""
    connected_accounts: int
    """Every Connected Account, Disconnected Accounts included."""
    integration_tokens: int
    """Integration Tokens not revoked."""
    held_rules: int = 0
    grace: OwnPlanGrace | None = None
    rules: tuple[RuleStanding, ...] = ()
    """Owned eligible keep choices in kept, oldest, identifier rank order."""

    @property
    def may_connect_account(self) -> bool:
        """Whether a new calendar account fits; Reauthorization always does."""
        return has_room(self.connected_accounts, self.allowance.limits.connected_accounts)

    @property
    def may_issue_token(self) -> bool:
        return has_room(self.integration_tokens, self.allowance.limits.integration_tokens)

    @property
    def over_rule_limit(self) -> bool:
        """Whether more rules count than the Allowance permits; held rules are excluded."""
        return exceeds(self.rules_counted, self.allowance.limits.rules)


@dataclass(slots=True)
class ShowOwnPlan:
    """What the signed-in User's Plan allows and how much of it they have, for Your plan."""

    allowances: Allowances
    unit_of_work: UnitOfWorkFactory
    accounts: ConnectedAccountRepository | None
    """None without the Installation Master Key, where no account is stored: none count."""
    tokens: IntegrationTokens
    owner: UserId

    def execute(self) -> OwnPlan:
        """Raises when the Allowance cannot be read: an Allowance made up here would show a
        Plan that is not theirs, and the Web UI reads a failure as no hints (ADR 0038)."""
        allowance = self.allowances.of(self.owner)
        with self.unit_of_work() as uow:
            standings = tuple(uow.rules.standings())
            held = sum(each.place is RulePlace.HELD for each in standings)
            grace = grace_view(
                uow.plan_grace.get(), standings, allowance.limits.rules, uow.plan_grace.admissions()
            )
        accounts = len(self.accounts.list()) if self.accounts is not None else 0
        tokens = sum(1 for token in self.tokens.list() if token.revoked_at is None)
        return OwnPlan(allowance, len(standings) - held, accounts, tokens, held, grace, standings)
