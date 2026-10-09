"""What an Installation Administrator does with Users (ADR 0030): who may join, Invitations,
Password Reset Links, roles, and disabling. None of it shows a User's calendars or events."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from calendar_sync.application.errors import (
    ApplicationError,
    IncorrectPassword,
    RemovalInterrupted,
    RemovalRequiresAuthorization,
    RemovalRequiresProvider,
    RuleNotFound,
    SignInThrottled,
)
from calendar_sync.application.identity import require_password, start_session
from calendar_sync.application.ports import (
    Clock,
    IdGenerator,
    Invitations,
    IssuedLink,
    PasswordHasher,
    PasswordResetLinks,
    PendingInvitation,
    RegistrationSettings,
    Session,
    Sessions,
    SignInThrottle,
    UnitOfWorkFactory,
    UserDirectory,
    UserPage,
    UserQuery,
)
from calendar_sync.application.removal import RemoveSyncRule
from calendar_sync.domain.access import (
    LastAdministrator,
    RegistrationPolicy,
    Role,
    User,
    UserId,
    UserState,
    email_address,
    require_administrator_remains,
)
from calendar_sync.domain.model import ProjectionHandling, SyncRuleId


class AdministratorRequired(ApplicationError):
    """Only an Installation Administrator may do this."""


class UserNotFound(ApplicationError):
    """No such User."""


class RegistrationClosed(ApplicationError):
    """Under Only Me nobody can join, so nobody can be invited."""


class LinkUnusable(ApplicationError):
    """The link was used, revoked, replaced, or has expired, or nobody may join now."""


class YourOwnState(ApplicationError):
    """An Installation Administrator cannot disable themself."""


class LinkAttemptsThrottled(SignInThrottled):
    """Too many unusable links from this client; the Web UI says what it says for sign-ins."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(retry_after)
        self.args = (f"too many unusable links; try again in {self.retry_after} seconds",)


@dataclass(frozen=True, slots=True)
class LinkAttempts:
    """Unusable Invitation and Password Reset Links tried from one client address, counted as
    failed sign-ins are, so nobody can try tokens without end. A link is checked before any
    password is hashed, so an unusable one costs the installation no hashing."""

    throttle: SignInThrottle

    def usable(self, client: str, check: Callable[[], bool]) -> bool:
        """Whether `check` finds the link usable; raises LinkAttemptsThrottled first when the
        client has tried too many unusable links lately."""
        keys = (f"client:{client}",)
        wait = self.throttle.wait(keys)
        if wait > 0:
            raise LinkAttemptsThrottled(wait)
        usable = check()
        if not usable:
            self.throttle.failed(keys)
        return usable


def require_administrator(users: UserDirectory, actor: UserId) -> User:
    user = users.get(actor)
    if user is None or not user.administers or user.state is not UserState.ACTIVE:
        raise AdministratorRequired("only an Installation Administrator may do this")
    return user


def _existing(users: UserDirectory, user_id: UserId) -> User:
    user = users.get(user_id)
    if user is None:
        raise UserNotFound(f"user {user_id.value} does not exist")
    return user


@dataclass(frozen=True, slots=True)
class RegistrationStatus:
    policy: RegistrationPolicy
    only_me_available: bool
    """Whether Only Me may be chosen now: only while no other User exists."""


@dataclass(slots=True)
class ShowRegistration:
    users: UserDirectory
    settings: RegistrationSettings

    def execute(self, actor: UserId) -> RegistrationStatus:
        require_administrator(self.users, actor)
        return RegistrationStatus(self.settings.policy(), self.users.count() == 1)


@dataclass(slots=True)
class SetRegistrationPolicy:
    users: UserDirectory
    settings: RegistrationSettings

    def execute(self, actor: UserId, policy: RegistrationPolicy) -> RegistrationStatus:
        require_administrator(self.users, actor)
        # Raises OnlyMeNeedsOneUser, counting Users in one step with the change.
        self.settings.set_policy(policy)
        return RegistrationStatus(policy, self.users.count() == 1)


