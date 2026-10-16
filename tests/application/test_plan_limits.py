"""The rule limit: Start checks it, and the rule page says whether Start would pass (ADR 0038)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace

import pytest

from calendar_sync.application.identity.plans import ChangePlan
from calendar_sync.application.sync.lapsed_authorization import LapsedAuthorizations
from calendar_sync.application.sync.locking import RuleLocks
from calendar_sync.application.sync.ports import Allowances
from calendar_sync.application.sync.rules import (
    ChangeSyncRulePolicy,
    EnableSyncRule,
    GetSyncRuleDetails,
)
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    BirthdayPolicy,
    ProjectionContent,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TentativeEventPolicy,
    UnansweredInvitationPolicy,
)
from calendar_sync.domain.plans import LimitedResource, Plan, PlanLimitReached
from calendar_sync.infrastructure.persistence.memory import (
    InMemoryIncidentRepository,
    InMemoryUserUnitOfWorkFactory,
)
from tests.fake_calendar import FixedClock
from tests.helpers import NOW, endpoint, rule
from tests.identity_fakes import BrokenAllowances, MemoryPlans, MemoryUsers
from tests.plans import FAMILY, FREE, plans_on
from tests.users import USER, memory_units

ADMIN = UserId("admin-1")
NEXT = SyncRuleId("next")
LATER = SyncRuleId("later")


def _rule(rule_id: SyncRuleId, state: SyncRuleState = SyncRuleState.PREVIEWED) -> SyncRule:
    """Another rule of the User, from a calendar of its own, so each relationship is unique."""
    return SyncRule(
        rule_id,
        endpoint("personal-account", f"{rule_id.value}-calendar"),
        rule().destination,
        state=state,
    )


def _plans(role: Role = Role.USER, plan: Plan | None = None) -> MemoryPlans:
    """Plans on, Free (one rule) the Default Plan and Family defined. USER has `role`, and
    `plan` as their own Plan when given; ADMIN administers."""
    users = MemoryUsers()
    users.add(
        User(ADMIN, "admin@example.test", Role.INSTALLATION_ADMINISTRATOR, UserState.ACTIVE, NOW),
        "x",
    )
    own = plan.key if plan is not None else None
    users.add(User(USER, "member@example.test", role, UserState.ACTIVE, NOW, plan=own), "x")
    plans = MemoryPlans(users=users)
    plans_on(plans, FREE, FAMILY)
    return plans


def _plans_off() -> MemoryPlans:
    """Plans defined, with Free the default, but off: nobody is limited."""
    plans = _plans()
    plans.change_settings(False, FREE.key, NOW)
    return plans


def _units(*rules: SyncRule) -> InMemoryUserUnitOfWorkFactory:
    """USER's records, with `rules` added in order, as creating them would."""
    units = memory_units()
    with units() as uow:
        for each in rules:
            uow.rules.add(each)
        uow.commit()
    return units


def _start(
    units: InMemoryUserUnitOfWorkFactory, allowances: Allowances, rule_id: SyncRuleId
) -> SyncRule:
    return EnableSyncRule(units, RuleLocks(), allowances, USER).execute(rule_id)


def _details(
    units: InMemoryUserUnitOfWorkFactory, allowances: Allowances, rule_id: SyncRuleId
) -> tuple[bool, int | None]:
    details = GetSyncRuleDetails(units, RuleLocks(), allowances, USER).execute(rule_id)
    return details.can_start, details.rule_limit


def _change(
    units: InMemoryUserUnitOfWorkFactory,
    rule_id: SyncRuleId,
    transition: Callable[[SyncRule], SyncRule],
) -> None:
    """Apply what a run or a preview would do to the rule, in a unit of its own."""
    with units() as uow:
        stored = uow.rules.get(rule_id)
        assert stored is not None
        uow.rules.save(transition(stored))
        uow.commit()


def _state(units: InMemoryUserUnitOfWorkFactory, rule_id: SyncRuleId) -> SyncRuleState:
    return units.state.rules[rule_id].state


def _counted(units: InMemoryUserUnitOfWorkFactory) -> int:
    return sum(each.counts_toward_plan for each in units.state.rules.values())


def test_a_start_within_the_rule_limit_enables_the_rule() -> None:
    units = _units(_rule(NEXT))

    started = _start(units, _plans(), NEXT)

    assert started.state is SyncRuleState.ENABLED
    assert units.state.rules[NEXT] == started


