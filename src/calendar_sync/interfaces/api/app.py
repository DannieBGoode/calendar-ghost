from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import URL
from starlette.routing import Match, Route
from starlette.types import Receive, Scope, Send

from calendar_sync import __version__
from calendar_sync.application.accounts import ConnectedAccountSummary
from calendar_sync.application.activity import (
    ActivityCategory,
    ActivityEntry,
    ActivityEvent,
    ActivityFilter,
    RecordedTime,
)
from calendar_sync.application.errors import (
    AccountAccessCheckFailed,
    ActivityEventNotFound,
    ActivityRuleRemoved,
    AdminAlreadyConfigured,
    ApplicationError,
    AuthorizationFailed,
    AuthorizationNotConfigured,
    CalendarPermissionRequired,
    ConnectedAccountDisconnected,
    ConnectedAccountMustBeDisconnected,
    ConnectedAccountNotFound,
    ConnectedAccountRequired,
    DuplicateDirectionalRelationship,
    EventInspectionUnavailable,
    InvalidAuthorizationState,
    NotACalendarChange,
    PasswordPolicyViolation,
    ProviderFailure,
    RemovalInterrupted,
    RemovalRequiresProvider,
    ReplacementInterrupted,
    RuleNotExecutable,
    RuleNotFound,
)
from calendar_sync.application.locking import RuleWork
from calendar_sync.application.ports import RulePreviewSummary, RuleRunOutcome
from calendar_sync.bootstrap.container import Container, build_container
from calendar_sync.domain.errors import DomainValidationError, InvalidStateTransition
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    CalendarEndpoint,
    CalendarEvent,
    CalendarId,
    ConnectedAccountId,
    EventStatus,
    PrivacyPolicy,
    ProjectionHandling,
    SyncRule,
    SyncRuleId,
    TimedInterval,
    TransformationPolicy,
)
from calendar_sync.interfaces.api.schemas import (
    ActivityEventResponse,
    AuditEntryResponse,
    CalendarEndpointPayload,
    ConnectedAccountResponse,
    CreateRuleRequest,
    DashboardResponse,
    DiscoveredCalendarResponse,
    EventSnapshotResponse,
    GoogleAccountAccessResponse,
    GoogleConfigurationResponse,
    IncidentResponse,
    NoChangeRunResponse,
    PasswordRequest,
    PreviewSummaryResponse,
    ProjectionChoice,
    RecentChangeResponse,
    RecordedEventResponse,
    RecordedTimeResponse,
    RemovalResponse,
    ReplaceRuleRequest,
    RuleDetailResponse,
    RuleReplacementResponse,
    RuleResponse,
    RuleSummaryResponse,
    RuleWorkResponse,
    RunOutcomeResponse,
    SessionResponse,
    SetupStatusResponse,
    UpdateRulePolicyRequest,
)

SESSION_COOKIE = "calendar_sync_session"
MANAGE_ACCOUNTS = "configure the installation master key before managing Google accounts"


