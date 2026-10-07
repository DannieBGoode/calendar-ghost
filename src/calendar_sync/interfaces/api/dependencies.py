"""What every router shares: the administrator session guard and the services it reads."""

from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import Cookie, Depends, Header, Request, Response, status

from calendar_sync.application.ports import AdministratorAccess, IntegrationTokens
from calendar_sync.interfaces.access import StatusAccess, status_access
from calendar_sync.interfaces.api.problems import ApiProblem, problem

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
        raise problem(
            status.HTTP_401_UNAUTHORIZED, "session_required", "administrator session required"
        )


class StatusReaderServices(AdministratorServices, Protocol):
    @property
    def integration_tokens(self) -> IntegrationTokens: ...


def _unauthenticated() -> ApiProblem:
    """A fresh exception every refusal, so repeated failures do not share one growing traceback."""
    return problem(
        status.HTTP_401_UNAUTHORIZED,
        "credentials_required",
        "valid credentials required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_status_reader(
    services: Annotated[StatusReaderServices, Depends(app_services)],
    authorization: Annotated[str | None, Header()] = None,
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    access = status_access(
        services.integration_tokens, services.administrator, authorization, session
    )
    if access is StatusAccess.FORBIDDEN:
        raise problem(
            status.HTTP_403_FORBIDDEN, "insufficient_scope", "token lacks the required scope"
        )
    if access is not StatusAccess.GRANTED:
        raise _unauthenticated()


def available[T](use_case: T | None, code: str, detail: str) -> T:
    """The one guard for what needs the installation master key or Google OAuth."""
    if use_case is None:
        raise problem(status.HTTP_503_SERVICE_UNAVAILABLE, code, detail)
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
