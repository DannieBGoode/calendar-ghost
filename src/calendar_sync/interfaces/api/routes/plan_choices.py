"""The signed-in User's whole-set choice of rules to keep under their Plan."""

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, status

from calendar_sync.application.sync.errors import RuleNotFound
from calendar_sync.application.sync.plan_holds import (
    ChooseKeptRules,
    PlanSettlementBusy,
    TooManyKeptRules,
)
from calendar_sync.domain.errors import DomainValidationError
from calendar_sync.domain.model import SyncRuleId
from calendar_sync.interfaces.api.dependencies import user_services
from calendar_sync.interfaces.api.problems import problem_from
from calendar_sync.interfaces.api.schemas.sync import KeptRulesRequest


class OwnPlanChoiceServices(Protocol):
    @property
    def choose_kept_rules(self) -> ChooseKeptRules: ...


Services = Annotated[OwnPlanChoiceServices, Depends(user_services)]
router = APIRouter()


@router.put("/api/v1/account/plan/kept-rules", status_code=status.HTTP_204_NO_CONTENT)
def keep_rules(payload: KeptRulesRequest, services: Services) -> None:
    """Replace the whole kept set and apply available places and swaps immediately, all or none.
    Only this User's eligible rules may be chosen. A busy choice saves nothing; retry it later.
    """
    try:
        chosen = [SyncRuleId(identifier) for identifier in payload.rule_ids]
    except DomainValidationError as error:
        raise problem_from(
            status.HTTP_404_NOT_FOUND, RuleNotFound("a chosen rule is not eligible to keep")
        ) from error
    try:
        services.choose_kept_rules.execute(chosen)
    except RuleNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except (TooManyKeptRules, PlanSettlementBusy) as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
