from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from calendar_sync.application.causes import Cause
from calendar_sync.application.locking import RuleWork, RuleWorkKind
from calendar_sync.application.ports import (
    AccountStanding,
    IncidentMessage,
    IncidentSummary,
    OpenBlock,
    OperationsOverview,
    RuleRunOutcome,
    RunKind,
    SchedulerProgress,
)
from calendar_sync.application.rules import SyncRuleSummary
from calendar_sync.application.status import (
    InstallationStatus,
    ProblemKind,
    StatusVerdict,
    assess_installation,
    calendar_display_name,
    rule_name,
)
from calendar_sync.domain.model import SyncRule, SyncRuleId, SyncRuleState
from tests.helpers import endpoint

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
CONNECTED = (
    AccountStanding("personal-account", "connected", "google"),
    AccountStanding("work-account", "connected", "google"),
)
LISTED = frozenset({"rule-1", "rule-2", "rule-a", "rule-b", "rule-c", "rule-d"})
"""Every rule id these tests enable, as the last completed pass listed them."""
TICKING = SchedulerProgress(NOW - timedelta(days=1), None, NOW - timedelta(minutes=2), LISTED)


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
    assert status.health is StatusVerdict.HEALTHY
    assert status.needs_attention is False
    assert status.problems == ()
    assert status.summary == "1 rule running."
    assert status.providers == {"personal-account": "google", "work-account": "google"}


def test_rule_names_use_last_known_calendar_names() -> None:
    summary = _summary(_rule())
    assert rule_name(summary) == "Personal → Work"
    assert rule_name(replace(summary, names={})) == "Unnamed calendar → Unnamed calendar"


def test_calendar_display_name_hides_a_name_that_is_the_account_email() -> None:
    account = endpoint("personal-account", "primary")
    assert calendar_display_name(account, {account: "person@example.test"}) == "Unnamed calendar"


def test_calendar_display_name_hides_a_name_that_is_the_bare_calendar_id() -> None:
    bare = endpoint("personal-account", "cal-raw-id-123")
    names = {bare: "cal-raw-id-123"}
    assert calendar_display_name(bare, names) == "Unnamed calendar"


def test_calendar_display_name_shows_a_normal_name() -> None:
    normal = endpoint("personal-account", "personal-calendar")
    assert calendar_display_name(normal, {normal: "Personal"}) == "Personal"


def test_calendar_display_name_hides_a_missing_name() -> None:
    missing = endpoint("personal-account", "personal-calendar")
    assert calendar_display_name(missing, {}) == "Unnamed calendar"


def test_rule_names_never_show_an_email_or_a_bare_calendar_id() -> None:
    leaky = _rule("leaky")
    summary = replace(
        _summary(leaky),
        names={
            leaky.source: "secret.person@example.test",
            leaky.destination: leaky.destination.calendar_id.value,
        },
    )
    assert rule_name(summary) == "Unnamed calendar → Unnamed calendar"


@pytest.mark.parametrize(
    ("progress", "health"),
    [
        (SchedulerProgress(NOW - timedelta(minutes=14), None, None), StatusVerdict.HEALTHY),
        (SchedulerProgress(NOW - timedelta(minutes=16), None, None), StatusVerdict.STALLED),
        (
            SchedulerProgress(NOW - timedelta(days=1), None, NOW - timedelta(minutes=14)),
            StatusVerdict.HEALTHY,
        ),
        (
            SchedulerProgress(NOW - timedelta(days=1), None, NOW - timedelta(minutes=16)),
            StatusVerdict.STALLED,
        ),
        (
            SchedulerProgress(
                NOW - timedelta(days=1),
                NOW - timedelta(hours=2, minutes=59),
                NOW - timedelta(hours=3),
            ),
            StatusVerdict.HEALTHY,
        ),
        (
            SchedulerProgress(
                NOW - timedelta(days=1),
                NOW - timedelta(hours=3, minutes=1),
                NOW - timedelta(hours=4),
            ),
            StatusVerdict.STALLED,
        ),
        (None, StatusVerdict.STALLED),
    ],
)
def test_a_scheduler_that_stopped_running_passes_is_stalled(
    progress: SchedulerProgress | None, health: StatusVerdict
) -> None:
    status = assess_installation([_summary(_rule())], _overview(), (), progress, NOW)
    assert status.health is health
    assert status.needs_attention is (health is StatusVerdict.STALLED)


