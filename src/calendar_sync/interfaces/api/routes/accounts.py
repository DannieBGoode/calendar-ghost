from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Protocol
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, status
from fastapi.responses import RedirectResponse

from calendar_sync.application.accounts import (
    CheckAccountAccess,
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
from calendar_sync.application.lapsed_authorization import LapsedAuthorizations
from calendar_sync.application.ports import CalendarAccess
from calendar_sync.application.provider_descriptors import ProviderDescriptor, ProviderDirectory
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.interfaces.api.dependencies import (
    app_services,
    available,
    current_user,
    session_user,
    user_services,
)
from calendar_sync.interfaces.api.problems import problem, problem_from
from calendar_sync.interfaces.api.schemas import (
    AccountAccessResponse,
    ConnectedAccountResponse,
    DiscoveredCalendarResponse,
    ProviderResponse,
)

MANAGE_ACCOUNTS = "configure the installation master key before managing accounts"
ACCOUNT_MANAGEMENT_UNAVAILABLE = "account_management_unavailable"
PROVIDER_NOT_CONFIGURED = "provider_not_configured"
# Where a provider returns the browser: Settings, at the tab that lists Connected Accounts.
CONNECTIONS = "/settings/connections"
# OAuth errors that mean the person refused what was asked, rather than that the flow failed
# (RFC 6749 section 4.1.2.1).
REFUSED = frozenset({"access_denied"})


class AccountServices(Protocol):
    """One User's account use cases."""

    @property
    def discover_calendars(self) -> DiscoverCalendars | None: ...
    @property
    def list_connected_accounts(self) -> ListConnectedAccounts | None: ...
    @property
    def disconnect_connected_account(self) -> DisconnectConnectedAccount | None: ...
    @property
    def delete_connected_account(self) -> DeleteConnectedAccount | None: ...
    @property
    def check_account_access(self) -> CheckAccountAccess | None: ...
    @property
    def lapsed_authorizations(self) -> LapsedAuthorizations | None: ...


class AuthorizationServices(Protocol):
    """The installation's calendar providers, and each User's account use cases."""

    @property
    def providers(self) -> ProviderDirectory: ...
    def for_user(self, user_id: UserId) -> AccountServices: ...


Services = Annotated[AccountServices, Depends(user_services)]
Installation = Annotated[AuthorizationServices, Depends(app_services)]
SignedIn = Annotated[UserId, Depends(current_user)]
Browser = Annotated[UserId | None, Depends(session_user)]
router = APIRouter()


@router.get(
    "/api/v1/providers",
    response_model=list[ProviderResponse],
    dependencies=[Depends(current_user)],
)
def list_providers(installation: Installation) -> list[ProviderResponse]:
    """The calendar providers this installation configured, and how to connect each."""
    return [
        ProviderResponse(
            kind=descriptor.kind.value,
            display_name=descriptor.guide.display_name,
            connect_url=start_url(descriptor),
            redirect_uri=descriptor.connection.redirect_uri,
            cause_anchors={
                cause.value: anchor for cause, anchor in descriptor.guide.cause_anchors.items()
            },
        )
        for descriptor in installation.providers.connectable
        if descriptor.connection is not None
    ]


def start_url(descriptor: ProviderDescriptor) -> str:
    return f"/api/v1/oauth/{descriptor.guide.slug}/start"


def _provider(installation: AuthorizationServices, slug: str) -> ProviderDescriptor:
    descriptor = installation.providers.at(slug)
    if descriptor is None:
        raise problem(
            status.HTTP_404_NOT_FOUND,
            "provider_not_found",
            "no calendar provider connects through this address",
        )
    return descriptor


@router.get("/api/v1/oauth/{slug}/start")
def start_oauth(
    slug: str, installation: Installation, user: SignedIn, account: str | None = None
) -> RedirectResponse:
    """Start the provider's consent for the signed-in User; reauthorizing a known `account`
    suggests its email to the provider."""
    descriptor = _provider(installation, slug)
    connection = available(
        descriptor.connection,
        ACCOUNT_MANAGEMENT_UNAVAILABLE,
        "configure the installation master key before connecting an account",
    )
    try:
        url = connection.authorization.authorization_url(
            user, _account_email(installation.for_user(user), account)
        )
        return RedirectResponse(url, status_code=302)
    except AuthorizationNotConfigured as error:
        raise problem_from(status.HTTP_503_SERVICE_UNAVAILABLE, error) from error


@router.get("/api/v1/oauth/{slug}/callback", include_in_schema=False)
def complete_oauth(
    slug: str,
    installation: Installation,
    browser: Browser,
    state: str,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """The provider returns the browser here. Its session cookie comes along, since the redirect
    is a top-level navigation, and only the User who began the flow may complete it: a consent
    link sent to someone else connects nothing."""
    descriptor = _provider(installation, slug)
    connection = available(
        descriptor.connection,
        "authorization_not_configured",
        f"{descriptor.guide.display_name} OAuth is not configured",
    )
    authorization = connection.authorization
    returned = _ReturnTo(descriptor.kind.value)
    if browser is None:
        return returned.outcome("authorization_failed")
    if error is not None:
        try:
            authorization.cancel(state)
        except InvalidAuthorizationState as state_error:
            raise problem_from(status.HTTP_400_BAD_REQUEST, state_error) from state_error
        refused = error in REFUSED
        return returned.outcome(
            "calendar_permission_required" if refused else "authorization_failed"
        )
    if code is None:
        raise problem(
            status.HTTP_400_BAD_REQUEST,
            "oauth_result_missing",
            "the OAuth callback did not include an authorization result",
        )
    try:
        authorized = authorization.complete(state, code, browser)
    except InvalidAuthorizationState as state_error:
        raise problem_from(status.HTTP_400_BAD_REQUEST, state_error) from state_error
    except CalendarPermissionRequired:
        return returned.outcome("calendar_permission_required")
    except AuthorizationFailed:
        return returned.outcome("authorization_failed")
    # The User who began the flow finished it; the account and its rules are theirs.
    account = authorized.account
    lapses = installation.for_user(authorized.owner).lapsed_authorizations
    # The provider accepted the account when its new credentials were saved.
    accepted_at = datetime.fromisoformat(account.authorized_at or datetime.now(UTC).isoformat())
    resumed = lapses.restored(account.id, accepted_at=accepted_at) if lapses is not None else 0
    return returned.outcome("connected", account=account.id.value, resumed=resumed)


class _ReturnTo:
    """Settings, told how a provider's connection flow ended."""

    def __init__(self, provider: str) -> None:
        self._provider = provider

    def outcome(self, outcome: str, **details: str | int) -> RedirectResponse:
        query = urlencode({"oauth": outcome, "provider": self._provider, **details})
        return RedirectResponse(f"{CONNECTIONS}?{query}", status_code=303)


def _account_email(services: AccountServices, account_id: str | None) -> str | None:
    """The email of the account being reauthorized, so the provider can offer it first."""
    if account_id is None or services.list_connected_accounts is None:
        return None
    return next(
        (
            summary.account.email
            for summary in services.list_connected_accounts.execute()
            if summary.account.id.value == account_id
        ),
        None,
    )


@router.get(
    "/api/v1/accounts",
    response_model=list[ConnectedAccountResponse],
    dependencies=[Depends(current_user)],
)
def list_accounts(services: Services) -> list[ConnectedAccountResponse]:
    if services.list_connected_accounts is None:
        return []
    return [_account_response(item) for item in services.list_connected_accounts.execute()]


@router.post(
    "/api/v1/accounts/{account_id}/disconnect",
    response_model=ConnectedAccountResponse,
    dependencies=[Depends(current_user)],
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
    dependencies=[Depends(current_user)],
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
    dependencies=[Depends(current_user)],
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
    response_model=AccountAccessResponse,
    dependencies=[Depends(current_user)],
)
def verify_account_access(account_id: str, services: Services) -> AccountAccessResponse:
    check = available(
        services.check_account_access, PROVIDER_NOT_CONFIGURED, "no calendar provider is configured"
    )
    try:
        result = check.execute(ConnectedAccountId(account_id))
    except ConnectedAccountNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except ConnectedAccountDisconnected as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except AccountAccessCheckFailed as error:
        raise problem_from(status.HTTP_424_FAILED_DEPENDENCY, error) from error
    except AuthorizationNotConfigured as error:
        raise problem_from(status.HTTP_503_SERVICE_UNAVAILABLE, error) from error
    return AccountAccessResponse(
        calendar_api=True,
        calendar_list_access=True,
        event_access=True,
        calendars_visible=result.access.calendars_visible,
        writable_calendars=result.access.writable_calendars,
        rules_resumed=result.rules_resumed,
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
        authorization_lapsed_at=account.authorization_lapsed_at,
    )
