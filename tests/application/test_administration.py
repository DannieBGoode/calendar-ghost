"""Registration Policy, Invitations, Password Reset Links, roles, and disabling (ADR 0030)."""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

import pytest

from calendar_sync.application.administration import (
    AcceptInvitation,
    AdministratorRequired,
    ChangeRole,
    ChangeUserState,
    CheckInvitation,
    CheckPasswordReset,
    InviteUser,
    IssuePasswordReset,
    LinkAttempts,
    LinkAttemptsThrottled,
    LinkUnusable,
    ListInvitations,
    ListUsers,
    RegistrationClosed,
    RegistrationStatus,
    ResetPassword,
    RevokeInvitation,
    SetRegistrationPolicy,
    ShowRegistration,
    UserNotFound,
    YourOwnResetLink,
    YourOwnState,
)
from calendar_sync.application.errors import EmailTaken, IncorrectCredentials
from calendar_sync.application.identity import SignIn
from calendar_sync.application.ports import UserPage, UserQuery
from calendar_sync.domain.access import (
    LastAdministrator,
    OnlyMeNeedsOneUser,
    RegistrationPolicy,
    Role,
    User,
    UserId,
    UserState,
)
from tests.helpers import NOW
from tests.identity_fakes import (
    CountingThrottle,
    MemoryInvitations,
    MemoryRegistration,
    MemoryResetLinks,
    MemorySessions,
    MemoryUsers,
    PlainPasswords,
)

PASSWORD = "correct horse battery staple"
CLIENT = "192.0.2.10"
ADMIN = User(
    UserId("admin"), "admin@example.test", Role.INSTALLATION_ADMINISTRATOR, UserState.ACTIVE, NOW
)
MEMBER = User(UserId("member"), "member@example.test", Role.USER, UserState.ACTIVE, NOW)


@dataclass
class MovableClock:
    moment: datetime = NOW

    def now(self) -> datetime:
        return self.moment


class SequentialIds:
    def __init__(self) -> None:
        self.issued = 0

    def new(self) -> str:
        self.issued += 1
        return f"joined-{self.issued}"


@dataclass
class Installation:
    users: MemoryUsers
    registration: MemoryRegistration
    invitations: MemoryInvitations
    resets: MemoryResetLinks
    sessions: MemorySessions
    clock: MovableClock
    attempts: LinkAttempts = field(default_factory=lambda: LinkAttempts(CountingThrottle()))

    def accept(self, passwords: PlainPasswords | None = None) -> AcceptInvitation:
        return AcceptInvitation(
            self.users,
            self.registration,
            self.invitations,
            passwords or PlainPasswords(),
            self.sessions,
            SequentialIds(),
            self.clock,
            self.attempts,
        )

    def check_invitation(self) -> CheckInvitation:
        return CheckInvitation(self.registration, self.invitations, self.clock, self.attempts)

    def reset(self, passwords: PlainPasswords | None = None) -> ResetPassword:
        return ResetPassword(
            self.resets, passwords or PlainPasswords(), self.sessions, self.clock, self.attempts
        )

    def invite(self) -> InviteUser:
        return InviteUser(self.users, self.registration, self.invitations, self.clock)

    def sign_in(self, email: str, password: str = PASSWORD) -> UserId:
        sign_in = SignIn(
            self.users, PlainPasswords(), self.sessions, CountingThrottle(), self.clock
        )
        return sign_in.execute(email, password, "client").user_id


def _installation(*others: User) -> Installation:
    users = MemoryUsers()
    for user in (ADMIN, *others):
        users.add(user, f"hashed:{PASSWORD}")
    registration = MemoryRegistration(users)
    return Installation(
        users,
        registration,
        MemoryInvitations(users, registration),
        MemoryResetLinks(users),
        MemorySessions(NOW, users),
        MovableClock(),
    )


# Registration Policy


def test_a_new_installation_lets_nobody_join_and_offers_only_me() -> None:
    installation = _installation()

    status = ShowRegistration(installation.users, installation.registration).execute(ADMIN.id)

    assert status == RegistrationStatus(RegistrationPolicy.ONLY_ME, only_me_available=True)