def test_a_stalled_scheduler_without_enabled_rules_is_not_a_problem() -> None:
    status = assess_installation(
        [_summary(_rule(state=SyncRuleState.PAUSED))], _overview(), (), None, NOW
    )
    assert status.health is StatusVerdict.PAUSED


def test_a_degraded_rule_is_stopped_and_names_its_incident() -> None:
    incident = _incident("rule-1", "authentication")
    status = assess_installation(
        [_summary(_rule(state=SyncRuleState.DEGRADED))],
        _overview(open_incidents=1),
        (incident,),
        TICKING,
        NOW,
    )
    assert status.health is StatusVerdict.STOPPED
    assert status.problems[0].kind is ProblemKind.STOPPED
    assert status.problems[0].summary == "Calendar provider authorization expired"
    assert status.problems[0].since == NOW - timedelta(hours=1)
    assert status.rules[0].problem == status.problems[0]
    assert status.summary == "Personal → Work: Calendar provider authorization expired."


def test_problems_from_an_incident_carry_its_message() -> None:
    message = IncidentMessage("provider_failure", {"kind": "authentication", "provider": "google"})
    stopped = replace(_incident("rule-1", "authentication"), message=message)
    waiting = replace(_incident("rule-2", "rate_limit"), message=message)
    status = _assess(
        [_summary(_rule(state=SyncRuleState.DEGRADED)), _summary(_rule("rule-2"))],
        incidents=(stopped, waiting),
    )
    assert [(problem.kind, problem.message) for problem in status.problems] == [
        (ProblemKind.STOPPED, message),
        (ProblemKind.WAITING, message),
    ]


def test_problems_without_an_incident_have_no_message() -> None:
    status = assess_installation(
        [_summary(_rule(state=SyncRuleState.REMOVING))], _overview(), (), TICKING, NOW
    )
    assert status.problems[0].message is None


@pytest.mark.parametrize("side", ["personal-account", "work-account"])
def test_an_enabled_rule_with_a_disconnected_account_is_stopped(side: str) -> None:
    accounts = tuple(
        replace(account, state="disconnected") if account.id == side else account
        for account in CONNECTED
    )
    status = assess_installation(
        [_summary(_rule())], _overview(accounts=accounts), (), TICKING, NOW
    )
    assert status.health is StatusVerdict.STOPPED
    assert status.problems[0].summary == "A calendar account needs reauthorization"


def test_a_rule_whose_removal_is_running_is_not_stopped() -> None:
    removing = _rule(state=SyncRuleState.REMOVING)
    work = RuleWork(RuleWorkKind.REMOVAL, NOW - timedelta(seconds=30))
    status = assess_installation(
        [_summary(_rule("rule-2")), _summary(removing, running=work)], _overview(), (), TICKING, NOW
    )
    assert status.health is StatusVerdict.HEALTHY
    assert [rule.summary.rule.id.value for rule in status.rules] == ["rule-2"]


def test_an_interrupted_removal_is_stopped() -> None:
    status = assess_installation(
        [_summary(_rule(state=SyncRuleState.REMOVING))], _overview(), (), TICKING, NOW
    )
    assert status.health is StatusVerdict.STOPPED
    assert status.problems[0].summary == "Stopped syncing"


def test_provider_waiting_turns_into_review_after_a_day() -> None:
    fresh = _incident("rule-1", "rate_limit", opened=NOW - timedelta(hours=23))
    lasting = _incident("rule-1", "rate_limit", opened=NOW - timedelta(hours=25))
    assert _assess([_summary(_rule())], incidents=(fresh,)).health is StatusVerdict.WAITING
    assert _assess([_summary(_rule())], incidents=(lasting,)).health is StatusVerdict.REVIEW


def test_waiting_does_not_need_attention() -> None:
    status = _assess([_summary(_rule())], incidents=(_incident("rule-1", "temporary"),))
    assert status.health is StatusVerdict.WAITING
    assert status.needs_attention is False


def test_open_blocks_need_a_look_and_name_their_rule() -> None:
    blocks = (OpenBlock(42, "rule-1"), OpenBlock(41, "rule-1"))
    status = _assess([_summary(_rule())], overview=_overview(blocks=blocks))
    assert status.health is StatusVerdict.REVIEW
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
    assert (status.health is StatusVerdict.REVIEW) is overdue
    if overdue:
        assert status.problems[0].kind is ProblemKind.OVERDUE
        assert status.problems[0].since == NOW - timedelta(hours=hours)


