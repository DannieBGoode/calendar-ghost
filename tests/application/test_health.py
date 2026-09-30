from __future__ import annotations

from datetime import datetime

import pytest

from calendar_sync.application.errors import ProviderFailure, ProviderFailureKind
from calendar_sync.application.health import (
    PROVIDER_INCIDENT_THRESHOLD,
    RuleHealth,
    RuleHealthPolicy,
)
from calendar_sync.application.ports import IncidentReport, IncidentResolution
from calendar_sync.domain.model import SyncRuleId, SyncRuleState
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.fake_calendar import FixedClock
from tests.helpers import NOW, rule

RULE = SyncRuleId("rule-1")
INTERVENTION = (
    ProviderFailureKind.AUTHENTICATION,
    ProviderFailureKind.AUTHORIZATION,
    ProviderFailureKind.PERMANENT,
    ProviderFailureKind.INFRASTRUCTURE,
)
TRANSIENT = (ProviderFailureKind.RATE_LIMIT, ProviderFailureKind.TEMPORARY)


def _failure(kind: ProviderFailureKind) -> ProviderFailure:
    return ProviderFailure(kind, "synthetic")


@pytest.mark.parametrize("kind", INTERVENTION)
def test_failures_requiring_intervention_degrade_and_open_an_incident_at_once(
    kind: ProviderFailureKind,
) -> None:
    response = RuleHealthPolicy().after_failure(RULE, _failure(kind), consecutive_failures=1)

    assert response.degrade
    assert response.incident == IncidentReport(
        f"provider:{RULE.value}", RULE, kind.value, RuleHealthPolicy.summary(kind)
    )


@pytest.mark.parametrize("kind", TRANSIENT)
def test_transient_failures_open_a_provider_incident_only_at_the_threshold(
    kind: ProviderFailureKind,
) -> None:
    policy = RuleHealthPolicy()

    below = policy.after_failure(RULE, _failure(kind), PROVIDER_INCIDENT_THRESHOLD - 1)
    at = policy.after_failure(RULE, _failure(kind), PROVIDER_INCIDENT_THRESHOLD)

    assert PROVIDER_INCIDENT_THRESHOLD == 3
    assert (below.degrade, below.incident) == (False, None)
    assert not at.degrade
    assert at.incident is not None
    assert at.incident.key == f"provider:{RULE.value}"


def test_persisting_blocks_open_one_incident_that_names_how_many() -> None:
    policy = RuleHealthPolicy()

    one = policy.after_full_pass(RULE, persisting=1)
    two = policy.after_full_pass(RULE, persisting=2)

    assert policy.after_full_pass(RULE, persisting=0) is None
    assert one == IncidentReport(
        f"blocked:{RULE.value}",
        RULE,
        "conflict",
        "1 event could not be synced and was still blocked at the daily check.",
    )
    assert two is not None
    assert two.summary == "2 events could not be synced and were still blocked at the daily check."


def test_a_blocked_removal_names_its_cause() -> None:
    incident = RuleHealthPolicy().removal_blocked(RULE, _failure(ProviderFailureKind.AUTHORIZATION))

    assert incident == IncidentReport(
        f"removal:{RULE.value}",
        RULE,
        "authorization",
        "Rule Removal stopped: Google calendar access was denied",
    )


class Records:
    def __init__(self) -> None:
        self.failures: dict[SyncRuleId, int] = {}
        self.times: list[datetime] = []

    def record_failure(self, rule_id: SyncRuleId, kind: ProviderFailureKind, at: datetime) -> int:
        self.times.append(at)
        self.failures[rule_id] = self.failures.get(rule_id, 0) + 1
        return self.failures[rule_id]

    def clear_failures(self, rule_id: SyncRuleId) -> None:
        self.failures.pop(rule_id, None)

    def audit_floor(self) -> int:
        return 0

    def record_block_check(
        self, rule_id: SyncRuleId, floor: int, run_id: str | None, at: datetime
    ) -> int | None:
        self.times.append(at)
        return 0


class Incidents:
    def __init__(self) -> None:
        self.open_keys: set[str] = set()
        self.events: list[tuple[str, str, datetime]] = []
        self.resolutions: dict[str, IncidentResolution] = {}

    def open(self, incident: IncidentReport, at: datetime) -> bool:
        self.events.append(("open", incident.key, at))
        newly = incident.key not in self.open_keys
        self.open_keys.add(incident.key)
        return newly

    def resolve(self, key: str, at: datetime, resolution: IncidentResolution) -> None:
        self.events.append(("resolve", key, at))
        self.resolutions[key] = resolution
        self.open_keys.discard(key)


class Notifications:
    def __init__(self) -> None:
        self.opened: list[tuple[IncidentReport, datetime]] = []

    def incident_opened(self, incident: IncidentReport, at: datetime) -> None:
        self.opened.append((incident, at))


def test_rule_health_times_everything_by_its_clock_and_notifies_only_new_incidents() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[RULE] = rule()
    records, incidents, notifications = Records(), Incidents(), Notifications()
    health = RuleHealth(unit_of_work, records, incidents, FixedClock(), notifications=notifications)
    denied = _failure(ProviderFailureKind.AUTHORIZATION)

    health.record_failure(rule(), denied)
    health.record_failure(rule(), denied)
    health.record_success(rule(), full_pass_floor=0)

    assert unit_of_work.state.rules[RULE].state is SyncRuleState.DEGRADED
    assert [incident.key for incident, _ in notifications.opened] == ["provider:rule-1"]
    assert records.failures == {}
    assert [event[:2] for event in incidents.events] == [
        ("open", "provider:rule-1"),
        ("open", "provider:rule-1"),
        ("resolve", "provider:rule-1"),
        ("resolve", "blocked:rule-1"),
    ]
    assert incidents.resolutions == {
        "provider:rule-1": IncidentResolution.SYNC_SUCCEEDED,
        "blocked:rule-1": IncidentResolution.BLOCKS_CLEARED,
    }
    assert {at for *_, at in incidents.events} | set(records.times) == {NOW}
