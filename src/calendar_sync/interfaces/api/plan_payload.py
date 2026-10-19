"""Plans as the Web API reads and answers them (ADR 0038): keys, limits, and Allowances."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fastapi import status

from calendar_sync.application.identity.errors import PlanNotFound
from calendar_sync.application.identity.plans import PlansOverview
from calendar_sync.application.identity.ports import PlanListing
from calendar_sync.application.operations.operator_overview import PersonPlan
from calendar_sync.application.operations.own_plan import OwnPlan
from calendar_sync.application.operations.plan_assignment import PlanMove
from calendar_sync.domain.plans import (
    Allowance,
    AllowanceBasis,
    InvalidPlan,
    OverLimit,
    Plan,
    PlanKey,
    PlanLimits,
    PlanReach,
    PlanUse,
    SyncInterval,
    UseCount,
)
from calendar_sync.interfaces.api.problems import problem_from
from calendar_sync.interfaces.api.schemas import (
    AppliedPlanResponse,
    LimitUseResponse,
    OverLimitResponse,
    OwnPlanResponse,
    PersonPlanOverviewResponse,
    PersonPlanUseResponse,
    PlanAssignmentsResponse,
    PlanLimitsRequest,
    PlanLimitsResponse,
    PlanMoveResponse,
    PlanNameResponse,
    PlanResponse,
    PlansResponse,
    PlanUseCountsResponse,
    UseCountResponse,
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


def plan_response(listing: PlanListing, reach: PlanReach) -> PlanResponse:
    """A Plan as Administration lists it, with how much the people it limits use."""
    plan = listing.plan
    return PlanResponse(
        key=plan.key.value,
        name=plan.name,
        limits=plan_limits_response(plan.limits),
        is_default=listing.is_default,
        people=listing.people,
        limited_people=listing.limited_people,
        over_people=reach.over,
        use=PlanUseCountsResponse(
            rules=_counts(reach.rules),
            connected_accounts=_counts(reach.connected_accounts),
            integration_tokens=_counts(reach.integration_tokens),
        ),
    )


def plans_response(overview: PlansOverview, reach: Mapping[PlanKey, PlanReach]) -> PlansResponse:
    """Every Plan, each with its reach in `reach`."""
    default = overview.setting.default
    return PlansResponse(
        enabled=overview.setting.enabled,
        default_plan=default.value if default is not None else None,
        sync_intervals=[interval.value for interval in overview.offered],
        followers=overview.followers,
        plans=[plan_response(listing, reach[listing.plan.key]) for listing in overview.plans],
    )


def person_plan_overview_response(person: PersonPlan) -> PersonPlanOverviewResponse:
    """A person's Plan for the Operator Overview: as it limits them now, the Plan they have,
    each of its limits they are over, who gave it and when, and how much of it they use."""
    allowance, has = person.allowance, person.has
    return PersonPlanOverviewResponse(
        basis=allowance.basis.value,
        plan=_applied(allowance),
        assigned=_named(allowance.assigned) if allowance.assigned is not None else None,
        has=_held(person),
        over=_over(person.over),
        assigned_by=person.assigned_by,
        assigned_at=person.assigned_at.isoformat() if person.assigned_at is not None else None,
        use=_use(person.use, has.limits) if has is not None and person.use is not None else None,
    )


def plan_assignments_response(
    moves: Sequence[PlanMove], *, dry_run: bool
) -> PlanAssignmentsResponse:
    """Each person given a Plan, or who would be: the Plan they had and have, and what they are
    over."""
    return PlanAssignmentsResponse(
        dry_run=dry_run,
        people=[
            PlanMoveResponse(
                user_id=move.user.id.value,
                email=move.user.email,
                had=_held(move.before),
                has=_held(move.after),
                over=_over(move.after.over),
            )
            for move in moves
        ],
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


def _held(person: PersonPlan) -> AppliedPlanResponse | None:
    """The Plan a person has, whether or not it limits them now."""
    has = person.has
    if has is None:
        return None
    return AppliedPlanResponse(key=has.key.value, name=has.name, on_default=person.on_default)


def _over(over: tuple[OverLimit, ...]) -> list[OverLimitResponse]:
    return [
        OverLimitResponse(limit=each.resource.value, in_use=each.in_use, allowed=each.allowed)
        for each in over
    ]


def _use(use: PlanUse, limits: PlanLimits) -> PersonPlanUseResponse:
    return PersonPlanUseResponse(
        rules=LimitUseResponse(in_use=use.rules, allowed=limits.rules),
        connected_accounts=LimitUseResponse(
            in_use=use.connected_accounts, allowed=limits.connected_accounts
        ),
        integration_tokens=LimitUseResponse(
            in_use=use.integration_tokens, allowed=limits.integration_tokens
        ),
        sync_interval=limits.sync_interval.value,
    )


def _counts(counts: tuple[UseCount, ...]) -> list[UseCountResponse]:
    return [UseCountResponse(in_use=count.in_use, people=count.people) for count in counts]
