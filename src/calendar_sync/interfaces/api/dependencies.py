"""What every router shares: the administrator session guard and the services it reads."""

from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import Cookie, Depends, HTTPException, Request, Response, status

from calendar_sync.application.ports import AdministratorAccess

SESSION_COOKIE = "calendar_sync_session"


def app_services(request: Request) -> object:
    """The composed services `create_app` installed; each router declares the part it reads."""
    return request.app.state.container


class AdministratorServices(Protocol):
    @property
    def administrator(self) -> AdministratorAccess: ...


def require_admin(
    services: Annotated[AdministratorServices, Depends(app_services)],
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    if not services.administrator.session_is_valid(session):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "administrator session required")


def available[T](use_case: T | None, detail: str) -> T:
    """The one guard for what needs the installation master key or Google OAuth."""
    if use_case is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail)
    return use_case


def set_session_cookie(response: Response, token: str, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=7 * 24 * 60 * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