def test_a_start_past_the_rule_limit_is_refused_and_the_rule_stays_previewed() -> None:
    units = _units(rule(), _rule(NEXT))

    with pytest.raises(PlanLimitReached) as refused:
        _start(units, _plans(), NEXT)

    assert (refused.value.resource, refused.value.limit) == (LimitedResource.RULES, 1)
    assert _state(units, NEXT) is SyncRuleState.PREVIEWED
    assert _state(units, rule().id) is SyncRuleState.ENABLED


def test_a_start_counts_against_the_users_own_plan() -> None:
    four = [_rule(SyncRuleId(f"rule-{index}"), SyncRuleState.ENABLED) for index in range(2, 6)]
    units = _units(*four, _rule(NEXT), _rule(LATER))

    _start(units, _plans(plan=FAMILY), NEXT)
    with pytest.raises(PlanLimitReached) as refused:
        _start(units, _plans(plan=FAMILY), LATER)

    assert refused.value.limit == 5
    assert _state(units, NEXT) is SyncRuleState.ENABLED
    assert _state(units, LATER) is SyncRuleState.PREVIEWED


def test_a_rule_that_keeps_a_place_starts_even_over_the_limit() -> None:
    successor = replace(_rule(NEXT), keeps_place=True)
    units = _units(rule(), successor)
    assert _counted(units) == 2

    started = _start(units, _plans(), NEXT)

    assert started.state is SyncRuleState.ENABLED
    assert started.keeps_place is False
    assert _counted(units) == 2


@pytest.mark.parametrize("who", ["administrator", "plans_off"])
def test_administrators_and_plans_off_are_never_refused(who: str) -> None:
    plans = _plans(role=Role.INSTALLATION_ADMINISTRATOR) if who == "administrator" else _plans_off()
    enabled = [_rule(SyncRuleId(f"rule-{index}"), SyncRuleState.ENABLED) for index in range(2, 5)]
    units = _units(*enabled, _rule(NEXT))

    started = _start(units, plans, NEXT)

    assert started.state is SyncRuleState.ENABLED
    assert _details(units, plans, NEXT) == (True, None)


def test_a_start_fails_closed_when_the_allowance_cannot_be_read() -> None:
    units = _units(_rule(NEXT))

    with pytest.raises(RuntimeError, match="database is locked"):
        _start(units, BrokenAllowances(), NEXT)

    assert _state(units, NEXT) is SyncRuleState.PREVIEWED


@pytest.mark.parametrize(
    ("who", "rules", "expected"),
    [
        ("member", (_rule(NEXT),), (True, 1)),
        ("member", (rule(), _rule(NEXT)), (False, 1)),
        ("member", (rule(), replace(_rule(NEXT), keeps_place=True)), (True, 1)),
        ("family", (rule(), _rule(NEXT)), (True, 5)),
        ("administrator", (rule(), _rule(NEXT)), (True, None)),
        ("plans_off", (rule(), _rule(NEXT)), (True, None)),
    ],
)
def test_details_say_whether_start_would_pass_and_name_the_rule_limit(
    who: str, rules: tuple[SyncRule, ...], expected: tuple[bool, int | None]
) -> None:
    plans = {
        "member": _plans,
        "family": lambda: _plans(plan=FAMILY),
        "administrator": lambda: _plans(role=Role.INSTALLATION_ADMINISTRATOR),
        "plans_off": _plans_off,
    }[who]()

    assert _details(_units(*rules), plans, NEXT) == expected


def test_details_fail_open_and_log_only_the_error_class(caplog: pytest.LogCaptureFixture) -> None:
    units = _units(rule(), _rule(NEXT))

    with caplog.at_level(logging.WARNING):
        answer = _details(units, BrokenAllowances(), NEXT)

    assert answer == (True, None)
    assert "RuntimeError" in caplog.text
    assert "database is locked" not in caplog.text
    # The Start itself still checks, and fails closed.
    with pytest.raises(RuntimeError):
        _start(units, BrokenAllowances(), NEXT)


def test_a_rule_a_provider_failure_stopped_is_checked_at_its_recovery_start() -> None:
    units = _units(rule(), _rule(NEXT))
    plans = _plans()
    # A failure that needs intervention stops the rule; it no longer counts.
    _change(units, rule().id, lambda stopped: stopped.degrade())
    _start(units, plans, NEXT)
    _change(units, rule().id, SyncRule.mark_previewed)

    with pytest.raises(PlanLimitReached):
        _start(units, plans, rule().id)

    assert _state(units, rule().id) is SyncRuleState.PREVIEWED
    assert _details(units, plans, rule().id) == (False, 1)


