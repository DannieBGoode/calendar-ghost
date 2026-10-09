"""Installation Status: one health verdict for the Overview, the status API, and MCP."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from calendar_sync.application.activity import OperationsQueries
from calendar_sync.application.errors import ProviderFailureKind
from calendar_sync.application.locking import RuleWorkKind
from calendar_sync.application.ports import (
    Clock,
    IncidentMessage,
    IncidentSummary,
    OperationsOverview,
    SchedulerHeartbeat,
    SchedulerProgress,
)
from calendar_sync.application.rules import ListSyncRules, SyncRuleSummary
from calendar_sync.domain.model import CalendarEndpoint, SyncRuleState

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


class StatusVerdict(StrEnum):
    STALLED = "stalled"
    STOPPED = "stopped"
    REVIEW = "review"
    WAITING = "waiting"
    PAUSED = "paused"
    SETUP = "setup"
    HEALTHY = "healthy"


NEEDS_ATTENTION = frozenset({StatusVerdict.STALLED, StatusVerdict.STOPPED, StatusVerdict.REVIEW})


class ProblemKind(StrEnum):
    STALLED = "stalled"
    STOPPED = "stopped"
    REVIEW = "review"
    OVERDUE = "overdue"
    BLOCKED = "blocked"
    WAITING = "waiting"


_HEALTH_OF = {
    ProblemKind.STALLED: StatusVerdict.STALLED,
    ProblemKind.STOPPED: StatusVerdict.STOPPED,
    ProblemKind.REVIEW: StatusVerdict.REVIEW,
    ProblemKind.OVERDUE: StatusVerdict.REVIEW,
    ProblemKind.BLOCKED: StatusVerdict.REVIEW,
    ProblemKind.WAITING: StatusVerdict.WAITING,
}


@dataclass(frozen=True, slots=True)
class Problem:
    kind: ProblemKind
    rule_id: str | None
    summary: str
    """Operational wording only; never event content."""
    since: datetime | None = None
    message: IncidentMessage | None = None
    """The message of the Incident behind this problem, for the Web UI to translate (ADR 0026)."""


@dataclass(frozen=True, slots=True)
class RuleStatus:
    summary: SyncRuleSummary
    name: str
    problem: Problem | None


@dataclass(frozen=True, slots=True)
class InstallationStatus:
    health: StatusVerdict
    problems: tuple[Problem, ...]
    rules: tuple[RuleStatus, ...]
    open_incidents: tuple[IncidentSummary, ...]
    overview: OperationsOverview
    scheduler: SchedulerProgress | None
    checked_at: datetime
    providers: Mapping[str, str] = field(default_factory=dict)
    """Each Connected Account's Provider Kind, by account id."""
    calendar_numbers: Mapping[CalendarEndpoint, int] = field(default_factory=dict)
    """In the Operator Overview, the number each calendar's neutral label carries; empty when
    calendars are named."""

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
        if self.health is StatusVerdict.HEALTHY:
            return f"{running} {'rule' if running == 1 else 'rules'} running."
        if self.health is StatusVerdict.PAUSED:
            return "Synchronization is paused."
        return "Setup is not finished."


def calendar_display_name(endpoint: CalendarEndpoint, names: Mapping[CalendarEndpoint, str]) -> str:
    """The calendar's last known name, except when showing it would leak an account email or
    bare calendar id: Google stores `summary or id` as a calendar's name (so an unnamed or
    unlisted calendar's "name" is its id), and a primary calendar's summary is the account email
    by default."""
    name = names.get(endpoint)
    if not name or name == endpoint.calendar_id.value or "@" in name:
        return UNNAMED_CALENDAR
    return name


