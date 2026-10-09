from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, status

from calendar_sync.application.errors import (
    ApplicationError,
    ConnectedAccountRequired,
    DuplicateDirectionalRelationship,
    NotACalendarChange,
    ProviderFailure,
    RemovalInterrupted,
    RemovalRequiresProvider,
    ReplacementInterrupted,
    RuleNotExecutable,
    RuleNotFound,
)
from calendar_sync.application.locking import RuleWork
from calendar_sync.application.ports import RulePreviewSummary, RuleRunOutcome
from calendar_sync.application.preview import PreviewSyncRule
from calendar_sync.application.reconciliation import ReconcileNow
from calendar_sync.application.removal import RemoveSyncRule
from calendar_sync.application.rules import (
    ChangeSyncRulePolicy,
    CreateDraftSyncRule,
    EnableSyncRule,
    GetSyncRuleDetails,
    ListSyncRules,
    PauseSyncRule,
    ReplaceSyncRuleCalendars,
)
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.domain.errors import DomainValidationError, InvalidStateTransition
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    CalendarEndpoint,
    CalendarId,
    ConnectedAccountId,
    ProjectionContent,
    ProjectionHandling,
    SyncRule,
    SyncRuleId,
    TentativeEventPolicy,
    TransformationPolicy,
    UnansweredInvitationPolicy,
)
from calendar_sync.interfaces.api.dependencies import available, current_user, user_services
from calendar_sync.interfaces.api.problems import ApiProblem, problem, problem_from
from calendar_sync.interfaces.api.schemas import (
    CalendarEndpointPayload,
    CreateRuleRequest,
    DriftResponse,
    NamedCalendarEndpointResponse,
    PreviewItemResponse,
    PreviewSummaryResponse,
    ProjectionChoice,
    ReconcileResultResponse,
    ReconciliationConflictResponse,
    RemovalResponse,
    ReplaceRuleRequest,
    RuleDetailResponse,
    RulePreviewResponse,
    RuleReplacementResponse,
    RuleResponse,
    RuleSummaryResponse,
    RuleWorkResponse,
    RunOutcomeResponse,
    SyncResultResponse,
    UpdateRulePolicyRequest,
)


class RuleServices(Protocol):
    @property
    def list_sync_rules(self) -> ListSyncRules: ...
    @property
    def create_draft_rule(self) -> CreateDraftSyncRule: ...
    @property
    def enable_sync_rule(self) -> EnableSyncRule: ...
    @property
    def pause_sync_rule(self) -> PauseSyncRule: ...
    @property
    def change_sync_rule_policy(self) -> ChangeSyncRulePolicy: ...
    @property
    def get_sync_rule_details(self) -> GetSyncRuleDetails: ...
    @property
    def remove_sync_rule(self) -> RemoveSyncRule: ...
    @property
    def replace_sync_rule_calendars(self) -> ReplaceSyncRuleCalendars: ...
    @property
    def execute_sync_rule(self) -> ExecuteSyncRule | None: ...
    @property
    def preview_sync_rule(self) -> PreviewSyncRule | None: ...
    @property
    def reconcile_now(self) -> ReconcileNow | None: ...


Services = Annotated[RuleServices, Depends(user_services)]
router = APIRouter()


@router.get(
    "/api/v1/rules",
    response_model=list[RuleSummaryResponse],
    dependencies=[Depends(current_user)],
)
def list_rules(services: Services) -> list[RuleSummaryResponse]:
    return [
        RuleSummaryResponse(
            **_named_rule_response(summary.rule, summary.names),
            last_sync=_outcome_response(summary.last_sync),
            latest_preview=_preview_response(summary.latest_preview),
            running=_work_response(summary.running),
        )
        for summary in services.list_sync_rules.execute()
    ]


