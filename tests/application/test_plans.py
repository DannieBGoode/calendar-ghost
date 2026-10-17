"""What Installation Administrators do with Plans (ADR 0038), over the in-memory Plans store."""

import logging
from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from datetime import datetime

import pytest

from calendar_sync.application.identity.administration import AdministratorRequired, UserNotFound
from calendar_sync.application.identity.errors import PlanKeyTaken, PlanNotFound
from calendar_sync.application.identity.plans import (
    AssignPlan,
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
    NO_LIMITS,
    OFFERED_INTERVALS,
    Allowance,
    AllowanceBasis,
    AssignmentSource,
    InvalidPlan,
    InvalidPlanReason,
    NewPlan,
    Plan,
    PlanInUse,
    PlanIsDefault,
    PlanKey,
    PlanLimits,
    PlanNameTaken,
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
NO_LIMITS_PLAN = Plan(PlanKey("no-limits"), "No limits", NO_LIMITS)


@dataclass(frozen=True)
class _Clock:
    def now(self) -> datetime:
        return NOW


CLOCK = _Clock()


class _DeletedMeanwhile:
    """PlanAssignments as the store answers once the User was deleted after the check."""

    def assign(self, user: UserId, plan: PlanKey | None, change: AssignmentChange) -> bool:
        return False

    def assign_all(
        self, users: Collection[UserId], plan: PlanKey | None, change: AssignmentChange
    ) -> bool:
        return False

    def last_changes(self, users: Collection[UserId]) -> dict[UserId, AssignmentChange]:
        return {}


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


def _assign(plans: MemoryPlans) -> AssignPlan:
    return AssignPlan(plans.users, plans, plans, CLOCK)


def _own_plan(plans: MemoryPlans, user: UserId) -> PlanKey | None:
    stored = plans.users.get(user)
    assert stored is not None
    return stored.plan


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
    "assign a plan": lambda plans, actor: _assign(plans).execute(actor, MEMBER.id, FAMILY.key),
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
    _assign(plans).execute(ADMIN.id, NEIGHBOUR.id, FAMILY.key)

    overview = ShowPlans(plans.users, plans).execute(ADMIN.id)

    # FREE is the default, so the administrator and the member have it; it limits the member.
    assert overview == PlansOverview(
        PlansSetting(True, FREE.key),
        (PlanListing(FAMILY, False, 1, 1), PlanListing(FREE, True, 2, 1)),
        (SyncInterval.INSTANT, SyncInterval.EVERY_5_MINUTES),
        administrators=1,
    )


def test_the_overview_counts_every_administrator_whom_no_plan_limits() -> None:
    """For the Never limited fact: a disabled administrator administers too."""
    plans = _plans(RETIRED, NEIGHBOUR)
    plans_on(plans, FREE)

    overview = ShowPlans(plans.users, plans).execute(ADMIN.id)

    assert overview.administrators == 2
    assert overview.plans == (PlanListing(FREE, True, 4, 2),)


def test_a_new_installation_shows_no_plans_and_plans_off() -> None:
    plans = _plans()

    overview = ShowPlans(plans.users, plans).execute(ADMIN.id)

    assert overview == PlansOverview(
        PlansSetting(False, None), (), OFFERED_INTERVALS, administrators=1
    )


# Defining and changing Plans


def test_an_administrator_defines_a_plan_with_an_offered_interval() -> None:
    plans = _plans()

    listing = _define(plans).execute(ADMIN.id, as_new(SOLO))

    assert listing == PlanListing(SOLO, False, 0, 0)
    assert plans.get(SOLO.key) == SOLO


def test_a_new_plan_without_a_key_gets_one_made_from_its_name() -> None:
    plans = _plans()

    first = _define(plans).execute(ADMIN.id, NewPlan("Solo", SOLO.limits))
    second = _define(plans).execute(ADMIN.id, NewPlan("Solo!", FAMILY.limits))

    assert first == PlanListing(SOLO, False, 0, 0)
    assert second == PlanListing(Plan(PlanKey("solo-2"), "Solo!", FAMILY.limits), False, 0, 0)


def test_a_new_plan_whose_interval_is_not_offered_is_refused() -> None:
    plans = _plans()

    with pytest.raises(InvalidPlan) as refused:
        _define(plans).execute(ADMIN.id, as_new(HOURLY))

    assert refused.value.reason is InvalidPlanReason.INTERVAL
    assert plans.any_plans() is False


def test_a_taken_key_is_refused_and_the_plan_with_it_is_kept() -> None:
    plans = _plans()
    plans.add(as_new(FREE), NOW)

    with pytest.raises(PlanKeyTaken):
        _define(plans).execute(ADMIN.id, NewPlan("Another free plan", FREE.limits, FREE.key))

    assert plans.get(FREE.key) == FREE


def test_a_name_another_plan_reads_as_is_refused_on_define_and_change() -> None:
    plans = _plans()
    plans.add(as_new(FREE), NOW)
    plans.add(as_new(FAMILY), NOW)
    before = _snapshot(plans)

    with pytest.raises(PlanNameTaken) as on_define:
        _define(plans).execute(ADMIN.id, NewPlan("free", SOLO.limits))
    with pytest.raises(PlanNameTaken) as on_change:
        _change(plans).execute(ADMIN.id, replace(FAMILY, name="FREE"))

    assert (on_define.value.name, on_change.value.name) == ("Free", "Free")
    assert _snapshot(plans) == before


def test_changing_a_plan_keeps_its_key_and_its_new_limits_apply_at_once() -> None:
    plans = _plans()
    plans_on(plans, FREE)
    roomier = Plan(FREE.key, "Starter", PlanLimits(2, 2, 1, SyncInterval.INSTANT))

    listing = _change(plans).execute(ADMIN.id, roomier)

    assert listing == PlanListing(roomier, True, 2, 1)
    assert list(plans.catalog) == [FREE.key]
    assert plans.of(MEMBER.id) == Allowance(AllowanceBasis.PLAN, plan=roomier, on_default=True)


def test_a_newly_chosen_interval_must_be_offered() -> None:
    plans = _plans()
    plans.add(as_new(FREE), NOW)
    hourly = replace(FREE, limits=replace(FREE.limits, sync_interval=SyncInterval.EVERY_60_MINUTES))

    with pytest.raises(InvalidPlan) as refused:
        _change(plans).execute(ADMIN.id, hourly)

    assert refused.value.reason is InvalidPlanReason.INTERVAL
    assert plans.get(FREE.key) == FREE


def test_an_interval_a_later_release_stored_may_be_kept() -> None:
    plans = _plans()
    # As a release offering every interval stored it, before a rollback to this one.
    plans.catalog[HOURLY.key] = HOURLY
    renamed = replace(HOURLY, name="Every hour")

    listing = _change(plans).execute(ADMIN.id, renamed)

    assert listing.plan == renamed
    assert plans.get(HOURLY.key) == renamed


def test_changing_a_plan_that_does_not_exist_is_plan_not_found() -> None:
    plans = _plans()

    with pytest.raises(PlanNotFound):
        _change(plans).execute(ADMIN.id, FREE)

    assert plans.any_plans() is False


# Removing Plans


def test_a_plan_nobody_has_is_removed() -> None:
    plans = _plans()
    plans_on(plans, FREE, FAMILY)

    _remove(plans).execute(ADMIN.id, FAMILY.key)

    assert plans.get(FAMILY.key) is None
    assert plans.get(FREE.key) == FREE


def test_a_plan_someone_has_is_kept_and_the_refusal_says_how_many_have_it() -> None:
    plans = _plans(NEIGHBOUR)
    plans_on(plans, FREE, FAMILY)
    for user in (MEMBER, NEIGHBOUR):
        _assign(plans).execute(ADMIN.id, user.id, FAMILY.key)

    with pytest.raises(PlanInUse) as in_use:
        _remove(plans).execute(ADMIN.id, FAMILY.key)

    assert in_use.value.people == 2
    assert plans.get(FAMILY.key) == FAMILY


def test_removing_a_plan_that_does_not_exist_is_plan_not_found() -> None:
    plans = _plans()
    plans_on(plans, FREE)

    with pytest.raises(PlanNotFound):
        _remove(plans).execute(ADMIN.id, FAMILY.key)

    assert plans.get(FREE.key) == FREE


# The Plans setting and the Default Plan


def test_turning_plans_on_with_a_default_answers_the_overview_and_limits_members() -> None:
    plans = _plans()
    plans.add(as_new(FREE), NOW)

    overview = _setting(plans).execute(ADMIN.id, True, FREE.key)

    assert overview == PlansOverview(
        PlansSetting(True, FREE.key),
        (PlanListing(FREE, True, 2, 1),),
        OFFERED_INTERVALS,
        administrators=1,
    )
    assert plans.of(MEMBER.id) == Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True)