def test_a_rule_a_material_rule_change_paused_is_checked_at_its_start() -> None:
    units = _units(rule(), _rule(NEXT))
    plans = _plans()
    ChangeSyncRulePolicy(units, FixedClock(), RuleLocks()).execute(
        rule().id,
        ProjectionContent.DETAILS,
        AllDaySyncPolicy.INCLUDE,
        tentative=TentativeEventPolicy.MARK,
        unanswered=UnansweredInvitationPolicy.AS_TENTATIVE,
        birthdays=BirthdayPolicy.EXCLUDE,
    )
    assert _state(units, rule().id) is SyncRuleState.PAUSED
    _start(units, plans, NEXT)
    _change(units, rule().id, SyncRule.mark_previewed)

    with pytest.raises(PlanLimitReached):
        _start(units, plans, rule().id)

    assert _state(units, rule().id) is SyncRuleState.PREVIEWED


def test_a_lapse_stopped_rule_counts_until_it_is_previewed_and_is_then_checked() -> None:
    lapse_stopped = rule().degrade(awaiting_reauthorization=True)
    units = _units(lapse_stopped, _rule(NEXT))
    plans = _plans()

    with pytest.raises(PlanLimitReached):
        _start(units, plans, NEXT)
    _change(units, rule().id, SyncRule.mark_previewed)
    _start(units, plans, NEXT)

    with pytest.raises(PlanLimitReached):
        _start(units, plans, rule().id)
    assert _state(units, rule().id) is SyncRuleState.PREVIEWED
    assert _state(units, NEXT) is SyncRuleState.ENABLED


def test_a_lapse_resume_while_over_the_limit_needs_no_plan() -> None:
    lapse_stopped = rule().degrade(awaiting_reauthorization=True)
    units = _units(lapse_stopped, _rule(NEXT, SyncRuleState.ENABLED))
    plans = _plans()
    assert plans.of(USER).limits.rules == 1
    assert _counted(units) == 2
    lapses = LapsedAuthorizations(
        units, InMemoryIncidentRepository(units.database, USER), FixedClock(), RuleLocks()
    )

    resumed = lapses.finish_interrupted()

    assert resumed == 1
    assert _state(units, rule().id) is SyncRuleState.ENABLED
    assert _counted(units) == 2


def test_lowering_the_limit_stops_nothing_and_refuses_the_next_start() -> None:
    enabled = [_rule(SyncRuleId(f"rule-{index}"), SyncRuleState.ENABLED) for index in range(2, 5)]
    units = _units(*enabled, _rule(NEXT))
    plans = _plans(plan=FAMILY)
    lowered = replace(FAMILY, limits=replace(FAMILY.limits, rules=1))

    ChangePlan(plans.users, plans, FixedClock()).execute(ADMIN, lowered)

    assert [_state(units, each.id) for each in enabled] == [SyncRuleState.ENABLED] * 3
    assert _details(units, plans, NEXT) == (False, 1)
    with pytest.raises(PlanLimitReached):
        _start(units, plans, NEXT)
    assert [_state(units, each.id) for each in enabled] == [SyncRuleState.ENABLED] * 3


def test_an_administrator_demoted_over_the_limit_keeps_every_rule_but_starts_no_more() -> None:
    enabled = [_rule(SyncRuleId(f"rule-{index}"), SyncRuleState.ENABLED) for index in range(2, 4)]
    units = _units(*enabled, _rule(NEXT), _rule(LATER))
    plans = _plans(role=Role.INSTALLATION_ADMINISTRATOR)
    _start(units, plans, NEXT)

    plans.users.set_role(USER, Role.USER)

    assert _counted(units) == 3
    assert _details(units, plans, LATER) == (False, 1)
    with pytest.raises(PlanLimitReached):
        _start(units, plans, LATER)
    assert _state(units, NEXT) is SyncRuleState.ENABLED
    # Promoting them again lifts the limit at the next request.
    plans.users.set_role(USER, Role.INSTALLATION_ADMINISTRATOR)
    assert _start(units, plans, LATER).state is SyncRuleState.ENABLED