def test_only_me_is_chosen_again_only_while_no_other_user_exists() -> None:
    installation = _installation()
    set_policy = SetRegistrationPolicy(installation.users, installation.registration)
    set_policy.execute(ADMIN.id, RegistrationPolicy.INVITATION_ONLY)
    installation.users.add(MEMBER, f"hashed:{PASSWORD}")

    with pytest.raises(OnlyMeNeedsOneUser):
        set_policy.execute(ADMIN.id, RegistrationPolicy.ONLY_ME)
    installation.users.delete(MEMBER.id)
    set_policy.execute(ADMIN.id, RegistrationPolicy.ONLY_ME)

    assert installation.registration.current is RegistrationPolicy.ONLY_ME


def test_an_invitation_accepted_while_only_me_is_chosen_is_refused() -> None:
    installation = _installation()
    installation.registration.current = RegistrationPolicy.INVITATION_ONLY
    link = installation.invite().execute(ADMIN.id)
    accept = installation.accept()
    set_policy = SetRegistrationPolicy(installation.users, installation.registration)
    use = installation.invitations.accept

    def chosen_meanwhile(token: str, user: User, password_hash: str, at: datetime) -> bool:
        # The administrator chooses Only Me after every check, just before the link is used.
        set_policy.execute(ADMIN.id, RegistrationPolicy.ONLY_ME)
        return use(token, user, password_hash, at)

    installation.invitations.accept = chosen_meanwhile  # type: ignore[method-assign]

    with pytest.raises(LinkUnusable):
        accept.execute(link.token, "new@example.test", PASSWORD, CLIENT)
    assert installation.users.count() == 1


def test_only_me_chosen_while_an_invitation_is_accepted_is_refused() -> None:
    installation = _installation()
    installation.registration.current = RegistrationPolicy.INVITATION_ONLY
    link = installation.invite().execute(ADMIN.id)
    accept = installation.accept()
    change = installation.registration.set_policy

    def joined_meanwhile(policy: RegistrationPolicy) -> None:
        # The person joins after every check of the administrator's request, just before the
        # policy changes.
        accept.execute(link.token, "new@example.test", PASSWORD, CLIENT)
        change(policy)

    installation.registration.set_policy = joined_meanwhile  # type: ignore[method-assign]

    with pytest.raises(OnlyMeNeedsOneUser):
        SetRegistrationPolicy(installation.users, installation.registration).execute(
            ADMIN.id, RegistrationPolicy.ONLY_ME
        )
    assert installation.registration.current is RegistrationPolicy.INVITATION_ONLY
    assert installation.users.count() == 2


def test_only_an_administrator_sees_or_changes_the_registration_policy() -> None:
    installation = _installation(MEMBER)

    with pytest.raises(AdministratorRequired):
        ShowRegistration(installation.users, installation.registration).execute(MEMBER.id)
    with pytest.raises(AdministratorRequired):
        SetRegistrationPolicy(installation.users, installation.registration).execute(
            MEMBER.id, RegistrationPolicy.INVITATION_ONLY
        )


# Invitations


def test_under_only_me_nobody_can_be_invited() -> None:
    installation = _installation()

    with pytest.raises(RegistrationClosed):
        installation.invite().execute(ADMIN.id)


def test_an_invited_person_chooses_their_own_email_and_password_and_is_signed_in() -> None:
    installation = _installation()
    installation.registration.current = RegistrationPolicy.INVITATION_ONLY
    link = installation.invite().execute(ADMIN.id)

    session = installation.accept().execute(link.token, " New@Example.test ", PASSWORD, CLIENT)

    joined = installation.users.get(session.user_id)
    assert joined is not None
    assert (joined.email, joined.role, joined.state) == (
        "new@example.test",
        Role.USER,
        UserState.ACTIVE,
    )
    assert link.expires_at == NOW + timedelta(days=7)
    assert installation.sign_in("new@example.test") == joined.id