@router.post(
    "/api/v1/rules",
    response_model=RuleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(current_user)],
)
def create_rule(request: CreateRuleRequest, services: Services) -> RuleResponse:
    transformation = TransformationPolicy(
        content=ProjectionContent(request.privacy_policy),
        all_day=_all_day(request.sync_all_day_events),
        tentative=TentativeEventPolicy(request.tentative_events),
        unanswered=UnansweredInvitationPolicy(request.unanswered_invitations),
    )
    try:
        rule = services.create_draft_rule.execute(
            _endpoint(request.source), _endpoint(request.destination), transformation
        )
    except DomainValidationError as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    except (ConnectedAccountRequired, DuplicateDirectionalRelationship) as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    return _rule_response(rule)


@router.post(
    "/api/v1/rules/{rule_id}/sync",
    response_model=SyncResultResponse,
    dependencies=[Depends(current_user)],
)
async def sync_now(rule_id: str, services: Services) -> SyncResultResponse:
    execute_sync_rule = available(
        services.execute_sync_rule,
        "rule_execution_unavailable",
        "configure a calendar provider and the installation master key before synchronizing",
    )
    try:
        result = await asyncio.to_thread(execute_sync_rule.execute, SyncRuleId(rule_id))
    except RuleNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except RuleNotExecutable as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    return SyncResultResponse(
        rule_id=result.rule_id.value,
        created=result.created,
        updated=result.updated,
        deleted=result.deleted,
        ignored=result.ignored,
        conflicts=result.conflicts,
    )


@router.post(
    "/api/v1/rules/{rule_id}/reconcile",
    response_model=ReconcileResultResponse,
    dependencies=[Depends(current_user)],
)
async def reconcile_now(rule_id: str, services: Services) -> ReconcileResultResponse:
    reconcile = available(
        services.reconcile_now,
        "rule_execution_unavailable",
        "configure a calendar provider and the installation master key before reconciling",
    )
    try:
        reconciled = await asyncio.to_thread(reconcile.execute, SyncRuleId(rule_id))
    except RuleNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except RuleNotExecutable as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    result, report = reconciled.sync, reconciled.report
    return ReconcileResultResponse(
        rule_id=result.rule_id.value,
        created=result.created,
        updated=result.updated,
        deleted=result.deleted,
        ignored=result.ignored,
        conflicts=result.conflicts,
        consistent=report.is_consistent,
        checked_mappings=report.checked_mappings,
        drift=[DriftResponse(kind=item.kind.value, detail=item.detail) for item in report.drift],
        reconciliation_conflicts=[
            ReconciliationConflictResponse(reason=item.reason.value, detail=item.detail)
            for item in report.conflicts
        ],
    )


@router.post(
    "/api/v1/rules/{rule_id}/preview",
    response_model=RulePreviewResponse,
    dependencies=[Depends(current_user)],
)
async def preview_rule(rule_id: str, services: Services) -> RulePreviewResponse:
    preview_sync_rule = available(
        services.preview_sync_rule,
        "rule_execution_unavailable",
        "configure a calendar provider and the installation master key before previewing",
    )
    try:
        preview = await asyncio.to_thread(preview_sync_rule.execute, SyncRuleId(rule_id))
    except RuleNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except RuleNotExecutable as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except ProviderFailure as error:
        # The provider refused to list the source; a lapsed authorization is already recorded.
        raise problem_from(status.HTTP_424_FAILED_DEPENDENCY, error) from error
    return RulePreviewResponse(
        rule_id=preview.rule_id.value,
        eligible_events=preview.eligible_events,
        excluded_events=preview.excluded_events,
        recurring_series=preview.recurring_series,
        occurrence_changes=preview.occurrence_changes,
        sample=[
            PreviewItemResponse(
                source_event_id=item.source_event_id,
                projected_title=item.projected_title,
                all_day=item.all_day,
                kind=item.kind,
                planned_action=item.planned_action.value,
            )
            for item in preview.sample
        ],
    )


