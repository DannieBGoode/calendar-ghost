"""The signed-in User's guarded sign-in email changes."""

from collections.abc import Callable
from typing import Annotated, Protocol

from fastapi import APIRouter, Cookie, Depends, Query, Request, status

from calendar_sync.application.identity.email_change_admission import (
    EmailChangeStorageUnavailable,
    EmailChangeThrottled,
)
from calendar_sync.application.identity.email_changes import (
    CancelEmailChange,
    CheckEmailChange,
    ConfirmEmailChange,
    DirectEmailChange,
    EmailChangeConfigurationRequired,
    EmailChangeProofUnusable,
    EmailChangeUnavailable,
    RequestEmailChange,
    ShowEmailChange,
)
from calendar_sync.application.identity.errors import IncorrectCredentials, IncorrectPassword
from calendar_sync.domain.access import UserId
from calendar_sync.interfaces.api.dependencies import (
    SESSION_COOKIE,
    app_services,
    current_user,
)
from calendar_sync.interfaces.api.identity_schemas import (
    ConfirmEmailChangeRequest,
    EmailChangeAcceptedResponse,
    EmailChangeCheckResponse,
    EmailChangeStatusResponse,
    EmailChangeTokenRequest,
    RequestEmailChangeRequest,
)
from calendar_sync.interfaces.api.problems import ApiProblem, problem_from


class EmailChanges(Protocol):
    @property
    def show(self) -> ShowEmailChange: ...
    @property
    def direct(self) -> DirectEmailChange: ...
    @property
    def request(self) -> RequestEmailChange: ...
    @property
    def cancel(self) -> CancelEmailChange: ...
    @property
    def check(self) -> CheckEmailChange: ...
    @property
    def confirm(self) -> ConfirmEmailChange: ...


class IdentityEmail(Protocol):
    @property
    def email_changes(self) -> EmailChanges: ...


class EmailChangeApiServices(Protocol):
    @property
    def identity_email(self) -> IdentityEmail: ...
    @property
    def reset_client_network(self) -> Callable[[str], str]: ...


Services = Annotated[EmailChangeApiServices, Depends(app_services)]
CurrentUser = Annotated[UserId, Depends(current_user)]
Session = Annotated[str | None, Cookie(alias=SESSION_COOKIE)]
router = APIRouter()


def _network(request: Request, services: EmailChangeApiServices) -> str:
    return services.reset_client_network(request.client.host if request.client else "unknown")


def email_change_failure(error: Exception) -> ApiProblem:
    if isinstance(error, EmailChangeThrottled):
        code = status.HTTP_429_TOO_MANY_REQUESTS
    elif isinstance(error, (EmailChangeStorageUnavailable, EmailChangeConfigurationRequired)):
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(error, EmailChangeProofUnusable):
        code = status.HTTP_410_GONE
    elif isinstance(error, IncorrectPassword):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(error, IncorrectCredentials):
        code = status.HTTP_401_UNAUTHORIZED
    else:
        code = status.HTTP_409_CONFLICT
    return problem_from(code, error)


@router.get("/api/v1/account/email-change", response_model=EmailChangeStatusResponse)
def show_email_change(services: Services, user: CurrentUser) -> EmailChangeStatusResponse:
    try:
        result = services.identity_email.email_changes.show.execute(user)
    except (IncorrectCredentials, EmailChangeStorageUnavailable) as error:
        raise email_change_failure(error) from None
    return EmailChangeStatusResponse.model_validate(result, from_attributes=True)


@router.post(
    "/api/v1/account/email-change",
    response_model=EmailChangeAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_email_change(
    payload: RequestEmailChangeRequest,
    request: Request,
    services: Services,
    user: CurrentUser,
    session: Session = None,
) -> EmailChangeAcceptedResponse:
    try:
        services.identity_email.email_changes.request.execute(
            user, payload.email, payload.password, session or "", _network(request, services)
        )
    except (
        EmailChangeThrottled,
        EmailChangeStorageUnavailable,
        EmailChangeConfigurationRequired,
        EmailChangeUnavailable,
        IncorrectCredentials,
        IncorrectPassword,
    ) as error:
        raise email_change_failure(error) from None
    return EmailChangeAcceptedResponse()


@router.delete("/api/v1/account/email-change", status_code=status.HTTP_204_NO_CONTENT)
def cancel_email_change(
    services: Services,
    user: CurrentUser,
    request_id: Annotated[str, Query(min_length=1, max_length=128)],
) -> None:
    try:
        services.identity_email.email_changes.cancel.execute(user, request_id)
    except EmailChangeStorageUnavailable as error:
        raise email_change_failure(error) from None


@router.post("/api/v1/account/email-change/check", response_model=EmailChangeCheckResponse)
def check_email_change(
    payload: EmailChangeTokenRequest, request: Request, services: Services, user: CurrentUser
) -> EmailChangeCheckResponse:
    try:
        usable = services.identity_email.email_changes.check.execute(
            user, payload.token, _network(request, services)
        )
    except (EmailChangeThrottled, EmailChangeStorageUnavailable) as error:
        raise email_change_failure(error) from None
    return EmailChangeCheckResponse(usable=usable)


@router.post("/api/v1/account/email-change/confirm", status_code=status.HTTP_204_NO_CONTENT)
def confirm_email_change(
    payload: ConfirmEmailChangeRequest,
    request: Request,
    services: Services,
    user: CurrentUser,
    session: Session = None,
) -> None:
    try:
        services.identity_email.email_changes.confirm.execute(
            user, payload.token, payload.password, session or "", _network(request, services)
        )
    except (
        EmailChangeThrottled,
        EmailChangeStorageUnavailable,
        EmailChangeUnavailable,
        EmailChangeProofUnusable,
        IncorrectCredentials,
        IncorrectPassword,
    ) as error:
        raise email_change_failure(error) from None
