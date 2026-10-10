"""The signed-in User's own account: their email and password, and what the Operator Overview
shows about them."""

from __future__ import annotations

import asyncio
from typing import Annotated, Protocol

from fastapi import APIRouter, Cookie, Depends, Response, status

from calendar_sync.application.administration import (
    DeleteOwnAccount,
    ShowOwnAccountDeletion,
    UserDeletionInterrupted,
)
from calendar_sync.application.errors import (
    EmailTaken,
    IncorrectPassword,
    PasswordPolicyViolation,
    RemovalRequiresAuthorization,
    RemovalRequiresProvider,
)
from calendar_sync.application.identity import (
    ChangeOwnPassword,
    SetNotificationEmail,
    SetOwnEmail,
)
from calendar_sync.domain.access import InvalidEmail, LastAdministrator, User, UserId
from calendar_sync.domain.model import ProjectionHandling
from calendar_sync.interfaces.api.dependencies import (
    SESSION_COOKIE,
    Identity,
    app_services,
    current_user,
    signed_in_user,
)
from calendar_sync.interfaces.api.problems import problem_from
from calendar_sync.interfaces.api.routes.session import user_response
from calendar_sync.interfaces.api.routes.users import deletion_response
from calendar_sync.interfaces.api.schemas import (
    ChangePasswordRequest,
    DeleteOwnAccountRequest,
    NotificationPreferenceRequest,
    OwnAccountDeletionResponse,
    SetEmailRequest,
    SignedInUserResponse,
    UserDeletionResponse,
)


class OwnAccountAdministration(Protocol):
    @property
    def delete_own_account(self) -> DeleteOwnAccount: ...
    @property
    def show_own_account_deletion(self) -> ShowOwnAccountDeletion: ...


class AccountIdentity(Identity, Protocol):
    @property
    def set_own_email(self) -> SetOwnEmail: ...
    @property
    def set_notification_email(self) -> SetNotificationEmail: ...
    @property
    def change_own_password(self) -> ChangeOwnPassword: ...


class OwnAccountServices(Protocol):
    @property
    def identity(self) -> AccountIdentity: ...
    @property
    def administration(self) -> OwnAccountAdministration: ...


Services = Annotated[OwnAccountServices, Depends(app_services)]
SignedIn = Annotated[User, Depends(signed_in_user)]
CurrentUser = Annotated[UserId, Depends(current_user)]
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


@router.put("/api/v1/account/notifications", response_model=SignedInUserResponse)
def set_notifications(
    payload: NotificationPreferenceRequest,
    services: Services,
    user_id: Annotated[UserId, Depends(current_user)],
) -> SignedInUserResponse:
    """Whether the User's Incident Notifications also come by email; the Web UI keeps them all."""
    changed = services.identity.set_notification_email.execute(user_id, payload.notify_by_email)
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


@router.get("/api/v1/account/deletion", response_model=OwnAccountDeletionResponse)
def own_account_deletion(
    services: Services, user_id: Annotated[UserId, Depends(current_user)]
) -> OwnAccountDeletionResponse:
    """Whether the User may delete themself now, and whether nobody would remain."""
    shown = services.administration.show_own_account_deletion.execute(user_id)
    return OwnAccountDeletionResponse(
        needs_another_administrator=shown.needs_another_administrator, last_user=shown.last_user
    )


@router.delete("/api/v1/account", response_model=UserDeletionResponse)
async def delete_own_account(
    payload: DeleteOwnAccountRequest,
    services: Services,
    response: Response,
    user_id: Annotated[UserId, Depends(current_user)],
) -> UserDeletionResponse:
    """Delete the signed-in User and every record they own, keeping or deleting projections."""
    delete = services.administration.delete_own_account
    try:
        # Rule Removal waits on the calendar provider, so it runs off the event loop.
        result = await asyncio.to_thread(
            delete.execute, user_id, payload.password, ProjectionHandling(payload.projections)
        )
    except IncorrectPassword as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error
    except (
        LastAdministrator,
        UserDeletionInterrupted,
        RemovalRequiresAuthorization,
        RemovalRequiresProvider,
    ) as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    response.delete_cookie(SESSION_COOKIE, path="/")
    return deletion_response(result)
