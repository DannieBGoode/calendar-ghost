"""Plans as the Web API reads and answers them (ADR 0038): keys, limits, and Allowances."""

from __future__ import annotations

from fastapi import status

from calendar_sync.application.identity.errors import PlanNotFound
from calendar_sync.application.identity.plans import PlansOverview
from calendar_sync.application.identity.ports import PlanListing
from calendar_sync.application.operations.own_plan import OwnPlan
from calendar_sync.domain.plans import (
    Allowance,
    AllowanceBasis,
    InvalidPlan,
    Plan,
    PlanKey,
    PlanLimits,
    SyncInterval,
)
from calendar_sync.interfaces.api.problems import problem_from
from calendar_sync.interfaces.api.schemas import (
    AppliedPlanResponse,
    OwnPlanResponse,
    PersonPlanResponse,
    PlanLimitsRequest,
    PlanLimitsResponse,
    PlanNameResponse,
    PlanResponse,
    PlansResponse,
)


def named_plan(raw: str) -> PlanKey:
    """The Plan a path or a request names. A key this release refuses, of any length, names no
    Plan, so it is answered 404 as an unknown Plan is, never as a validation or server error.
    The answer does not repeat that key, so it stays short however long the key was."""
    try:
        return PlanKey(raw)
    except InvalidPlan as error:
        missing = PlanNotFound("no plan has this key")
        raise problem_from(status.HTTP_404_NOT_FOUND, missing) from error


def plan_limits(payload: PlanLimitsRequest) -> PlanLimits:
    """The limits a request asks for; raises InvalidPlan when one is out of range."""
    return PlanLimits(
        payload.rules,
        payload.connected_accounts,
        payload.integration_tokens,
        SyncInterval(payload.sync_interval),
    )


def plan_limits_response(limits: PlanLimits) -> PlanLimitsResponse:
    return PlanLimitsResponse(
        rules=limits.rules,
        connected_accounts=limits.connected_accounts,
        integration_tokens=limits.integration_tokens,
        sync_interval=limits.sync_interval.value,
    )


def plan_response(listing: PlanListing) -> PlanResponse:
    plan = listing.plan
    return PlanResponse(
        key=plan.key.value,
        name=plan.name,
        limits=plan_limits_response(plan.limits),
        is_default=listing.is_default,
        people=listing.people,
        limited_people=listing.limited_people,
    )


def plans_response(overview: PlansOverview) -> PlansResponse:
    default = overview.setting.default
    return PlansResponse(
        enabled=overview.setting.enabled,
        default_plan=default.value if default is not None else None,
        sync_intervals=[interval.value for interval in overview.offered],
        plans=[plan_response(listing) for listing in overview.plans],
    )


def person_plan_response(allowance: Allowance) -> PersonPlanResponse:
    """A person's Plan for the Operator Overview: the one that limits them, and their own."""
    assigned = allowance.assigned
    return PersonPlanResponse(
        basis=allowance.basis.value,
        plan=_applied(allowance),
        assigned=_named(assigned) if assigned is not None else None,
    )


def own_plan_response(own: OwnPlan) -> OwnPlanResponse:
    allowance = own.allowance
    cadence = allowance.cadence
    limited = allowance.basis is AllowanceBasis.PLAN
    return OwnPlanResponse(
        basis=allowance.basis.value,
        plan=_applied(allowance),
        limits=plan_limits_response(allowance.limits) if limited else None,
        rules_counted=own.rules_counted,
        connected_accounts=own.connected_accounts,
        integration_tokens=own.integration_tokens,
        instant=cadence.instant,
        poll_every_minutes=int(cadence.poll_every.total_seconds() // 60),
        may_connect_account=own.may_connect_account,
        may_issue_token=own.may_issue_token,
        over_rule_limit=own.over_rule_limit,
    )


def _applied(allowance: Allowance) -> AppliedPlanResponse | None:
    """The Plan that limits the User; None unless one does."""
    plan = allowance.plan
    if allowance.basis is not AllowanceBasis.PLAN or plan is None:
        return None
    return AppliedPlanResponse(key=plan.key.value, name=plan.name, on_default=allowance.on_default)


def _named(plan: Plan) -> PlanNameResponse:
    return PlanNameResponse(key=plan.key.value, name=plan.name)
