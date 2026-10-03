"""Installation Status as the status API and MCP return it: no IDs of accounts or calendars."""

from __future__ import annotations

from calendar_sync import __version__
from calendar_sync.application.status import (
    InstallationStatus,
    Problem,
    ProblemKind,
    RuleStatus,
    calendar_display_name,
)
from calendar_sync.domain.model import CalendarEndpoint, SyncRuleState
from calendar_sync.interfaces.api.schemas import (
    ProblemResponse,
    SchedulerResponse,
    StatusCalendarResponse,
    StatusCountsResponse,
    StatusIncidentResponse,
    StatusResponse,
    StatusRuleResponse,
)


def problem_response(problem: Problem) -> ProblemResponse:
    return ProblemResponse(
        kind=problem.kind.value,
        rule_id=problem.rule_id,
        summary=problem.summary,
        since=problem.since.isoformat() if problem.since else None,
    )


def status_response(status: InstallationStatus) -> StatusResponse:
    overview = status.overview
    scheduler = status.scheduler
    states = [rule.summary.rule.state for rule in status.rules]
    return StatusResponse(
        status=status.health.value,
        needs_attention=status.needs_attention,
        summary=status.summary,
        version=__version__,
        checked_at=status.checked_at.isoformat(),
        last_synced_at=overview.last_synced_at,
        scheduler=SchedulerResponse(
            running=scheduler is not None,
            last_pass_completed_at=(
                scheduler.last_completed_at.isoformat()
                if scheduler and scheduler.last_completed_at
                else None
            ),
            current_pass_started_at=(
                scheduler.pass_started_at.isoformat()
                if scheduler and scheduler.pass_started_at
                else None
            ),
        ),
        counts=StatusCountsResponse(
            rules=len(status.rules),
            running=states.count(SyncRuleState.ENABLED),
            stopped=sum(p.kind is ProblemKind.STOPPED for p in status.problems),
            paused=states.count(SyncRuleState.PAUSED),
            overdue=sum(p.kind is ProblemKind.OVERDUE for p in status.problems),
            open_incidents=overview.open_incidents,
            blocked_events=len(overview.open_blocks),
            disconnected_accounts=overview.disconnected_accounts,
        ),
        problems=[problem_response(problem) for problem in status.problems],
        rules=[_rule(status, rule) for rule in status.rules],
        incidents=[
            StatusIncidentResponse(
                rule_id=incident.rule_id,
                category=incident.category,
                summary=incident.summary,
                opened_at=incident.opened_at,
            )
            for incident in status.open_incidents
        ],
    )


def _rule(status: InstallationStatus, rule: RuleStatus) -> StatusRuleResponse:
    summary = rule.summary
    last = summary.last_sync.last_succeeded_at if summary.last_sync else None
    return StatusRuleResponse(
        id=summary.rule.id.value,
        name=rule.name,
        state=summary.rule.state.value,
        source=_calendar(status, rule, summary.rule.source),
        destination=_calendar(status, rule, summary.rule.destination),
        projection=summary.rule.transformation.content.value,
        last_succeeded_at=last.isoformat() if last else None,
        running=summary.running.kind.value if summary.running else None,
        problem=problem_response(rule.problem) if rule.problem else None,
    )


def _calendar(
    status: InstallationStatus, rule: RuleStatus, endpoint: CalendarEndpoint
) -> StatusCalendarResponse:
    return StatusCalendarResponse(
        calendar=calendar_display_name(endpoint, rule.summary.names),
        provider=status.providers.get(endpoint.connected_account_id.value),
    )