def create_app(container: Container | None = None) -> FastAPI:  # noqa: C901, PLR0915
    resolved = container or build_container()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        scheduler_task: asyncio.Task[None] | None = None
        if resolved.scheduler is not None:
            scheduler_task = asyncio.create_task(resolved.scheduler.run_forever())
        try:
            yield
        finally:
            if scheduler_task is not None:
                scheduler_task.cancel()
                with suppress(asyncio.CancelledError):
                    await scheduler_task

    app = FastAPI(
        title="Google Calendar Sync",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.container = resolved

    def require_admin(session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None) -> None:
        if not resolved.administrator.session_is_valid(session):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "administrator session required")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/v1/setup", response_model=SetupStatusResponse)
    def setup_status() -> SetupStatusResponse:
        return SetupStatusResponse(administrator_configured=resolved.administrator.is_configured())

    @app.post("/api/v1/setup/admin", response_model=SessionResponse)
    def create_admin(request: PasswordRequest, response: Response) -> SessionResponse:
        try:
            resolved.administrator.create_admin(request.password)
        except (AdminAlreadyConfigured, PasswordPolicyViolation) as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        session = resolved.administrator.authenticate(request.password)
        assert session is not None
        _set_session_cookie(response, session.token, resolved.secure_cookies)
        return SessionResponse(authenticated=True)

    @app.post("/api/v1/session", response_model=SessionResponse)
    def log_in(request: PasswordRequest, response: Response) -> SessionResponse:
        session = resolved.administrator.authenticate(request.password)
        if session is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "incorrect password")
        _set_session_cookie(response, session.token, resolved.secure_cookies)
        return SessionResponse(authenticated=True)

    @app.get("/api/v1/session", response_model=SessionResponse)
    def session_status(
        session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    ) -> SessionResponse:
        return SessionResponse(authenticated=resolved.administrator.session_is_valid(session))

    @app.delete("/api/v1/session", status_code=status.HTTP_204_NO_CONTENT)
    def log_out(
        response: Response,
        session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    ) -> None:
        resolved.administrator.revoke(session)
        response.delete_cookie(SESSION_COOKIE, path="/")

    @app.get(
        "/api/v1/dashboard",
        response_model=DashboardResponse,
        dependencies=[Depends(require_admin)],
    )
    def dashboard() -> DashboardResponse:
        summary = resolved.get_dashboard.execute()
        return DashboardResponse(
            health="healthy" if summary.healthy else "attention",
            connected_accounts=summary.connected_accounts,
            disconnected_accounts=summary.disconnected_accounts,
            sync_rules=summary.sync_rules,
            enabled_rules=summary.enabled_rules,
            stopped_rules=summary.stopped_rules,
            open_incidents=summary.open_incidents,
            last_synced_at=summary.last_synced_at,
            blocked_events=summary.blocked_events,
            blocked_entry_id=summary.blocked_entry_id,
            blocked_rule_id=summary.blocked_rule_id,
        )

    @app.get(
        "/api/v1/google/configuration",
        response_model=GoogleConfigurationResponse,
        dependencies=[Depends(require_admin)],
    )
    def google_configuration() -> GoogleConfigurationResponse:
        return GoogleConfigurationResponse(
            configured=resolved.google.configured, redirect_uri=resolved.google.redirect_uri
        )

    @app.get(
        "/api/v1/oauth/google/start",
        dependencies=[Depends(require_admin)],
    )
    def start_google_oauth() -> RedirectResponse:
        authorization = _available(
            resolved.authorization,
            "configure the installation master key before connecting Google",
        )
        try:
            return RedirectResponse(authorization.authorization_url(), status_code=302)
        except AuthorizationNotConfigured as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error

    @app.get("/api/v1/oauth/google/callback", include_in_schema=False)
    def complete_google_oauth(
        state: str,
        code: str | None = None,
        error: str | None = None,
    ) -> RedirectResponse:
        authorization = _available(resolved.authorization, "Google OAuth is not configured")
        if error is not None:
            try:
                authorization.cancel(state)
            except InvalidAuthorizationState as state_error:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(state_error)) from state_error
            outcome = (
                "calendar_permission_required"
                if error == "access_denied"
                else "authorization_failed"
            )
            return RedirectResponse(f"/settings?google={outcome}", status_code=303)
        if code is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Google OAuth callback did not include an authorization result",
            )
        try:
            authorization.complete(state, code)
        except InvalidAuthorizationState as state_error:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(state_error)) from state_error
        except CalendarPermissionRequired:
            return RedirectResponse(
                "/settings?google=calendar_permission_required", status_code=303
            )
        except AuthorizationFailed:
            return RedirectResponse("/settings?google=authorization_failed", status_code=303)
        return RedirectResponse("/settings?google=connected", status_code=303)

    @app.get(
        "/api/v1/accounts",
        response_model=list[ConnectedAccountResponse],
        dependencies=[Depends(require_admin)],
    )
    def list_accounts() -> list[ConnectedAccountResponse]:
        if resolved.list_connected_accounts is None:
            return []
        return [_account_response(item) for item in resolved.list_connected_accounts.execute()]

    @app.post(
        "/api/v1/accounts/{account_id}/disconnect",
        response_model=ConnectedAccountResponse,
        dependencies=[Depends(require_admin)],
    )
    def disconnect_account(account_id: str) -> ConnectedAccountResponse:
        disconnect = _available(resolved.disconnect_connected_account, MANAGE_ACCOUNTS)
        try:
            return _account_response(disconnect.execute(ConnectedAccountId(account_id)))
        except ConnectedAccountNotFound as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error

    @app.delete(
        "/api/v1/accounts/{account_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_admin)],
    )
    def delete_account(account_id: str) -> None:
        delete = _available(resolved.delete_connected_account, MANAGE_ACCOUNTS)
        try:
            delete.execute(ConnectedAccountId(account_id))
        except ConnectedAccountNotFound as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
        except ConnectedAccountMustBeDisconnected as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error

    @app.get(
        "/api/v1/accounts/{account_id}/calendars",
        response_model=list[DiscoveredCalendarResponse],
        dependencies=[Depends(require_admin)],
    )
    def discover_calendars(account_id: str) -> list[DiscoveredCalendarResponse]:
        calendars = _available(resolved.account_calendars, "Google OAuth is not configured")
        try:
            discovered = calendars.calendars(ConnectedAccountId(account_id))
        except ConnectedAccountNotFound as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
        except ConnectedAccountDisconnected as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        return [
            DiscoveredCalendarResponse(
                id=calendar.id,
                summary=calendar.summary,
                access_role=calendar.access_role,
                primary=calendar.primary,
            )
            for calendar in discovered
        ]

    @app.post(
        "/api/v1/accounts/{account_id}/verify",
        response_model=GoogleAccountAccessResponse,
        dependencies=[Depends(require_admin)],
    )
    def verify_account_access(account_id: str) -> GoogleAccountAccessResponse:
        calendars = _available(resolved.account_calendars, "Google OAuth is not configured")
        try:
            access = calendars.verify_access(ConnectedAccountId(account_id))
        except ConnectedAccountNotFound as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
        except ConnectedAccountDisconnected as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        except AccountAccessCheckFailed as error:
            raise HTTPException(status.HTTP_424_FAILED_DEPENDENCY, str(error)) from error
        return GoogleAccountAccessResponse(
            calendar_api=True,
            calendar_list_access=True,
            event_access=True,
            calendars_visible=access.calendars_visible,
            writable_calendars=access.writable_calendars,
        )

    @app.get(
        "/api/v1/rules",
        response_model=list[RuleSummaryResponse],
        dependencies=[Depends(require_admin)],
    )
    def list_rules() -> list[RuleSummaryResponse]:
        return [
            RuleSummaryResponse(
                **_rule_response(summary.rule).model_dump(),
                last_sync=_outcome_response(summary.last_sync),
                latest_preview=_preview_response(summary.latest_preview),
                running=_work_response(summary.running),
            )
            for summary in resolved.list_sync_rules.execute()
        ]

    @app.get(
        "/api/v1/audit-entries",
        response_model=list[AuditEntryResponse],
        dependencies=[Depends(require_admin)],
    )
    def list_activity(
        rule_id: str | None = None,
        run_id: str | None = None,
        category: Annotated[list[ActivityCategory] | None, Query()] = None,
        before: Annotated[int | None, Query(ge=1)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        q: Annotated[str | None, Query(max_length=200)] = None,
    ) -> list[AuditEntryResponse]:
        selection = ActivityFilter(
            rule_id=rule_id,
            run_id=run_id,
            categories=frozenset(category or ()),
            before=before,
            limit=limit,
            search=q,
        )
        return [_entry_response(entry) for entry in resolved.activity.entries(selection)]

    @app.get(
        "/api/v1/audit-entries/no-change-runs",
        response_model=list[NoChangeRunResponse],
        dependencies=[Depends(require_admin)],
    )
    def list_no_change_runs(
        rule_id: str | None = None,
        after: Annotated[int, Query(ge=0)] = 0,
    ) -> list[NoChangeRunResponse]:
        """Runs newer than entry `after` that made no-change checks, with how many each made.

        The default Activity view hides these checks, including runs that made nothing else.
        """
        return [
            NoChangeRunResponse(
                run_id=run.run_id,
                rule_id=run.rule_id,
                newest_id=run.newest_id,
                occurred_at=run.occurred_at,
                count=run.count,
            )
            for run in resolved.activity.no_change_runs(rule_id, after)
        ]

    @app.get(
        "/api/v1/audit-entries/{entry_id}",
        response_model=AuditEntryResponse,
        dependencies=[Depends(require_admin)],
    )
    def get_activity_entry(entry_id: int) -> AuditEntryResponse:
        entry = resolved.activity.entry(entry_id)
        if entry is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "activity entry not found")
        return _entry_response(entry)

    @app.get(
        "/api/v1/recent-changes",
        response_model=list[RecentChangeResponse],
        dependencies=[Depends(require_admin)],
    )
    def recent_changes(
        limit: Annotated[int, Query(ge=1, le=20)] = 5,
    ) -> list[RecentChangeResponse]:
        return [
            RecentChangeResponse(
                entry=_entry_response(change.entry),
                repeats=change.repeats,
                first_occurred_at=change.first_occurred_at,
            )
            for change in resolved.activity.recent_changes(limit)
        ]

    @app.get(
        "/api/v1/audit-entries/{entry_id}/event",
        response_model=ActivityEventResponse,
        dependencies=[Depends(require_admin)],
    )
    async def inspect_activity_event(entry_id: int) -> ActivityEventResponse:
        try:
            inspected = await asyncio.to_thread(resolved.inspect_activity_event.execute, entry_id)
        except ActivityEventNotFound as error:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "activity entry has no source event"
            ) from error
        except ActivityRuleRemoved as error:
            raise HTTPException(
                status.HTTP_410_GONE,
                "the rule for this activity entry was removed, so its events cannot be looked up",
            ) from error
        except EventInspectionUnavailable as error:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "configure Google OAuth and the installation master key before inspecting events",
            ) from error
        except ProviderFailure as error:
            raise HTTPException(
                status.HTTP_424_FAILED_DEPENDENCY,
                f"Google could not return this event: {error.kind.value}",
            ) from error
        return ActivityEventResponse(
            source=_event_snapshot(inspected.source),
            destination=(
                _event_snapshot(inspected.destination) if inspected.destination_recorded else None
            ),
        )

    @app.get(
        "/api/v1/incidents",
        response_model=list[IncidentResponse],
        dependencies=[Depends(require_admin)],
    )
    def list_incidents() -> list[IncidentResponse]:
        return [
            IncidentResponse(
                id=incident.id,
                rule_id=incident.rule_id,
                category=incident.category,
                state=incident.state,
                summary=incident.summary,
                opened_at=incident.opened_at,
                updated_at=incident.updated_at,
            )
            for incident in resolved.operations.incidents()
        ]

    @app.post(
        "/api/v1/rules",
        response_model=RuleResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_admin)],
    )
    def create_rule(request: CreateRuleRequest) -> RuleResponse:
        transformation = TransformationPolicy(
            privacy=_privacy(request.privacy_policy),
            all_day=_all_day(request.sync_all_day_events),
        )
        try:
            rule = resolved.create_draft_rule.execute(
                _endpoint(request.source), _endpoint(request.destination), transformation
            )
        except DomainValidationError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
        except (ConnectedAccountRequired, DuplicateDirectionalRelationship) as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        return _rule_response(rule)

    @app.post(
        "/api/v1/rules/{rule_id}/sync",
        dependencies=[Depends(require_admin)],
    )
    async def sync_now(rule_id: str) -> dict[str, int | str]:
        execute_sync_rule = _available(
            resolved.execute_sync_rule,
            "configure Google OAuth and the installation master key before synchronizing",
        )
        try:
            result = await asyncio.to_thread(execute_sync_rule.execute, SyncRuleId(rule_id))
        except RuleNotExecutable as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        return {
            "rule_id": result.rule_id.value,
            "created": result.created,
            "updated": result.updated,
            "deleted": result.deleted,
            "ignored": result.ignored,
            "conflicts": result.conflicts,
        }

    @app.post(
        "/api/v1/rules/{rule_id}/reconcile",
        dependencies=[Depends(require_admin)],
    )
    async def reconcile_now(rule_id: str) -> dict[str, object]:
        reconcile = _available(
            resolved.reconcile_now,
            "configure Google OAuth and the installation master key before reconciling",
        )
        try:
            reconciled = await asyncio.to_thread(reconcile.execute, SyncRuleId(rule_id))
        except RuleNotExecutable as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        result, report = reconciled.sync, reconciled.report
        return {
            "rule_id": result.rule_id.value,
            "created": result.created,
            "updated": result.updated,
            "deleted": result.deleted,
            "ignored": result.ignored,
            "conflicts": result.conflicts,
            "consistent": report.is_consistent,
            "checked_mappings": report.checked_mappings,
            "drift": [{"kind": item.kind.value, "detail": item.detail} for item in report.drift],
        }

    @app.post(
        "/api/v1/rules/{rule_id}/preview",
        dependencies=[Depends(require_admin)],
    )
    async def preview_rule(rule_id: str) -> dict[str, object]:
        preview_sync_rule = _available(
            resolved.preview_sync_rule,
            "configure Google OAuth and the installation master key before previewing",
        )
        try:
            preview = await asyncio.to_thread(preview_sync_rule.execute, SyncRuleId(rule_id))
        except RuleNotExecutable as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        return {
            "rule_id": preview.rule_id.value,
            "eligible_events": preview.eligible_events,
            "excluded_events": preview.excluded_events,
            "recurring_series": preview.recurring_series,
            "occurrence_changes": preview.occurrence_changes,
            "sample": [
                {
                    "source_event_id": item.source_event_id,
                    "projected_title": item.projected_title,
                    "all_day": item.all_day,
                    "kind": item.kind,
                    "planned_action": item.planned_action.value,
                }
                for item in preview.sample
            ],
        }

    @app.post(
        "/api/v1/rules/{rule_id}/enable",
        response_model=RuleResponse,
        dependencies=[Depends(require_admin)],
    )
    def enable_rule(rule_id: str) -> RuleResponse:
        return _rule_response(_lifecycle_change(resolved.enable_sync_rule.execute, rule_id))

    @app.post(
        "/api/v1/rules/{rule_id}/pause",
        response_model=RuleResponse,
        dependencies=[Depends(require_admin)],
    )
    def pause_rule(rule_id: str) -> RuleResponse:
        return _rule_response(_lifecycle_change(resolved.pause_sync_rule.execute, rule_id))

    @app.get(
        "/api/v1/rules/{rule_id}",
        response_model=RuleDetailResponse,
        dependencies=[Depends(require_admin)],
    )
    def rule_details(rule_id: str) -> RuleDetailResponse:
        try:
            details = resolved.get_sync_rule_details.execute(SyncRuleId(rule_id))
        except RuleNotFound as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
        return RuleDetailResponse(
            **_rule_response(details.rule).model_dump(),
            initial_lookback_days=details.rule.initial_lookback_days,
            mapping_count=details.mapping_count,
            last_sync=_outcome_response(details.last_sync),
            last_reconciliation=_outcome_response(details.last_reconciliation),
            latest_preview=_preview_response(details.latest_preview),
            running=_work_response(details.running),
        )

    @app.patch(
        "/api/v1/rules/{rule_id}",
        response_model=RuleResponse,
        dependencies=[Depends(require_admin)],
    )
    def change_rule_policy(rule_id: str, request: UpdateRulePolicyRequest) -> RuleResponse:
        privacy = _privacy(request.privacy_policy)
        all_day = _all_day(request.sync_all_day_events)
        try:
            rule = resolved.change_sync_rule_policy.execute(SyncRuleId(rule_id), privacy, all_day)
        except RuleNotFound as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
        except InvalidStateTransition as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        return _rule_response(rule)

    @app.delete(
        "/api/v1/rules/{rule_id}",
        response_model=RemovalResponse,
        dependencies=[Depends(require_admin)],
    )
    async def remove_rule(rule_id: str, projections: ProjectionChoice) -> RemovalResponse:
        try:
            result = await asyncio.to_thread(
                resolved.remove_sync_rule.execute,
                SyncRuleId(rule_id),
                ProjectionHandling(projections),
            )
        except ApplicationError as error:
            raise _rule_change_http_error(error) from error
        return RemovalResponse(
            deleted=result.deleted, detached=result.detached, conflicts=result.conflicts
        )

    @app.post(
        "/api/v1/rules/{rule_id}/replace",
        response_model=RuleReplacementResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_admin)],
    )
    async def replace_rule_calendars(
        rule_id: str, request: ReplaceRuleRequest
    ) -> RuleReplacementResponse:
        try:
            replacement = await asyncio.to_thread(
                resolved.replace_sync_rule_calendars.execute,
                SyncRuleId(rule_id),
                _endpoint(request.source),
                _endpoint(request.destination),
                ProjectionHandling(request.projections),
            )
        except DomainValidationError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
        except ApplicationError as error:
            raise _rule_change_http_error(error) from error
        return RuleReplacementResponse(
            rule=_rule_response(replacement.rule),
            deleted=replacement.removal.deleted,
            detached=replacement.removal.detached,
            conflicts=replacement.removal.conflicts,
        )

    # Registered after every API route so an unknown API path is a JSON error for any method
    # instead of falling through to the web page.
    app.router.routes.append(Route("/api", UnknownApiPath(), include_in_schema=False))
    app.router.routes.append(Route("/api/{path:path}", UnknownApiPath(), include_in_schema=False))

    static_directory = Path(__file__).with_name("static")
    if static_directory.exists():
        static_root = static_directory.resolve()
        assets = static_directory / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def frontend(full_path: str) -> FileResponse:
            index = static_root / "index.html"
            requested = (static_root / full_path).resolve()
            if (
                full_path
                and requested.is_file()
                and requested.is_relative_to(static_root)
                and not requested.samefile(index)
            ):
                return FileResponse(requested)
            # Revalidate the page on every load so an upgrade replaces it and its asset hashes.
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