def test_a_rule_resumed_after_days_is_not_overdue_before_the_next_pass_lists_it() -> None:
    # Resuming only flips the rule's state, so its last success is still three days old; the
    # last completed pass ran while it was paused and did not list it.
    resumed = _summary(_rule("rule-resumed"), succeeded_at=NOW - timedelta(days=3))
    status = _assess([resumed])
    assert status.health is StatusVerdict.HEALTHY
    assert status.problems == ()


def test_a_rule_the_last_pass_listed_that_is_still_stale_is_overdue() -> None:
    listed = replace(TICKING, last_pass_rule_ids=frozenset({"rule-resumed"}))
    stale = _summary(_rule("rule-resumed"), succeeded_at=NOW - timedelta(days=3))
    status = _assess([stale], scheduler=listed)
    assert status.health is StatusVerdict.REVIEW
    assert [(p.kind, p.rule_id) for p in status.problems] == [(ProblemKind.OVERDUE, "rule-resumed")]


def test_running_and_never_synced_rules_are_never_overdue() -> None:
    work = RuleWork(RuleWorkKind.SYNC, NOW - timedelta(minutes=1))
    running = _summary(_rule(), succeeded_at=NOW - timedelta(days=3), running=work)
    never = _summary(_rule("rule-2"), succeeded_at=None)
    assert _assess([running, never]).health is StatusVerdict.HEALTHY


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
    assert status.health is StatusVerdict.STOPPED


def test_an_open_incident_never_reads_as_healthy() -> None:
    status = _assess([_summary(_rule())], incidents=(_incident(None, "permanent"),))
    assert status.health is StatusVerdict.REVIEW
    assert status.problems[0].rule_id is None


@pytest.mark.parametrize(
    ("summaries", "overview", "health"),
    [
        ([], _overview(accounts=()), StatusVerdict.SETUP),
        ([], _overview(), StatusVerdict.SETUP),
        (
            [_summary(_rule(state=SyncRuleState.PAUSED))],
            _overview(),
            StatusVerdict.PAUSED,
        ),
        (
            [_summary(_rule(state=SyncRuleState.PREVIEWED), succeeded_at=None)],
            _overview(last_synced_at=None),
            StatusVerdict.SETUP,
        ),
        (
            [_summary(_rule(state=SyncRuleState.PAUSED))],
            _overview(accounts=tuple(replace(a, state="disconnected") for a in CONNECTED)),
            StatusVerdict.SETUP,
        ),
    ],
)
def test_installations_without_running_rules(
    summaries: list[SyncRuleSummary], overview: OperationsOverview, health: StatusVerdict
) -> None:
    status = assess_installation(summaries, overview, (), TICKING, NOW)
    assert status.health is health
    assert status.needs_attention is False


def test_overdue_is_superseded_by_a_waiting_incident_on_the_same_rule() -> None:
    incident = _incident("rule-1", "rate_limit", opened=NOW - timedelta(hours=1))
    status = assess_installation(
        [_summary(_rule(), succeeded_at=NOW - timedelta(days=2))],
        _overview(open_incidents=1),
        (incident,),
        TICKING,
        NOW,
    )
    assert status.health is StatusVerdict.WAITING
    assert status.needs_attention is False
    assert len(status.problems) == 1
    assert status.problems[0].kind is ProblemKind.WAITING
    assert status.problems[0].rule_id == "rule-1"


def test_an_uncovered_conflict_incident_becomes_a_review_for_its_rule() -> None:
    uncovered = _incident("rule-1", "conflict")
    status = assess_installation(
        [
            _summary(_rule("rule-1")),
            _summary(_rule("rule-2"), succeeded_at=NOW - timedelta(days=2)),
        ],
        _overview(open_incidents=1),
        (uncovered,),
        TICKING,
        NOW,
    )
    by_rule = {problem.rule_id: problem.kind for problem in status.problems}
    assert by_rule["rule-1"] is ProblemKind.REVIEW
    assert by_rule["rule-2"] is ProblemKind.OVERDUE


