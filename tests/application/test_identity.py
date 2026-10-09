"""Signing in by email and password (ADR 0030)."""

from dataclasses import replace

import pytest

from calendar_sync.application.errors import (
    AdminAlreadyConfigured,
    EmailTaken,
    IncorrectCredentials,
    IncorrectPassword,
    PasswordPolicyViolation,
    SignInThrottled,
    UserDisabled,
)
from calendar_sync.application.identity import (
    ChangeOwnPassword,
    SetNotificationEmail,
    SetOwnEmail,
    SetUpInstallation,
    SignIn,
)
from calendar_sync.domain.access import InvalidEmail, Role, User, UserId, UserState
from tests.fake_calendar import FixedClock
from tests.helpers import NOW
from tests.identity_fakes import CountingThrottle, MemorySessions, MemoryUsers, PlainPasswords

PASSWORD = "correct horse battery staple"
UPGRADED = User(UserId("upgraded"), None, Role.INSTALLATION_ADMINISTRATOR, UserState.ACTIVE, NOW)


class SequentialIds:
    def __init__(self) -> None:
        self.issued = 0

    def new(self) -> str:
        self.issued += 1
        return f"user-{self.issued}"


def _set_up(users: MemoryUsers, sessions: MemorySessions) -> SetUpInstallation:
    return SetUpInstallation(users, PlainPasswords(), sessions, SequentialIds(), FixedClock())


def _sign_in(
    users: MemoryUsers, sessions: MemorySessions, throttle: CountingThrottle | None = None
) -> SignIn:
    return SignIn(users, PlainPasswords(), sessions, throttle or CountingThrottle(), FixedClock())


def _installation() -> tuple[MemoryUsers, MemorySessions]:
    users, sessions = MemoryUsers(), MemorySessions(NOW)
    _set_up(users, sessions).execute(" Admin@Example.TEST ", PASSWORD)
    return users, sessions


def test_setup_makes_the_first_user_an_administrator_signed_in_by_email() -> None:
    users, sessions = MemoryUsers(), MemorySessions(NOW)

    session = _set_up(users, sessions).execute(" Admin@Example.TEST ", PASSWORD)

    user = users.get(session.user_id)
    assert user is not None
    assert (user.email, user.role, user.state) == (
        "admin@example.test",
        Role.INSTALLATION_ADMINISTRATOR,
        UserState.ACTIVE,
    )
    assert user.last_sign_in_at == NOW
    assert sessions.user_of(session.token) == user.id
    assert users.password_hash(user.id) == f"hashed:{PASSWORD}"


def test_setup_runs_once() -> None:
    users, sessions = _installation()

    with pytest.raises(AdminAlreadyConfigured):
        _set_up(users, sessions).execute("other@example.test", PASSWORD)
    assert users.count() == 1


@pytest.mark.parametrize(
    ("email", "password", "refused"),
    [
        ("not-an-email", PASSWORD, InvalidEmail),
        ("admin@example.test", "too short", PasswordPolicyViolation),
    ],
)
def test_setup_refuses_an_invalid_email_or_a_weak_password(
    email: str, password: str, refused: type[Exception]
) -> None:
    users = MemoryUsers()

    with pytest.raises(refused):
        _set_up(users, MemorySessions(NOW)).execute(email, password)
    assert users.count() == 0


def test_a_user_signs_in_with_their_email_in_any_case_and_their_password() -> None:
    users, sessions = _installation()

    session = _sign_in(users, sessions).execute("ADMIN@example.test", PASSWORD, "client")

    assert session.user_id == users.list()[0].id


@pytest.mark.parametrize(
    ("email", "password"),
    [("admin@example.test", "wrong password!"), ("missing@example.test", PASSWORD), ("", PASSWORD)],
)
def test_a_wrong_email_or_password_is_refused_alike(email: str, password: str) -> None:
    users, sessions = _installation()

    with pytest.raises(IncorrectCredentials):
        _sign_in(users, sessions).execute(email, password, "client")


def test_the_upgraded_first_user_signs_in_by_password_alone_until_they_add_an_email() -> None:
    users, sessions = MemoryUsers(), MemorySessions(NOW)
    users.add(UPGRADED, f"hashed:{PASSWORD}")

    session = _sign_in(users, sessions).execute(None, PASSWORD, "client")
    SetOwnEmail(users, PlainPasswords()).execute(session.user_id, "admin@example.test", None)

    with pytest.raises(IncorrectCredentials):
        _sign_in(users, sessions).execute(None, PASSWORD, "client")
    again = _sign_in(users, sessions).execute("admin@example.test", PASSWORD, "client")
    assert again.user_id == UPGRADED.id


