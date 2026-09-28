from __future__ import annotations

import asyncio
import sqlite3
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Literal

import uvicorn
from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import URL
from starlette.routing import Match, Route
from starlette.types import Receive, Scope, Send

from calendar_sync import __version__
from calendar_sync.application.errors import (
    ApplicationError,
    DuplicateDirectionalRelationship,
    NotACalendarChange,
    ProviderFailure,
    RemovalInterrupted,
    RemovalRequiresProvider,
    RuleNotExecutable,
    RuleNotFound,
)
from calendar_sync.application.ports import RuleRunOutcome
from calendar_sync.bootstrap.container import Container, build_container
from calendar_sync.domain.errors import DomainValidationError, InvalidStateTransition
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    CalendarEndpoint,
    CalendarEvent,
    CalendarId,
    ConnectedAccountId,
    EventId,
    EventRef,
    EventStatus,
    PrivacyPolicy,
    ProjectionHandling,
    SyncAction,
    SyncReason,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TimedInterval,
    TransformationPolicy,
)
from calendar_sync.infrastructure.google.oauth import (
    ConnectedGoogleAccount,
    ConnectedGoogleAccountDisconnected,
    ConnectedGoogleAccountMustBeDisconnected,
    ConnectedGoogleAccountNotFound,
    GoogleAccountAccessCheckFailed,
    GoogleCalendarPermissionRequired,
    GoogleOAuthCompletionFailed,
    GoogleOAuthNotConfigured,
    InvalidOAuthState,
)
from calendar_sync.infrastructure.security import (
    AdminAlreadyConfigured,
    PasswordPolicyViolation,
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
    PasswordRequest,
    ProjectionChoice,
    RemovalResponse,
    ReplaceRuleRequest,
    RuleDetailResponse,
    RuleReplacementResponse,
    RuleResponse,
    RunOutcomeResponse,
    SessionResponse,
    SetupStatusResponse,
    UpdateRulePolicyRequest,
)

SESSION_COOKIE = "calendar_sync_session"

ActivityCategory = Literal["changed", "unchanged", "skipped", "blocked"]

# Recurring exclusions were recorded as conflicts before reason codes existed; they are skips.
_ACTIVITY_CATEGORY_SQL: dict[ActivityCategory, str] = {
    "changed": (
        "action IN ('create', 'update', 'delete', 'policy_changed', 'remove_projection',"
        " 'detach_projection', 'rule_removed')"
    ),
    "unchanged": "action = 'ignore' AND reason = 'projection_current'",
    "skipped": (
        "((action = 'ignore' AND COALESCE(reason, '') != 'projection_current')"
        " OR reason = 'recurring_unsupported')"
    ),
    "blocked": "action = 'conflict' AND COALESCE(reason, '') != 'recurring_unsupported'",
}


