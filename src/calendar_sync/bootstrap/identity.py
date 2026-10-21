from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from calendar_sync.application.identity.administration import (
    AcceptInvitation,
    ChangeRole,
    ChangeUserState,
    CheckInvitation,
    CheckPasswordReset,
    DeleteOwnAccount,
    DeleteUser,
    InviteUser,
    IssuePasswordReset,
    LinkAttempts,
    ListInvitations,
    OwnedRules,
    ResetPassword,
    RevokeInvitation,
    SetRegistrationPolicy,
    ShowOwnAccountDeletion,
    ShowRegistration,
)
from calendar_sync.application.identity.ports import (
    Sessions,
    UserDirectory,
)
from calendar_sync.application.identity.sign_in import (
    ChangeOwnPassword,
    SetInstantSync,
    SetNotificationEmail,
    SetOwnEmail,
    SetUpInstallation,
    SignIn,
)
from calendar_sync.bootstrap.shared import UserServices
from calendar_sync.domain.access import UserId

if TYPE_CHECKING:
    from calendar_sync.bootstrap.container import Adapters


@dataclass(frozen=True, slots=True)
class IdentityServices:
    """Who is signed in: setup, sign-in, sessions, and a User's own credentials."""

    users: UserDirectory
    sessions: Sessions
    set_up: SetUpInstallation
    sign_in: SignIn
    set_own_email: SetOwnEmail
    set_notification_email: SetNotificationEmail
    set_instant_sync: SetInstantSync
    change_own_password: ChangeOwnPassword


@dataclass(frozen=True, slots=True)
class AdministrationServices:
    """What Installation Administrators do with Users, and the links people use to join or to
    choose a new password."""

    show_registration: ShowRegistration
    set_registration_policy: SetRegistrationPolicy
    invite_user: InviteUser
    list_invitations: ListInvitations
    revoke_invitation: RevokeInvitation
    check_invitation: CheckInvitation
    accept_invitation: AcceptInvitation
    issue_password_reset: IssuePasswordReset
    check_password_reset: CheckPasswordReset
    reset_password: ResetPassword
    change_role: ChangeRole
    change_user_state: ChangeUserState
    delete_user: DeleteUser
    delete_own_account: DeleteOwnAccount
    show_own_account_deletion: ShowOwnAccountDeletion


def _owned_rules(owner: UserId, adapters: Adapters, services: UserServices) -> OwnedRules:
    """What deleting `owner` needs: their units, Rule Removal, and stopping their watches."""
    upkeep = services.watch_upkeep
    return OwnedRules(
        adapters.unit_of_work(owner),
        services.remove_sync_rule,
        upkeep.stop_all if upkeep is not None else _no_watches,
    )


def _no_watches() -> None:
    """Where no provider can watch, nothing is watched to stop."""


def _identity(adapters: Adapters) -> IdentityServices:
    users, passwords, sessions = adapters.users, adapters.passwords, adapters.sessions
    return IdentityServices(
        users=users,
        sessions=sessions,
        set_up=SetUpInstallation(users, passwords, sessions, adapters.ids, adapters.clock),
        sign_in=SignIn(users, passwords, sessions, adapters.sign_in_throttle, adapters.clock),
        set_own_email=SetOwnEmail(users, passwords, adapters.credential_changes),
        set_notification_email=SetNotificationEmail(users),
        set_instant_sync=SetInstantSync(users),
        change_own_password=ChangeOwnPassword(adapters.credential_changes, passwords),
    )


def _administration(
    adapters: Adapters, owned: Callable[[UserId], OwnedRules]
) -> AdministrationServices:
    users, clock, sessions = adapters.users, adapters.clock, adapters.sessions
    settings, invitations, resets = (
        adapters.registration,
        adapters.invitations,
        adapters.password_resets,
    )
    passwords = adapters.passwords
    attempts = LinkAttempts(adapters.link_throttle)
    return AdministrationServices(
        show_registration=ShowRegistration(users, settings),
        set_registration_policy=SetRegistrationPolicy(users, settings),
        invite_user=InviteUser(users, settings, invitations, clock),
        list_invitations=ListInvitations(users, invitations, clock),
        revoke_invitation=RevokeInvitation(users, invitations, clock),
        check_invitation=CheckInvitation(settings, invitations, clock, attempts),
        accept_invitation=AcceptInvitation(
            users, settings, invitations, passwords, sessions, adapters.ids, clock, attempts
        ),
        issue_password_reset=IssuePasswordReset(users, resets, clock),
        check_password_reset=CheckPasswordReset(resets, clock, adapters.reset_admission),
        reset_password=ResetPassword(resets, passwords, clock, adapters.reset_admission),
        change_role=ChangeRole(users),
        change_user_state=ChangeUserState(users, sessions),
        delete_user=DeleteUser(users, sessions, owned),
        delete_own_account=DeleteOwnAccount(users, passwords, sessions, owned, settings, clock),
        show_own_account_deletion=ShowOwnAccountDeletion(users),
    )
