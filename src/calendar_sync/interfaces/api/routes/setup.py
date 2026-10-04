from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from calendar_sync.application.errors import AdminAlreadyConfigured, PasswordPolicyViolation
from calendar_sync.interfaces.api.dependencies import app_services, set_session_cookie
from calendar_sync.interfaces.api.problems import problem_from
from calendar_sync.interfaces.api.routes.session import SessionServices
from calendar_sync.interfaces.api.schemas import (
    PasswordRequest,
    SessionResponse,
    SetupStatusResponse,
)

Services = Annotated[SessionServices, Depends(app_services)]
router = APIRouter()


@router.get("/api/v1/setup", response_model=SetupStatusResponse)
def setup_status(services: Services) -> SetupStatusResponse:
    return SetupStatusResponse(administrator_configured=services.administrator.is_configured())


@router.post("/api/v1/setup/admin", response_model=SessionResponse)
def create_admin(
    request: PasswordRequest, response: Response, services: Services
) -> SessionResponse:
    try:
        services.administrator.create_admin(request.password)
    except (AdminAlreadyConfigured, PasswordPolicyViolation) as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    session = services.administrator.authenticate(request.password)
    assert session is not None
    set_session_cookie(response, session.token, services.secure_cookies)
    return SessionResponse(authenticated=True)