def create_app(container: Container | None = None) -> FastAPI:
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
        if not resolved.admin_auth.session_is_valid(session):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "administrator session required")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/v1/setup", response_model=SetupStatusResponse)
    def setup_status() -> SetupStatusResponse:
        return SetupStatusResponse(administrator_configured=resolved.admin_auth.is_configured())

    @app.post("/api/v1/setup/admin", response_model=SessionResponse)
    def create_admin(request: PasswordRequest, response: Response) -> SessionResponse:
        try:
            resolved.admin_auth.create_admin(request.password)
        except (AdminAlreadyConfigured, PasswordPolicyViolation) as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        session = resolved.admin_auth.authenticate(request.password)
        assert session is not None
        _set_session_cookie(response, session.token, resolved.settings.secure_cookies)
        return SessionResponse(authenticated=True)

    @app.post("/api/v1/session", response_model=SessionResponse)
    def log_in(request: PasswordRequest, response: Response) -> SessionResponse:
        session = resolved.admin_auth.authenticate(request.password)
        if session is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "incorrect password")
        _set_session_cookie(response, session.token, resolved.settings.secure_cookies)
        return SessionResponse(authenticated=True)

    @app.get("/api/v1/session", response_model=SessionResponse)
    def session_status(
        session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    ) -> SessionResponse:
        return SessionResponse(authenticated=resolved.admin_auth.session_is_valid(session))

    @app.delete("/api/v1/session", status_code=status.HTTP_204_NO_CONTENT)
    def log_out(
        response: Response,
        session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    ) -> None:
        resolved.admin_auth.revoke(session)
        response.delete_cookie(SESSION_COOKIE, path="/")

    @app.get(
        "/api/v1/dashboard",
        response_model=DashboardResponse,
        dependencies=[Depends(require_admin)],
    )
    def dashboard() -> DashboardResponse:
        with sqlite3.connect(resolved.settings.database_path) as connection:
            accounts = int(
                connection.execute(
                    "SELECT COUNT(*) FROM connected_accounts WHERE state = 'connected'"
                ).fetchone()[0]
            )
            incidents = int(
                connection.execute(
                    "SELECT COUNT(*) FROM incidents WHERE state = 'open'"
                ).fetchone()[0]
            )
        with resolved.unit_of_work() as uow:
            rules = len(uow.rules.list())
        return DashboardResponse(
            health="attention" if incidents else "healthy",
            connected_accounts=accounts,
            sync_rules=rules,
            open_incidents=incidents,
        )

    @app.get(
        "/api/v1/google/configuration",
        response_model=GoogleConfigurationResponse,
        dependencies=[Depends(require_admin)],
    )
    def google_configuration() -> GoogleConfigurationResponse:
        configured = bool(
            resolved.google_oauth
            and resolved.settings.google_client_id
            and resolved.settings.google_client_secret
        )
        return GoogleConfigurationResponse(
            configured=configured,
            redirect_uri=resolved.settings.google_redirect_uri if configured else None,
        )

    @app.get(
        "/api/v1/oauth/google/start",
        dependencies=[Depends(require_admin)],
    )
    def start_google_oauth() -> RedirectResponse:
        if resolved.google_oauth is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "configure the installation master key before connecting Google",
            )
        try:
            return RedirectResponse(resolved.google_oauth.authorization_url(), status_code=302)
        except GoogleOAuthNotConfigured as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error

    @app.get("/api/v1/oauth/google/callback", include_in_schema=False)
    def complete_google_oauth(
        state: str,
        code: str | None = None,
        error: str | None = None,
    ) -> RedirectResponse:
        if resolved.google_oauth is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Google OAuth is not configured"
            )
        if error is not None:
            try:
                resolved.google_oauth.cancel(state)
            except InvalidOAuthState as state_error:
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
            resolved.google_oauth.complete(state, code)
        except InvalidOAuthState as state_error:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(state_error)) from state_error
        except GoogleCalendarPermissionRequired:
            return RedirectResponse(
                "/settings?google=calendar_permission_required", status_code=303
            )
        except GoogleOAuthCompletionFailed:
            return RedirectResponse("/settings?google=authorization_failed", status_code=303)
        return RedirectResponse("/settings?google=connected", status_code=303)

    @app.get(
        "/api/v1/accounts",
        response_model=list[ConnectedAccountResponse],
        dependencies=[Depends(require_admin)],
    )
    def list_accounts() -> list[ConnectedAccountResponse]:
        if resolved.connected_accounts is None:
            return []
        with resolved.unit_of_work() as uow:
            rules = tuple(uow.rules.list())
        return [_account_response(account, rules) for account in resolved.connected_accounts.list()]

    @app.post(
        "/api/v1/accounts/{account_id}/disconnect",
        response_model=ConnectedAccountResponse,
        dependencies=[Depends(require_admin)],
    )
    def disconnect_account(account_id: str) -> ConnectedAccountResponse:
        if resolved.connected_accounts is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "configure the installation master key before managing Google accounts",
            )
        try:
            existing = next(
                account
                for account in resolved.connected_accounts.list()
                if account.id == ConnectedAccountId(account_id)
            )
        except StopIteration as error:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"connected account {account_id} does not exist",
            ) from error
        with resolved.unit_of_work() as uow:
            for rule in uow.rules.list():
                if _rule_uses_account(rule, existing.id) and rule.state in {
                    SyncRuleState.DRY_RUN_VALIDATED,
                    SyncRuleState.ENABLED,
                }:
                    uow.rules.save(rule.degrade())
            uow.commit()
        try:
            account = resolved.connected_accounts.disconnect(ConnectedAccountId(account_id))
        except ConnectedGoogleAccountNotFound as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
        with resolved.unit_of_work() as uow:
            rules = tuple(uow.rules.list())
        return _account_response(account, rules)

    @app.delete(
        "/api/v1/accounts/{account_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_admin)],
    )
    def delete_account(account_id: str) -> None:
        if resolved.connected_accounts is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "configure the installation master key before managing Google accounts",
            )
        try:
            resolved.connected_accounts.delete(ConnectedAccountId(account_id))
        except ConnectedGoogleAccountNotFound as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
        except ConnectedGoogleAccountMustBeDisconnected as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error

    @app.get(
        "/api/v1/accounts/{account_id}/calendars",
        response_model=list[DiscoveredCalendarResponse],
        dependencies=[Depends(require_admin)],
    )
    def discover_calendars(account_id: str) -> list[DiscoveredCalendarResponse]:
        if resolved.google_oauth is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Google OAuth is not configured"
            )
        try:
            calendars = resolved.google_oauth.calendars(ConnectedAccountId(account_id))
        except ConnectedGoogleAccountNotFound as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
        except ConnectedGoogleAccountDisconnected as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        return [
            DiscoveredCalendarResponse(
                id=calendar.id,
                summary=calendar.summary,
                access_role=calendar.access_role,
                primary=calendar.primary,
            )
            for calendar in calendars
        ]

    @app.post(
        "/api/v1/accounts/{account_id}/verify",
        response_model=GoogleAccountAccessResponse,
        dependencies=[Depends(require_admin)],
    )
    def verify_account_access(account_id: str) -> GoogleAccountAccessResponse:
        if resolved.google_oauth is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Google OAuth is not configured"
            )
        try:
            access = resolved.google_oauth.verify_access(ConnectedAccountId(account_id))
        except ConnectedGoogleAccountNotFound as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
        except ConnectedGoogleAccountDisconnected as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        except GoogleAccountAccessCheckFailed as error:
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
        response_model=list[RuleResponse],
        dependencies=[Depends(require_admin)],
    )
    def list_rules() -> list[RuleResponse]:
        with resolved.unit_of_work() as uow:
            return [_rule_response(rule) for rule in uow.rules.list()]

    @app.get(
        "/api/v1/audit-entries",
        response_model=list[AuditEntryResponse],
        dependencies=[Depends(require_admin)],
    )
    def list_activity(
        rule_id: str | None = None,
        category: ActivityCategory | None = None,
        before: Annotated[int | None, Query(ge=1)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> list[AuditEntryResponse]:
        conditions: list[str] = []
        parameters: list[object] = []
        if rule_id is not None:
            conditions.append("rule_id = ?")
            parameters.append(rule_id)
        if category is not None:
            conditions.append(_ACTIVITY_CATEGORY_SQL[category])
        if before is not None:
            conditions.append("id < ?")
            parameters.append(before)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with sqlite3.connect(resolved.settings.database_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"""
                SELECT id, run_id, occurred_at, rule_id, action, outcome, reason, detail,
                    source_event_id, destination_event_id
                FROM audit_entries {where} ORDER BY id DESC LIMIT ?
                """,
                (*parameters, limit),
            ).fetchall()
        return [
            AuditEntryResponse(
                **dict(row), category=_activity_category(row["action"], row["reason"])
            )
            for row in rows
        ]

    @app.get(
        "/api/v1/audit-entries/{entry_id}/event",
        response_model=ActivityEventResponse,
        dependencies=[Depends(require_admin)],
    )
    async def inspect_activity_event(entry_id: int) -> ActivityEventResponse:
        provider = resolved.calendar_provider
        if provider is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "configure Google OAuth and the installation master key before inspecting events",
            )
        with sqlite3.connect(resolved.settings.database_path) as connection:
            row = connection.execute(
                """
                SELECT rule_id, source_event_id, destination_event_id
                FROM audit_entries WHERE id = ?
                """,
                (entry_id,),
            ).fetchone()
        if row is None or row[1] is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "activity entry has no source event")
        with resolved.unit_of_work() as uow:
            rule = uow.rules.get(SyncRuleId(str(row[0])))
        if rule is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "sync rule does not exist")
        # Event content is read live for display only; it is never persisted or logged.
        try:
            source = await asyncio.to_thread(
                provider.get_event, EventRef(rule.source, EventId(str(row[1])))
            )
            destination = (
                await asyncio.to_thread(
                    provider.get_event, EventRef(rule.destination, EventId(str(row[2])))
                )
                if row[2] is not None
                else None
            )
        except ProviderFailure as error:
            raise HTTPException(
                status.HTTP_424_FAILED_DEPENDENCY,
                f"Google could not return this event: {error.kind.value}",
            ) from error
        return ActivityEventResponse(
            source=_event_snapshot(source),
            destination=_event_snapshot(destination) if row[2] is not None else None,
        )

    @app.get(
        "/api/v1/incidents",
        response_model=list[IncidentResponse],
        dependencies=[Depends(require_admin)],
    )
    def list_incidents() -> list[IncidentResponse]:
        with sqlite3.connect(resolved.settings.database_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT id, rule_id, category, state, summary, opened_at, updated_at
                FROM incidents ORDER BY state ASC, updated_at DESC LIMIT 100
                """
            ).fetchall()
        return [IncidentResponse(**dict(row)) for row in rows]

    @app.post(
        "/api/v1/rules",
        response_model=RuleResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_admin)],
    )
    def create_rule(request: CreateRuleRequest) -> RuleResponse:
        privacy = _privacy(request.privacy_policy)
        try:
            rule = SyncRule(
                id=SyncRuleId(str(uuid.uuid4())),
                source=_endpoint(request.source),
                destination=_endpoint(request.destination),
                transformation=TransformationPolicy(
                    privacy=privacy,
                    all_day=(
                        AllDaySyncPolicy.INCLUDE
                        if request.sync_all_day_events
                        else AllDaySyncPolicy.EXCLUDE
                    ),
                ),
            )
        except DomainValidationError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
        try:
            resolved.create_sync_rule.execute(rule)
        except DuplicateDirectionalRelationship as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        return _rule_response(rule)

    @app.post(
        "/api/v1/rules/{rule_id}/sync",
        dependencies=[Depends(require_admin)],
    )
    async def sync_now(rule_id: str) -> dict[str, int | str]:
        if resolved.execute_sync_rule is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "configure Google OAuth and the installation master key before synchronizing",
            )
        try:
            result = await asyncio.to_thread(
                resolved.execute_sync_rule.execute, SyncRuleId(rule_id)
            )
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
        if resolved.execute_sync_rule is None or resolved.reconcile_sync_rule is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "configure Google OAuth and the installation master key before reconciling",
            )
        try:
            result = await asyncio.to_thread(
                resolved.execute_sync_rule.execute, SyncRuleId(rule_id), full=True
            )
            report = await asyncio.to_thread(
                resolved.reconcile_sync_rule.execute, SyncRuleId(rule_id)
            )
        except RuleNotExecutable as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
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
        if resolved.preview_sync_rule is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "configure Google OAuth and the installation master key before previewing",
            )
        try:
            preview = await asyncio.to_thread(
                resolved.preview_sync_rule.execute, SyncRuleId(rule_id)
            )
        except RuleNotExecutable as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        return {
            "rule_id": preview.rule_id.value,
            "eligible_events": preview.eligible_events,
            "excluded_events": preview.excluded_events,
            "sample": [
                {
                    "source_event_id": item.source_event_id,
                    "projected_title": item.projected_title,
                    "all_day": item.all_day,
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
        with resolved.unit_of_work() as uow:
            rule = uow.rules.get(SyncRuleId(rule_id))
            if rule is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "sync rule does not exist")
            try:
                enabled = rule.enable()
            except InvalidStateTransition as error:
                raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
            uow.rules.save(enabled)
            uow.commit()
        return _rule_response(enabled)

    @app.post(
        "/api/v1/rules/{rule_id}/pause",
        response_model=RuleResponse,
        dependencies=[Depends(require_admin)],
    )
    def pause_rule(rule_id: str) -> RuleResponse:
        with resolved.unit_of_work() as uow:
            rule = uow.rules.get(SyncRuleId(rule_id))
            if rule is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "sync rule does not exist")
            try:
                paused = rule.pause()
            except InvalidStateTransition as error:
                raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
            uow.rules.save(paused)
            uow.commit()
        return _rule_response(paused)

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
        )

    @app.patch(
        "/api/v1/rules/{rule_id}",
        response_model=RuleResponse,
        dependencies=[Depends(require_admin)],
    )
    def change_rule_policy(rule_id: str, request: UpdateRulePolicyRequest) -> RuleResponse:
        privacy = _privacy(request.privacy_policy)
        all_day = (
            AllDaySyncPolicy.INCLUDE if request.sync_all_day_events else AllDaySyncPolicy.EXCLUDE
        )
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
        return RemovalResponse(deleted=result.deleted, detached=result.detached)

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


def _activity_category(action: str, reason: str | None) -> ActivityCategory:
    if reason == SyncReason.RECURRING_UNSUPPORTED:
        return "skipped"
    if action == SyncAction.CONFLICT:
        return "blocked"
    if action == SyncAction.IGNORE:
        return "unchanged" if reason == SyncReason.PROJECTION_CURRENT else "skipped"
    return "changed"


def _event_snapshot(event: CalendarEvent | None) -> EventSnapshotResponse:
    if event is None:
        return EventSnapshotResponse(found=False)
    if event.status is EventStatus.CANCELLED or event.time is None:
        return EventSnapshotResponse(found=True, cancelled=True, web_link=event.web_link)
    time = event.time
    if isinstance(time, TimedInterval):
        starts, ends = time.starts_at.isoformat(), time.ends_at.isoformat()
    else:
        starts, ends = time.starts_on.isoformat(), time.ends_before.isoformat()
    return EventSnapshotResponse(
        found=True,
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


def _privacy(value: str) -> PrivacyPolicy:
    try:
        return PrivacyPolicy(value)
    except ValueError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown privacy policy"
        ) from error


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
    )


def _rule_change_http_error(error: ApplicationError) -> HTTPException:
    """Map removal and replacement failures; the remaining ones need administrator action."""
    if isinstance(error, RuleNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(error))
    if isinstance(error, RemovalRequiresProvider):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error))
    if isinstance(error, RemovalInterrupted):
        return HTTPException(status.HTTP_424_FAILED_DEPENDENCY, str(error))
    if isinstance(error, NotACalendarChange):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
    return HTTPException(status.HTTP_409_CONFLICT, str(error))


def _account_response(
    account: ConnectedGoogleAccount, rules: tuple[SyncRule, ...]
) -> ConnectedAccountResponse:
    rule_count = sum(1 for rule in rules if _rule_uses_account(rule, account.id))
    return ConnectedAccountResponse(
        id=account.id.value,
        display_name=account.display_name,
        email=account.email,
        avatar_url=account.avatar_url,
        state=account.state,
        rule_count=rule_count,
    )


def _rule_uses_account(rule: SyncRule, account_id: ConnectedAccountId) -> bool:
    return account_id in {
        rule.source.connected_account_id,
        rule.destination.connected_account_id,
    }


def run() -> None:
    uvicorn.run(
        "calendar_sync.interfaces.api.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
    )