def test_a_review_worthy_incident_wins_over_a_waiting_one_regardless_of_order() -> None:
    permanent = _incident("rule-1", "permanent")
    waiting = _incident("rule-1", "rate_limit")
    for incidents in ((permanent, waiting), (waiting, permanent)):
        status = _assess([_summary(_rule())], incidents=incidents)
        assert status.health is StatusVerdict.REVIEW
        assert len(status.problems) == 1
        assert status.problems[0].kind is ProblemKind.REVIEW
        assert status.problems[0].rule_id == "rule-1"


LAPSED = (
    AccountStanding("personal-account", "connected", "google"),
    AccountStanding("work-account", "connected", "google", lapsed=True),
)


def test_rules_a_lapsed_account_stops_need_reauthorization_and_name_no_account() -> None:
    stopped = _rule("rule-1", SyncRuleState.DEGRADED)
    running = _rule("rule-2")
    account_incident = replace(
        _incident(None, "authentication"), id="incident-account", account_id="work-account"
    )

    status = _assess(
        [_summary(stopped), _summary(running)],
        _overview(accounts=LAPSED, open_incidents=1),
        (account_incident,),
    )

    assert status.health is StatusVerdict.STOPPED
    # The account's Incident is covered by the rules it stopped, so it is not a problem itself.
    assert [(p.kind, p.rule_id) for p in status.problems] == [
        (ProblemKind.STOPPED, "rule-1"),
        (ProblemKind.STOPPED, "rule-2"),
    ]
    assert [p.message for p in status.problems] == [
        IncidentMessage("authorization_lapsed", {"provider": "google"})
    ] * 2
    assert "@" not in status.summary
    assert status.overview.lapsed_accounts == 1


def test_a_lapsed_account_no_rule_uses_is_still_a_problem_to_review() -> None:
    account_incident = replace(
        _incident(None, "authentication"), id="incident-account", account_id="work-account"
    )
    paused = _rule("rule-1", SyncRuleState.PAUSED)

    status = _assess(
        [_summary(paused)], _overview(accounts=LAPSED, open_incidents=1), (account_incident,)
    )

    assert [(p.kind, p.rule_id) for p in status.problems] == [(ProblemKind.REVIEW, None)]


def test_a_lapsed_accounts_rules_carry_why_the_provider_refused() -> None:
    stopped = _rule("rule-1", SyncRuleState.DEGRADED)
    refused = NOW - timedelta(minutes=30)
    account_incident = replace(
        _incident(None, "authorization", opened=NOW - timedelta(hours=2)),
        id="incident-account",
        account_id="work-account",
        cause=Cause.API_DISABLED,
        updated_at=refused.isoformat(),
    )

    status = _assess(
        [_summary(stopped)], _overview(accounts=LAPSED, open_incidents=1), (account_incident,)
    )

    (problem,) = status.problems
    assert (problem.cause, problem.last_tried_at) == (Cause.API_DISABLED, refused)


def test_a_problem_an_incident_explains_carries_its_cause_and_when_it_was_last_tried() -> None:
    waiting = replace(
        _incident("rule-1", "rate_limit", opened=NOW - timedelta(hours=2)),
        cause=Cause.RATE_LIMITED,
        updated_at=(NOW - timedelta(minutes=4)).isoformat(),
    )
    stopped = replace(_incident("rule-2", "permanent"), cause=Cause.CALENDAR_NOT_FOUND)

    status = _assess(
        [_summary(_rule("rule-1")), _summary(_rule("rule-2", SyncRuleState.DEGRADED))],
        incidents=(waiting, stopped),
    )

    causes = {p.rule_id: (p.kind, p.cause, p.last_tried_at) for p in status.problems}
    assert causes == {
        "rule-1": (ProblemKind.WAITING, Cause.RATE_LIMITED, NOW - timedelta(minutes=4)),
        "rule-2": (ProblemKind.STOPPED, Cause.CALENDAR_NOT_FOUND, NOW - timedelta(hours=1)),
    }


def test_a_problem_no_provider_failure_explains_has_no_cause() -> None:
    overdue = _summary(_rule("rule-1"), succeeded_at=NOW - timedelta(days=2))

    status = _assess([overdue])

    (problem,) = status.problems
    assert (problem.kind, problem.cause, problem.last_tried_at) == (ProblemKind.OVERDUE, None, None)