def test_a_password_reset_right_after_joining_leaves_no_session_for_the_chosen_password() -> None:
    installation = _installation()
    installation.registration.current = RegistrationPolicy.INVITATION_ONLY
    link = installation.invite().execute(ADMIN.id)
    accept = installation.invitations.accept

    def accepted_then_reset(token: str, user: User, password_hash: str, at: datetime) -> bool:
        used = accept(token, user, password_hash, at)
        installation.users.set_password_hash(user.id, "hashed:reset meanwhile")
        return used

    installation.invitations.accept = accepted_then_reset  # type: ignore[method-assign]

    with pytest.raises(IncorrectCredentials):
        installation.accept().execute(link.token, "new@example.test", PASSWORD, CLIENT)
    assert installation.sessions.sessions == {}


def test_an_invitation_is_used_once() -> None:
    installation = _installation()
    installation.registration.current = RegistrationPolicy.INVITATION_ONLY
    link = installation.invite().execute(ADMIN.id)
    installation.accept().execute(link.token, "new@example.test", PASSWORD, CLIENT)

    with pytest.raises(LinkUnusable):
        installation.accept().execute(link.token, "again@example.test", PASSWORD, CLIENT)
    assert installation.users.count() == 2


def test_an_invitation_expires_after_seven_days() -> None:
    installation = _installation()
    installation.registration.current = RegistrationPolicy.INVITATION_ONLY
    link = installation.invite().execute(ADMIN.id)
    check = installation.check_invitation()
    installation.clock.moment = NOW + timedelta(days=7) - timedelta(seconds=1)
    assert check.execute(link.token, CLIENT)

    installation.clock.moment = NOW + timedelta(days=7)
    assert not check.execute(link.token, CLIENT)
    with pytest.raises(LinkUnusable):
        installation.accept().execute(link.token, "new@example.test", PASSWORD, CLIENT)


def test_returning_to_only_me_stops_pending_invitations() -> None:
    installation = _installation()
    installation.registration.current = RegistrationPolicy.INVITATION_ONLY
    link = installation.invite().execute(ADMIN.id)
    installation.registration.current = RegistrationPolicy.ONLY_ME
    check = installation.check_invitation()

    assert not check.execute(link.token, CLIENT)
    with pytest.raises(LinkUnusable):
        installation.accept().execute(link.token, "new@example.test", PASSWORD, CLIENT)


def test_an_invitation_for_an_email_already_used_creates_no_user_and_stays_usable() -> None:
    installation = _installation()
    installation.registration.current = RegistrationPolicy.INVITATION_ONLY
    link = installation.invite().execute(ADMIN.id)

    with pytest.raises(EmailTaken):
        installation.accept().execute(link.token, "admin@example.test", PASSWORD, CLIENT)
    assert installation.invitations.usable(link.token, NOW)


def test_pending_invitations_are_listed_and_revoked_by_an_administrator() -> None:
    installation = _installation(MEMBER)
    installation.registration.current = RegistrationPolicy.INVITATION_ONLY
    first = installation.invite().execute(ADMIN.id)
    second = installation.invite().execute(ADMIN.id)
    listing = ListInvitations(installation.users, installation.invitations, installation.clock)
    revoke = RevokeInvitation(installation.users, installation.invitations, installation.clock)

    revoke.execute(ADMIN.id, first.id)

    assert [pending.id for pending in listing.execute(ADMIN.id)] == [second.id]
    with pytest.raises(LinkUnusable):
        installation.accept().execute(first.token, "new@example.test", PASSWORD, CLIENT)
    with pytest.raises(LinkUnusable):
        revoke.execute(ADMIN.id, first.id)
    with pytest.raises(AdministratorRequired):
        installation.invite().execute(MEMBER.id)
    with pytest.raises(AdministratorRequired):
        listing.execute(MEMBER.id)


# Password Reset Links


