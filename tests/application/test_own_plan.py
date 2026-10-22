"""Your plan: what the signed-in User's Plan allows them, and how much of it they have."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import timedelta

import pytest

from calendar_sync.application.identity.ports import (
    AssignmentChange,
    IntegrationTokenScope,
    IntegrationTokenSummary,
    IssuedIntegrationToken,
)
from calendar_sync.application.operations.own_plan import OwnPlan, ShowOwnPlan
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.domain.accounts import ConnectedAccount, ConnectedAccountState, ProviderKind
from calendar_sync.domain.model import ConnectedAccountId, SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.domain.plan_hold import PlanGrace, RulePlace, RuleStanding
from calendar_sync.domain.plans import (
    Allowance,
    AllowanceBasis,
    AssignmentSource,
    Plan,
    PlanKey,
    PlanLimits,
    SyncInterval,
)
from tests.application.test_accounts import RecordingAccounts
from tests.helpers import NOW, endpoint
from tests.identity_fakes import BrokenAllowances, MemoryPlans
from tests.plans import FAMILY, FREE, plans_on
from tests.users import memory_units

ADMIN = User(
    UserId("admin"), "admin@example.test", Role.INSTALLATION_ADMINISTRATOR, UserState.ACTIVE, NOW
)
ALICE = User(UserId("alice"), "alice@example.test", Role.USER, UserState.ACTIVE, NOW)


@dataclass
class ListedTokens:
    """One User's Integration Tokens, as Your plan lists them; it never issues or revokes one."""

    tokens: list[IntegrationTokenSummary] = field(default_factory=list)

    def issue(
        self,
        name: str,
        scopes: frozenset[IntegrationTokenScope] = frozenset({IntegrationTokenScope.STATUS_READ}),
        *,
        within: Callable[[], int | None] | None = None,
    ) -> IssuedIntegrationToken:
        raise AssertionError("Your plan never issues a token")

    def list(self) -> Sequence[IntegrationTokenSummary]:
        return self.tokens

    def revoke(self, token_id: str) -> bool:
        raise AssertionError("Your plan never revokes a token")


def _rule(
    name: str, state: SyncRuleState, *, lapsed: bool = False, keeps_place: bool = False
) -> SyncRule:
    return SyncRule(
        SyncRuleId(name),
        endpoint("personal-account", f"{name}-source"),
        endpoint("work-account", f"{name}-destination"),
        state=state,
        awaiting_reauthorization=lapsed,
        keeps_place=keeps_place,
    )


COUNTED = (
    _rule("enabled", SyncRuleState.ENABLED),
    _rule("lapse-stopped", SyncRuleState.DEGRADED, lapsed=True),
    _rule("replacement", SyncRuleState.DRAFT, keeps_place=True),
    _rule("previewed-replacement", SyncRuleState.PREVIEWED, keeps_place=True),
)
NOT_COUNTED = (
    _rule("draft", SyncRuleState.DRAFT),
    _rule("previewed", SyncRuleState.PREVIEWED),
    _rule("paused", SyncRuleState.PAUSED),
    _rule("stopped", SyncRuleState.DEGRADED),
    _rule("removing", SyncRuleState.REMOVING),
)


def _account(
    account_id: str, state: ConnectedAccountState = ConnectedAccountState.CONNECTED
) -> ConnectedAccount:
    return ConnectedAccount(
        ConnectedAccountId(account_id),
        account_id,
        f"{account_id}@example.test",
        state,
        provider=ProviderKind.GOOGLE,
    )


def _token(token_id: str, *, revoked: bool = False) -> IntegrationTokenSummary:
    return IntegrationTokenSummary(
        token_id,
        token_id,
        frozenset({IntegrationTokenScope.STATUS_READ}),
        NOW,
        None,
        NOW if revoked else None,
        owner=ALICE.id,
    )


def _plans(*, on: bool = True) -> MemoryPlans:
    """An administrator and Alice; with `on`, Plans are on, Free is the default, Family exists."""
    plans = MemoryPlans()
    plans.users.add(ADMIN, "hash")
    plans.users.add(ALICE, "hash")
    if on:
        plans_on(plans, FREE, FAMILY)
    return plans


def _show(
    plans: MemoryPlans,
    user: User = ALICE,
    *,
    rules: Sequence[SyncRule] = (),
    accounts: Sequence[ConnectedAccount] = (),
    tokens: Sequence[IntegrationTokenSummary] = (),
) -> ShowOwnPlan:
    units = memory_units(user=user.id)
    with units() as uow:
        for rule in rules:
            uow.rules.add(rule)
        uow.commit()
    return ShowOwnPlan(
        plans, units, RecordingAccounts(*accounts), ListedTokens(list(tokens)), user.id
    )


def test_only_rules_that_count_toward_the_plan_are_counted() -> None:
    own = _show(_plans(), rules=COUNTED + NOT_COUNTED).execute()

    assert own.rules_counted == len(COUNTED)


