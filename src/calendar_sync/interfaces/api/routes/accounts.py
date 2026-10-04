from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, status
from fastapi.responses import RedirectResponse

from calendar_sync.application.accounts import (
    ConnectedAccountSummary,
    DeleteConnectedAccount,
    DisconnectConnectedAccount,
    DiscoverCalendars,
    ListConnectedAccounts,
)
from calendar_sync.application.errors import (
    AccountAccessCheckFailed,
    AuthorizationFailed,
    AuthorizationNotConfigured,
    CalendarPermissionRequired,
    ConnectedAccountDisconnected,
    ConnectedAccountMustBeDisconnected,
    ConnectedAccountNotFound,
    InvalidAuthorizationState,
)
from calendar_sync.application.ports import AccountAuthorization, AccountCalendars, CalendarAccess
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.interfaces.api.dependencies import app_services, available, require_admin
from calendar_sync.interfaces.api.problems import problem, problem_from
from calendar_sync.interfaces.api.schemas import (
    ConnectedAccountResponse,
    DiscoveredCalendarResponse,
    GoogleAccountAccessResponse,
    GoogleConfigurationResponse,
)

MANAGE_ACCOUNTS = "configure the installation master key before managing accounts"
ACCOUNT_MANAGEMENT_UNAVAILABLE = "account_management_unavailable"
PROVIDER_NOT_CONFIGURED = "provider_not_configured"


class GoogleConnection(Protocol):
    @property
    def configured(self) -> bool: ...
    @property
    def redirect_uri(self) -> str | None: ...


class AccountServices(Protocol):
    @property
    def google(self) -> GoogleConnection: ...
    @property
    def authorization(self) -> AccountAuthorization | None: ...
    @property
    def account_calendars(self) -> AccountCalendars | None: ...
    @property
    def discover_calendars(self) -> DiscoverCalendars | None: ...
    @property
    def list_connected_accounts(self) -> ListConnectedAccounts | None: ...
    @property
    def disconnect_connected_account(self) -> DisconnectConnectedAccount | None: ...
    @property
    def delete_connected_account(self) -> DeleteConnectedAccount | None: ...


Services = Annotated[AccountServices, Depends(app_services)]
router = APIRouter()


@router.get(
    "/api/v1/google/configuration",
    response_model=GoogleConfigurationResponse,
    dependencies=[Depends(require_admin)],
)
def google_configuration(services: Services) -> GoogleConfigurationResponse:
    return GoogleConfigurationResponse(
        configured=services.google.configured, redirect_uri=services.google.redirect_uri
    )


@router.get(
    "/api/v1/oauth/google/start",
    dependencies=[Depends(require_admin)],
)
def start_google_oauth(services: Services) -> RedirectResponse:
    authorization = available(
        services.authorization,
        ACCOUNT_MANAGEMENT_UNAVAILABLE,
        "configure the installation master key before connecting Google",
    )
    try:
        return RedirectResponse(authorization.authorization_url(), status_code=302)
    except AuthorizationNotConfigured as error:
        raise problem_from(status.HTTP_503_SERVICE_UNAVAILABLE, error) from error


