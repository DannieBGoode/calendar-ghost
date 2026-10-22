"""Installation Status as the status API, MCP, and the Operator Overview return it: no IDs of
accounts or calendars."""

from __future__ import annotations

from calendar_sync import __version__
from calendar_sync.application.operations.installation_health import (
    InstallationHealth,
    InstallationIncident,
)
from calendar_sync.application.operations.operator_overview import UserOverview
from calendar_sync.application.operations.status import (
    Dashboard,
    InstallationStatus,
    Problem,
    RuleStatus,
    calendar_display_name,
)
from calendar_sync.domain.incidents import IncidentMessage
from calendar_sync.domain.model import CalendarEndpoint
from calendar_sync.interfaces.api.schemas.operations import (
    DashboardResponse,
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
from calendar_sync.interfaces.api.schemas.shared import (
    IncidentMessageResponse,
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
        provider=problem.provider.value if problem.provider else None,
    )


def status_response(status: InstallationStatus) -> StatusResponse:
    overview = status.overview
    scheduler = status.scheduler
    counts = status.counts
    return StatusResponse(
        status=status.health.value,
        needs_attention=status.needs_attention,
        summary=status.summary,
        version=__version__,
        checked_at=status.checked_at.isoformat(),
        last_synced_at=overview.last_synced_at.isoformat() if overview.last_synced_at else None,
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
            rules=counts.rules,
            running=counts.running,
            stopped=counts.stopped,
            paused=counts.paused,
            held=counts.held,
            overdue=counts.overdue,
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
                category=incident.category.value,
                summary=incident.summary,
                opened_at=incident.opened_at.isoformat(),
                cause=incident.cause.value if incident.cause else None,
            )
            for incident in status.open_incidents
        ],
    )


def dashboard_response(status: InstallationStatus) -> DashboardResponse:
    """The Overview's verdict and counts, counted as `status_response` counts them."""
    summary = Dashboard.of(status)
    next_pass = status.scheduler.next_pass_at if status.scheduler else None
    return DashboardResponse(
        status=status.health.value,
        needs_attention=status.needs_attention,
        problems=[problem_response(problem) for problem in status.problems],
        connected_accounts=summary.connected_accounts,
        disconnected_accounts=summary.disconnected_accounts,
        lapsed_accounts=summary.lapsed_accounts,
        sync_rules=summary.rules.rules,
        enabled_rules=summary.enabled_rules,
        running_rules=summary.rules.running,
        stopped_rules=summary.rules.stopped,
        held_rules=summary.rules.held,
        open_incidents=summary.open_incidents,
        last_synced_at=summary.last_synced_at.isoformat() if summary.last_synced_at else None,
        blocked_events=summary.blocked_events,
        blocked_entry_id=summary.blocked_entry_id,
        blocked_rule_id=summary.blocked_rule_id,
        next_pass_at=next_pass.isoformat() if next_pass else None,
    )


def _rule(status: InstallationStatus, rule: RuleStatus) -> StatusRuleResponse:
    summary = rule.summary
    last = summary.last_sync.last_succeeded_at if summary.last_sync else None
    return StatusRuleResponse(
        id=summary.rule.id.value,
        name=rule.name,
        state=summary.rule.state.value,
        stop_cause=summary.rule.stop_cause.value if summary.rule.stop_cause else None,
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
        provider=provider.value
        if (provider := status.providers.get(endpoint.connected_account_id.value))
        else None,
        number=status.calendar_numbers.get(endpoint),
    )


def installation_health_response(health: InstallationHealth) -> InstallationHealthResponse:
    return InstallationHealthResponse(
        status=health.status.value,
        needs_attention=health.needs_attention,
        incidents=[installation_incident_response(incident) for incident in health.incidents],
        users={verdict.value: count for verdict, count in health.users.items()},
        disabled_users=health.disabled_users,
        checked_at=health.checked_at.isoformat(),
        hints=[
            InstallationHintResponse(
                kind=hint.kind.value,
                cause=hint.cause.value if hint.cause is not None else None,
                users=hint.users,
                anchor=hint.anchor,
                provider=hint.provider.value if hint.provider else None,
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


def installation_incident_response(incident: InstallationIncident) -> InstallationIncidentResponse:
    secret = incident.secret
    return InstallationIncidentResponse(
        kind=incident.kind.value,
        since=incident.since.isoformat(),
        provider=secret.provider.value if secret is not None else None,
        expires_on=secret.expires.isoformat() if secret is not None else None,
    )