@router.post(
    "/api/v1/rules/{rule_id}/enable",
    response_model=RuleResponse,
    dependencies=[Depends(current_user)],
)
def enable_rule(rule_id: str, services: Services) -> RuleResponse:
    return _rule_response(_lifecycle_change(services.enable_sync_rule.execute, rule_id))


@router.post(
    "/api/v1/rules/{rule_id}/pause",
    response_model=RuleResponse,
    dependencies=[Depends(current_user)],
)
def pause_rule(rule_id: str, services: Services) -> RuleResponse:
    return _rule_response(_lifecycle_change(services.pause_sync_rule.execute, rule_id))


@router.get(
    "/api/v1/rules/{rule_id}",
    response_model=RuleDetailResponse,
    dependencies=[Depends(current_user)],
)
def rule_details(rule_id: str, services: Services) -> RuleDetailResponse:
    try:
        details = services.get_sync_rule_details.execute(SyncRuleId(rule_id))
    except RuleNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    return RuleDetailResponse(
        **_named_rule_response(details.rule, details.names),
        initial_lookback_days=details.rule.initial_lookback_days,
        mapping_count=details.mapping_count,
        last_sync=_outcome_response(details.last_sync),
        last_reconciliation=_outcome_response(details.last_reconciliation),
        latest_preview=_preview_response(details.latest_preview),
        running=_work_response(details.running),
    )


@router.patch(
    "/api/v1/rules/{rule_id}",
    response_model=RuleResponse,
    dependencies=[Depends(current_user)],
)
def change_rule_policy(
    rule_id: str, request: UpdateRulePolicyRequest, services: Services
) -> RuleResponse:
    content = ProjectionContent(request.privacy_policy)
    all_day = _all_day(request.sync_all_day_events)
    try:
        rule = services.change_sync_rule_policy.execute(
            SyncRuleId(rule_id),
            content,
            all_day,
            tentative=TentativeEventPolicy(request.tentative_events),
            unanswered=UnansweredInvitationPolicy(request.unanswered_invitations),
        )
    except RuleNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except InvalidStateTransition as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    return _rule_response(rule)


@router.delete(
    "/api/v1/rules/{rule_id}",
    response_model=RemovalResponse,
    dependencies=[Depends(current_user)],
)
async def remove_rule(
    rule_id: str, projections: ProjectionChoice, services: Services
) -> RemovalResponse:
    try:
        result = await asyncio.to_thread(
            services.remove_sync_rule.execute,
            SyncRuleId(rule_id),
            ProjectionHandling(projections),
        )
    except ApplicationError as error:
        raise _rule_change_problem(error) from error
    return RemovalResponse(
        deleted=result.deleted, detached=result.detached, conflicts=result.conflicts
    )


@router.post(
    "/api/v1/rules/{rule_id}/replace",
    response_model=RuleReplacementResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(current_user)],
)
async def replace_rule_calendars(
    rule_id: str, request: ReplaceRuleRequest, services: Services
) -> RuleReplacementResponse:
    try:
        replacement = await asyncio.to_thread(
            services.replace_sync_rule_calendars.execute,
            SyncRuleId(rule_id),
            _endpoint(request.source),
            _endpoint(request.destination),
            ProjectionHandling(request.projections),
        )
    except DomainValidationError as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    except ApplicationError as error:
        raise _rule_change_problem(error) from error
    return RuleReplacementResponse(
        rule=_rule_response(replacement.rule),
        deleted=replacement.removal.deleted,
        detached=replacement.removal.detached,
        conflicts=replacement.removal.conflicts,
    )


def _lifecycle_change(change: Callable[[SyncRuleId], SyncRule], rule_id: str) -> SyncRule:
    try:
        return change(SyncRuleId(rule_id))
    except RuleNotFound as error:
        raise problem(
            status.HTTP_404_NOT_FOUND, "rule_not_found", "sync rule does not exist"
        ) from error
    except InvalidStateTransition as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error