def rule_name(summary: SyncRuleSummary) -> str:
    source = calendar_display_name(summary.rule.source, summary.names)
    destination = calendar_display_name(summary.rule.destination, summary.names)
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
    lapsed = {a.id: a.provider for a in overview.accounts if a.lapsed}
    open_incidents = tuple(incident for incident in incidents if incident.state == "open")
    block_rule_ids = {block.rule_id for block in overview.open_blocks}
    stalled = bool(enabled) and _stalled(scheduler, now)

    problems: list[Problem] = []
    if stalled:
        problems.append(
            Problem(ProblemKind.STALLED, None, "Scheduled synchronization stopped running")
        )
    stopped = _stopped(visible, open_incidents, disconnected, lapsed, now)
    problems.extend(stopped)
    named: set[str | None] = {problem.rule_id for problem in problems if problem.rule_id}
    # A lapsed account's Incident is covered by the Stopped problems of the rules it stopped.
    covered = _accounts_of(visible, named) & lapsed.keys()
    reviews, waits = _incident_problems(
        [i for i in open_incidents if i.rule_id is not None or i.account_id not in covered],
        named,
        block_rule_ids,
        now,
    )
    problems.extend(reviews)
    named |= {problem.rule_id for problem in reviews if problem.rule_id}
    # A rule already waiting on its own incident is not also overdue: the incident already
    # explains why it hasn't synced.
    overdue_excluded = named | {problem.rule_id for problem in waits if problem.rule_id}
    if not stalled and scheduler is not None:
        problems.extend(_overdue(enabled, overdue_excluded, scheduler.last_pass_rule_ids, now))
    if overview.open_blocks:
        problems.append(_blocked(overview))
    # Every open incident is now covered: by its rule's Stopped problem, by the open blocks, or
    # by a review or waiting problem of its own. So open incidents never leave this list empty.
    problems.extend(problem for problem in waits if problem.rule_id not in named)

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
    return scheduler is None or stalled_since(scheduler, now) is not None


def stalled_since(scheduler: SchedulerProgress, now: datetime) -> datetime | None:
    """Since when a scheduler stopped doing its job; None while it does it (ADR 0024).

    A pass running for longer than PASS_LIMIT has stalled since it started; otherwise the
    scheduler has stalled since its last completed pass, or its start, once that is longer ago
    than STALL_AFTER.
    """
    if scheduler.pass_started_at is not None:
        started = scheduler.pass_started_at
        return started if now - started > PASS_LIMIT else None
    baseline = scheduler.last_completed_at or scheduler.running_since
    return baseline if now - baseline > STALL_AFTER else None


def _accounts_of(visible: Sequence[SyncRuleSummary], rule_ids: set[str | None]) -> set[str]:
    return {
        account
        for summary in visible
        if summary.rule.id.value in rule_ids
        for account in _rule_accounts(summary)
    }


def _rule_accounts(summary: SyncRuleSummary) -> set[str]:
    rule = summary.rule
    return {rule.source.connected_account_id.value, rule.destination.connected_account_id.value}


