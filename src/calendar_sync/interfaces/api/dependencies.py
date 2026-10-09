"""What every router shares: the session guard, and the services of the User it resolves."""

from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import Cookie, Depends, Header, Request, Response, status

from calendar_sync.application.ports import (
    IntegrationTokenAuthentication,
    IntegrationTokenScope,
    Sessions,
    UserDirectory,
)
from calendar_sync.domain.access import User, UserId
from calendar_sync.interfaces.access import StatusAccess, status_access
from calendar_sync.interfaces.api.problems import ApiProblem, problem

SESSION_COOKIE = "calendar_sync_session"


def app_services(request: Request) -> object:
    """The composed services `create_app` installed; each router declares the part it reads."""
    return request.app.state.container


class Identity(Protocol):
    @property
    def users(self) -> UserDirectory: ...
    @property
    def sessions(self) -> Sessions: ...


class SessionServices(Protocol):
    @property
    def identity(self) -> Identity: ...


class UserScopedServices(Protocol):
    def for_user(self, user_id: UserId) -> object: ...


def signed_in_user(
    services: Annotated[SessionServices, Depends(app_services)],
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> User:
    """The signed-in User, even before they add the email they must add first."""
    identity = services.identity
    user_id = identity.sessions.user_of(session)
    user = identity.users.get(user_id) if user_id is not None else None
    if user is None:
        raise problem(status.HTTP_401_UNAUTHORIZED, "session_required", "a signed-in User required")
    return user


def session_user(
    services: Annotated[SessionServices, Depends(app_services)],
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> UserId | None:
    """The User this browser is signed in as, or None; for a route that answers a redirect
    rather than a 401, such as the OAuth callback a provider sends the browser to."""
    return services.identity.sessions.user_of(session)


def current_user(user: Annotated[User, Depends(signed_in_user)]) -> UserId:
    """The signed-in User, once they have an email; every route but a few depends on it."""
    _require_email(user)
    return user.id


def _require_email(user: User | None) -> None:
    if user is not None and user.needs_email:
        raise problem(status.HTTP_403_FORBIDDEN, "email_required", "add your email to continue")


def administrator(
    user: Annotated[User, Depends(signed_in_user)],
    user_id: Annotated[UserId, Depends(current_user)],
) -> UserId:
    """The signed-in Installation Administrator; other Users are refused before anything is
    looked up, so an administrator route reveals nothing about what exists."""
    if not user.administers:
        raise problem(
            status.HTTP_403_FORBIDDEN,
            "administrator_required",
            "only an Installation Administrator may do this",
        )
    return user_id


def user_services(
    services: Annotated[UserScopedServices, Depends(app_services)],
    user: Annotated[UserId, Depends(current_user)],
) -> object:
    """The signed-in User's use cases, which see only that User's records (ADR 0029)."""
    return services.for_user(user)


class StatusReaderServices(SessionServices, Protocol):
    @property
    def token_authentication(self) -> IntegrationTokenAuthentication: ...


def _unauthenticated() -> ApiProblem:
    """A fresh exception every refusal, so repeated failures do not share one growing traceback."""
    return problem(
        status.HTTP_401_UNAUTHORIZED,
        "credentials_required",
        "valid credentials required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def status_reader(
    services: Annotated[StatusReaderServices, Depends(app_services)],
    authorization: Annotated[str | None, Header()] = None,
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> UserId:
    """The User whose Installation Status a token or session may read."""
    access = status_access(
        services.token_authentication, services.identity.sessions, authorization, session
    )
    if access.result is StatusAccess.FORBIDDEN:
        raise problem(
            status.HTTP_403_FORBIDDEN, "insufficient_scope", "token lacks the required scope"
        )
    if access.result is not StatusAccess.GRANTED or access.user is None:
        raise _unauthenticated()
    if authorization is None:
        # A session reads status only once its User has added the email they must add first.
        _require_email(services.identity.users.get(access.user))
    return access.user


def installation_reader(
    services: Annotated[StatusReaderServices, Depends(app_services)],
    authorization: Annotated[str | None, Header()] = None,
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> UserId:
    """An Installation Administrator reading Installation Health with a session or a token
    carrying installation:read. A token stops working here once its User stops administering."""
    access = status_access(
        services.token_authentication,
        services.identity.sessions,
        authorization,
        session,
        frozenset({IntegrationTokenScope.INSTALLATION_READ}),
    )
    if access.result is StatusAccess.FORBIDDEN:
        raise problem(
            status.HTTP_403_FORBIDDEN, "insufficient_scope", "token lacks the required scope"
        )
    if access.result is not StatusAccess.GRANTED or access.user is None:
        raise _unauthenticated()
    reader = services.identity.users.get(access.user)
    if authorization is None:
        _require_email(reader)
    if reader is None or not reader.administers:
        raise problem(
            status.HTTP_403_FORBIDDEN,
            "administrator_required",
            "only an Installation Administrator may do this",
        )
    return reader.id


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