def _preview_response(summary: RulePreviewSummary | None) -> PreviewSummaryResponse | None:
    if summary is None:
        return None
    return PreviewSummaryResponse(
        completed_at=summary.completed_at.isoformat(),
        eligible_events=summary.eligible_events,
        excluded_events=summary.excluded_events,
        recurring_series=summary.recurring_series,
        occurrence_changes=summary.occurrence_changes,
    )


def _endpoint(payload: CalendarEndpointPayload) -> CalendarEndpoint:
    return CalendarEndpoint(
        ConnectedAccountId(payload.connected_account_id), CalendarId(payload.calendar_id)
    )


def _rule_response(rule: SyncRule) -> RuleResponse:
    return RuleResponse(
        id=rule.id.value,
        source=CalendarEndpointPayload(
            connected_account_id=rule.source.connected_account_id.value,
            calendar_id=rule.source.calendar_id.value,
        ),
        destination=CalendarEndpointPayload(
            connected_account_id=rule.destination.connected_account_id.value,
            calendar_id=rule.destination.calendar_id.value,
        ),
        privacy_policy=rule.transformation.content.value,
        sync_all_day_events=rule.transformation.all_day is AllDaySyncPolicy.INCLUDE,
        tentative_events=rule.transformation.tentative.value,
        unanswered_invitations=rule.transformation.unanswered.value,
        state=rule.state.value,
        reprojection_required=rule.reprojection_required,
    )


def _named_rule_response(rule: SyncRule, names: Mapping[CalendarEndpoint, str]) -> dict[str, Any]:
    def named(endpoint: CalendarEndpoint) -> NamedCalendarEndpointResponse:
        return NamedCalendarEndpointResponse(
            connected_account_id=endpoint.connected_account_id.value,
            calendar_id=endpoint.calendar_id.value,
            calendar_name=names.get(endpoint),
        )

    return {
        **_rule_response(rule).model_dump(exclude={"source", "destination"}),
        "source": named(rule.source),
        "destination": named(rule.destination),
    }


def _all_day(sync_all_day_events: bool) -> AllDaySyncPolicy:
    return AllDaySyncPolicy.INCLUDE if sync_all_day_events else AllDaySyncPolicy.EXCLUDE


def _work_response(work: RuleWork | None) -> RuleWorkResponse | None:
    if work is None:
        return None
    return RuleWorkResponse(
        kind=work.kind.value,
        started_at=work.started_at.isoformat(),
        handling=work.handling.value if work.handling else None,
        total=work.total,
        done=work.done,
        stage=work.stage.value if work.stage else None,
    )


def _outcome_response(outcome: RuleRunOutcome | None) -> RunOutcomeResponse | None:
    if outcome is None:
        return None
    return RunOutcomeResponse(
        completed_at=outcome.completed_at.isoformat(),
        succeeded=outcome.succeeded,
        full_run=outcome.full_run,
        created=outcome.created,
        updated=outcome.updated,
        deleted=outcome.deleted,
        conflicts=outcome.conflicts,
        checked_mappings=outcome.checked_mappings,
        drift=outcome.drift,
        failure_kind=outcome.failure_kind,
        last_succeeded_at=(
            outcome.last_succeeded_at.isoformat() if outcome.last_succeeded_at else None
        ),
    )


def _rule_change_problem(error: ApplicationError) -> ApiProblem:
    """Map removal and replacement failures; the remaining ones need administrator action."""
    if isinstance(error, RuleNotFound):
        return problem_from(status.HTTP_404_NOT_FOUND, error)
    if isinstance(error, RemovalRequiresProvider):
        return problem_from(status.HTTP_503_SERVICE_UNAVAILABLE, error)
    if isinstance(error, RemovalInterrupted | ReplacementInterrupted):
        return problem_from(status.HTTP_424_FAILED_DEPENDENCY, error)
    if isinstance(error, NotACalendarChange):
        return problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error)
    return problem_from(status.HTTP_409_CONFLICT, error, fallback="conflict")
