"""Installation Status: one health verdict for the Overview, the status API, and MCP."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from calendar_sync.application.activity import (
    IncidentSummary,
    OperationsOverview,
    OperationsQueries,
)
from calendar_sync.application.errors import ProviderFailureKind
from calendar_sync.application.locking import RuleWorkKind
from calendar_sync.application.ports import Clock, SchedulerHeartbeat, SchedulerProgress
from calendar_sync.application.rules import ListSyncRules, SyncRuleSummary
from calendar_sync.domain.model import SyncRuleState

STALL_AFTER = timedelta(minutes=15)
"""Three scheduler intervals without a completed pass."""
PASS_LIMIT = timedelta(hours=3)
"""Far beyond the 40-minute full pass seen on a Raspberry Pi."""
OVERDUE_AFTER = timedelta(hours=24)
WAITING_LIMIT = timedelta(hours=24)

# Provider conditions that retry by themselves; nothing to do unless they last.
WAITING_CATEGORIES = frozenset(
    {ProviderFailureKind.RATE_LIMIT.value, ProviderFailureKind.TEMPORARY.value}
)
# Blocked-event incidents; the open blocks already describe them.
BLOCKED_CATEGORY = "conflict"
UNNAMED_CALENDAR = "Unnamed calendar"


class InstallationHealth(StrEnum):
    STALLED = "stalled"
    STOPPED = "stopped"
    REVIEW = "review"
    WAITING = "waiting"
    PAUSED = "paused"
    SETUP = "setup"
    HEALTHY = "healthy"


NEEDS_ATTENTION = frozenset(
    {InstallationHealth.STALLED, InstallationHealth.STOPPED, InstallationHealth.REVIEW}
)


class ProblemKind(StrEnum):
    STALLED = "stalled"
    STOPPED = "stopped"
    REVIEW = "review"
    OVERDUE = "overdue"
    BLOCKED = "blocked"
    WAITING = "waiting"


_HEALTH_OF = {
    ProblemKind.STALLED: InstallationHealth.STALLED,
    ProblemKind.STOPPED: InstallationHealth.STOPPED,
    ProblemKind.REVIEW: InstallationHealth.REVIEW,
    ProblemKind.OVERDUE: InstallationHealth.REVIEW,
    ProblemKind.BLOCKED: InstallationHealth.REVIEW,
    ProblemKind.WAITING: InstallationHealth.WAITING,
}


@dataclass(frozen=True, slots=True)
class Problem:
    kind: ProblemKind
    rule_id: str | None
    summary: str
    """Operational wording only; never event content."""
    since: datetime | None = None


@dataclass(frozen=True, slots=True)
class RuleStatus:
    summary: SyncRuleSummary
    name: str
    problem: Problem | None


@dataclass(frozen=True, slots=True)
class InstallationStatus:
    health: InstallationHealth
    problems: tuple[Problem, ...]
    rules: tuple[RuleStatus, ...]
    open_incidents: tuple[IncidentSummary, ...]
    overview: OperationsOverview
    scheduler: SchedulerProgress | None
    checked_at: datetime
    providers: Mapping[str, str] = field(default_factory=dict)
    """Each Connected Account's Provider Kind, by account id."""

    @property
    def needs_attention(self) -> bool:
        return self.health in NEEDS_ATTENTION

    @property
    def summary(self) -> str:
        if self.problems:
            first = self.problems[0]
            named = next(
                (rule.name for rule in self.rules if rule.summary.rule.id.value == first.rule_id),
                None,
            )
            return f"{named}: {first.summary}." if named else f"{first.summary}."
        running = sum(rule.summary.rule.state is SyncRuleState.ENABLED for rule in self.rules)
        if self.health is InstallationHealth.HEALTHY:
            return f"{running} {'rule' if running == 1 else 'rules'} running."
        if self.health is InstallationHealth.PAUSED:
            return "Synchronization is paused."
        return "Setup is not finished."


def rule_name(summary: SyncRuleSummary) -> str:
    source = summary.names.get(summary.rule.source, UNNAMED_CALENDAR)
    destination = summary.names.get(summary.rule.destination, UNNAMED_CALENDAR)
    return f"{source} → {destination}"


def assess_installation(
    rules: Sequence[SyncRuleSummary],
    overview: OperationsOverview,
    incidents: Sequence[IncidentSummary],
    scheduler: SchedulerProgress | None,
    now: datetime,
) -> InstallationStatus:
    """The verdict, most urgent problem first, from what the installation recorded."""
    visible = [summary for summary in rules if not _removal_running(summary)]
    enabled = [s for s in visible if s.rule.state is SyncRuleState.ENABLED]
    disconnected = {a.id for a in overview.accounts if a.state == "disconnected"}
    open_incidents = tuple(incident for incident in incidents if incident.state == "open")
    stalled = bool(enabled) and _stalled(scheduler, now)

    problems: list[Problem] = []
    if stalled:
        problems.append(
            Problem(ProblemKind.STALLED, None, "Scheduled synchronization stopped running")
        )
    problems.extend(_stopped(visible, open_incidents, disconnected))
    named: set[str | None] = {problem.rule_id for problem in problems if problem.rule_id}
    reviews, waits = _incident_problems(open_incidents, named, now)
    problems.extend(reviews)
    named |= {problem.rule_id for problem in reviews if problem.rule_id}
    if not stalled:
        problems.extend(_overdue(enabled, named, now))
    if overview.open_blocks:
        problems.append(_blocked(overview))
    problems.extend(problem for problem in waits if problem.rule_id not in named)
    if not problems and open_incidents:
        count = len(open_incidents)
        problems.append(
            Problem(
                ProblemKind.REVIEW,
                None,
                f"{count} {'problem' if count == 1 else 'problems'} kept happening",
            )
        )

    first_by_rule: dict[str, Problem] = {}
    for problem in problems:
        if problem.rule_id is not None:
            first_by_rule.setdefault(problem.rule_id, problem)
    return InstallationStatus(
        health=_health(problems, visible, enabled, overview, stalled),
        problems=tuple(problems),
        rules=tuple(
            RuleStatus(s, rule_name(s), first_by_rule.get(s.rule.id.value)) for s in visible
        ),
        open_incidents=open_incidents,
        overview=overview,
        scheduler=scheduler,
        checked_at=now,
        providers={account.id: account.provider for account in overview.accounts},
    )