def test_a_reset_link_lets_its_user_choose_a_new_password_once_and_signs_them_out() -> None:
    installation = _installation(MEMBER)
    session = installation.sessions.signed_in(MEMBER.id)
    issue = IssuePasswordReset(installation.users, installation.resets, installation.clock)
    reset = installation.reset()
    link = issue.execute(ADMIN.id, MEMBER.id)

    reset.execute(link.token, "a brand new password", CLIENT)

    assert installation.users.password_hash(MEMBER.id) == "hashed:a brand new password"
    assert installation.sessions.user_of(session.token) is None
    with pytest.raises(LinkUnusable):
        reset.execute(link.token, "another new password", CLIENT)
    with pytest.raises(IncorrectCredentials):
        installation.sign_in("member@example.test")


def test_a_newer_reset_link_replaces_the_earlier_one() -> None:
    installation = _installation(MEMBER)
    issue = IssuePasswordReset(installation.users, installation.resets, installation.clock)
    check = CheckPasswordReset(installation.resets, installation.clock, installation.attempts)
    earlier = issue.execute(ADMIN.id, MEMBER.id)

    later = issue.execute(ADMIN.id, MEMBER.id)

    assert not check.execute(earlier.token, CLIENT)
    assert check.execute(later.token, CLIENT)


def test_an_administrator_changes_their_own_password_with_it_not_with_a_reset_link() -> None:
    installation = _installation(MEMBER)
    issue = IssuePasswordReset(installation.users, installation.resets, installation.clock)

    # A reset link would let whoever holds the session skip the current password.
    with pytest.raises(YourOwnResetLink):
        issue.execute(ADMIN.id, ADMIN.id)


def test_only_an_administrator_issues_a_reset_link_for_a_user_who_exists() -> None:
    installation = _installation(MEMBER)
    issue = IssuePasswordReset(installation.users, installation.resets, installation.clock)

    with pytest.raises(AdministratorRequired):
        issue.execute(MEMBER.id, ADMIN.id)
    with pytest.raises(UserNotFound):
        issue.execute(ADMIN.id, UserId("missing"))


# Roles and states


def test_an_administrator_lists_every_user() -> None:
    installation = _installation(MEMBER)

    assert ListUsers(installation.users).execute(ADMIN.id, UserQuery()) == UserPage(
        (ADMIN, MEMBER), total=2
    )
    assert ListUsers(installation.users).execute(ADMIN.id, UserQuery(role=Role.USER)) == UserPage(
        (MEMBER,), total=1
    )
    with pytest.raises(AdministratorRequired):
        ListUsers(installation.users).execute(MEMBER.id, UserQuery())


def test_the_role_is_granted_and_revoked_but_never_from_the_last_administrator() -> None:
    installation = _installation(MEMBER)
    change = ChangeRole(installation.users)

    with pytest.raises(LastAdministrator):
        change.execute(ADMIN.id, ADMIN.id, Role.USER)
    change.execute(ADMIN.id, MEMBER.id, Role.INSTALLATION_ADMINISTRATOR)
    change.execute(MEMBER.id, ADMIN.id, Role.USER)

    assert installation.users.get(ADMIN.id) == replace(ADMIN, role=Role.USER)
    with pytest.raises(AdministratorRequired):
        change.execute(ADMIN.id, MEMBER.id, Role.USER)


OTHER_ADMIN = replace(MEMBER, role=Role.INSTALLATION_ADMINISTRATOR)


def _demote(user_id: UserId) -> Callable[[MemoryUsers], object]:
    """Another Installation Administrator demoting `user_id` at the same moment."""
    return lambda users: users.users.update(
        {user_id: replace(users.users[user_id], role=Role.USER)}
    )


def test_two_administrators_demoting_each_other_at_once_leave_one() -> None:
    installation = _installation(OTHER_ADMIN)
    installation.users.meanwhile = _demote(ADMIN.id)

    with pytest.raises(LastAdministrator):
        ChangeRole(installation.users).execute(ADMIN.id, OTHER_ADMIN.id, Role.USER)

    assert installation.users.get(OTHER_ADMIN.id) == OTHER_ADMIN


