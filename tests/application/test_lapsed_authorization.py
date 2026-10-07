from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from calendar_sync.application.errors import ProviderFailure, ProviderFailureKind
from calendar_sync.application.lapsed_authorization import LapsedAuthorizations
from calendar_sync.application.ports import (
    ConnectedAccountState,
    IncidentReport,
    IncidentResolution,
)
from calendar_sync.application.providers import ProviderKind
from calendar_sync.domain.model import ConnectedAccountId, SyncRuleId, SyncRuleState
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.fake_calendar import FixedClock
from tests.helpers import NOW, endpoint, rule

PERSONAL = ConnectedAccountId("personal-account")
WORK = ConnectedAccountId("work-account")
EXPIRED = ProviderFailure(
    ProviderFailureKind.AUTHENTICATION, "expired", account_id=WORK, provider=ProviderKind.GOOGLE
)


class Incidents:
    def __init__(self) -> None:
        self.opened: list[IncidentReport] = []
        self.resolved: list[tuple[str, IncidentResolution]] = []

    def open(self, incident: IncidentReport, at: datetime) -> bool:
        self.opened.append(incident)
        return len(self.opened) == 1

    def resolve(
        self,
        key: str,
        at: datetime,
        resolution: IncidentResolution,
        *,
        while_authorized: ConnectedAccountId | None = None,
    ) -> None:
        self.resolved.append((key, resolution))


def _installation() -> tuple[InMemoryUnitOfWorkFactory, Incidents, LapsedAuthorizations]:
    unit_of_work = InMemoryUnitOfWorkFactory()
    for account in (PERSONAL, WORK):
        unit_of_work.state.accounts[account] = ConnectedAccountState.CONNECTED
    incidents = Incidents()
    return unit_of_work, incidents, LapsedAuthorizations(unit_of_work, incidents, FixedClock())


def test_a_lapse_marks_the_account_and_opens_one_incident_for_it() -> None:
    unit_of_work, incidents, lapses = _installation()

    lapses.lapsed(WORK, EXPIRED, attempted_at=NOW)

    assert unit_of_work.state.lapsed == {WORK: NOW}
    (incident,) = incidents.opened
    assert (incident.key, incident.rule_id, incident.account_id) == (
        "authorization:work-account",
        None,
        WORK,
    )
    assert incident.summary == "Authorization for Google Calendar expired"
    assert incident.message is not None
    assert incident.message.code == "authorization_lapsed"


def test_a_disconnected_account_does_not_lapse() -> None:
    unit_of_work, _, lapses = _installation()
    unit_of_work.state.accounts[WORK] = ConnectedAccountState.DISCONNECTED

    lapses.lapsed(WORK, EXPIRED, attempted_at=NOW)

    assert unit_of_work.state.lapsed == {}


def test_restoring_access_resumes_only_rules_the_lapse_alone_stopped() -> None:
    unit_of_work, incidents, lapses = _installation()
    awaiting = rule().degrade(awaiting_reauthorization=True)
    needs_preview = replace(
        rule().degrade(), id=SyncRuleId("rule-2"), source=endpoint("personal-account", "other")
    )
    unit_of_work.state.rules = {awaiting.id: awaiting, needs_preview.id: needs_preview}
    lapses.lapsed(WORK, EXPIRED, attempted_at=NOW)

    resumed = lapses.restored(WORK, accepted_at=NOW)

    assert resumed == 1
    assert unit_of_work.state.rules[awaiting.id].state is SyncRuleState.ENABLED
    assert unit_of_work.state.rules[needs_preview.id].state is SyncRuleState.DEGRADED
    assert unit_of_work.state.lapsed == {}
    assert incidents.resolved == [
        ("authorization:work-account", IncidentResolution.ACCESS_RESTORED)
    ]


def test_a_rule_waits_while_its_other_account_is_still_lapsed() -> None:
    unit_of_work, _, lapses = _installation()
    awaiting = rule().degrade(awaiting_reauthorization=True)
    unit_of_work.state.rules = {awaiting.id: awaiting}
    lapses.lapsed(WORK, EXPIRED, attempted_at=NOW)
    lapses.lapsed(PERSONAL, replace(EXPIRED, account_id=PERSONAL), attempted_at=NOW)

    assert lapses.restored(WORK, accepted_at=NOW) == 0
    assert unit_of_work.state.rules[awaiting.id].state is SyncRuleState.DEGRADED

    assert lapses.restored(PERSONAL, accepted_at=NOW) == 1
    assert unit_of_work.state.rules[awaiting.id].state is SyncRuleState.ENABLED


def test_restoring_an_account_that_never_lapsed_changes_no_rule() -> None:
    unit_of_work, _, lapses = _installation()
    unit_of_work.state.rules = {rule().id: rule()}

    assert lapses.restored(WORK, accepted_at=NOW) == 0
    assert unit_of_work.state.rules[rule().id] == rule()


def test_a_refusal_after_the_provider_accepted_the_account_stands() -> None:
    # Google accepted the account, then refused a later request before restoring ran.
    unit_of_work, incidents, lapses = _installation()
    awaiting = rule().degrade(awaiting_reauthorization=True)
    unit_of_work.state.rules = {awaiting.id: awaiting}
    lapses.lapsed(WORK, EXPIRED, attempted_at=NOW)

    resumed = lapses.restored(WORK, accepted_at=NOW - timedelta(seconds=1))

    assert resumed == 0
    assert unit_of_work.state.lapsed == {WORK: NOW}
    assert unit_of_work.state.rules[awaiting.id].state is SyncRuleState.DEGRADED
    assert incidents.resolved == []


def test_a_lapse_found_outside_a_sync_run_stops_the_accounts_enabled_rules() -> None:
    # Check access or a preview found it, so no failing run stopped these rules first.
    unit_of_work, _, lapses = _installation()
    enabled = rule()
    previewed = replace(
        rule(state=SyncRuleState.PREVIEWED),
        id=SyncRuleId("previewed"),
        source=endpoint("work-account", "other"),
    )
    elsewhere = replace(
        rule(),
        id=SyncRuleId("elsewhere"),
        source=endpoint("other-account", "home"),
        destination=endpoint("other-account", "away"),
    )
    unit_of_work.state.rules = {r.id: r for r in (enabled, previewed, elsewhere)}

    lapses.lapsed(WORK, EXPIRED, attempted_at=NOW)

    states = {
        rule_id.value: (stored.state, stored.awaiting_reauthorization)
        for rule_id, stored in unit_of_work.state.rules.items()
    }
    assert states == {
        "rule-1": (SyncRuleState.DEGRADED, True),
        # Never enabled, so restoring must not enable it; enabling it later fails and stops it.
        "previewed": (SyncRuleState.PREVIEWED, False),
        "elsewhere": (SyncRuleState.ENABLED, False),
    }


def test_a_passing_check_clears_a_refusal_of_a_request_begun_before_it() -> None:
    # An older request was refused while Check access ran; the check then passed.
    unit_of_work, _, lapses = _installation()
    unit_of_work.state.accounts[PERSONAL] = ConnectedAccountState.CONNECTED
    awaiting = rule().degrade(awaiting_reauthorization=True)
    unit_of_work.state.rules = {awaiting.id: awaiting}
    check_began = NOW - timedelta(seconds=1)
    lapses.lapsed(WORK, EXPIRED, attempted_at=check_began - timedelta(seconds=1))

    assert lapses.restored(WORK, accepted_at=check_began) == 1
    assert unit_of_work.state.lapsed == {}