def _stopped(
    visible: Sequence[SyncRuleSummary],
    incidents: Sequence[IncidentSummary],
    disconnected: set[str],
    lapsed: Mapping[str, str],
    now: datetime,
) -> list[Problem]:
    problems = []
    for summary in visible:
        rule = summary.rule
        lapse = _lapse_problem(summary, lapsed)
        if lapse is not None:
            problems.append(lapse)
            continue
        lost_account = rule.state is SyncRuleState.ENABLED and bool(
            _rule_accounts(summary) & disconnected
        )
        if rule.state not in {SyncRuleState.DEGRADED, SyncRuleState.REMOVING} and not lost_account:
            continue
        candidates = [
            item
            for item in incidents
            if item.rule_id == rule.id.value and item.category != BLOCKED_CATEGORY
        ]
        incident = _primary_incident(candidates, now) if candidates else None
        if incident is not None:
            problems.append(
                Problem(
                    ProblemKind.STOPPED,
                    rule.id.value,
                    incident.summary,
                    datetime.fromisoformat(incident.opened_at),
                    incident.message,
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


def _lapse_problem(summary: SyncRuleSummary, lapsed: Mapping[str, str]) -> Problem | None:
    """A running or stopped rule an account's Lapsed Authorization stops, naming no account."""
    if summary.rule.state not in {SyncRuleState.ENABLED, SyncRuleState.DEGRADED}:
        return None
    account = next((a for a in sorted(_rule_accounts(summary)) if a in lapsed), None)
    if account is None:
        return None
    return Problem(
        ProblemKind.STOPPED,
        summary.rule.id.value,
        "A calendar account needs reauthorization",
        message=IncidentMessage("authorization_lapsed", {"provider": lapsed[account]}),
    )


def _is_waiting(incident: IncidentSummary, now: datetime) -> bool:
    """Whether a provider condition that retries by itself still has time left to do so."""
    opened = datetime.fromisoformat(incident.opened_at)
    return incident.category in WAITING_CATEGORIES and now - opened <= WAITING_LIMIT


def _primary_incident(incidents: Sequence[IncidentSummary], now: datetime) -> IncidentSummary:
    """A rule's most urgent open incident: one still worth reviewing before one merely waiting."""
    return min(incidents, key=lambda incident: _is_waiting(incident, now))


def _group_incidents(
    incidents: Sequence[IncidentSummary], named: set[str | None], block_rule_ids: set[str]
) -> list[list[IncidentSummary]]:
    """Open incidents eligible for a Problem, grouped by rule; each unnamed incident alone.

    A rule already named, such as one with a Stopped problem, is skipped here: that problem
    already covers it. A conflict incident is skipped too, but only when an open block for the
    same rule already describes it; an uncovered one is grouped like any other.
    """
    groups: dict[object, list[IncidentSummary]] = {}
    for incident in incidents:
        if incident.rule_id is not None and incident.rule_id in named:
            continue
        if incident.category == BLOCKED_CATEGORY and incident.rule_id in block_rule_ids:
            continue
        key: object = incident.rule_id if incident.rule_id is not None else incident
        groups.setdefault(key, []).append(incident)
    return list(groups.values())


def _incident_problems(
    incidents: Sequence[IncidentSummary],
    named: set[str | None],
    block_rule_ids: set[str],
    now: datetime,
) -> tuple[list[Problem], list[Problem]]:
    """Open incidents on rules not already named: those to review, then those still waiting.

    Several open incidents on the same rule yield one Problem: whichever is still worth
    reviewing, not merely waiting, regardless of which one happens first in the given order.
    """
    reviews: list[Problem] = []
    waits: list[Problem] = []
    for group in _group_incidents(incidents, named, block_rule_ids):
        incident = _primary_incident(group, now)
        waiting = _is_waiting(incident, now)
        problem = Problem(
            ProblemKind.WAITING if waiting else ProblemKind.REVIEW,
            incident.rule_id,
            incident.summary,
            datetime.fromisoformat(incident.opened_at),
            incident.message,
        )
        if waiting:
            waits.append(problem)
        else:
            reviews.append(problem)
    return reviews, waits


def _overdue(
    enabled: Sequence[SyncRuleSummary],
    named: set[str | None],
    listed: frozenset[str],
    now: datetime,
) -> list[Problem]:
    """Enabled rules the last completed pass listed that still have not succeeded in a day.

    A rule that pass did not list, such as one resumed or reauthorized since, keeps its old last
    success until the next pass reaches it; that alone is not a reason to look.
    """
    problems = []
    for summary in enabled:
        succeeded = summary.last_sync.last_succeeded_at if summary.last_sync else None
        if (
            succeeded is None
            or summary.running is not None
            or summary.rule.id.value in named
            or summary.rule.id.value not in listed
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
) -> StatusVerdict:
    if stalled:
        return StatusVerdict.STALLED
    stopped = any(problem.kind is ProblemKind.STOPPED for problem in problems)
    if not overview.accounts:
        return StatusVerdict.SETUP
    if overview.connected_accounts == 0 and not stopped and overview.open_incidents == 0:
        return StatusVerdict.SETUP
    if problems:
        return _HEALTH_OF[problems[0].kind]
    if not visible:
        return StatusVerdict.SETUP
    if not enabled:
        return StatusVerdict.PAUSED if overview.last_synced_at else StatusVerdict.SETUP
    return StatusVerdict.HEALTHY


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
