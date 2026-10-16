"""Plans (ADR 0038): the limits an Installation Administrator defines, the Default Plan, the
setting that turns Plans on, and what the signed-in User's own Plan allows.

Every route here is an Installation Administrator's, except Your plan, which every User reads.
Assigning a Plan to a User is in `users.py`, beside the other changes to a User.
"""

from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, status

from calendar_sync.application.identity.administration import AdministratorRequired
from calendar_sync.application.identity.errors import PlanKeyTaken, PlanNotFound
from calendar_sync.application.identity.plans import (
    ChangePlan,
    DefinePlan,
    RemovePlan,
    SetPlansSetting,
    ShowPlans,
)
from calendar_sync.application.operations.own_plan import ShowOwnPlan
from calendar_sync.domain.access import UserId
from calendar_sync.domain.plans import (
    InvalidPlan,
    NewPlan,
    Plan,
    PlanInUse,
    PlanIsDefault,
    PlanKey,
    PlansNeedDefault,
)
from calendar_sync.interfaces.api.dependencies import administrator, app_services, user_services
from calendar_sync.interfaces.api.plan_payload import (
    named_plan,
    own_plan_response,
    plan_limits,
    plan_response,
    plans_response,
)
from calendar_sync.interfaces.api.problems import problem_from
from calendar_sync.interfaces.api.schemas import (
    ChangePlanRequest,
    DefinePlanRequest,
    OwnPlanResponse,
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


class PlansApiServices(Protocol):
    @property
    def plans(self) -> PlanAdministration: ...


class OwnPlanServices(Protocol):
    @property
    def show_own_plan(self) -> ShowOwnPlan: ...


Services = Annotated[PlansApiServices, Depends(app_services)]
OwnServices = Annotated[OwnPlanServices, Depends(user_services)]
Administrator = Annotated[UserId, Depends(administrator)]
router = APIRouter()


@router.get("/api/v1/plans", response_model=PlansResponse)
def list_plans(services: Services, actor: Administrator) -> PlansResponse:
    """Every Plan with how many people have it, the Plans setting, and the offered intervals."""
    try:
        return plans_response(services.plans.show_plans.execute(actor))
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
    except PlanNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except PlansNeedDefault as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except AdministratorRequired as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error
    return plans_response(overview)


@router.post("/api/v1/plans", response_model=PlanResponse, status_code=status.HTTP_201_CREATED)
def define_plan(
    payload: DefinePlanRequest, services: Services, actor: Administrator
) -> PlanResponse:
    """Add a Plan. Its key is the one asked for, or one made from its name; it never changes,
    so billing can name it later."""
    try:
        key = PlanKey(payload.key) if payload.key is not None else None
        plan = NewPlan(payload.name.strip(), plan_limits(payload.limits), key)
        listing = services.plans.define_plan.execute(actor, plan)
    except InvalidPlan as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    except PlanKeyTaken as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except PlanNotFound as error:
        # Stored, then removed by another administrator before it was read back.
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except AdministratorRequired as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error
    return plan_response(listing)


@router.put("/api/v1/plans/{plan_key}", response_model=PlanResponse)
def change_plan(
    plan_key: str, payload: ChangePlanRequest, services: Services, actor: Administrator
) -> PlanResponse:
    """Rename a Plan or change its limits; its key stays. New limits apply at once to new
    rules, accounts, and tokens, and stop nothing that exists."""
    key = named_plan(plan_key)
    try:
        plan = _plan(key, payload.name, payload.limits)
        listing = services.plans.change_plan.execute(actor, plan)
    except InvalidPlan as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    except PlanNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except AdministratorRequired as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error
    return plan_response(listing)


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


@router.get("/api/v1/account/plan", response_model=OwnPlanResponse)
def own_plan(services: OwnServices) -> OwnPlanResponse:
    """What the signed-in User's Plan allows and how much of it they have, for Your plan. A
    fault reading Plans fails this request; each limit is still checked where it applies."""
    return own_plan_response(services.show_own_plan.execute())


def _plan(key: PlanKey, name: str, limits: PlanLimitsRequest) -> Plan:
    """The Plan a request describes, without spaces around its name; raises InvalidPlan."""
    return Plan(key, name.strip(), plan_limits(limits))
