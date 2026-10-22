from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Request, Response, status

from calendar_sync.application.identity.errors import (
    AdminAlreadyConfigured,
    IncorrectCredentials,
    PasswordPolicyViolation,
)
from calendar_sync.application.identity.sign_in import SetUpInstallation
from calendar_sync.domain.access import InvalidEmail
from calendar_sync.interfaces.api.dependencies import Identity, app_services, set_session_cookie
from calendar_sync.interfaces.api.problems import problem_from
from calendar_sync.interfaces.api.routes.registration import RegistrationAvailability
from calendar_sync.interfaces.api.routes.session import SignedInAnswers, signed_in
from calendar_sync.interfaces.api.schemas.identity import (
    SessionResponse,
    SetupRequest,
    SetupStatusResponse,
)
from calendar_sync.interfaces.api.sign_in_cookies import browser_context


class SetupIdentity(Identity, Protocol):
    @property
    def set_up(self) -> SetUpInstallation: ...


class ResetAvailability(Protocol):
    @property
    def configured(self) -> bool: ...


class SetupServices(SignedInAnswers, Protocol):
    @property
    def registrations(self) -> RegistrationAvailability: ...
    @property
    def identity_email(self) -> ResetAvailability: ...
    @property
    def identity(self) -> SetupIdentity: ...
    @property
    def secure_cookies(self) -> bool: ...


Services = Annotated[SetupServices, Depends(app_services)]
router = APIRouter()


@router.get("/api/v1/setup", response_model=SetupStatusResponse)
def setup_status(services: Services) -> SetupStatusResponse:
    users = services.identity.users
    return SetupStatusResponse(
        administrator_configured=users.count() > 0,
        password_reset_available=services.identity_email.configured,
        public_registration_available=services.registrations.readiness.public_available(),
        password_only_sign_in=users.without_email() is not None,
    )


@router.post("/api/v1/setup/admin", response_model=SessionResponse)
def set_up(
    payload: SetupRequest, request: Request, response: Response, services: Services
) -> SessionResponse:
    try:
        session = services.identity.set_up.execute(
            payload.email, payload.password, browser_context(request)
        )
    except (AdminAlreadyConfigured, PasswordPolicyViolation) as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except InvalidEmail as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    except IncorrectCredentials as error:
        raise problem_from(status.HTTP_401_UNAUTHORIZED, error) from error
    answer = signed_in(services.identity.users.get(session.user_id), services)
    set_session_cookie(response, session.token, services.secure_cookies)
    return answer