def test_turning_plans_on_with_no_default_makes_a_no_limits_plan_the_default() -> None:
    plans = _plans()
    plans.add(as_new(FREE), NOW)

    overview = _setting(plans).execute(ADMIN.id, True, None)

    assert overview == PlansOverview(
        PlansSetting(True, NO_LIMITS_PLAN.key),
        (PlanListing(FREE, False, 0, 0), PlanListing(NO_LIMITS_PLAN, True, 2, 1)),
        OFFERED_INTERVALS,
        administrators=1,
    )
    # Turning Plans on this way limits nobody until someone has a smaller Plan.
    assert plans.of(MEMBER.id).limits == NO_LIMITS


def test_turning_plans_on_never_clears_a_default_already_chosen() -> None:
    plans = _plans()
    plans.add(as_new(FREE), NOW)
    _setting(plans).execute(ADMIN.id, False, FREE.key)

    with pytest.raises(PlansNeedDefault):
        _setting(plans).execute(ADMIN.id, True, None)

    assert plans.settings() == PlansSetting(False, FREE.key)
    assert list(plans.catalog) == [FREE.key]


def test_a_default_that_names_no_plan_is_plan_not_found() -> None:
    plans = _plans()
    plans.add(as_new(FREE), NOW)

    with pytest.raises(PlanNotFound):
        _setting(plans).execute(ADMIN.id, True, PlanKey("missing"))

    assert plans.settings() == PlansSetting(False, None)


