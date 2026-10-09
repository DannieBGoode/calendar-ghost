from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Cookie, Depends, Request, Response, status

from calendar_sync.application.errors import (
    IncorrectCredentials,
    SignInThrottled,
    UserDisabled,
)
from calendar_sync.application.identity import SignIn
from calendar_sync.domain.access import User
from calendar_sync.interfaces.api.dependencies import (
    SESSION_COOKIE,
    Identity,
    app_services,
    set_session_cookie,
)
from calendar_sync.interfaces.api.problems import problem_from
from calendar_sync.interfaces.api.schemas import (
    SessionResponse,
    SignedInUserResponse,
    SignInRequest,
)


class SignInIdentity(Identity, Protocol):
    @property
    def sign_in(self) -> SignIn: ...


class SessionServices(Protocol):
    @property
    def identity(self) -> SignInIdentity: ...
    @property
    def secure_cookies(self) -> bool: ...


Services = Annotated[SessionServices, Depends(app_services)]
router = APIRouter()


@router.post("/api/v1/session", response_model=SessionResponse)
def sign_in(
    payload: SignInRequest, request: Request, response: Response, services: Services
) -> SessionResponse:
    client = request.client.host if request.client is not None else "unknown"
    try:
        session = services.identity.sign_in.execute(payload.email, payload.password, client)
    except IncorrectCredentials as error:
        raise problem_from(status.HTTP_401_UNAUTHORIZED, error) from error
    except UserDisabled as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error
    except SignInThrottled as error:
        throttled = problem_from(status.HTTP_429_TOO_MANY_REQUESTS, error)
        throttled.headers = {"Retry-After": str(error.retry_after)}
        raise throttled from error
    set_session_cookie(response, session.token, services.secure_cookies)
    return signed_in(services.identity.users.get(session.user_id))


@router.get("/api/v1/session", response_model=SessionResponse)
def session_status(
    services: Services,
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> SessionResponse:
    user_id = services.identity.sessions.user_of(session)
    return signed_in(services.identity.users.get(user_id) if user_id is not None else None)


@router.delete("/api/v1/session", status_code=status.HTTP_204_NO_CONTENT)
def sign_out(
    response: Response,
    services: Services,
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    services.identity.sessions.end(session)
    response.delete_cookie(SESSION_COOKIE, path="/")


def signed_in(user: User | None) -> SessionResponse:
    if user is None:
        return SessionResponse(authenticated=False)
    return SessionResponse(authenticated=True, user=user_response(user))


def user_response(user: User) -> SignedInUserResponse:
    return SignedInUserResponse(
        id=user.id.value,
        email=user.email,
        role=user.role.value,
        notify_by_email=user.notify_by_email,
        language=user.language,
    )
