"""Installation Status as the status API, MCP, and the Operator Overview return it: no IDs of
accounts or calendars."""

from __future__ import annotations

from calendar_sync import __version__
from calendar_sync.application.installation_health import InstallationHealth
from calendar_sync.application.operator_overview import UserOverview
from calendar_sync.application.ports import IncidentMessage
from calendar_sync.application.status import (
    InstallationStatus,
    Problem,
    ProblemKind,
    RuleStatus,
    calendar_display_name,
)
from calendar_sync.domain.model import CalendarEndpoint, SyncRuleState
from calendar_sync.interfaces.api.schemas import (
    IncidentMessageResponse,
    InstallationHealthResponse,
    InstallationHintResponse,
    InstallationIncidentResponse,
    ProblemResponse,
    ProviderCallsResponse,
    ResourceUseResponse,
    SchedulerResponse,
    StatusCalendarResponse,
    StatusCountsResponse,
    StatusIncidentResponse,
    StatusResponse,
    StatusRuleResponse,
)


def message_response(message: IncidentMessage | None) -> IncidentMessageResponse | None:
    if message is None:
        return None
    return IncidentMessageResponse(code=message.code, params=dict(message.params))


def problem_response(problem: Problem) -> ProblemResponse:
    return ProblemResponse(
        kind=problem.kind.value,
        rule_id=problem.rule_id,
        summary=problem.summary,
        since=problem.since.isoformat() if problem.since else None,
        message=message_response(problem.message),
        cause=problem.cause.value if problem.cause else None,
        last_tried_at=problem.last_tried_at.isoformat() if problem.last_tried_at else None,
    )


def status_response(status: InstallationStatus) -> StatusResponse:
    overview = status.overview
    scheduler = status.scheduler
    states = [rule.summary.rule.state for rule in status.rules]
    stopped = {p.rule_id for p in status.problems if p.kind is ProblemKind.STOPPED}
    return StatusResponse(
        status=status.health.value,
        needs_attention=status.needs_attention,
        summary=status.summary,
        version=__version__,
        checked_at=status.checked_at.isoformat(),
        last_synced_at=overview.last_synced_at,
        scheduler=SchedulerResponse(
            configured=scheduler is not None,
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
            next_pass_at=(
                scheduler.next_pass_at.isoformat() if scheduler and scheduler.next_pass_at else None
            ),
        ),
        counts=StatusCountsResponse(
            rules=len(status.rules),
            running=sum(
                rule.summary.rule.state is SyncRuleState.ENABLED
                and rule.summary.rule.id.value not in stopped
                for rule in status.rules
            ),
            stopped=len(stopped),
            paused=states.count(SyncRuleState.PAUSED),
            overdue=sum(p.kind is ProblemKind.OVERDUE for p in status.problems),
            open_incidents=overview.open_incidents,
            blocked_events=len(overview.open_blocks),
            disconnected_accounts=overview.disconnected_accounts,
            lapsed_accounts=overview.lapsed_accounts,
        ),
        problems=[problem_response(problem) for problem in status.problems],
        rules=[_rule(status, rule) for rule in status.rules],
        incidents=[
            StatusIncidentResponse(
                rule_id=incident.rule_id,
                category=incident.category,
                summary=incident.summary,
                opened_at=incident.opened_at,
                cause=incident.cause.value if incident.cause else None,
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
        number=status.calendar_numbers.get(endpoint),
    )


def installation_health_response(health: InstallationHealth) -> InstallationHealthResponse:
    return InstallationHealthResponse(
        status=health.status.value,
        needs_attention=health.needs_attention,
        incidents=[
            InstallationIncidentResponse(kind=incident.kind.value, since=incident.since.isoformat())
            for incident in health.incidents
        ],
        users={verdict.value: count for verdict, count in health.users.items()},
        disabled_users=health.disabled_users,
        checked_at=health.checked_at.isoformat(),
        hints=[
            InstallationHintResponse(
                kind=hint.kind.value, cause=hint.cause.value, users=hint.users, anchor=hint.anchor
            )
            for hint in health.hints
        ],
    )


def resource_use_response(overview: UserOverview) -> ResourceUseResponse:
    resources = overview.resources
    return ResourceUseResponse(
        rules=resources.rules,
        connected_accounts=resources.connected_accounts,
        activity_entries=resources.activity_entries,
        provider_calls=[
            ProviderCallsResponse(
                provider=calls.provider.value,
                calls=calls.calls,
                rate_limited=calls.rate_limited,
                failed=calls.failed,
            )
            for calls in resources.provider_calls
        ],
        since=overview.calls_since.isoformat(),
    )