@dataclass(slots=True)
class InviteUser:
    """Issue an Invitation; the administrator passes its link on themself."""

    users: UserDirectory
    settings: RegistrationSettings
    invitations: Invitations
    clock: Clock

    def execute(self, actor: UserId) -> IssuedLink:
        require_administrator(self.users, actor)
        if not self.settings.policy().lets_people_join:
            raise RegistrationClosed("choose Invitation Only before inviting anyone")
        return self.invitations.issue(actor, self.clock.now())


@dataclass(slots=True)
class ListInvitations:
    users: UserDirectory
    invitations: Invitations
    clock: Clock

    def execute(self, actor: UserId) -> Sequence[PendingInvitation]:
        require_administrator(self.users, actor)
        return self.invitations.pending(self.clock.now())


@dataclass(slots=True)
class RevokeInvitation:
    users: UserDirectory
    invitations: Invitations
    clock: Clock

    def execute(self, actor: UserId, invitation_id: str) -> None:
        require_administrator(self.users, actor)
        if not self.invitations.revoke(invitation_id, self.clock.now()):
            raise LinkUnusable("this invitation was already used, revoked, or has expired")


def _invitation_usable(
    settings: RegistrationSettings, invitations: Invitations, token: str, at: datetime
) -> bool:
    return settings.policy().lets_people_join and invitations.usable(token, at)


@dataclass(slots=True)
class CheckInvitation:
    """Whether an invitation link can still be used, before its form is filled in."""

    settings: RegistrationSettings
    invitations: Invitations
    clock: Clock
    attempts: LinkAttempts

    def execute(self, token: str, client: str) -> bool:
        now = self.clock.now()
        return self.attempts.usable(
            client, lambda: _invitation_usable(self.settings, self.invitations, token, now)
        )


@dataclass(slots=True)
class AcceptInvitation:
    """Become a User through an Invitation, choosing one's own email and password."""

    users: UserDirectory
    settings: RegistrationSettings
    invitations: Invitations
    passwords: PasswordHasher
    sessions: Sessions
    ids: IdGenerator
    clock: Clock
    attempts: LinkAttempts

    def execute(self, token: str, email: str, password: str, client: str) -> Session:
        now = self.clock.now()
        user = User(UserId(self.ids.new()), email_address(email), Role.USER, UserState.ACTIVE, now)
        require_password(password)
        # Checked before hashing, which is slow on purpose; using it checks again.
        usable = self.attempts.usable(
            client, lambda: _invitation_usable(self.settings, self.invitations, token, now)
        )
        if not usable:
            raise LinkUnusable("this invitation was already used, revoked, or has expired")
        hashed = self.passwords.hash(password)
        joining = self.settings.policy().lets_people_join
        if not joining or not self.invitations.accept(token, user, hashed, now):
            raise LinkUnusable("this invitation was already used, revoked, or has expired")
        session = start_session(self.sessions, user.id, hashed)
        self.users.record_sign_in(user.id, now)
        return session


@dataclass(slots=True)
class IssuePasswordReset:
    """Issue a Password Reset Link for a User; the administrator never sees the password."""

    users: UserDirectory
    links: PasswordResetLinks
    clock: Clock

    def execute(self, actor: UserId, user_id: UserId) -> IssuedLink:
        require_administrator(self.users, actor)
        _existing(self.users, user_id)
        return self.links.issue(user_id, actor, self.clock.now())


@dataclass(slots=True)
class CheckPasswordReset:
    links: PasswordResetLinks
    clock: Clock
    attempts: LinkAttempts

    def execute(self, token: str, client: str) -> bool:
        now = self.clock.now()
        return self.attempts.usable(client, lambda: self.links.owner(token, now) is not None)


