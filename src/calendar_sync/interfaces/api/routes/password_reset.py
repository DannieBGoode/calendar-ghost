"""Anonymous password recovery, separate from sign-in and Invitation allowances."""

from collections.abc import Callable
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Request, status

from calendar_sync.application.identity.administration import (
    CheckPasswordReset,
    LinkUnusable,
    ResetPassword,
)
from calendar_sync.application.identity.errors import (
    PasswordPolicyViolation,
    ResetStorageUnavailable,
)
from calendar_sync.application.identity.identity_email import IdentityEmailNotConfigured
from calendar_sync.application.identity.password_reset import RequestPasswordReset
from calendar_sync.application.identity.reset_admission import (
    ResetAdmissionStorageUnavailable,
    ResetGlobalThrottled,
    ResetNetworkThrottled,
)
from calendar_sync.domain.access import InvalidEmail
from calendar_sync.interfaces.api.dependencies import app_services
from calendar_sync.interfaces.api.problems import ApiProblem, problem_from
from calendar_sync.interfaces.api.schemas import (
    LinkStatusResponse,
    PasswordResetAcceptedResponse,
    PasswordResetLinkRequest,
    RequestPasswordResetRequest,
    ResetPasswordRequest,
)


class ResetAdministration(Protocol):
    @property
    def check_password_reset(self) -> CheckPasswordReset: ...
    @property
    def reset_password(self) -> ResetPassword: ...


class ResetRequests(Protocol):
    @property
    def request_reset(self) -> RequestPasswordReset: ...


class PasswordResetServices(Protocol):
    @property
    def reset_client_network(self) -> Callable[[str], str]: ...
    @property
    def identity_email(self) -> ResetRequests: ...
    @property
    def administration(self) -> ResetAdministration: ...


Services = Annotated[PasswordResetServices, Depends(app_services)]
router = APIRouter()


def _network(request: Request, services: PasswordResetServices) -> str:
    return services.reset_client_network(request.client.host if request.client else "unknown")


def _unavailable(error: Exception) -> ApiProblem:
    safe = error if isinstance(error, IdentityEmailNotConfigured) else ResetStorageUnavailable()
    return problem_from(status.HTTP_503_SERVICE_UNAVAILABLE, safe)


@router.post(
    "/api/v1/password-resets/request",
    response_model=PasswordResetAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_password_reset(
    payload: RequestPasswordResetRequest, request: Request, services: Services
) -> PasswordResetAcceptedResponse:
    try:
        services.identity_email.request_reset.execute(payload.email, _network(request, services))
    except (ResetNetworkThrottled, ResetGlobalThrottled) as error:
        raise problem_from(status.HTTP_429_TOO_MANY_REQUESTS, error) from error
    except (ResetAdmissionStorageUnavailable, IdentityEmailNotConfigured) as error:
        raise _unavailable(error) from error
    except InvalidEmail as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    return PasswordResetAcceptedResponse()


@router.post("/api/v1/password-resets/check", response_model=LinkStatusResponse)
def check_password_reset(
    payload: PasswordResetLinkRequest, request: Request, services: Services
) -> LinkStatusResponse:
    try:
        usable = services.administration.check_password_reset.execute(
            payload.token, _network(request, services)
        )
    except (ResetNetworkThrottled, ResetGlobalThrottled) as error:
        raise problem_from(status.HTTP_429_TOO_MANY_REQUESTS, error) from error
    except (ResetAdmissionStorageUnavailable, ResetStorageUnavailable) as error:
        raise _unavailable(error) from error
    return LinkStatusResponse(usable=usable)


@router.post("/api/v1/password-resets", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(payload: ResetPasswordRequest, request: Request, services: Services) -> None:
    try:
        services.administration.reset_password.execute(
            payload.token, payload.password, _network(request, services)
        )
    except (ResetNetworkThrottled, ResetGlobalThrottled) as error:
        raise problem_from(status.HTTP_429_TOO_MANY_REQUESTS, error) from error
    except (ResetAdmissionStorageUnavailable, ResetStorageUnavailable) as error:
        raise _unavailable(error) from error
    except LinkUnusable as error:
        raise problem_from(status.HTTP_410_GONE, error) from error
    except PasswordPolicyViolation as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