def _removal_running(summary: SyncRuleSummary) -> bool:
    return (
        summary.rule.state is SyncRuleState.REMOVING
        and summary.running is not None
        and summary.running.kind is RuleWorkKind.REMOVAL
    )


def _stalled(scheduler: SchedulerProgress | None, now: datetime) -> bool:
    if scheduler is None:
        return True
    if scheduler.pass_started_at is not None:
        return now - scheduler.pass_started_at > PASS_LIMIT
    baseline = scheduler.last_completed_at or scheduler.running_since
    return now - baseline > STALL_AFTER


def _stopped(
    visible: Sequence[SyncRuleSummary],
    incidents: Sequence[IncidentSummary],
    disconnected: set[str],
) -> list[Problem]:
    problems = []
    for summary in visible:
        rule = summary.rule
        lost_account = rule.state is SyncRuleState.ENABLED and bool(
            {rule.source.connected_account_id.value, rule.destination.connected_account_id.value}
            & disconnected
        )
        if rule.state not in {SyncRuleState.DEGRADED, SyncRuleState.REMOVING} and not lost_account:
            continue
        incident = next(
            (
                item
                for item in incidents
                if item.rule_id == rule.id.value and item.category != BLOCKED_CATEGORY
            ),
            None,
        )
        if incident is not None:
            problems.append(
                Problem(
                    ProblemKind.STOPPED,
                    rule.id.value,
                    incident.summary,
                    datetime.fromisoformat(incident.opened_at),
                )
            )
        elif lost_account:
            problems.append(
                Problem(
                    ProblemKind.STOPPED, rule.id.value, "A calendar account needs reauthorization"
                )
            )
        else:
            problems.append(Problem(ProblemKind.STOPPED, rule.id.value, "Stopped syncing"))
    return problems


def _incident_problems(
    incidents: Sequence[IncidentSummary], named: set[str | None], now: datetime
) -> tuple[list[Problem], list[Problem]]:
    """Open incidents on rules not already named: those to review, then those still waiting."""
    reviews: list[Problem] = []
    waits: list[Problem] = []
    seen: set[str | None] = set(named)
    for incident in incidents:
        if incident.category == BLOCKED_CATEGORY or (
            incident.rule_id is not None and incident.rule_id in seen
        ):
            continue
        opened = datetime.fromisoformat(incident.opened_at)
        waiting = incident.category in WAITING_CATEGORIES and now - opened <= WAITING_LIMIT
        kind = ProblemKind.WAITING if waiting else ProblemKind.REVIEW
        (waits if waiting else reviews).append(
            Problem(kind, incident.rule_id, incident.summary, opened)
        )
        if incident.rule_id is not None:
            seen.add(incident.rule_id)
    return reviews, waits


def _overdue(
    enabled: Sequence[SyncRuleSummary], named: set[str | None], now: datetime
) -> list[Problem]:
    problems = []
    for summary in enabled:
        succeeded = summary.last_sync.last_succeeded_at if summary.last_sync else None
        if (
            succeeded is None
            or summary.running is not None
            or summary.rule.id.value in named
            or now - succeeded <= OVERDUE_AFTER
        ):
            continue
        problems.append(
            Problem(
                ProblemKind.OVERDUE, summary.rule.id.value, "Not synced in over a day", succeeded
            )
        )
    return problems


def _blocked(overview: OperationsOverview) -> Problem:
    count = len(overview.open_blocks)
    rules = {block.rule_id for block in overview.open_blocks}
    return Problem(
        ProblemKind.BLOCKED,
        rules.pop() if len(rules) == 1 else None,
        f"{count} {'event' if count == 1 else 'events'} couldn't be synced",
    )


def _health(
    problems: Sequence[Problem],
    visible: Sequence[SyncRuleSummary],
    enabled: Sequence[SyncRuleSummary],
    overview: OperationsOverview,
    stalled: bool,
) -> InstallationHealth:
    if stalled:
        return InstallationHealth.STALLED
    stopped = any(problem.kind is ProblemKind.STOPPED for problem in problems)
    if not overview.accounts:
        return InstallationHealth.SETUP
    if overview.connected_accounts == 0 and not stopped and overview.open_incidents == 0:
        return InstallationHealth.SETUP
    if problems:
        return _HEALTH_OF[problems[0].kind]
    if not visible:
        return InstallationHealth.SETUP
    if not enabled:
        return InstallationHealth.PAUSED if overview.last_synced_at else InstallationHealth.SETUP
    return InstallationHealth.HEALTHY


@dataclass(slots=True)
class GetInstallationStatus:
    rules: ListSyncRules
    operations: OperationsQueries
    clock: Clock
    scheduler: SchedulerHeartbeat | None

    def execute(self) -> InstallationStatus:
        return assess_installation(
            self.rules.execute(),
            self.operations.overview(),
            self.operations.incidents(),
            self.scheduler.progress() if self.scheduler is not None else None,
            self.clock.now(),
        )
