from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from calendar_sync.application.activity import (
    AccountStanding,
    IncidentSummary,
    OpenBlock,
    OperationsOverview,
)
from calendar_sync.application.locking import RuleWork, RuleWorkKind
from calendar_sync.application.ports import RuleRunOutcome, RunKind, SchedulerProgress
from calendar_sync.application.rules import SyncRuleSummary
from calendar_sync.application.status import (
    InstallationHealth,
    InstallationStatus,
    ProblemKind,
    assess_installation,
    rule_name,
)
from calendar_sync.domain.model import SyncRule, SyncRuleId, SyncRuleState
from tests.helpers import endpoint

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
CONNECTED = (
    AccountStanding("personal-account", "connected", "google"),
    AccountStanding("work-account", "connected", "google"),
)
TICKING = SchedulerProgress(NOW - timedelta(days=1), None, NOW - timedelta(minutes=2))


def _rule(rule_id: str = "rule-1", state: SyncRuleState = SyncRuleState.ENABLED) -> SyncRule:
    return SyncRule(
        id=SyncRuleId(rule_id),
        source=endpoint("personal-account", f"{rule_id}-source"),
        destination=endpoint("work-account", f"{rule_id}-destination"),
        state=state,
    )


def _summary(
    rule: SyncRule,
    *,
    succeeded_at: datetime | None = NOW - timedelta(minutes=2),
    running: RuleWork | None = None,
) -> SyncRuleSummary:
    last_sync = (
        RuleRunOutcome(
            rule.id, RunKind.SYNC, succeeded_at, succeeded=True, last_succeeded_at=succeeded_at
        )
        if succeeded_at
        else None
    )
    names = {rule.source: "Personal", rule.destination: "Work"}
    return SyncRuleSummary(rule, last_sync, None, running, names)


def _overview(
    *,
    accounts: tuple[AccountStanding, ...] = CONNECTED,
    open_incidents: int = 0,
    blocks: tuple[OpenBlock, ...] = (),
    last_synced_at: str | None = "2026-10-03T11:58:00+00:00",
) -> OperationsOverview:
    return OperationsOverview(
        connected_accounts=sum(a.state == "connected" for a in accounts),
        disconnected_accounts=sum(a.state == "disconnected" for a in accounts),
        open_incidents=open_incidents,
        last_synced_at=last_synced_at,
        open_blocks=blocks,
        accounts=accounts,
    )


def _incident(
    rule_id: str | None, category: str, *, opened: datetime = NOW - timedelta(hours=1)
) -> IncidentSummary:
    return IncidentSummary(
        id=f"incident-{rule_id}-{category}",
        rule_id=rule_id,
        category=category,
        state="open",
        summary="Calendar provider authorization expired",
        opened_at=opened.isoformat(),
        updated_at=opened.isoformat(),
    )


def _assess(
    summaries: list[SyncRuleSummary],
    overview: OperationsOverview | None = None,
    incidents: tuple[IncidentSummary, ...] = (),
    scheduler: SchedulerProgress | None = TICKING,
) -> InstallationStatus:
    return assess_installation(
        summaries,
        overview or _overview(open_incidents=len(incidents)),
        incidents,
        scheduler,
        NOW,
    )


def test_a_running_installation_is_healthy() -> None:
    status = assess_installation([_summary(_rule())], _overview(), (), TICKING, NOW)
    assert status.health is InstallationHealth.HEALTHY
    assert status.needs_attention is False
    assert status.problems == ()
    assert status.summary == "1 rule running."


def test_rule_names_use_last_known_calendar_names() -> None:
    summary = _summary(_rule())
    assert rule_name(summary) == "Personal → Work"
    assert rule_name(replace(summary, names={})) == "Unnamed calendar → Unnamed calendar"


