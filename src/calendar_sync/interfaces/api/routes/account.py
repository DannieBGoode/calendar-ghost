"""The signed-in User's own account: their email and password."""

from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Cookie, Depends, status

from calendar_sync.application.errors import (
    EmailTaken,
    IncorrectPassword,
    PasswordPolicyViolation,
)
from calendar_sync.application.identity import ChangeOwnPassword, SetOwnEmail
from calendar_sync.domain.access import InvalidEmail, User
from calendar_sync.interfaces.api.dependencies import (
    SESSION_COOKIE,
    Identity,
    app_services,
    current_user,
    signed_in_user,
)
from calendar_sync.interfaces.api.problems import problem_from
from calendar_sync.interfaces.api.routes.session import user_response
from calendar_sync.interfaces.api.schemas import (
    ChangePasswordRequest,
    SetEmailRequest,
    SignedInUserResponse,
)


class AccountIdentity(Identity, Protocol):
    @property
    def set_own_email(self) -> SetOwnEmail: ...
    @property
    def change_own_password(self) -> ChangeOwnPassword: ...


class OwnAccountServices(Protocol):
    @property
    def identity(self) -> AccountIdentity: ...


Services = Annotated[OwnAccountServices, Depends(app_services)]
SignedIn = Annotated[User, Depends(signed_in_user)]
router = APIRouter()


@router.put("/api/v1/account/email", response_model=SignedInUserResponse)
def set_email(payload: SetEmailRequest, user: SignedIn, services: Services) -> SignedInUserResponse:
    """Add the email the upgraded first User must add, or change one with the password."""
    try:
        changed = services.identity.set_own_email.execute(user.id, payload.email, payload.password)
    except InvalidEmail as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    except IncorrectPassword as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error
    except EmailTaken as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    return user_response(changed)


@router.put(
    "/api/v1/account/password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(current_user)],
)
def change_password(
    payload: ChangePasswordRequest,
    user: SignedIn,
    services: Services,
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    """Replace the password; every other session of the User ends."""
    try:
        services.identity.change_own_password.execute(
            user.id, payload.current_password, payload.new_password, session
        )
    except IncorrectPassword as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error
    except PasswordPolicyViolation as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
