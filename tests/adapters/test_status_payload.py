"""The Overview's dashboard and the status API count rules with one rule (RuleCounts)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from calendar_sync.application.operations.ports import (
    AccountStanding,
    IncidentSummary,
    OpenBlock,
    OperationsOverview,
    SchedulerProgress,
)
from calendar_sync.application.operations.status import Dashboard, assess_installation
from calendar_sync.application.sync.locking import RuleWork, RuleWorkKind
from calendar_sync.application.sync.rules import SyncRuleSummary
from calendar_sync.domain.accounts import ConnectedAccountState, ProviderKind
from calendar_sync.domain.incidents import IncidentCategory
from calendar_sync.domain.model import SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.domain.runs import RuleRunOutcome, RunKind
from calendar_sync.interfaces.api.status_payload import dashboard_response, status_response
from tests.helpers import endpoint

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
RULE = "rule-1"
SCHEDULER = SchedulerProgress(
    NOW - timedelta(days=3), None, NOW - timedelta(minutes=2), frozenset({RULE})
)


def _account(
    account_id: str, *, disconnected: bool = False, lapsed: bool = False
) -> AccountStanding:
    state = ConnectedAccountState.DISCONNECTED if disconnected else ConnectedAccountState.CONNECTED
    return AccountStanding(account_id, state, ProviderKind.GOOGLE, lapsed=lapsed)


HEALTHY_ACCOUNTS = (_account("personal-account"), _account("work-account"))


def _summary(
    state: SyncRuleState = SyncRuleState.ENABLED,
    *,
    succeeded_at: datetime = NOW - timedelta(minutes=2),
    running: RuleWork | None = None,
) -> SyncRuleSummary:
    rule = SyncRule(
        id=SyncRuleId(RULE),
        source=endpoint("personal-account", "source"),
        destination=endpoint("work-account", "destination"),
        state=state,
    )
    last = RuleRunOutcome(
        rule.id, RunKind.SYNC, succeeded_at, succeeded=True, last_succeeded_at=succeeded_at
    )
    return SyncRuleSummary(rule, last, None, running, {})


def _incident(category: IncidentCategory) -> IncidentSummary:
    return IncidentSummary(
        id="incident-1",
        rule_id=RULE,
        category=category,
        state="open",
        summary="The calendar provider refused the change",
        opened_at=NOW - timedelta(hours=2),
        updated_at=NOW - timedelta(hours=1),
    )


# Each situation a rule can be in: its summary, its accounts, its open incidents, and the
# rules, running, stopped, paused, and overdue counts both payloads must report.
SITUATIONS = {
    "enabled and healthy": (_summary(), HEALTHY_ACCOUNTS, (), (1, 1, 0, 0, 0)),
    "enabled with an open blocking incident": (
        _summary(),
        HEALTHY_ACCOUNTS,
        (_incident(IncidentCategory.PERMANENT),),
        (1, 1, 0, 0, 0),
    ),
    "enabled with a lapsed account": (
        _summary(),
        (_account("personal-account"), _account("work-account", lapsed=True)),
        (),
        (1, 0, 1, 0, 0),
    ),
    "enabled with a disconnected account": (
        _summary(),
        (_account("personal-account"), _account("work-account", disconnected=True)),
        (),
        (1, 0, 1, 0, 0),
    ),
    "degraded": (
        _summary(SyncRuleState.DEGRADED),
        HEALTHY_ACCOUNTS,
        (_incident(IncidentCategory.AUTHENTICATION),),
        (1, 0, 1, 0, 0),
    ),
    "paused": (_summary(SyncRuleState.PAUSED), HEALTHY_ACCOUNTS, (), (1, 0, 0, 1, 0)),
    "with an interrupted removal": (
        _summary(SyncRuleState.REMOVING),
        HEALTHY_ACCOUNTS,
        (),
        (1, 0, 1, 0, 0),
    ),
    "being removed": (
        _summary(
            SyncRuleState.REMOVING,
            running=RuleWork(RuleWorkKind.REMOVAL, NOW - timedelta(seconds=30)),
        ),
        HEALTHY_ACCOUNTS,
        (),
        (0, 0, 0, 0, 0),
    ),
    "overdue": (
        _summary(succeeded_at=NOW - timedelta(days=2)),
        HEALTHY_ACCOUNTS,
        (),
        (1, 1, 0, 0, 1),
    ),
}


@pytest.mark.parametrize("situation", SITUATIONS)
def test_the_dashboard_and_the_status_api_count_every_rule_alike(situation: str) -> None:
    summary, accounts, incidents, expected = SITUATIONS[situation]
    overview = OperationsOverview(
        connected_accounts=sum(a.state is ConnectedAccountState.CONNECTED for a in accounts),
        disconnected_accounts=sum(a.state is ConnectedAccountState.DISCONNECTED for a in accounts),
        open_incidents=len(incidents),
        last_synced_at=NOW - timedelta(minutes=2),
        open_blocks=(),
        accounts=accounts,
    )
    status = assess_installation([summary], overview, incidents, SCHEDULER, NOW)

    counts = status_response(status).counts
    dashboard = dashboard_response(status)

    assert (counts.rules, counts.running, counts.stopped, counts.paused, counts.overdue) == expected
    assert (dashboard.sync_rules, dashboard.running_rules, dashboard.stopped_rules) == (
        counts.rules,
        counts.running,
        counts.stopped,
    )
    assert Dashboard.of(status).rules.paused == counts.paused


def test_an_enabled_rule_is_enabled_on_the_dashboard_even_while_it_is_stopped() -> None:
    accounts = (_account("personal-account"), _account("work-account", lapsed=True))
    overview = OperationsOverview(2, 0, 0, NOW, (), accounts)
    status = assess_installation([_summary()], overview, (), SCHEDULER, NOW)

    dashboard = dashboard_response(status)

    # The Overview's setup checklist reads `enabled_rules`: the rule was turned on.
    assert (dashboard.enabled_rules, dashboard.running_rules, dashboard.stopped_rules) == (1, 0, 1)


def test_held_status_payload_preserves_raw_incidents_and_blocks() -> None:
    summary = _summary()
    held = replace(summary, rule=summary.rule.hold())
    incidents = (_incident(IncidentCategory.PERMANENT),)
    overview = OperationsOverview(
        2, 0, 1, NOW, (OpenBlock(42, RULE),), HEALTHY_ACCOUNTS, held_open_incidents=1
    )
    status = assess_installation([held], overview, incidents, SCHEDULER, NOW)
    payload = status_response(status)
    dashboard = dashboard_response(status)
    assert (payload.counts.open_incidents, payload.counts.blocked_events) == (1, 1)
    assert len(payload.incidents) == 1
    assert (dashboard.open_incidents, dashboard.blocked_events) == (0, 0)
    assert dashboard.blocked_entry_id is None
    assert dashboard.blocked_rule_id is None
    assert payload.rules[0].stop_cause == "plan_hold"
    assert payload.problems == []
    assert dashboard.held_rules == payload.counts.held == 1


@pytest.mark.parametrize(
    ("state", "awaiting", "held", "cause"),
    [
        (SyncRuleState.ENABLED, False, False, None),
        (SyncRuleState.DEGRADED, False, False, None),
        (SyncRuleState.DEGRADED, True, False, "lapsed_authorization"),
        (SyncRuleState.DEGRADED, False, True, "plan_hold"),
    ],
)
def test_status_rule_exposes_exact_self_resuming_stop_cause(
    state: SyncRuleState, awaiting: bool, held: bool, cause: str | None
) -> None:
    summary = _summary()
    summary = replace(
        summary,
        rule=replace(
            summary.rule, state=state, awaiting_reauthorization=awaiting, held_by_plan=held
        ),
    )
    overview = OperationsOverview(2, 0, 0, NOW, (), HEALTHY_ACCOUNTS)
    payload = status_response(assess_installation([summary], overview, (), SCHEDULER, NOW))
    assert payload.rules[0].stop_cause == cause
    assert set(payload.counts.model_dump()) == {
        "rules",
        "running",
        "stopped",
        "paused",
        "held",
        "overdue",
        "open_incidents",
        "blocked_events",
        "disconnected_accounts",
        "lapsed_accounts",
    }
    assert set(payload.rules[0].model_dump()) == {
        "id",
        "name",
        "state",
        "stop_cause",
        "source",
        "destination",
        "projection",
        "last_succeeded_at",
        "running",
        "problem",
    }