@pytest.mark.parametrize(
    ("progress", "health"),
    [
        (SchedulerProgress(NOW - timedelta(minutes=14), None, None), InstallationHealth.HEALTHY),
        (SchedulerProgress(NOW - timedelta(minutes=16), None, None), InstallationHealth.STALLED),
        (
            SchedulerProgress(NOW - timedelta(days=1), None, NOW - timedelta(minutes=14)),
            InstallationHealth.HEALTHY,
        ),
        (
            SchedulerProgress(NOW - timedelta(days=1), None, NOW - timedelta(minutes=16)),
            InstallationHealth.STALLED,
        ),
        (
            SchedulerProgress(
                NOW - timedelta(days=1),
                NOW - timedelta(hours=2, minutes=59),
                NOW - timedelta(hours=3),
            ),
            InstallationHealth.HEALTHY,
        ),
        (
            SchedulerProgress(
                NOW - timedelta(days=1),
                NOW - timedelta(hours=3, minutes=1),
                NOW - timedelta(hours=4),
            ),
            InstallationHealth.STALLED,
        ),
        (None, InstallationHealth.STALLED),
    ],
)
def test_a_scheduler_that_stopped_running_passes_is_stalled(
    progress: SchedulerProgress | None, health: InstallationHealth
) -> None:
    status = assess_installation([_summary(_rule())], _overview(), (), progress, NOW)
    assert status.health is health
    assert status.needs_attention is (health is InstallationHealth.STALLED)


def test_a_stalled_scheduler_without_enabled_rules_is_not_a_problem() -> None:
    status = assess_installation(
        [_summary(_rule(state=SyncRuleState.PAUSED))], _overview(), (), None, NOW
    )
    assert status.health is InstallationHealth.PAUSED


def test_a_degraded_rule_is_stopped_and_names_its_incident() -> None:
    incident = _incident("rule-1", "authentication")
    status = assess_installation(
        [_summary(_rule(state=SyncRuleState.DEGRADED))],
        _overview(open_incidents=1),
        (incident,),
        TICKING,
        NOW,
    )
    assert status.health is InstallationHealth.STOPPED
    assert status.problems[0].kind is ProblemKind.STOPPED
    assert status.problems[0].summary == "Calendar provider authorization expired"
    assert status.problems[0].since == NOW - timedelta(hours=1)
    assert status.rules[0].problem == status.problems[0]
    assert status.summary == "Personal → Work: Calendar provider authorization expired."


@pytest.mark.parametrize("side", ["personal-account", "work-account"])
def test_an_enabled_rule_with_a_disconnected_account_is_stopped(side: str) -> None:
    accounts = tuple(
        replace(account, state="disconnected") if account.id == side else account
        for account in CONNECTED
    )
    status = assess_installation(
        [_summary(_rule())], _overview(accounts=accounts), (), TICKING, NOW
    )
    assert status.health is InstallationHealth.STOPPED
    assert status.problems[0].summary == "A calendar account needs reauthorization"


def test_a_rule_whose_removal_is_running_is_not_stopped() -> None:
    removing = _rule(state=SyncRuleState.REMOVING)
    work = RuleWork(RuleWorkKind.REMOVAL, NOW - timedelta(seconds=30))
    status = assess_installation(
        [_summary(_rule("rule-2")), _summary(removing, running=work)], _overview(), (), TICKING, NOW
    )
    assert status.health is InstallationHealth.HEALTHY
    assert [rule.summary.rule.id.value for rule in status.rules] == ["rule-2"]


def test_an_interrupted_removal_is_stopped() -> None:
    status = assess_installation(
        [_summary(_rule(state=SyncRuleState.REMOVING))], _overview(), (), TICKING, NOW
    )
    assert status.health is InstallationHealth.STOPPED
    assert status.problems[0].summary == "Stopped syncing"


def test_provider_waiting_turns_into_review_after_a_day() -> None:
    fresh = _incident("rule-1", "rate_limit", opened=NOW - timedelta(hours=23))
    lasting = _incident("rule-1", "rate_limit", opened=NOW - timedelta(hours=25))
    assert _assess([_summary(_rule())], incidents=(fresh,)).health is InstallationHealth.WAITING
    assert _assess([_summary(_rule())], incidents=(lasting,)).health is InstallationHealth.REVIEW


def test_waiting_does_not_need_attention() -> None:
    status = _assess([_summary(_rule())], incidents=(_incident("rule-1", "temporary"),))
    assert status.health is InstallationHealth.WAITING
    assert status.needs_attention is False