def test_two_administrators_disabling_each_other_at_once_leave_one() -> None:
    installation = _installation(OTHER_ADMIN)
    installation.users.meanwhile = _demote(ADMIN.id)
    session = installation.sessions.signed_in(OTHER_ADMIN.id)

    with pytest.raises(LastAdministrator):
        ChangeUserState(installation.users, installation.sessions).execute(
            ADMIN.id, OTHER_ADMIN.id, UserState.DISABLED
        )

    assert installation.users.get(OTHER_ADMIN.id) == OTHER_ADMIN
    assert installation.sessions.user_of(session.token) == OTHER_ADMIN.id


def test_a_disabled_user_is_signed_out_and_signs_in_again_once_enabled() -> None:
    installation = _installation(MEMBER)
    session = installation.sessions.signed_in(MEMBER.id)
    change = ChangeUserState(installation.users, installation.sessions)

    change.execute(ADMIN.id, MEMBER.id, UserState.DISABLED)

    assert installation.sessions.user_of(session.token) is None
    change.execute(ADMIN.id, MEMBER.id, UserState.ACTIVE)
    assert installation.sign_in("member@example.test") == MEMBER.id


def test_an_administrator_neither_disables_themself_nor_the_last_administrator() -> None:
    other = replace(MEMBER, role=Role.INSTALLATION_ADMINISTRATOR)
    installation = _installation(other)
    change = ChangeUserState(installation.users, installation.sessions)

    with pytest.raises(YourOwnState):
        change.execute(ADMIN.id, ADMIN.id, UserState.DISABLED)
    change.execute(ADMIN.id, other.id, UserState.DISABLED)
    with pytest.raises(LastAdministrator):
        ChangeRole(installation.users).execute(ADMIN.id, ADMIN.id, Role.USER)
    with pytest.raises(UserNotFound):
        change.execute(ADMIN.id, UserId("missing"), UserState.DISABLED)


class CountingPasswords(PlainPasswords):
    def __init__(self) -> None:
        self.hashed = 0

    def hash(self, password: str) -> str:
        self.hashed += 1
        return super().hash(password)


def test_an_unusable_link_is_refused_before_any_password_is_hashed() -> None:
    installation = _installation(MEMBER)
    installation.registration.current = RegistrationPolicy.INVITATION_ONLY
    passwords = CountingPasswords()

    with pytest.raises(LinkUnusable):
        installation.accept(passwords).execute("forged", "new@example.test", PASSWORD, CLIENT)
    with pytest.raises(LinkUnusable):
        installation.reset(passwords).execute("forged", "a brand new password", CLIENT)

    assert passwords.hashed == 0
    assert installation.users.count() == 2


def test_an_invitation_under_only_me_is_refused_before_any_password_is_hashed() -> None:
    installation = _installation()
    installation.registration.current = RegistrationPolicy.INVITATION_ONLY
    link = installation.invite().execute(ADMIN.id)
    installation.registration.current = RegistrationPolicy.ONLY_ME
    passwords = CountingPasswords()

    with pytest.raises(LinkUnusable):
        installation.accept(passwords).execute(link.token, "new@example.test", PASSWORD, CLIENT)
    assert passwords.hashed == 0


def test_a_client_trying_unusable_links_waits_whichever_link_route_it_uses() -> None:
    installation = _installation(MEMBER)
    installation.registration.current = RegistrationPolicy.INVITATION_ONLY
    link = installation.invite().execute(ADMIN.id)
    check_reset = CheckPasswordReset(installation.resets, installation.clock, installation.attempts)

    assert not installation.check_invitation().execute("forged", CLIENT)
    assert not check_reset.execute("forged", CLIENT)
    with pytest.raises(LinkUnusable):
        installation.reset().execute("forged", "a brand new password", CLIENT)

    with pytest.raises(LinkAttemptsThrottled):
        installation.check_invitation().execute(link.token, CLIENT)
    with pytest.raises(LinkAttemptsThrottled):
        installation.accept().execute(link.token, "new@example.test", PASSWORD, CLIENT)
    # Another address is not held up, and a usable link counts no failure.
    assert installation.check_invitation().execute(link.token, "198.51.100.7")
    installation.accept().execute(link.token, "new@example.test", PASSWORD, "198.51.100.7")
