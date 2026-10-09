"""Settings → Users: the Registration Policy, Invitations, roles, disabling, and deletion.

Every route here is an Installation Administrator's, except the two links people follow to join
or to choose a new password, which are public and need the link's token.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Response, status

from calendar_sync.application.administration import (
    AcceptInvitation,
    AdministratorRequired,
    ChangeRole,
    ChangeUserState,
    CheckInvitation,
    CheckPasswordReset,
    DeleteUser,
    DeletionResult,
    InviteUser,
    IssuePasswordReset,
    LinkUnusable,
    ListInvitations,
    ListUsers,
    RegistrationClosed,
    RegistrationStatus,
    ResetPassword,
    RevokeInvitation,
    SetRegistrationPolicy,
    ShowRegistration,
    UserDeletionInterrupted,
    UserNotFound,
    YourOwnState,
)
from calendar_sync.application.errors import EmailTaken, PasswordPolicyViolation
from calendar_sync.application.ports import IssuedLink
from calendar_sync.domain.access import (
    InvalidEmail,
    LastAdministrator,
    OnlyMeNeedsOneUser,
    RegistrationPolicy,
    Role,
    User,
    UserId,
    UserState,
)
from calendar_sync.interfaces.api.dependencies import (
    Identity,
    administrator,
    app_services,
    set_session_cookie,
)
from calendar_sync.interfaces.api.problems import problem_from
from calendar_sync.interfaces.api.routes.session import signed_in
from calendar_sync.interfaces.api.schemas import (
    AcceptInvitationRequest,
    IssuedLinkResponse,
    LinkRequest,
    LinkStatusResponse,
    PendingInvitationResponse,
    RegistrationRequest,
    RegistrationResponse,
    ResetPasswordRequest,
    RoleRequest,
    SessionResponse,
    UserDeletionResponse,
    UserResponse,
    UserStateRequest,
)


class Administration(Protocol):
    @property
    def show_registration(self) -> ShowRegistration: ...
    @property
    def set_registration_policy(self) -> SetRegistrationPolicy: ...
    @property
    def invite_user(self) -> InviteUser: ...
    @property
    def list_invitations(self) -> ListInvitations: ...
    @property
    def revoke_invitation(self) -> RevokeInvitation: ...
    @property
    def check_invitation(self) -> CheckInvitation: ...
    @property
    def accept_invitation(self) -> AcceptInvitation: ...
    @property
    def issue_password_reset(self) -> IssuePasswordReset: ...
    @property
    def check_password_reset(self) -> CheckPasswordReset: ...
    @property
    def reset_password(self) -> ResetPassword: ...
    @property
    def list_users(self) -> ListUsers: ...
    @property
    def change_role(self) -> ChangeRole: ...
    @property
    def change_user_state(self) -> ChangeUserState: ...
    @property
    def delete_user(self) -> DeleteUser: ...


class AdministrationServices(Protocol):
    @property
    def administration(self) -> Administration: ...
    @property
    def identity(self) -> Identity: ...
    @property
    def secure_cookies(self) -> bool: ...


Services = Annotated[AdministrationServices, Depends(app_services)]
Administrator = Annotated[UserId, Depends(administrator)]
router = APIRouter()
NO_STORE = {"Cache-Control": "no-store"}


@router.get("/api/v1/registration", response_model=RegistrationResponse)
def registration(services: Services, actor: Administrator) -> RegistrationResponse:
    return _registration(services.administration.show_registration.execute(actor))


@router.put("/api/v1/registration", response_model=RegistrationResponse)
def set_registration(
    payload: RegistrationRequest, services: Services, actor: Administrator
) -> RegistrationResponse:
    policy = RegistrationPolicy(payload.policy)
    try:
        changed = services.administration.set_registration_policy.execute(actor, policy)
    except OnlyMeNeedsOneUser as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    return _registration(changed)


@router.get("/api/v1/invitations", response_model=list[PendingInvitationResponse])
def invitations(services: Services, actor: Administrator) -> list[PendingInvitationResponse]:
    return [
        PendingInvitationResponse(
            id=pending.id,
            created_at=pending.created_at.isoformat(),
            expires_at=pending.expires_at.isoformat(),
        )
        for pending in services.administration.list_invitations.execute(actor)
    ]


@router.post(
    "/api/v1/invitations", response_model=IssuedLinkResponse, status_code=status.HTTP_201_CREATED
)
def invite(services: Services, actor: Administrator, response: Response) -> IssuedLinkResponse:
    response.headers.update(NO_STORE)
    try:
        return _link(services.administration.invite_user.execute(actor))
    except RegistrationClosed as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error


@router.delete("/api/v1/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(invitation_id: str, services: Services, actor: Administrator) -> None:
    try:
        services.administration.revoke_invitation.execute(actor, invitation_id)
    except LinkUnusable as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error


@router.post("/api/v1/invitations/check", response_model=LinkStatusResponse)
def check_invitation(payload: LinkRequest, services: Services) -> LinkStatusResponse:
    return LinkStatusResponse(
        usable=services.administration.check_invitation.execute(payload.token)
    )


@router.post("/api/v1/invitations/accept", response_model=SessionResponse)
def accept_invitation(
    payload: AcceptInvitationRequest, services: Services, response: Response
) -> SessionResponse:
    accept = services.administration.accept_invitation
    try:
        session = accept.execute(payload.token, payload.email, payload.password)
    except LinkUnusable as error:
        raise problem_from(status.HTTP_410_GONE, error) from error
    except (InvalidEmail, PasswordPolicyViolation) as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    except EmailTaken as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    set_session_cookie(response, session.token, services.secure_cookies)
    return signed_in(services.identity.users.get(session.user_id))


@router.post("/api/v1/password-resets/check", response_model=LinkStatusResponse)
def check_password_reset(payload: LinkRequest, services: Services) -> LinkStatusResponse:
    return LinkStatusResponse(
        usable=services.administration.check_password_reset.execute(payload.token)
    )


@router.post("/api/v1/password-resets", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(payload: ResetPasswordRequest, services: Services) -> None:
    try:
        services.administration.reset_password.execute(payload.token, payload.password)
    except LinkUnusable as error:
        raise problem_from(status.HTTP_410_GONE, error) from error
    except PasswordPolicyViolation as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error


@router.get("/api/v1/users", response_model=list[UserResponse])
def users(services: Services, actor: Administrator) -> list[UserResponse]:
    return [_user(user) for user in services.administration.list_users.execute(actor)]


@router.put("/api/v1/users/{user_id}/role", response_model=UserResponse)
def change_role(
    user_id: str, payload: RoleRequest, services: Services, actor: Administrator
) -> UserResponse:
    try:
        changed = services.administration.change_role.execute(
            actor, UserId(user_id), Role(payload.role)
        )
    except UserNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except LastAdministrator as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    return _user(changed)


@router.put("/api/v1/users/{user_id}/state", response_model=UserResponse)
def change_state(
    user_id: str, payload: UserStateRequest, services: Services, actor: Administrator
) -> UserResponse:
    try:
        changed = services.administration.change_user_state.execute(
            actor, UserId(user_id), UserState(payload.state)
        )
    except UserNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except (LastAdministrator, YourOwnState) as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    return _user(changed)


@router.post(
    "/api/v1/users/{user_id}/password-reset-links",
    response_model=IssuedLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
def issue_password_reset(
    user_id: str, services: Services, actor: Administrator, response: Response
) -> IssuedLinkResponse:
    response.headers.update(NO_STORE)
    try:
        return _link(services.administration.issue_password_reset.execute(actor, UserId(user_id)))
    except UserNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error


@router.delete("/api/v1/users/{user_id}", response_model=UserDeletionResponse)
async def delete_user(
    user_id: str, services: Services, actor: Administrator
) -> UserDeletionResponse:
    """Delete another User and every record they own; their projections are deleted."""
    delete = services.administration.delete_user
    try:
        # Rule Removal waits on the calendar provider, so it runs off the event loop.
        result = await asyncio.to_thread(delete.execute, actor, UserId(user_id))
    except UserNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error
    except (LastAdministrator, UserDeletionInterrupted) as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except AdministratorRequired as error:
        raise problem_from(status.HTTP_403_FORBIDDEN, error) from error
    return deletion_response(result)


def deletion_response(result: DeletionResult) -> UserDeletionResponse:
    return UserDeletionResponse(
        rules=result.rules, deleted=result.deleted, detached=result.detached, left=result.left
    )


def _registration(status_: RegistrationStatus) -> RegistrationResponse:
    return RegistrationResponse(
        policy=status_.policy.value, only_me_available=status_.only_me_available
    )


def _link(link: IssuedLink) -> IssuedLinkResponse:
    return IssuedLinkResponse(id=link.id, token=link.token, expires_at=link.expires_at.isoformat())


def _user(user: User) -> UserResponse:
    return UserResponse(
        id=user.id.value,
        email=user.email,
        role=user.role.value,
        state=user.state.value,
        created_at=user.created_at.isoformat(),
        last_sign_in_at=user.last_sign_in_at.isoformat() if user.last_sign_in_at else None,
    )
