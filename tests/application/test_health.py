from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from calendar_sync.application.errors import ProviderFailure, ProviderFailureKind
from calendar_sync.application.health import (
    PROVIDER_INCIDENT_THRESHOLD,
    FailureResponse,
    RuleHealth,
    RuleHealthPolicy,
)
from calendar_sync.application.lapsed_authorization import LapsedAuthorizations
from calendar_sync.application.ports import (
    ConnectedAccountState,
    IncidentMessage,
    IncidentReport,
    IncidentResolution,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId, SyncRuleState
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.fake_calendar import FixedClock
from tests.helpers import NOW, rule

RULE = SyncRuleId("rule-1")
ACCOUNT = ConnectedAccountId("work-account")
DENIED = ProviderFailure(ProviderFailureKind.AUTHORIZATION, "403", provider=ProviderKind.GOOGLE)
INTERVENTION = (
    ProviderFailureKind.AUTHENTICATION,
    ProviderFailureKind.AUTHORIZATION,
    ProviderFailureKind.PERMANENT,
    ProviderFailureKind.INFRASTRUCTURE,
)
TRANSIENT = (ProviderFailureKind.RATE_LIMIT, ProviderFailureKind.TEMPORARY)
AUTHORIZATION = (ProviderFailureKind.AUTHENTICATION, ProviderFailureKind.AUTHORIZATION)


def _failure(kind: ProviderFailureKind) -> ProviderFailure:
    return ProviderFailure(kind, "synthetic")


@pytest.mark.parametrize("kind", INTERVENTION)
def test_failures_requiring_intervention_degrade_and_open_an_incident_at_once(
    kind: ProviderFailureKind,
) -> None:
    failure = replace(_failure(kind), account_id=None if kind in AUTHORIZATION else ACCOUNT)
    response = RuleHealthPolicy().after_failure(RULE, failure, consecutive_failures=1)

    assert response.degrade
    assert response.incident == IncidentReport(
        f"provider:{RULE.value}",
        RULE,
        kind.value,
        RuleHealthPolicy.summary(failure),
        account_id=failure.account_id,
        message=IncidentMessage("provider_failure", {"kind": kind.value, "provider": None}),
    )
    assert response.lapsed is None


@pytest.mark.parametrize("kind", AUTHORIZATION)
def test_an_account_the_provider_refuses_lapses_instead_of_opening_a_rule_incident(
    kind: ProviderFailureKind,
) -> None:
    failure = replace(_failure(kind), account_id=ACCOUNT)

    response = RuleHealthPolicy().after_failure(RULE, failure, consecutive_failures=1)

    assert response == FailureResponse(degrade=True, incident=None, lapsed=ACCOUNT)


@pytest.mark.parametrize(
    ("kind", "summary"),
    [
        (ProviderFailureKind.AUTHENTICATION, "Authorization for Google Calendar expired"),
        (ProviderFailureKind.AUTHORIZATION, "Access to Google Calendar was denied"),
        (ProviderFailureKind.RATE_LIMIT, "Google Calendar is limiting requests"),
        (ProviderFailureKind.TEMPORARY, "Google Calendar is temporarily unavailable"),
        (ProviderFailureKind.PERMANENT, "Google Calendar rejected synchronization"),
        (ProviderFailureKind.INFRASTRUCTURE, "Local synchronization infrastructure failed"),
    ],
)
def test_incident_summaries_name_the_provider_that_failed(
    kind: ProviderFailureKind, summary: str
) -> None:
    failure = ProviderFailure(kind, "synthetic", provider=ProviderKind.GOOGLE)

    assert RuleHealthPolicy.summary(failure) == summary


def test_a_failure_naming_no_provider_is_summarized_without_one() -> None:
    assert (
        RuleHealthPolicy.summary(_failure(ProviderFailureKind.RATE_LIMIT))
        == "The calendar provider is limiting requests"
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
        message=IncidentMessage("events_still_blocked", {"count": 1}),
    )
    assert two is not None
    assert two.summary == "2 events could not be synced and were still blocked at the daily check."


def test_a_blocked_removal_names_its_cause() -> None:
    failure = replace(_failure(ProviderFailureKind.AUTHORIZATION), account_id=ACCOUNT)
    incident = RuleHealthPolicy().removal_blocked(RULE, failure)

    assert incident == IncidentReport(
        f"removal:{RULE.value}",
        RULE,
        "authorization",
        "Rule Removal stopped: Access to the calendar provider was denied",
        account_id=ACCOUNT,
        message=IncidentMessage("removal_stopped", {"kind": "authorization", "provider": None}),
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
        self.reports: list[IncidentReport] = []

    def open(self, incident: IncidentReport, at: datetime) -> bool:
        self.events.append(("open", incident.key, at))
        self.reports.append(incident)
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


def test_recovery_lapses_the_account_still_unauthorized() -> None:
    # The rule stopped on one account; recovering it met the other, which also lost access.
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[RULE] = rule(state=SyncRuleState.DEGRADED)
    unit_of_work.state.accounts[ACCOUNT] = ConnectedAccountState.CONNECTED
    records, incidents, notifications = Records(), Incidents(), Notifications()
    health = RuleHealth(unit_of_work, records, incidents, FixedClock(), notifications=notifications)
    failure = replace(_failure(ProviderFailureKind.AUTHENTICATION), account_id=ACCOUNT)

    health.recovery_blocked(RULE, failure, attempted_at=NOW)

    assert unit_of_work.state.lapsed == {ACCOUNT: NOW}
    assert incidents.events == [("open", "authorization:work-account", NOW)]
    assert incidents.reports[-1].rule_id is None
    assert [incident.key for incident, _ in notifications.opened] == ["authorization:work-account"]
    # A preview is not a failed sync run.
    assert records.failures == {}


def test_recovery_without_the_account_refreshes_the_rules_incident() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    records, incidents = Records(), Incidents()
    incidents.open_keys.add("provider:rule-1")
    health = RuleHealth(unit_of_work, records, incidents, FixedClock())

    health.recovery_blocked(RULE, _failure(ProviderFailureKind.AUTHENTICATION), attempted_at=NOW)

    assert incidents.events == [("open", "provider:rule-1", NOW)]
    assert unit_of_work.state.lapsed == {}


def test_a_refused_account_stops_its_rule_until_reauthorization() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[RULE] = rule()
    unit_of_work.state.accounts[ACCOUNT] = ConnectedAccountState.CONNECTED
    records, incidents, notifications = Records(), Incidents(), Notifications()
    health = RuleHealth(unit_of_work, records, incidents, FixedClock(), notifications=notifications)
    expired = replace(_failure(ProviderFailureKind.AUTHENTICATION), account_id=ACCOUNT)

    health.record_failure(rule(), expired)
    health.record_failure(rule(), expired)

    stopped = unit_of_work.state.rules[RULE]
    assert (stopped.state, stopped.awaiting_reauthorization) == (SyncRuleState.DEGRADED, True)
    assert unit_of_work.state.lapsed == {ACCOUNT: NOW}
    assert [event[1] for event in incidents.events] == ["authorization:work-account"] * 2
    # One notification for the account, however many times its rules fail.
    assert len(notifications.opened) == 1


def test_a_refusal_of_credentials_reauthorization_replaced_stops_nothing() -> None:
    # The run began with the old credentials; the account was reauthorized before it failed.
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[RULE] = rule()
    unit_of_work.state.accounts[ACCOUNT] = ConnectedAccountState.CONNECTED
    unit_of_work.state.authorized_at[ACCOUNT] = NOW
    incidents, notifications = Incidents(), Notifications()
    health = RuleHealth(
        unit_of_work, Records(), incidents, FixedClock(), notifications=notifications
    )
    expired = replace(_failure(ProviderFailureKind.AUTHENTICATION), account_id=ACCOUNT)

    health.record_failure(rule(), expired, attempted_at=NOW - timedelta(minutes=1))

    assert unit_of_work.state.rules[RULE].state is SyncRuleState.ENABLED
    assert unit_of_work.state.lapsed == {}
    assert incidents.events == []
    assert notifications.opened == []


class RestoredRightAfterLapsing(LapsedAuthorizations):
    """Reauthorization that lands between lapsing an account and stopping its rule."""

    def lapsed(
        self, account_id: ConnectedAccountId, failure: ProviderFailure, *, attempted_at: datetime
    ) -> bool:
        lapsed = super().lapsed(account_id, failure, attempted_at=attempted_at)
        self.restored(account_id, accepted_at=self.clock.now())
        return lapsed


def test_a_rule_whose_account_was_restored_before_it_stopped_keeps_running() -> None:
    # Reauthorization landed after the account lapsed but before the rule was stopped, so it
    # found nothing to resume; the rule must not stop for an account that is authorized again.
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[RULE] = rule()
    unit_of_work.state.accounts[ACCOUNT] = ConnectedAccountState.CONNECTED
    health = RuleHealth(unit_of_work, Records(), Incidents(), FixedClock())
    health.lapses = RestoredRightAfterLapsing(unit_of_work, Incidents(), FixedClock())
    expired = replace(_failure(ProviderFailureKind.AUTHENTICATION), account_id=ACCOUNT)

    health.record_failure(rule(), expired)

    assert unit_of_work.state.rules[RULE].state is SyncRuleState.ENABLED
    assert unit_of_work.state.lapsed == {}


def test_a_permanent_failure_stops_its_rule_for_a_preview() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[RULE] = rule()
    health = RuleHealth(unit_of_work, Records(), Incidents(), FixedClock())

    health.record_failure(
        rule(), replace(_failure(ProviderFailureKind.PERMANENT), account_id=ACCOUNT)
    )

    assert not unit_of_work.state.rules[RULE].awaiting_reauthorization
    assert unit_of_work.state.lapsed == {}


def test_every_incident_report_carries_a_message() -> None:
    policy = RuleHealthPolicy()
    provider = policy.provider_incident(RULE, DENIED)
    blocked = policy.after_full_pass(RULE, 3)
    removal = policy.removal_blocked(RULE, DENIED)
    assert provider.message == IncidentMessage(
        "provider_failure", {"kind": "authorization", "provider": "google"}
    )
    assert blocked is not None
    assert blocked.message == IncidentMessage("events_still_blocked", {"count": 3})
    assert removal.message == IncidentMessage(
        "removal_stopped", {"kind": "authorization", "provider": "google"}
    )


def test_a_failure_without_a_provider_has_a_null_provider() -> None:
    failure = ProviderFailure(ProviderFailureKind.INFRASTRUCTURE, "disk")
    report = RuleHealthPolicy().provider_incident(RULE, failure)
    assert report.message == IncidentMessage(
        "provider_failure", {"kind": "infrastructure", "provider": None}
    )
