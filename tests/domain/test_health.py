"""The rule health policy decides from domain facts alone, with no application error (#104)."""

from dataclasses import dataclass

import pytest

from calendar_sync.domain.accounts import ProviderKind
from calendar_sync.domain.causes import Cause
from calendar_sync.domain.health import PROVIDER_INCIDENT_THRESHOLD, RuleHealthPolicy
from calendar_sync.domain.incidents import IncidentCategory, IncidentMessage
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId
from calendar_sync.domain.providers import ProviderFailureKind

RULE = SyncRuleId("rule-1")
ACCOUNT = ConnectedAccountId("work-account")


@dataclass(frozen=True)
class Facts:
    """A failed call as the domain sees it, without the application's ProviderFailure."""

    kind: ProviderFailureKind
    summary: str = "Google Calendar is temporarily unavailable"
    account_id: ConnectedAccountId | None = ACCOUNT
    provider: ProviderKind | None = ProviderKind.GOOGLE
    provider_cause: Cause | None = Cause.TEMPORARY


@pytest.mark.parametrize(
    "kind", [ProviderFailureKind.AUTHENTICATION, ProviderFailureKind.AUTHORIZATION]
)
def test_an_authorization_failure_lapses_the_account_instead_of_opening_a_rule_incident(
    kind: ProviderFailureKind,
) -> None:
    response = RuleHealthPolicy().after_failure(RULE, Facts(kind), consecutive_failures=1)

    assert (response.degrade, response.incident, response.lapsed) == (True, None, ACCOUNT)


def test_a_temporary_failure_opens_an_incident_only_at_the_threshold() -> None:
    policy, facts = RuleHealthPolicy(), Facts(ProviderFailureKind.TEMPORARY)

    before = policy.after_failure(RULE, facts, PROVIDER_INCIDENT_THRESHOLD - 1)
    at = policy.after_failure(RULE, facts, PROVIDER_INCIDENT_THRESHOLD)

    assert (before.degrade, before.incident) == (False, None)
    assert at.degrade is False
    assert at.incident is not None
    assert at.incident.key == "provider:rule-1"
    assert at.incident.category is IncidentCategory.TEMPORARY


@pytest.mark.parametrize(
    "kind", [ProviderFailureKind.PERMANENT, ProviderFailureKind.INFRASTRUCTURE]
)
def test_a_failure_retrying_cannot_fix_stops_the_rule_at_once(kind: ProviderFailureKind) -> None:
    response = RuleHealthPolicy().after_failure(RULE, Facts(kind), consecutive_failures=1)

    assert response.degrade is True
    assert response.incident is not None


def test_a_provider_incident_carries_the_facts_and_no_provider_text() -> None:
    facts = Facts(ProviderFailureKind.RATE_LIMIT, summary="Google Calendar is limiting requests")

    incident = RuleHealthPolicy().provider_incident(RULE, facts)

    assert incident.summary == "Google Calendar is limiting requests"
    assert incident.account_id == ACCOUNT
    assert incident.provider is ProviderKind.GOOGLE
    assert incident.cause is Cause.TEMPORARY
    assert incident.message == IncidentMessage(
        "provider_failure", {"kind": "rate_limit", "provider": "google"}
    )