def test_open_blocks_need_a_look_and_name_their_rule() -> None:
    blocks = (OpenBlock(42, "rule-1"), OpenBlock(41, "rule-1"))
    status = _assess([_summary(_rule())], overview=_overview(blocks=blocks))
    assert status.health is InstallationHealth.REVIEW
    assert status.problems[0].kind is ProblemKind.BLOCKED
    assert status.problems[0].rule_id == "rule-1"
    assert status.problems[0].summary == "2 events couldn't be synced"


def test_a_blocked_incident_is_covered_by_the_open_blocks() -> None:
    blocked = _incident("rule-1", "conflict")
    status = _assess(
        [_summary(_rule())],
        overview=_overview(open_incidents=1, blocks=(OpenBlock(42, "rule-1"),)),
        incidents=(blocked,),
    )
    assert [problem.kind for problem in status.problems] == [ProblemKind.BLOCKED]


@pytest.mark.parametrize(("hours", "overdue"), [(23, False), (25, True)])
def test_a_rule_not_synced_for_a_day_is_overdue(hours: int, overdue: bool) -> None:
    status = _assess([_summary(_rule(), succeeded_at=NOW - timedelta(hours=hours))])
    assert (status.health is InstallationHealth.REVIEW) is overdue
    if overdue:
        assert status.problems[0].kind is ProblemKind.OVERDUE
        assert status.problems[0].since == NOW - timedelta(hours=hours)


def test_running_and_never_synced_rules_are_never_overdue() -> None:
    work = RuleWork(RuleWorkKind.SYNC, NOW - timedelta(minutes=1))
    running = _summary(_rule(), succeeded_at=NOW - timedelta(days=3), running=work)
    never = _summary(_rule("rule-2"), succeeded_at=None)
    assert _assess([running, never]).health is InstallationHealth.HEALTHY


def test_problems_are_ordered_most_urgent_first() -> None:
    status = _assess(
        [
            _summary(_rule("rule-a", SyncRuleState.DEGRADED)),
            _summary(_rule("rule-b")),
            _summary(_rule("rule-c")),
            _summary(_rule("rule-d"), succeeded_at=NOW - timedelta(days=2)),
        ],
        overview=_overview(open_incidents=2, blocks=(OpenBlock(9, "rule-x"),)),
        incidents=(_incident("rule-c", "rate_limit"), _incident("rule-b", "permanent")),
    )
    assert [(problem.kind, problem.rule_id) for problem in status.problems] == [
        (ProblemKind.STOPPED, "rule-a"),
        (ProblemKind.REVIEW, "rule-b"),
        (ProblemKind.OVERDUE, "rule-d"),
        (ProblemKind.BLOCKED, "rule-x"),
        (ProblemKind.WAITING, "rule-c"),
    ]
    assert status.health is InstallationHealth.STOPPED


def test_an_open_incident_never_reads_as_healthy() -> None:
    status = _assess([_summary(_rule())], incidents=(_incident(None, "permanent"),))
    assert status.health is InstallationHealth.REVIEW
    assert status.problems[0].rule_id is None


@pytest.mark.parametrize(
    ("summaries", "overview", "health"),
    [
        ([], _overview(accounts=()), InstallationHealth.SETUP),
        ([], _overview(), InstallationHealth.SETUP),
        (
            [_summary(_rule(state=SyncRuleState.PAUSED))],
            _overview(),
            InstallationHealth.PAUSED,
        ),
        (
            [_summary(_rule(state=SyncRuleState.PREVIEWED), succeeded_at=None)],
            _overview(last_synced_at=None),
            InstallationHealth.SETUP,
        ),
        (
            [_summary(_rule(state=SyncRuleState.PAUSED))],
            _overview(accounts=tuple(replace(a, state="disconnected") for a in CONNECTED)),
            InstallationHealth.SETUP,
        ),
    ],
)
def test_installations_without_running_rules(
    summaries: list[SyncRuleSummary], overview: OperationsOverview, health: InstallationHealth
) -> None:
    status = assess_installation(summaries, overview, (), TICKING, NOW)
    assert status.health is health
    assert status.needs_attention is False
