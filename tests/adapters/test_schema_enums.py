"""Each Literal alias the API schemas use lists exactly the values of the enum it mirrors.

The OpenAPI document, and the frontend types generated from it, take their values from these
aliases, so a value added to the enum alone would reach clients that do not know it.
"""

from enum import StrEnum
from typing import Literal, get_args, get_origin

import pytest

from calendar_sync.application.identity.ports import IntegrationTokenScope
from calendar_sync.application.operations.installation_hints import HintKind
from calendar_sync.application.operations.status import ProblemKind, StatusVerdict
from calendar_sync.application.sync.locking import RuleWorkKind
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.incidents import IncidentCategory, IncidentResolution, IncidentStep
from calendar_sync.domain.model import (
    ProjectionContent,
    ProjectionHandling,
    TentativeEventPolicy,
    UnansweredInvitationPolicy,
)
from calendar_sync.interfaces.api import schemas

MIRRORS: dict[str, type[StrEnum]] = {
    "CauseValue": Cause,
    "HintKindValue": HintKind,
    "IncidentCategoryValue": IncidentCategory,
    "IncidentResolutionValue": IncidentResolution,
    "IncidentStepValue": IncidentStep,
    "PrivacyPolicy": ProjectionContent,
    "ProblemKindValue": ProblemKind,
    "ProjectionChoice": ProjectionHandling,
    "StatusVerdictValue": StatusVerdict,
    "TentativeChoice": TentativeEventPolicy,
    "TokenScope": IntegrationTokenScope,
    "UnansweredChoice": UnansweredInvitationPolicy,
    "WorkKind": RuleWorkKind,
}

# Aliases that mirror no enum, each with the reason.
UNMIRRORED = {
    # The incidents table's CHECK constraint is its only other definition.
    "IncidentState",
}


@pytest.mark.parametrize(("alias", "enum"), sorted(MIRRORS.items()), ids=sorted(MIRRORS))
def test_a_schema_literal_lists_exactly_the_values_of_its_enum(
    alias: str, enum: type[StrEnum]
) -> None:
    assert set(get_args(getattr(schemas, alias))) == {member.value for member in enum}


def test_every_schema_literal_alias_mirrors_an_enum_or_says_why_not() -> None:
    aliases = {name for name, value in vars(schemas).items() if get_origin(value) is Literal}

    assert aliases == MIRRORS.keys() | UNMIRRORED
