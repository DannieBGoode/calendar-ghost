from __future__ import annotations

import asyncio
import sqlite3
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from calendar_sync import __version__
from calendar_sync.application.errors import DuplicateDirectionalRelationship, RuleNotExecutable
from calendar_sync.bootstrap.container import Container, build_container
from calendar_sync.domain.errors import DomainValidationError, InvalidStateTransition
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    CalendarEndpoint,
    CalendarId,
    ConnectedAccountId,
    PrivacyPolicy,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
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
    AuditEntryResponse,
    CalendarEndpointPayload,
    ConnectedAccountResponse,
    CreateRuleRequest,
    DashboardResponse,
    DiscoveredCalendarResponse,
    GoogleAccountAccessResponse,
    GoogleConfigurationResponse,
    IncidentResponse,
    PasswordRequest,
    RuleResponse,
    SessionResponse,
    SetupStatusResponse,
)

SESSION_COOKIE = "calendar_sync_session"


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
        "/api/v1/activity",
        response_model=list[AuditEntryResponse],
        dependencies=[Depends(require_admin)],
    )
    def list_activity() -> list[AuditEntryResponse]:
        with sqlite3.connect(resolved.settings.database_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT occurred_at, rule_id, action, outcome, detail
                FROM audit_entries ORDER BY id DESC LIMIT 100
                """
            ).fetchall()
        return [AuditEntryResponse(**dict(row)) for row in rows]

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
        try:
            privacy = PrivacyPolicy(request.privacy_policy)
        except ValueError as error:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown privacy policy"
            ) from error
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
        result = await asyncio.to_thread(resolved.execute_sync_rule.execute, SyncRuleId(rule_id))
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
        result = await asyncio.to_thread(
            resolved.execute_sync_rule.execute, SyncRuleId(rule_id), full=True
        )
        report = await asyncio.to_thread(resolved.reconcile_sync_rule.execute, SyncRuleId(rule_id))
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

    static_directory = Path(__file__).with_name("static")
    if static_directory.exists():
        static_root = static_directory.resolve()
        assets = static_directory / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def frontend(full_path: str) -> FileResponse:
            requested = (static_root / full_path).resolve()
            if full_path and requested.is_file() and requested.is_relative_to(static_root):
                return FileResponse(requested)
            return FileResponse(static_root / "index.html")

    return app


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
    )


def _account_response(
    account: ConnectedGoogleAccount, rules: tuple[SyncRule, ...]
) -> ConnectedAccountResponse:
    rule_count = sum(1 for rule in rules if _rule_uses_account(rule, account.id))
    return ConnectedAccountResponse(
        id=account.id.value,
        display_name=account.display_name,
        email=account.email,
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