def test_a_disabled_user_cannot_sign_in() -> None:
    users, sessions = _installation()
    admin = users.list()[0]
    users.save(replace(admin, state=UserState.DISABLED))

    with pytest.raises(UserDisabled):
        _sign_in(users, sessions).execute("admin@example.test", PASSWORD, "client")
    assert len(sessions.sessions) == 1


def test_repeated_failures_throttle_sign_in_even_with_the_right_password() -> None:
    users, sessions = _installation()
    throttle = CountingThrottle(limit=2)
    sign_in = _sign_in(users, sessions, throttle)
    for _ in range(2):
        with pytest.raises(IncorrectCredentials):
            sign_in.execute("admin@example.test", "wrong password!", "client")

    with pytest.raises(SignInThrottled) as throttled:
        sign_in.execute("admin@example.test", PASSWORD, "client")

    assert throttled.value.retry_after == 60
    assert throttle.failures == {"email:admin@example.test": 2, "client:client": 2}


def test_a_successful_sign_in_clears_the_failures_of_its_email() -> None:
    users, sessions = _installation()
    throttle = CountingThrottle(limit=3)
    sign_in = _sign_in(users, sessions, throttle)
    with pytest.raises(IncorrectCredentials):
        sign_in.execute("admin@example.test", "wrong password!", "client")

    sign_in.execute("admin@example.test", PASSWORD, "client")

    assert throttle.failures == {"client:client": 1}


def test_a_user_with_an_email_changes_it_only_with_their_password() -> None:
    users, _ = _installation()
    admin = users.list()[0]
    set_email = SetOwnEmail(users, PlainPasswords())

    with pytest.raises(IncorrectPassword):
        set_email.execute(admin.id, "new@example.test", "wrong password!")
    changed = set_email.execute(admin.id, "New@Example.test", PASSWORD)

    assert changed.email == "new@example.test"
    assert users.get(admin.id) == changed


def test_an_email_another_user_signs_in_with_is_refused() -> None:
    users, _ = _installation()
    users.add(replace(UPGRADED, role=Role.USER), f"hashed:{PASSWORD}")

    with pytest.raises(EmailTaken):
        SetOwnEmail(users, PlainPasswords()).execute(UPGRADED.id, "admin@example.test", None)
    assert users.get(UPGRADED.id) == replace(UPGRADED, role=Role.USER)


class DemotedAfterReading(MemoryUsers):
    """An Installation Administrator demotes and disables the User just after it is read."""

    def get(self, user_id: UserId) -> User | None:
        user = super().get(user_id)
        if user is not None:
            self.users[user_id] = replace(user, role=Role.USER, state=UserState.DISABLED)
        return user


def test_setting_ones_email_never_restores_a_role_or_state_changed_meanwhile() -> None:
    users = DemotedAfterReading()
    users.add(
        User(
            UserId("admin"),
            "admin@example.test",
            Role.INSTALLATION_ADMINISTRATOR,
            UserState.ACTIVE,
            NOW,
        ),
        f"hashed:{PASSWORD}",
    )

    changed = SetOwnEmail(users, PlainPasswords()).execute(
        UserId("admin"), "new@example.test", PASSWORD
    )

    stored = users.users[UserId("admin")]
    assert (stored.email, stored.role, stored.state) == (
        "new@example.test",
        Role.USER,
        UserState.DISABLED,
    )
    assert (changed.role, changed.state) == (Role.USER, UserState.DISABLED)


def test_choosing_incident_emails_never_restores_a_role_or_state_changed_meanwhile() -> None:
    users = DemotedAfterReading()
    users.add(
        User(
            UserId("admin"),
            "admin@example.test",
            Role.INSTALLATION_ADMINISTRATOR,
            UserState.ACTIVE,
            NOW,
        ),
        f"hashed:{PASSWORD}",
    )

    changed = SetNotificationEmail(users).execute(UserId("admin"), notify_by_email=False)

    stored = users.users[UserId("admin")]
    assert (stored.notify_by_email, stored.role, stored.state) == (
        False,
        Role.USER,
        UserState.DISABLED,
    )
    assert changed == stored


def test_changing_a_password_needs_the_current_one_and_ends_every_other_session() -> None:
    users, sessions = _installation()
    admin = users.list()[0]
    other = sessions.start(admin.id)
    current = sessions.start(admin.id)
    change = ChangeOwnPassword(users, PlainPasswords(), sessions)

    with pytest.raises(IncorrectPassword):
        change.execute(admin.id, "wrong password!", "a new long password", current.token)
    with pytest.raises(PasswordPolicyViolation):
        change.execute(admin.id, PASSWORD, "short", current.token)
    change.execute(admin.id, PASSWORD, "a new long password", current.token)

    assert users.password_hash(admin.id) == "hashed:a new long password"
    assert sessions.user_of(current.token) == admin.id
    assert sessions.user_of(other.token) is None
