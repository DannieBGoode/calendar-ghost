"""People and Who can join: the Registration Policy, Invitations, roles, disabling, and deletion.

Every route here is an Installation Administrator's, except the two links people follow to join
or to choose a new password, which are public and need the link's token.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Query, Request, Response, status

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
    LinkAttemptsThrottled,
    LinkUnusable,
    ListInvitations,
    RegistrationClosed,
    RegistrationStatus,
    ResetPassword,
    RevokeInvitation,
    SetRegistrationPolicy,
    ShowRegistration,
    UserDeletionInterrupted,
    UserNotFound,
    YourOwnDeletion,
    YourOwnResetLink,
    YourOwnState,
)
from calendar_sync.application.errors import (
    EmailTaken,
    IncorrectCredentials,
    PasswordPolicyViolation,
)
from calendar_sync.application.operator_overview import (
    OperatorOverview,
    OverviewQuery,
    UserOverview,
)
from calendar_sync.application.ports import IssuedLink, UserQuery, UserSort
from calendar_sync.application.status import StatusVerdict
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
    current_user,
    set_session_cookie,
)
from calendar_sync.interfaces.api.problems import ApiProblem, problem_from
from calendar_sync.interfaces.api.routes.session import signed_in
from calendar_sync.interfaces.api.schemas import (
    AcceptInvitationRequest,
    IssuedLinkResponse,
    LinkRequest,
    LinkStatusResponse,
    PendingInvitationResponse,
    PeopleQuery,
    PersonResponse,
    RegistrationRequest,
    RegistrationResponse,
    ResetPasswordRequest,
    RoleRequest,
    SessionResponse,
    UserDeletionResponse,
    UserOverviewResponse,
    UserPageResponse,
    UserResponse,
    UserStateRequest,
)
from calendar_sync.interfaces.api.status_payload import resource_use_response, status_response


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
    def change_role(self) -> ChangeRole: ...
    @property
    def change_user_state(self) -> ChangeUserState: ...
    @property
    def delete_user(self) -> DeleteUser: ...


class AdministrationServices(Protocol):
    @property
    def administration(self) -> Administration: ...
    @property
    def operator_overview(self) -> OperatorOverview: ...
    @property
    def identity(self) -> Identity: ...
    @property
    def secure_cookies(self) -> bool: ...
    @property
    def sends_email(self) -> bool: ...


Services = Annotated[AdministrationServices, Depends(app_services)]
Administrator = Annotated[UserId, Depends(administrator)]
SignedIn = Annotated[UserId, Depends(current_user)]
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


def _client(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _throttled(error: LinkAttemptsThrottled) -> ApiProblem:
    throttled = problem_from(status.HTTP_429_TOO_MANY_REQUESTS, error)
    throttled.headers = {"Retry-After": str(error.retry_after)}
    return throttled


@router.post("/api/v1/invitations/check", response_model=LinkStatusResponse)
def check_invitation(
    payload: LinkRequest, request: Request, services: Services
) -> LinkStatusResponse:
    check = services.administration.check_invitation
    try:
        return LinkStatusResponse(usable=check.execute(payload.token, _client(request)))
    except LinkAttemptsThrottled as error:
        raise _throttled(error) from error


@router.post("/api/v1/invitations/accept", response_model=SessionResponse)
def accept_invitation(
    payload: AcceptInvitationRequest, request: Request, services: Services, response: Response
) -> SessionResponse:
    accept = services.administration.accept_invitation
    try:
        session = accept.execute(payload.token, payload.email, payload.password, _client(request))
    except LinkAttemptsThrottled as error:
        raise _throttled(error) from error
    except LinkUnusable as error:
        raise problem_from(status.HTTP_410_GONE, error) from error
    except (InvalidEmail, PasswordPolicyViolation) as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error
    except EmailTaken as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error
    except IncorrectCredentials as error:
        # Joined, but the password was reset before the session started: sign in instead.
        raise problem_from(status.HTTP_401_UNAUTHORIZED, error) from error
    set_session_cookie(response, session.token, services.secure_cookies)
    return signed_in(services.identity.users.get(session.user_id), services.sends_email)


@router.post("/api/v1/password-resets/check", response_model=LinkStatusResponse)
def check_password_reset(
    payload: LinkRequest, request: Request, services: Services
) -> LinkStatusResponse:
    check = services.administration.check_password_reset
    try:
        return LinkStatusResponse(usable=check.execute(payload.token, _client(request)))
    except LinkAttemptsThrottled as error:
        raise _throttled(error) from error


@router.post("/api/v1/password-resets", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(payload: ResetPasswordRequest, request: Request, services: Services) -> None:
    reset = services.administration.reset_password
    try:
        reset.execute(payload.token, payload.password, _client(request))
    except LinkAttemptsThrottled as error:
        raise _throttled(error) from error
    except LinkUnusable as error:
        raise problem_from(status.HTTP_410_GONE, error) from error
    except PasswordPolicyViolation as error:
        raise problem_from(status.HTTP_422_UNPROCESSABLE_CONTENT, error) from error


@router.get("/api/v1/users", response_model=UserPageResponse)
def users(
    services: Services,
    actor: Administrator,
    query: Annotated[PeopleQuery, Query()],
    response: Response,
) -> UserPageResponse:
    """One page of the people here, by part of their email, role, state, and Installation
    Status, each with what the Operator Overview shows about them; never their calendars."""
    response.headers.update(NO_STORE)
    found = services.operator_overview.page(actor, _overview_query(query))
    return UserPageResponse(
        users=[_person(overview) for overview in found.users],
        total=found.total,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/api/v1/users/{user_id}/overview", response_model=UserOverviewResponse)
def user_overview(
    user_id: str, services: Services, actor: SignedIn, response: Response
) -> UserOverviewResponse:
    """What the Operator Overview shows about one User, for an Installation Administrator.
    Anyone else, and an unknown identifier, is answered 404, so nothing is revealed."""
    response.headers.update(NO_STORE)
    try:
        return user_overview_response(services.operator_overview.of(actor, UserId(user_id)))
    except UserNotFound as error:
        raise problem_from(status.HTTP_404_NOT_FOUND, error) from error


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
    except YourOwnResetLink as error:
        raise problem_from(status.HTTP_409_CONFLICT, error) from error


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
    except (LastAdministrator, UserDeletionInterrupted, YourOwnDeletion) as error:
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


def _overview_query(query: PeopleQuery) -> OverviewQuery:
    by_verdict = query.sort == "verdict"
    return OverviewQuery(
        UserQuery(
            search=query.search.strip(),
            role=Role(query.role) if query.role else None,
            state=UserState(query.state) if query.state else None,
            # Within a verdict, people keep the order they joined in.
            sort=UserSort.JOINED if by_verdict else UserSort(query.sort),
            descending=query.order == "desc",
            offset=(query.page - 1) * query.page_size,
            limit=query.page_size,
        ),
        verdict=StatusVerdict(query.verdict) if query.verdict else None,
        by_verdict=by_verdict,
    )


def user_overview_response(overview: UserOverview) -> UserOverviewResponse:
    return UserOverviewResponse(
        user=_user(overview.user),
        status=status_response(overview.status),
        resources=resource_use_response(overview),
    )


def _person(overview: UserOverview) -> PersonResponse:
    status_ = overview.status
    return PersonResponse(
        **_user(overview.user).model_dump(),
        verdict=status_.health.value,
        problems=len(status_.problems),
        last_synced_at=status_.overview.last_synced_at,
        resources=resource_use_response(overview),
    )


def _user(user: User) -> UserResponse:
    return UserResponse(
        id=user.id.value,
        email=user.email,
        role=user.role.value,
        state=user.state.value,
        created_at=user.created_at.isoformat(),
        last_sign_in_at=user.last_sign_in_at.isoformat() if user.last_sign_in_at else None,
    )
