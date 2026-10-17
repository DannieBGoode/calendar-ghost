"""Plans (ADR 0038): the limits an Installation Administrator defines, the Default Plan, the
setting that turns Plans on, and what the signed-in User's own Plan allows.

Every route here is an Installation Administrator's, except Your plan, which every User reads.
Giving one User a Plan is in `users.py`, beside the other changes to a User; giving one Plan to
many people at once is here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, status

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.errors import PlanKeyTaken, PlanNotFound
from calendar_sync.application.identity.plans import (
    ChangePlan,
    DefinePlan,
    PlansOverview,
    RemovePlan,
    SetPlansSetting,
    ShowPlans,
)
from calendar_sync.application.identity.ports import PlanListing
from calendar_sync.application.operations.operator_overview import OperatorOverview
from calendar_sync.application.operations.own_plan import ShowOwnPlan
from calendar_sync.application.operations.plan_assignment import AssignPlans, unknown_people
from calendar_sync.domain.access import UserId
from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.domain.plans import (
    InvalidAssignment,
    InvalidPlan,
    NewPlan,
    Plan,
    PlanInUse,
    PlanIsDefault,
    PlanKey,
    PlanNameTaken,
    PlansNeedDefault,
)
from calendar_sync.interfaces.api.dependencies import administrator, app_services, user_services
from calendar_sync.interfaces.api.plan_payload import (
    named_plan,
    own_plan_response,
    plan_assignments_response,
    plan_limits,
    plan_response,
    plans_response,
)
from calendar_sync.interfaces.api.problems import problem_from
from calendar_sync.interfaces.api.schemas import (
    ChangePlanRequest,
    DefinePlanRequest,
    OwnPlanResponse,
    PlanAssignmentsRequest,
    PlanAssignmentsResponse,
    PlanLimitsRequest,
    PlanResponse,
    PlansResponse,
    PlansSettingRequest,
)


class PlanAdministration(Protocol):
    @property
    def show_plans(self) -> ShowPlans: ...
    @property
    def define_plan(self) -> DefinePlan: ...
    @property
    def change_plan(self) -> ChangePlan: ...
    @property
    def remove_plan(self) -> RemovePlan: ...
    @property
    def set_plans_setting(self) -> SetPlansSetting: ...
    @property
    def assign_plans(self) -> AssignPlans: ...


class PlansApiServices(Protocol):
    @property
    def plans(self) -> PlanAdministration: ...
    @property
    def operator_overview(self) -> OperatorOverview:
        """Counts how much the people each Plan limits use, as only it reads across Users."""
        ...


class OwnPlanServices(Protocol):
    @property
    def show_own_plan(self) -> ShowOwnPlan: ...


Services = Annotated[PlansApiServices, Depends(app_services)]
OwnServices = Annotated[OwnPlanServices, Depends(user_services)]
Administrator = Annotated[UserId, Depends(administrator)]
router = APIRouter()


@router.get("/api/v1/plans", response_model=PlansResponse)
def list_plans(services: Services, actor: Administrator) -> PlansResponse:
    """Every Plan with how many people have it and how many of them have more than it allows,
    the Plans setting, and the offered intervals."""
    try:
        return _plans(services, actor, services.plans.show_plans.execute(actor))
    except AdministratorRequired as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error


@router.put("/api/v1/plan-settings", response_model=PlansResponse)
def set_plans_setting(
    payload: PlansSettingRequest, services: Services, actor: Administrator
) -> PlansResponse:
    """Turn Plans on or off, and choose the Default Plan. Turning Plans on with no default makes
    a Plan named "No limits" the default; the default cannot be cleared while Plans are on.
    Turning them off is always allowed and keeps every Plan and assignment."""
    default = named_plan(payload.default_plan) if payload.default_plan is not None else None
    try:
        overview = services.plans.set_plans_setting.execute(actor, payload.enabled, default)
        return _plans(services, actor, overview)
    except PlanNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except PlansNeedDefault as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except AdministratorRequired as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error


@router.post("/api/v1/plans", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
def define_plan(
    payload: DefinePlanRequest, services: Services, actor: Administrator
) -> PlanResponse:
    """Add a Plan. Its key is the one asked for, or one made from its name; it never changes,
    so billing can name it later."""
    try:
        key = PlanKey(payload.key) if payload.key is not None else None
        plan = NewPlan(payload.name.strip(), plan_limits(payload.limits), key)
        return _plan(services, actor, services.plans.define_plan.execute(actor, plan))
    except InvalidPlan as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    except (PlanKeyTaken, PlanNameTaken) as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except PlanNotFound as error:
        # Stored, then removed by another administrator before it was read back.
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except AdministratorRequired as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error


@router.put("/api/v1/plans/{plan_key}", response_model=PlanResponse)
def change_plan(
    plan_key: str, payload: ChangePlanRequest, services: Services, actor: Administrator
) -> PlanResponse:
    """Rename a Plan or change its limits; its key stays. New limits apply at once to new
    rules, accounts, and tokens, and stop nothing that exists."""
    key = named_plan(plan_key)
    try:
        plan = _changed(key, payload.name, payload.limits)
        return _plan(services, actor, services.plans.change_plan.execute(actor, plan))
    except InvalidPlan as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    except PlanNameTaken as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except PlanNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except AdministratorRequired as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error


@router.delete("/api/v1/plans/{plan_key}", status_code=status.HTTP_204_NO_CONTENT)
def remove_plan(plan_key: str, services: Services, actor: Administrator) -> None:
    """Remove a Plan that is not the default and that nobody has."""
    key = named_plan(plan_key)
    try:
        services.plans.remove_plan.execute(actor, key)
    except PlanNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except (PlanIsDefault, PlanInUse) as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except AdministratorRequired as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error


@router.post("/api/v1/plan-assignments", response_model=PlanAssignmentsResponse)
def assign_plans(
    payload: PlanAssignmentsRequest, services: Services, actor: Administrator
) -> PlanAssignmentsResponse:
    """Give one Plan, or with null the Default Plan, to up to 100 people at once, all or none,
    and answer each person's Plan before and after and what they are over. With `dry_run`,
    give nothing and answer the same, so who would be over is known before anyone confirms."""
    plan = named_plan(payload.plan) if payload.plan is not None else None
    assign = services.plans.assign_plans
    try:
        moves = assign.execute(
            actor, _named_people(payload.user_ids), plan, dry_run=payload.dry_run
        )
    except InvalidAssignment as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    except PlanNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except AdministratorRequired as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error
    return plan_assignments_response(moves, dry_run=payload.dry_run)


@router.get("/api/v1/account/plan", response_model=OwnPlanResponse)
def own_plan(services: OwnServices) -> OwnPlanResponse:
    """What the signed-in User's Plan allows and how much of it they have, for Your plan. A
    fault reading Plans fails this request; each limit is still checked where it applies."""
    return own_plan_response(services.show_own_plan.execute())


def _named_people(user_ids: Sequence[str]) -> list[UserId]:
    """The Users a request names; a malformed identifier names nobody, as an unknown one does.
    Raises InvalidAssignment."""
    try:
        return [UserId(user_id) for user_id in user_ids]
    except DomainValidationError as error:
        raise unknown_people() from error


def _changed(key: PlanKey, name: str, limits: PlanLimitsRequest) -> Plan:
    """The Plan a request describes, without spaces around its name; raises InvalidPlan."""
    return Plan(key, name.strip(), plan_limits(limits))


def _plans(services: PlansApiServices, actor: UserId, overview: PlansOverview) -> PlansResponse:
    """Every Plan, each with how much the people it limits use, which the Operator Overview
    counts; raises AdministratorRequired."""
    plans = [listing.plan for listing in overview.plans]
    return plans_response(overview, services.operator_overview.reach_of(actor, plans))


def _plan(services: PlansApiServices, actor: UserId, listing: PlanListing) -> PlanResponse:
    """A Plan as listed, with how much the people it limits use; raises AdministratorRequired."""
    reach = services.operator_overview.reach_of(actor, [listing.plan])
    return plan_response(listing, reach[listing.plan.key])