@router.get("/api/v1/oauth/google/callback", include_in_schema=False)
def complete_google_oauth(
    services: Services,
    state: str,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    authorization = available(
        services.authorization, "authorization_not_configured", "Google OAuth is not configured"
    )
    if error is not None:
        try:
            authorization.cancel(state)
        except InvalidAuthorizationState as state_error:
            raise problem_from(status.HTTP_400_BAD_REQUEST, state_error) from state_error
        outcome = (
            "calendar_permission_required" if error == "access_denied" else "authorization_failed"
        )
        return RedirectResponse(f"/settings?google={outcome}", status_code=303)
    if code is None:
        raise problem(
            status.HTTP_400_BAD_REQUEST,
            "oauth_result_missing",
            "Google OAuth callback did not include an authorization result",
        )
    try:
        authorization.complete(state, code)
    except InvalidAuthorizationState as state_error:
        raise problem_from(status.HTTP_400_BAD_REQUEST, state_error) from state_error
    except CalendarPermissionRequired:
        return RedirectResponse("/settings?google=calendar_permission_required", status_code=303)
    except AuthorizationFailed:
        return RedirectResponse("/settings?google=authorization_failed", status_code=303)
    return RedirectResponse("/settings?google=connected", status_code=303)


@router.get(
    "/api/v1/accounts",
    response_model=list[ConnectedAccountResponse],
    dependencies=[Depends(require_admin)],
)
def list_accounts(services: Services) -> list[ConnectedAccountResponse]:
    if services.list_connected_accounts is None:
        return []
    return [_account_response(item) for item in services.list_connected_accounts.execute()]


@router.post(
    "/api/v1/accounts/{account_id}/disconnect",
    response_model=ConnectedAccountResponse,
    dependencies=[Depends(require_admin)],
)
def disconnect_account(account_id: str, services: Services) -> ConnectedAccountResponse:
    disconnect = available(
        services.disconnect_connected_account, ACCOUNT_MANAGEMENT_UNAVAILABLE, MANAGE_ACCOUNTS
    )
    try:
        return _account_response(disconnect.execute(ConnectedAccountId(account_id)))
    except ConnectedAccountNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error


@router.delete(
    "/api/v1/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
def delete_account(account_id: str, services: Services) -> None:
    delete = available(
        services.delete_connected_account, ACCOUNT_MANAGEMENT_UNAVAILABLE, MANAGE_ACCOUNTS
    )
    try:
        delete.execute(ConnectedAccountId(account_id))
    except ConnectedAccountNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except ConnectedAccountMustBeDisconnected as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error


@router.get(
    "/api/v1/accounts/{account_id}/calendars",
    response_model=list[DiscoveredCalendarResponse],
    dependencies=[Depends(require_admin)],
)
def discover_calendars(account_id: str, services: Services) -> list[DiscoveredCalendarResponse]:
    discover = available(
        services.discover_calendars, PROVIDER_NOT_CONFIGURED, "no calendar provider is configured"
    )
    try:
        discovered = discover.execute(ConnectedAccountId(account_id))
    except ConnectedAccountNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except ConnectedAccountDisconnected as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except AuthorizationNotConfigured as error:
        raise problem_from(status.HTTP_503_SERVICE_UNAVAILABLE, error) from error
    return [
        DiscoveredCalendarResponse(
            id=calendar.id,
            summary=calendar.summary,
            access_role=_LEGACY_ACCESS_ROLES[calendar.access],
            writable=calendar.writable,
            primary=calendar.primary,
        )
        for calendar in discovered
    ]


# access_role's values the field has always had, before CalendarAccess existed (ADR 0022).
_LEGACY_ACCESS_ROLES: dict[CalendarAccess, str] = {
    CalendarAccess.OWNER: "owner",
    CalendarAccess.WRITER: "writer",
    CalendarAccess.READER: "reader",
    CalendarAccess.FREE_BUSY: "freeBusyReader",
}


@router.post(
    "/api/v1/accounts/{account_id}/verify",
    response_model=GoogleAccountAccessResponse,
    dependencies=[Depends(require_admin)],
)
def verify_account_access(account_id: str, services: Services) -> GoogleAccountAccessResponse:
    calendars = available(
        services.account_calendars, PROVIDER_NOT_CONFIGURED, "no calendar provider is configured"
    )
    try:
        access = calendars.verify_access(ConnectedAccountId(account_id))
    except ConnectedAccountNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except ConnectedAccountDisconnected as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except AccountAccessCheckFailed as error:
        raise problem_from(status.HTTP_424_FAILED_DEPENDENCY, error) from error
    except AuthorizationNotConfigured as error:
        raise problem_from(status.HTTP_503_SERVICE_UNAVAILABLE, error) from error
    return GoogleAccountAccessResponse(
        calendar_api=True,
        calendar_list_access=True,
        event_access=True,
        calendars_visible=access.calendars_visible,
        writable_calendars=access.writable_calendars,
    )


def _account_response(summary: ConnectedAccountSummary) -> ConnectedAccountResponse:
    account = summary.account
    return ConnectedAccountResponse(
        id=account.id.value,
        display_name=account.display_name,
        email=account.email,
        provider=account.provider.value,
        avatar_url=account.avatar_url,
        state=account.state.value,
        rule_count=summary.rule_count,
        authorized_at=account.authorized_at,
    )