def test_disconnected_accounts_count_and_revoked_tokens_do_not() -> None:
    accounts = (_account("home"), _account("old", ConnectedAccountState.DISCONNECTED))
    tokens = (_token("monitor"), _token("retired", revoked=True))

    own = _show(_plans(), accounts=accounts, tokens=tokens).execute()

    assert (own.connected_accounts, own.integration_tokens) == (2, 1)


def test_without_the_master_key_no_account_counts() -> None:
    show = ShowOwnPlan(_plans(), memory_units(user=ALICE.id), None, ListedTokens(), ALICE.id)

    assert show.execute().connected_accounts == 0


def test_a_member_without_a_plan_of_their_own_has_the_default() -> None:
    own = _show(_plans()).execute()

    assert own.allowance == Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True)


def test_a_member_with_their_own_plan_has_it() -> None:
    plans = _plans()
    plans.assign_all(
        {ALICE.id: FAMILY.key}, AssignmentChange(AssignmentSource.ADMINISTRATOR, ADMIN.id, NOW)
    )

    own = _show(plans).execute()

    assert own.allowance == Allowance(AllowanceBasis.PLAN, plan=FAMILY, assigned=FAMILY)


SMALL = Plan(PlanKey("small"), "Small", PlanLimits(2, 2, 2, SyncInterval.INSTANT))


@pytest.mark.parametrize(
    ("used", "room", "over"),
    [(1, True, False), (2, False, False), (3, False, True)],
    ids=["below", "at", "above"],
)
def test_each_limit_has_room_only_below_it_and_is_passed_only_above_it(
    used: int, room: bool, over: bool
) -> None:
    own = OwnPlan(Allowance(AllowanceBasis.PLAN, plan=SMALL, assigned=SMALL), used, used, used)

    assert (own.may_connect_account, own.may_issue_token, own.over_rule_limit) == (
        room,
        room,
        over,
    )


def test_a_plan_without_tokens_has_no_room_for_the_first() -> None:
    own = OwnPlan(Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True), 0, 0, 0)

    assert (own.may_connect_account, own.may_issue_token) == (True, False)


def test_unlimited_values_always_have_room() -> None:
    unlimited = Plan(
        PlanKey("unlimited"), "Unlimited", PlanLimits(None, None, None, SyncInterval.INSTANT)
    )

    own = OwnPlan(Allowance(AllowanceBasis.PLAN, plan=unlimited), 500, 500, 500)

    assert (own.may_connect_account, own.may_issue_token, own.over_rule_limit) == (
        True,
        True,
        False,
    )


def test_an_administrator_is_never_limited() -> None:
    accounts = (_account("one"), _account("two"))

    own = _show(_plans(), ADMIN, rules=COUNTED, accounts=accounts, tokens=(_token("t"),)).execute()

    assert own.allowance.basis is AllowanceBasis.ADMINISTRATOR
    assert (own.may_connect_account, own.may_issue_token, own.over_rule_limit) == (
        True,
        True,
        False,
    )


def test_with_plans_off_nobody_is_limited() -> None:
    own = _show(
        _plans(on=False), rules=COUNTED, accounts=(_account("one"), _account("two"))
    ).execute()

    assert own.allowance.basis is AllowanceBasis.PLANS_OFF
    assert (own.may_connect_account, own.may_issue_token, own.over_rule_limit) == (
        True,
        True,
        False,
    )


def test_an_administrator_demoted_over_the_limit_is_limited_until_promoted_again() -> None:
    plans = _plans()
    plans.users.set_role(ALICE.id, Role.INSTALLATION_ADMINISTRATOR)
    show = _show(
        plans,
        rules=COUNTED,
        accounts=(_account("one"), _account("two")),
        tokens=(_token("monitor"),),
    )
    assert show.execute().allowance.basis is AllowanceBasis.ADMINISTRATOR

    plans.users.set_role(ALICE.id, Role.USER)
    demoted = show.execute()

    # Free allows one rule, one account, and no tokens: Your plan shows the over-limit line,
    # and Connect and issuing a token are unavailable. Nothing she has stops.
    assert demoted.allowance == Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True)
    assert (demoted.over_rule_limit, demoted.may_connect_account, demoted.may_issue_token) == (
        True,
        False,
        False,
    )
    plans.users.set_role(ALICE.id, Role.INSTALLATION_ADMINISTRATOR)
    promoted = show.execute()
    assert promoted.allowance.basis is AllowanceBasis.ADMINISTRATOR
    assert (promoted.over_rule_limit, promoted.may_connect_account, promoted.may_issue_token) == (
        False,
        True,
        True,
    )


def test_own_plan_failure_never_invents_an_allowance() -> None:
    show = ShowOwnPlan(
        BrokenAllowances(), memory_units(user=ALICE.id), None, ListedTokens(), ALICE.id
    )

    # Never a made-up Allowance: the Web UI reads the failure as no hints, and the server
    # still checks every limit.
    with pytest.raises(RuntimeError, match="database is locked"):
        show.execute()