@dataclass(slots=True)
class ResetPassword:
    """Choose a new password through a Password Reset Link; every session of the User ends."""

    links: PasswordResetLinks
    passwords: PasswordHasher
    sessions: Sessions
    clock: Clock
    attempts: LinkAttempts

    def execute(self, token: str, password: str, client: str) -> None:
        now = self.clock.now()
        require_password(password)
        # Checked before hashing, which is slow on purpose; using it checks again.
        if not self.attempts.usable(client, lambda: self.links.owner(token, now) is not None):
            raise LinkUnusable("this link was already used, replaced, or has expired")
        owner = self.links.reset(token, self.passwords.hash(password), now)
        if owner is None:
            raise LinkUnusable("this link was already used, replaced, or has expired")
        self.sessions.end_all(owner)


@dataclass(slots=True)
class ListUsers:
    users: UserDirectory

    def execute(self, actor: UserId, query: UserQuery) -> UserPage:
        require_administrator(self.users, actor)
        return self.users.find(query)


@dataclass(slots=True)
class ChangeRole:
    """Grant or revoke the Installation Administrator role; the last holder keeps it."""

    users: UserDirectory

    def execute(self, actor: UserId, user_id: UserId, role: Role) -> User:
        require_administrator(self.users, actor)
        _existing(self.users, user_id)
        # Raises LastAdministrator in the same step as the write, so two administrators
        # demoting each other at once cannot both succeed.
        self.users.set_role(user_id, role)
        return _existing(self.users, user_id)


@dataclass(slots=True)
class ChangeUserState:
    """Disable a User, which signs them out and holds their rules, or enable them again."""

    users: UserDirectory
    sessions: Sessions

    def execute(self, actor: UserId, user_id: UserId, state: UserState) -> User:
        require_administrator(self.users, actor)
        _existing(self.users, user_id)
        if state is UserState.DISABLED and user_id == actor:
            raise YourOwnState("you cannot disable yourself")
        # Guarded like ChangeRole: the last active administrator is never disabled.
        self.users.set_state(user_id, state)
        if state is UserState.DISABLED:
            self.sessions.end_all(user_id)
        return _existing(self.users, user_id)


class UserDeletionInterrupted(ApplicationError):
    """A rule's removal stopped; the User is kept, with what is left, until it is retried."""

    def __init__(self, removed: int, remaining: int) -> None:
        self.removed = removed
        self.remaining = remaining
        super().__init__(
            f"removing the User's rules stopped after {removed}; {remaining} remain. Try again"
        )


@dataclass(frozen=True, slots=True)
class OwnedRules:
    """What deleting a User needs of their own rules: that User's units and Rule Removal."""

    unit_of_work: UnitOfWorkFactory
    removal: RemoveSyncRule


@dataclass(frozen=True, slots=True)
class DeletionResult:
    rules: int
    deleted: int
    detached: int
    left: int
    """Rules whose projections nothing could delete, such as a disconnected destination's; their
    projections stay where they are, no longer managed, as deleting a Disconnected Account
    leaves them."""


@dataclass(slots=True)
class DeleteUser:
    """An Installation Administrator deletes another User, deleting their projections.

    The User is disabled first, so they cannot sign in and the scheduler holds their rules while
    each rule is removed; then the User and every record they own go from the live database.
    Disabling is guarded like ChangeUserState, so the last active administrator is refused
    before anything is removed, even when another administrator is demoted at the same moment.
    """

    users: UserDirectory
    sessions: Sessions
    owned: Callable[[UserId], OwnedRules]

    def execute(self, actor: UserId, user_id: UserId) -> DeletionResult:
        require_administrator(self.users, actor)
        user = _existing(self.users, user_id)
        self.users.set_state(user.id, UserState.DISABLED)
        self.sessions.end_all(user.id)
        result = _remove_rules(
            self.owned(user.id), ProjectionHandling.DELETE, keep_unreachable=True
        )
        self.users.delete(user.id)
        return result


