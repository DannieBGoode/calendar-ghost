from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Cookie, Depends, Response, status

from calendar_sync.application.ports import AdministratorAccess
from calendar_sync.interfaces.api.dependencies import (
    SESSION_COOKIE,
    app_services,
    set_session_cookie,
)
from calendar_sync.interfaces.api.problems import problem
from calendar_sync.interfaces.api.schemas import PasswordRequest, SessionResponse


class SessionServices(Protocol):
    @property
    def administrator(self) -> AdministratorAccess: ...
    @property
    def secure_cookies(self) -> bool: ...


Services = Annotated[SessionServices, Depends(app_services)]
router = APIRouter()


@router.post("/api/v1/session", response_model=SessionResponse)
def log_in(request: PasswordRequest, response: Response, services: Services) -> SessionResponse:
    session = services.administrator.authenticate(request.password)
    if session is None:
        raise problem(status.HTTP_401_UNAUTHORIZED, "incorrect_password", "incorrect password")
    set_session_cookie(response, session.token, services.secure_cookies)
    return SessionResponse(authenticated=True)


@router.get("/api/v1/session", response_model=SessionResponse)
def session_status(
    services: Services,
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> SessionResponse:
    return SessionResponse(authenticated=services.administrator.session_is_valid(session))


@router.delete("/api/v1/session", status_code=status.HTTP_204_NO_CONTENT)
def log_out(
    response: Response,
    services: Services,
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    services.administrator.revoke(session)
    response.delete_cookie(SESSION_COOKIE, path="/")