def _available[T](use_case: T | None, detail: str) -> T:
    """The one guard for what needs the installation master key or Google OAuth."""
    if use_case is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail)
    return use_case


def _lifecycle_change(change: Callable[[SyncRuleId], SyncRule], rule_id: str) -> SyncRule:
    try:
        return change(SyncRuleId(rule_id))
    except RuleNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sync rule does not exist") from error
    except InvalidStateTransition as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error


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


def _entry_response(entry: ActivityEntry) -> AuditEntryResponse:
    return AuditEntryResponse(
        id=entry.id,
        run_id=entry.run_id,
        occurred_at=entry.occurred_at,
        rule_id=entry.rule_id,
        action=entry.action,
        outcome=entry.outcome,
        category=entry.category,
        reason=entry.reason,
        detail=entry.detail,
        source_event_id=entry.source_event_id,
        destination_event_id=entry.destination_event_id,
        event=_recorded_event_response(entry.event) if entry.event is not None else None,
        repeated=entry.repeated,
    )


def _recorded_event_response(event: ActivityEvent) -> RecordedEventResponse:
    return RecordedEventResponse(
        title=event.title,
        all_day=event.all_day,
        starts=event.starts,
        ends=event.ends,
        recurring=event.recurring,
        cancelled=event.cancelled,
        renamed_from=event.renamed_from,
        moved_from=_recorded_time_response(event.moved_from) if event.moved_from else None,
    )


