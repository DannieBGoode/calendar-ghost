"""What Installation Administrators do with Plans (ADR 0038), over the in-memory Plans store."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

import pytest

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.plans import (
    ChangePlan,
    DefinePlan,
    PlansOverview,
    RemovePlan,
    SetPlansSetting,
    ShowPlans,
)
from calendar_sync.application.identity.ports import AssignmentChange, PlanListing, PlansSetting
from calendar_sync.domain.access import Role, User, UserId, UserState
from calendar_sync.domain.plans import (
    OFFERED_INTERVALS,
    Allowance,
    AllowanceBasis,
    AssignmentSource,
    NewPlan,
    Plan,
    PlanIsDefault,
    PlanKey,
    PlanLimits,
    PlansNeedDefault,
    SyncInterval,
)
from tests.helpers import NOW
from tests.identity_fakes import MemoryPlans, MemoryUsers
from tests.plans import FAMILY, FREE, as_new, plans_on

PLANS_LOGGER = "calendar_sync.application.identity.plans"
ADMIN = User(
    UserId("admin"), "admin@example.test", Role.INSTALLATION_ADMINISTRATOR, UserState.ACTIVE, NOW
)
MEMBER = User(UserId("member"), "member@example.test", Role.USER, UserState.ACTIVE, NOW)
NEIGHBOUR = User(UserId("neighbour"), "neighbour@example.test", Role.USER, UserState.ACTIVE, NOW)
LATECOMER = User(UserId("latecomer"), "latecomer@example.test", Role.USER, UserState.ACTIVE, NOW)
RETIRED = User(
    UserId("retired"),
    "retired@example.test",
    Role.INSTALLATION_ADMINISTRATOR,
    UserState.DISABLED,
    NOW,
)
SOLO = Plan(PlanKey("solo"), "Solo", PlanLimits(2, 2, 1, SyncInterval.INSTANT))
HOURLY = Plan(
    PlanKey("hourly"), "Hourly", PlanLimits(None, None, None, SyncInterval.EVERY_60_MINUTES)
)


@dataclass(frozen=True)
class _Clock:
    def now(self) -> datetime:
        return NOW


CLOCK = _Clock()
BY_ADMIN = AssignmentChange(AssignmentSource.ADMINISTRATOR, ADMIN.id, NOW)


def _plans(*others: User) -> MemoryPlans:
    """An installation with an administrator and a member, Plans off, and no Plan yet."""
    users = MemoryUsers()
    for user in (ADMIN, MEMBER, *others):
        users.add(user, "hashed:password")
    return MemoryPlans(users)


def _define(plans: MemoryPlans) -> DefinePlan:
    return DefinePlan(plans.users, plans, CLOCK)


def _change(plans: MemoryPlans) -> ChangePlan:
    return ChangePlan(plans.users, plans, CLOCK)


def _remove(plans: MemoryPlans) -> RemovePlan:
    return RemovePlan(plans.users, plans)


def _setting(plans: MemoryPlans) -> SetPlansSetting:
    return SetPlansSetting(plans.users, plans, CLOCK)


def _snapshot(plans: MemoryPlans) -> tuple[object, ...]:
    return (
        plans.enabled,
        plans.default,
        dict(plans.catalog),
        dict(plans.changes),
        dict(plans.users.users),
    )


# Each would succeed for an active administrator, on Plans turned on with FREE and FAMILY.
ATTEMPTS: dict[str, Callable[[MemoryPlans, UserId], object]] = {
    "show plans": lambda plans, actor: ShowPlans(plans.users, plans).execute(actor),
    "define a plan": lambda plans, actor: _define(plans).execute(actor, as_new(SOLO)),
    "change a plan": lambda plans, actor: _change(plans).execute(
        actor, replace(FREE, name="Starter")
    ),
    "remove a plan": lambda plans, actor: _remove(plans).execute(actor, FAMILY.key),
    "turn plans off": lambda plans, actor: _setting(plans).execute(actor, False, FREE.key),
}


@pytest.mark.parametrize("attempt", list(ATTEMPTS.values()), ids=list(ATTEMPTS))
@pytest.mark.parametrize(
    "actor",
    [MEMBER.id, RETIRED.id, UserId("nobody")],
    ids=["member", "disabled administrator", "unknown"],
)
def test_only_an_active_administrator_manages_plans(
    attempt: Callable[[MemoryPlans, UserId], object], actor: UserId
) -> None:
    plans = _plans(RETIRED)
    plans_on(plans, FREE, FAMILY)
    before = _snapshot(plans)

    with pytest.raises(AdministratorRequired):
        attempt(plans, actor)

    assert _snapshot(plans) == before
    # The same request goes through for an active administrator.
    attempt(plans, ADMIN.id)


# Showing Plans


def test_show_plans_answers_each_plan_who_has_it_the_setting_and_the_offered_intervals() -> None:
    plans = _plans(NEIGHBOUR)
    plans_on(plans, FREE, FAMILY)
    plans.assign_all({NEIGHBOUR.id: FAMILY.key}, BY_ADMIN)

    overview = ShowPlans(plans.users, plans).execute(ADMIN.id)

    # FREE is the default, so the administrator and the member have it; it limits the member.
    assert overview == PlansOverview(
        PlansSetting(True, FREE.key),
        (PlanListing(FAMILY, False, 1, 1), PlanListing(FREE, True, 2, 1)),
        tuple(SyncInterval),
        followers=2,
    )


# Defining and changing Plans


@pytest.mark.parametrize("plan", [SOLO, HOURLY], ids=["instant", "every-hour"])
def test_an_administrator_defines_a_plan_with_any_interval(plan: Plan) -> None:
    plans = _plans()

    listing = _define(plans).execute(ADMIN.id, as_new(plan))

    assert listing == PlanListing(plan, False, 0, 0)
    assert plans.get(plan.key) == plan


def test_changing_a_plan_keeps_its_key_and_its_new_limits_apply_at_once() -> None:
    plans = _plans()
    plans_on(plans, FREE)
    roomier = Plan(FREE.key, "Starter", PlanLimits(2, 2, 1, SyncInterval.INSTANT))

    listing = _change(plans).execute(ADMIN.id, roomier)

    assert listing == PlanListing(roomier, True, 2, 1)
    assert list(plans.catalog) == [FREE.key]
    assert plans.of(MEMBER.id) == Allowance(AllowanceBasis.PLAN, plan=roomier, on_default=True)


# The Plans setting and the Default Plan


def test_turning_plans_on_with_a_default_answers_the_overview_and_limits_members() -> None:
    plans = _plans()
    plans.add(as_new(FREE), NOW)

    overview = _setting(plans).execute(ADMIN.id, True, FREE.key)

    assert overview == PlansOverview(
        PlansSetting(True, FREE.key),
        (PlanListing(FREE, True, 2, 1),),
        OFFERED_INTERVALS,
        followers=2,
    )
    assert plans.of(MEMBER.id) == Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True)


def test_turning_plans_on_never_clears_a_default_already_chosen() -> None:
    plans = _plans()
    plans.add(as_new(FREE), NOW)
    _setting(plans).execute(ADMIN.id, False, FREE.key)

    with pytest.raises(PlansNeedDefault):
        _setting(plans).execute(ADMIN.id, True, None)

    assert plans.settings() == PlansSetting(False, FREE.key)
    assert list(plans.catalog) == [FREE.key]


@pytest.mark.parametrize("default", [FREE.key, None], ids=["keeping the default", "clearing it"])
def test_turning_plans_off_is_always_allowed_and_keeps_every_plan(default: PlanKey | None) -> None:
    plans = _plans()
    plans_on(plans, FREE, FAMILY)
    plans.assign_all({MEMBER.id: FAMILY.key}, BY_ADMIN)

    overview = _setting(plans).execute(ADMIN.id, False, default)

    assert overview.setting == PlansSetting(False, default)
    assert [listing.plan for listing in overview.plans] == [FAMILY, FREE]
    assert plans.of(MEMBER.id) == Allowance(AllowanceBasis.PLANS_OFF, assigned=FAMILY)


def test_a_new_default_applies_at_once_to_everyone_without_a_plan_of_their_own() -> None:
    plans = _plans(NEIGHBOUR)
    plans_on(plans, FREE, FAMILY)
    plans.assign_all({NEIGHBOUR.id: FAMILY.key}, BY_ADMIN)

    _setting(plans).execute(ADMIN.id, True, FAMILY.key)
    # Someone who joins later has no Plan of their own either.
    plans.users.add(LATECOMER, "hashed:password")

    on_default = Allowance(AllowanceBasis.PLAN, plan=FAMILY, on_default=True)
    assert plans.of(MEMBER.id) == on_default
    assert plans.of(LATECOMER.id) == on_default
    # Given the new default before it was the default, so it stays their own.
    assert plans.of(NEIGHBOUR.id) == Allowance(AllowanceBasis.PLAN, plan=FAMILY, assigned=FAMILY)
    assert set(plans.changes) == {NEIGHBOUR.id}


def test_the_default_is_never_removed_nor_cleared_while_plans_are_on() -> None:
    plans = _plans()
    plans_on(plans, FREE, FAMILY)

    with pytest.raises(PlanIsDefault):
        _remove(plans).execute(ADMIN.id, FREE.key)
    with pytest.raises(PlansNeedDefault):
        _setting(plans).execute(ADMIN.id, True, None)

    assert plans.settings() == PlansSetting(True, FREE.key)
    assert plans.get(FREE.key) == FREE


# Log lines


def test_each_change_logs_one_line_naming_only_ids(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=PLANS_LOGGER)
    plans = _plans()
    plans.add(as_new(FREE), NOW)

    _define(plans).execute(ADMIN.id, NewPlan("Solo", SOLO.limits))
    _change(plans).execute(ADMIN.id, replace(SOLO, name="Solo, renamed"))
    _setting(plans).execute(ADMIN.id, True, FREE.key)
    _remove(plans).execute(ADMIN.id, SOLO.key)
    _setting(plans).execute(ADMIN.id, False, None)
    _setting(plans).execute(ADMIN.id, True, None)
    ShowPlans(plans.users, plans).execute(ADMIN.id)

    lines = [record.getMessage() for record in caplog.records if record.name == PLANS_LOGGER]
    assert lines == [
        "plan defined key=solo by=admin",
        "plan changed key=solo by=admin",
        "plans setting changed enabled=True default=free by=admin",
        "plan removed key=solo by=admin",
        "plans setting changed enabled=False default=None by=admin",
        # The default the change made, not the none it asked for.
        "plans setting changed enabled=True default=no-limits by=admin",
    ]
    logged = "\n".join(lines)
    assert "Solo" not in logged
    assert "Free" not in logged
    assert "@example.test" not in logged