@pytest.mark.parametrize("default", [FREE.key, None], ids=["keeping the default", "clearing it"])
def test_turning_plans_off_is_always_allowed_and_keeps_every_plan(default: PlanKey | None) -> None:
    plans = _plans()
    plans_on(plans, FREE, FAMILY)
    _assign(plans).execute(ADMIN.id, MEMBER.id, FAMILY.key)

    overview = _setting(plans).execute(ADMIN.id, False, default)

    assert overview.setting == PlansSetting(False, default)
    assert [listing.plan for listing in overview.plans] == [FAMILY, FREE]
    assert plans.of(MEMBER.id) == Allowance(AllowanceBasis.PLANS_OFF, assigned=FAMILY)


def test_a_new_default_applies_at_once_to_everyone_without_a_plan_of_their_own() -> None:
    plans = _plans(NEIGHBOUR)
    plans_on(plans, FREE, FAMILY)
    _assign(plans).execute(ADMIN.id, NEIGHBOUR.id, FREE.key)

    _setting(plans).execute(ADMIN.id, True, FAMILY.key)
    # Someone who joins later has no Plan of their own either.
    plans.users.add(LATECOMER, "hashed:password")

    on_default = Allowance(AllowanceBasis.PLAN, plan=FAMILY, on_default=True)
    assert plans.of(MEMBER.id) == on_default
    assert plans.of(LATECOMER.id) == on_default
    assert plans.of(NEIGHBOUR.id) == Allowance(AllowanceBasis.PLAN, plan=FREE, assigned=FREE)
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


# Assigning a Plan


def test_assigning_a_plan_records_the_administrator_and_when() -> None:
    plans = _plans()
    plans_on(plans, FREE, FAMILY)

    allowance = _assign(plans).execute(ADMIN.id, MEMBER.id, FAMILY.key)

    assert allowance == Allowance(AllowanceBasis.PLAN, plan=FAMILY, assigned=FAMILY)
    assert _own_plan(plans, MEMBER.id) == FAMILY.key
    assert plans.changes[MEMBER.id] == AssignmentChange(
        AssignmentSource.ADMINISTRATOR, ADMIN.id, NOW
    )