@dataclass(frozen=True, slots=True)
class OwnAccountDeletion:
    """Whether a User may delete themself now, and what follows if they do."""

    needs_another_administrator: bool
    """The User is the last Installation Administrator and someone else remains."""
    last_user: bool
    """Nobody would remain, so the installation returns to setup."""


def _require_may_leave(users: UserDirectory, user: User) -> None:
    """The last Installation Administrator may leave only when nobody else remains."""
    require_administrator_remains(users.list(), user.id, None)


@dataclass(slots=True)
class ShowOwnAccountDeletion:
    users: UserDirectory

    def execute(self, user_id: UserId) -> OwnAccountDeletion:
        user = _existing(self.users, user_id)
        try:
            _require_may_leave(self.users, user)
        except LastAdministrator:
            return OwnAccountDeletion(needs_another_administrator=True, last_user=False)
        return OwnAccountDeletion(
            needs_another_administrator=False, last_user=self.users.count() == 1
        )


@dataclass(slots=True)
class DeleteOwnAccount:
    """A User deletes themself, choosing whether their projections are deleted or kept.

    When nobody else remains, the installation returns to setup: the Registration Policy goes back
    to Only Me and every pending Invitation is revoked first, so nobody joins an installation
    without an administrator.

    Whether the User may leave is checked before Rule Removal, for a clear refusal, and again by
    the final deletion in one step with it. When another administrator is demoted, disabled, or
    leaves meanwhile, that deletion is refused, keeping an administrator: the User stays, with
    their rules already removed, and may try again. When everyone else left meanwhile, the
    installation returns to setup after the deletion instead.
    """

    users: UserDirectory
    passwords: PasswordHasher
    sessions: Sessions
    owned: Callable[[UserId], OwnedRules]
    settings: RegistrationSettings
    invitations: Invitations
    clock: Clock

    def execute(
        self, user_id: UserId, password: str, handling: ProjectionHandling
    ) -> DeletionResult:
        user = _existing(self.users, user_id)
        hashed = self.users.password_hash(user_id)
        if hashed is None or not self.passwords.verify(password, hashed):
            raise IncorrectPassword("that is not your current password")
        _require_may_leave(self.users, user)
        if self.users.count() == 1:
            self._return_to_setup()
        result = _remove_rules(self.owned(user.id), handling, keep_unreachable=False)
        self.users.delete(user.id)
        if self.users.count() == 0:
            self._return_to_setup()
        return result

    def _return_to_setup(self) -> None:
        self.settings.set_policy(RegistrationPolicy.ONLY_ME)
        self.invitations.revoke_all(self.clock.now())


def _remove_rules(
    owned: OwnedRules, handling: ProjectionHandling, *, keep_unreachable: bool
) -> DeletionResult:
    """Run Rule Removal for every rule. A rule whose projections cannot be deleted keeps them
    when `keep_unreachable`; otherwise its error is raised before anything is removed."""
    with owned.unit_of_work() as uow:
        rule_ids = tuple(rule.id for rule in uow.rules.list())
    plan = {
        rule_id: _handling(owned.removal, rule_id, handling, keep_unreachable)
        for rule_id in rule_ids
    }
    deleted = detached = 0
    for removed, (rule_id, chosen) in enumerate(plan.items()):
        try:
            result = owned.removal.execute(rule_id, chosen)
        except RuleNotFound:
            continue
        except RemovalInterrupted as error:
            raise UserDeletionInterrupted(removed, len(plan) - removed) from error
        deleted += result.deleted
        detached += result.detached
    left = sum(chosen is not handling for chosen in plan.values())
    return DeletionResult(len(plan), deleted, detached, left)


def _handling(
    removal: RemoveSyncRule,
    rule_id: SyncRuleId,
    handling: ProjectionHandling,
    keep_unreachable: bool,
) -> ProjectionHandling:
    try:
        removal.check(rule_id, handling)
    except (RemovalRequiresAuthorization, RemovalRequiresProvider):
        if not keep_unreachable:
            raise
        return ProjectionHandling.DETACH
    return handling
