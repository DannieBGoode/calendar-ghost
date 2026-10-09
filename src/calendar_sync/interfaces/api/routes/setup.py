from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Response, status

from calendar_sync.application.errors import AdminAlreadyConfigured, PasswordPolicyViolation
from calendar_sync.application.identity import SetUpInstallation
from calendar_sync.domain.access import InvalidEmail
from calendar_sync.interfaces.api.dependencies import Identity, app_services, set_session_cookie
from calendar_sync.interfaces.api.problems import problem_from
from calendar_sync.interfaces.api.routes.session import signed_in
from calendar_sync.interfaces.api.schemas import (
    SessionResponse,
    SetupRequest,
    SetupStatusResponse,
)


class SetupIdentity(Identity, Protocol):
    @property
    def set_up(self) -> SetUpInstallation: ...


class SetupServices(Protocol):
    @property
    def identity(self) -> SetupIdentity: ...
    @property
    def secure_cookies(self) -> bool: ...
    @property
    def sends_email(self) -> bool: ...


Services = Annotated[SetupServices, Depends(app_services)]
router = APIRouter()


@router.get("/api/v1/setup", response_model=SetupStatusResponse)
def setup_status(services: Services) -> SetupStatusResponse:
    users = services.identity.users
    return SetupStatusResponse(
        administrator_configured=users.count() > 0,
        password_only_sign_in=users.without_email() is not None,
    )


@router.post("/api/v1/setup/admin", response_model=SessionResponse)
def set_up(payload: SetupRequest, response: Response, services: Services) -> SessionResponse:
    try:
        session = services.identity.set_up.execute(payload.email, payload.password)
    except (AdminAlreadyConfigured, PasswordPolicyViolation) as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except InvalidEmail as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    set_session_cookie(response, session.token, services.secure_cookies)
    return signed_in(services.identity.users.get(session.user_id), services.sends_email)
