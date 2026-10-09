"""Registration Policy, Invitations, Password Reset Links, roles, and disabling (ADR 0030)."""

from dataclasses import dataclass, replace
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
    YourOwnState,
)
from calendar_sync.application.errors import EmailTaken, IncorrectCredentials
from calendar_sync.application.identity import SignIn
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

    def accept(self) -> AcceptInvitation:
        return AcceptInvitation(
            self.users,
            self.registration,
            self.invitations,
            PlainPasswords(),
            self.sessions,
            SequentialIds(),
            self.clock,
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
    return Installation(
        users,
        MemoryRegistration(),
        MemoryInvitations(users),
        MemoryResetLinks(users),
        MemorySessions(NOW),
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

    session = installation.accept().execute(link.token, " New@Example.test ", PASSWORD)

    joined = installation.users.get(session.user_id)
    assert joined is not None
    assert (joined.email, joined.role, joined.state) == (
        "new@example.test",
        Role.USER,
        UserState.ACTIVE,
    )
    assert link.expires_at == NOW + timedelta(days=7)
    assert installation.sign_in("new@example.test") == joined.id


def test_an_invitation_is_used_once() -> None:
    installation = _installation()
    installation.registration.current = RegistrationPolicy.INVITATION_ONLY
    link = installation.invite().execute(ADMIN.id)
    installation.accept().execute(link.token, "new@example.test", PASSWORD)

    with pytest.raises(LinkUnusable):
        installation.accept().execute(link.token, "again@example.test", PASSWORD)
    assert installation.users.count() == 2


def test_an_invitation_expires_after_seven_days() -> None:
    installation = _installation()
    installation.registration.current = RegistrationPolicy.INVITATION_ONLY
    link = installation.invite().execute(ADMIN.id)
    check = CheckInvitation(installation.registration, installation.invitations, installation.clock)
    installation.clock.moment = NOW + timedelta(days=7) - timedelta(seconds=1)
    assert check.execute(link.token)

    installation.clock.moment = NOW + timedelta(days=7)
    assert not check.execute(link.token)
    with pytest.raises(LinkUnusable):
        installation.accept().execute(link.token, "new@example.test", PASSWORD)


def test_returning_to_only_me_stops_pending_invitations() -> None:
    installation = _installation()
    installation.registration.current = RegistrationPolicy.INVITATION_ONLY
    link = installation.invite().execute(ADMIN.id)
    installation.registration.current = RegistrationPolicy.ONLY_ME
    check = CheckInvitation(installation.registration, installation.invitations, installation.clock)

    assert not check.execute(link.token)
    with pytest.raises(LinkUnusable):
        installation.accept().execute(link.token, "new@example.test", PASSWORD)


def test_an_invitation_for_an_email_already_used_creates_no_user_and_stays_usable() -> None:
    installation = _installation()
    installation.registration.current = RegistrationPolicy.INVITATION_ONLY
    link = installation.invite().execute(ADMIN.id)

    with pytest.raises(EmailTaken):
        installation.accept().execute(link.token, "admin@example.test", PASSWORD)
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
        installation.accept().execute(first.token, "new@example.test", PASSWORD)
    with pytest.raises(LinkUnusable):
        revoke.execute(ADMIN.id, first.id)
    with pytest.raises(AdministratorRequired):
        installation.invite().execute(MEMBER.id)
    with pytest.raises(AdministratorRequired):
        listing.execute(MEMBER.id)


# Password Reset Links


def test_a_reset_link_lets_its_user_choose_a_new_password_once_and_signs_them_out() -> None:
    installation = _installation(MEMBER)
    session = installation.sessions.start(MEMBER.id)
    issue = IssuePasswordReset(installation.users, installation.resets, installation.clock)
    reset = ResetPassword(
        installation.resets, PlainPasswords(), installation.sessions, installation.clock
    )
    link = issue.execute(ADMIN.id, MEMBER.id)

    reset.execute(link.token, "a brand new password")

    assert installation.users.password_hash(MEMBER.id) == "hashed:a brand new password"
    assert installation.sessions.user_of(session.token) is None
    with pytest.raises(LinkUnusable):
        reset.execute(link.token, "another new password")
    with pytest.raises(IncorrectCredentials):
        installation.sign_in("member@example.test")


def test_a_newer_reset_link_replaces_the_earlier_one() -> None:
    installation = _installation(MEMBER)
    issue = IssuePasswordReset(installation.users, installation.resets, installation.clock)
    check = CheckPasswordReset(installation.resets, installation.clock)
    earlier = issue.execute(ADMIN.id, MEMBER.id)

    later = issue.execute(ADMIN.id, MEMBER.id)

    assert not check.execute(earlier.token)
    assert check.execute(later.token)


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

    assert ListUsers(installation.users).execute(ADMIN.id) == (ADMIN, MEMBER)
    with pytest.raises(AdministratorRequired):
        ListUsers(installation.users).execute(MEMBER.id)


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


def test_a_disabled_user_is_signed_out_and_signs_in_again_once_enabled() -> None:
    installation = _installation(MEMBER)
    session = installation.sessions.start(MEMBER.id)
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