def test_a_plan_assigned_while_plans_are_off_applies_once_they_are_on() -> None:
    plans = _plans()
    plans.add(as_new(FREE), NOW)
    plans.add(as_new(FAMILY), NOW)

    allowance = _assign(plans).execute(ADMIN.id, MEMBER.id, FAMILY.key)
    _setting(plans).execute(ADMIN.id, True, FREE.key)

    assert allowance == Allowance(AllowanceBasis.PLANS_OFF, assigned=FAMILY)
    assert plans.of(MEMBER.id) == Allowance(AllowanceBasis.PLAN, plan=FAMILY, assigned=FAMILY)


def test_assigning_none_returns_the_user_to_the_default_plan() -> None:
    plans = _plans()
    plans_on(plans, FREE, FAMILY)
    _assign(plans).execute(ADMIN.id, MEMBER.id, FAMILY.key)

    allowance = _assign(plans).execute(ADMIN.id, MEMBER.id, None)

    assert allowance == Allowance(AllowanceBasis.PLAN, plan=FREE, on_default=True)
    assert _own_plan(plans, MEMBER.id) is None
    assert plans.changes[MEMBER.id] == AssignmentChange(
        AssignmentSource.ADMINISTRATOR, ADMIN.id, NOW
    )


def test_an_administrators_own_plan_is_stored_and_limits_them_not_at_all() -> None:
    plans = _plans()
    plans_on(plans, FREE, FAMILY)

    allowance = _assign(plans).execute(ADMIN.id, ADMIN.id, FAMILY.key)

    assert allowance == Allowance(AllowanceBasis.ADMINISTRATOR, assigned=FAMILY)
    assert allowance.limits == NO_LIMITS
    assert _own_plan(plans, ADMIN.id) == FAMILY.key


def test_assigning_to_an_unknown_user_is_user_not_found() -> None:
    plans = _plans()
    plans_on(plans, FREE, FAMILY)

    with pytest.raises(UserNotFound):
        _assign(plans).execute(ADMIN.id, UserId("nobody"), FAMILY.key)

    assert plans.changes == {}


def test_a_user_deleted_before_the_assignment_is_user_not_found() -> None:
    plans = _plans()
    plans_on(plans, FREE, FAMILY)
    assigning = AssignPlan(plans.users, _DeletedMeanwhile(), plans, CLOCK)

    with pytest.raises(UserNotFound):
        assigning.execute(ADMIN.id, MEMBER.id, FAMILY.key)


def test_assigning_an_unknown_plan_is_plan_not_found_and_changes_nothing() -> None:
    plans = _plans()
    plans_on(plans, FREE)

    with pytest.raises(PlanNotFound):
        _assign(plans).execute(ADMIN.id, MEMBER.id, PlanKey("missing"))

    assert _own_plan(plans, MEMBER.id) is None
    assert plans.changes == {}


# Log lines


def test_each_change_logs_one_line_naming_only_ids(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=PLANS_LOGGER)
    plans = _plans()
    plans.add(as_new(FREE), NOW)

    _define(plans).execute(ADMIN.id, NewPlan("Solo", SOLO.limits))
    _change(plans).execute(ADMIN.id, replace(SOLO, name="Solo, renamed"))
    _assign(plans).execute(ADMIN.id, MEMBER.id, SOLO.key)
    _setting(plans).execute(ADMIN.id, True, FREE.key)
    _assign(plans).execute(ADMIN.id, MEMBER.id, None)
    _remove(plans).execute(ADMIN.id, SOLO.key)
    _setting(plans).execute(ADMIN.id, False, None)
    _setting(plans).execute(ADMIN.id, True, None)
    ShowPlans(plans.users, plans).execute(ADMIN.id)

    lines = [record.getMessage() for record in caplog.records if record.name == PLANS_LOGGER]
    assert lines == [
        "plan defined key=solo by=admin",
        "plan changed key=solo by=admin",
        "plan assigned user=member plan=solo by=admin",
        "plans setting changed enabled=True default=free by=admin",
        "plan assigned user=member plan=None by=admin",
        "plan removed key=solo by=admin",
        "plans setting changed enabled=False default=None by=admin",
        # The default the change made, not the none it asked for.
        "plans setting changed enabled=True default=no-limits by=admin",
    ]
    logged = "\n".join(lines)
    assert "Solo" not in logged
    assert "Free" not in logged
    assert "@example.test" not in logged