def _recorded_time_response(time: RecordedTime) -> RecordedTimeResponse:
    return RecordedTimeResponse(all_day=time.all_day, starts=time.starts, ends=time.ends)


def _event_snapshot(event: CalendarEvent | None) -> EventSnapshotResponse:
    if event is None:
        return EventSnapshotResponse(found=False)
    # Google keeps a cancelled event's title for a while; it names what was removed.
    cancelled = event.status is EventStatus.CANCELLED
    time = event.time
    if time is None:
        return EventSnapshotResponse(
            found=True, cancelled=True, title=event.title, web_link=event.web_link
        )
    if isinstance(time, TimedInterval):
        starts, ends = time.starts_at.isoformat(), time.ends_at.isoformat()
    else:
        starts, ends = time.starts_on.isoformat(), time.ends_before.isoformat()
    return EventSnapshotResponse(
        found=True,
        cancelled=cancelled,
        title=event.title,
        all_day=event.is_all_day,
        starts=starts,
        ends=ends,
        recurring=event.recurrence is not None or event.occurrence is not None,
        web_link=event.web_link,
    )


class UnknownApiPath:
    """ASGI endpoint, rather than a function, so its route accepts every HTTP method.

    Its full match outranks what Starlette's router would otherwise do for a known route: the
    trailing-slash redirect and the 405 for a wrong method. Both are restored here.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        router = scope["app"].router
        api_routes = [
            route
            for route in router.routes
            if isinstance(route, Route)
            and route.path.startswith("/api/")
            and not isinstance(route.endpoint, UnknownApiPath)
        ]
        path = scope["path"]
        if router.redirect_slashes:
            redirect_scope = {
                **scope,
                "path": path.rstrip("/") if path.endswith("/") else path + "/",
            }
            if any(route.matches(redirect_scope)[0] is not Match.NONE for route in api_routes):
                await RedirectResponse(str(URL(scope=redirect_scope)))(scope, receive, send)
                return
        allowed = {
            method
            for route in api_routes
            if route.matches(scope)[0] is Match.PARTIAL
            for method in route.methods or ()
        }
        if allowed:
            raise HTTPException(
                status.HTTP_405_METHOD_NOT_ALLOWED,
                "Method Not Allowed",
                headers={"Allow": ", ".join(sorted(allowed))},
            )
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


def _set_session_cookie(response: Response, token: str, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=7 * 24 * 60 * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
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
        privacy_policy=rule.transformation.privacy.value,
        sync_all_day_events=rule.transformation.all_day is AllDaySyncPolicy.INCLUDE,
        state=rule.state.value,
        reprojection_required=rule.reprojection_required,
    )


def _all_day(sync_all_day_events: bool) -> AllDaySyncPolicy:
    return AllDaySyncPolicy.INCLUDE if sync_all_day_events else AllDaySyncPolicy.EXCLUDE


def _privacy(value: str) -> PrivacyPolicy:
    try:
        return PrivacyPolicy(value)
    except ValueError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown privacy policy"
        ) from error


def _work_response(work: RuleWork | None) -> RuleWorkResponse | None:
    if work is None:
        return None
    return RuleWorkResponse(
        kind=work.kind.value,
        started_at=work.started_at.isoformat(),
        handling=work.handling.value if work.handling else None,
        total=work.total,
        done=work.done,
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


def _rule_change_http_error(error: ApplicationError) -> HTTPException:
    """Map removal and replacement failures; the remaining ones need administrator action."""
    if isinstance(error, RuleNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(error))
    if isinstance(error, RemovalRequiresProvider):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error))
    if isinstance(error, RemovalInterrupted | ReplacementInterrupted):
        return HTTPException(status.HTTP_424_FAILED_DEPENDENCY, str(error))
    if isinstance(error, NotACalendarChange):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
    return HTTPException(status.HTTP_409_CONFLICT, str(error))


def _account_response(summary: ConnectedAccountSummary) -> ConnectedAccountResponse:
    account = summary.account
    return ConnectedAccountResponse(
        id=account.id.value,
        display_name=account.display_name,
        email=account.email,
        avatar_url=account.avatar_url,
        state=account.state.value,
        rule_count=summary.rule_count,
    )


def run() -> None:
    uvicorn.run(
        "calendar_sync.interfaces.api.app:create_app",
        factory=True,
        # The container publishes this port; Compose decides which host interface exposes it.
        host="0.0.0.0",  # noqa: S104
        port=8000,
    )