def test_own_plan_exposes_grace_held_rules_and_keep_choices() -> None:
    show = _show(
        _plans(), rules=COUNTED + NOT_COUNTED + (_rule("held", SyncRuleState.ENABLED).hold(),)
    )
    deadline = NOW + timedelta(days=7)
    grace = PlanGrace(deadline, 1, 2)
    with show.unit_of_work() as uow:
        uow.rules.keep([SyncRuleId("replacement")])
        uow.plan_grace.admit()
        uow.plan_grace.admit()
        uow.plan_grace.save(grace)
        before = (uow.rules.list(), uow.rules.standings())
        uow.commit()

    own = show.execute()

    assert own.held_rules == 1
    assert own.grace is not None
    assert (own.grace.holds_at, own.grace.rule_limit, own.grace.held, own.grace.reserved) == (
        deadline,
        1,
        2,
        1,
    )
    assert own.rules == tuple(sorted(before[1], key=lambda each: each.rank))
    assert own.rules[0].rule_id == SyncRuleId("replacement")
    assert len(own.rules) == 5
    with show.unit_of_work() as uow:
        assert (uow.rules.list(), uow.rules.standings()) == before
        assert (uow.plan_grace.get(), uow.plan_grace.admissions()) == (grace, 2)


def _standing(name: str, place: RulePlace, order: int, *, kept: bool = False) -> RuleStanding:
    return RuleStanding(SyncRuleId(name), place, order, kept)


@pytest.mark.parametrize(
    ("places", "predicted"),
    [
        ((RulePlace.COUNTED, RulePlace.RESERVED), (0, 1)),
        ((RulePlace.RESERVED, RulePlace.COUNTED), (1, 0)),
        ((RulePlace.COUNTED, RulePlace.RESERVED, RulePlace.COUNTED), (1, 1)),
    ],
)
def test_reserved_place_loss_is_not_a_predicted_hold(
    places: tuple[RulePlace, ...], predicted: tuple[int, int]
) -> None:
    from calendar_sync.application.operations.own_plan_holds import grace_view

    standings = tuple(_standing(str(order), place, order) for order, place in enumerate(places))
    own = grace_view(PlanGrace(NOW, 1, 0), standings, 1, 0)

    assert own is not None
    assert (own.held, own.reserved) == predicted


@pytest.mark.parametrize(
    ("limit", "admissions", "expected"),
    [(1, 3, None), (2, 4, None), (None, 3, None), (3, 3, (1, 0)), (2, 3, (1, 1)), (4, 3, None)],
)
def test_grace_view_uses_current_allowance_without_mutation(
    limit: int | None, admissions: int, expected: tuple[int, int] | None
) -> None:
    from calendar_sync.application.operations.own_plan_holds import grace_view

    # Kept first; creation order breaks ties. The already held rule consumes no place.
    standings = (
        _standing("new-kept", RulePlace.COUNTED, 5, kept=True),
        _standing("old", RulePlace.COUNTED, 1),
        _standing("reserved", RulePlace.RESERVED, 2),
        _standing("new", RulePlace.COUNTED, 3),
        _standing("held", RulePlace.HELD, 0),
    )
    grace = PlanGrace(NOW - timedelta(days=1), 2, 3)
    own = grace_view(grace, standings, limit, admissions)

    if expected is None:
        assert own is None
    else:
        assert own is not None
        assert (own.holds_at, own.rule_limit, own.held, own.reserved) == (
            grace.holds_at,
            limit,
            *expected,
        )
    assert grace == PlanGrace(NOW - timedelta(days=1), 2, 3)
    assert standings[-1].place is RulePlace.HELD


def test_pausing_within_the_limit_hides_grace_without_clearing_it() -> None:
    show = _show(_plans(), rules=COUNTED[:2])
    grace = PlanGrace(NOW, 1, 0)
    with show.unit_of_work() as uow:
        uow.plan_grace.save(grace)
        uow.rules.save(COUNTED[0].pause())
        uow.commit()

    assert show.execute().grace is None
    with show.unit_of_work() as uow:
        assert uow.plan_grace.get() == grace


@pytest.mark.parametrize("who", ["off", "administrator", "unlimited"])
def test_unlimited_allowances_hide_stored_grace(who: str) -> None:
    plans = _plans(on=who != "off")
    user = ADMIN if who == "administrator" else ALICE
    if who == "unlimited":
        plans.change(replace(FREE, limits=replace(FREE.limits, rules=None)), NOW)
    show = _show(plans, user, rules=COUNTED)
    with show.unit_of_work() as uow:
        uow.plan_grace.save(PlanGrace(NOW, 1, 0))
        uow.commit()

    assert show.execute().grace is None


@pytest.mark.parametrize("held", [False, True])
def test_empty_or_held_only_choices_have_no_grace(held: bool) -> None:
    rules = (_rule("held", SyncRuleState.ENABLED).hold(),) if held else NOT_COUNTED
    show = _show(_plans(), rules=rules)
    with show.unit_of_work() as uow:
        uow.plan_grace.save(PlanGrace(NOW, 1, 0))
        uow.commit()

    own = show.execute()

    assert (own.rules_counted, own.held_rules, own.grace) == (0, int(held), None)
    assert len(own.rules) == int(held)


def test_without_stored_grace_an_excess_does_not_invent_a_deadline() -> None:
    assert _show(_plans(), rules=COUNTED).execute().grace is None
