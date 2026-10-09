"""Who is signed in: setup, sign-in by email and password, and a User's own credentials.

ADR 0030: Users sign in with email and password. The first User of an upgraded installation has
no email and signs in by password alone until they add one.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from calendar_sync.application.errors import (
    AdminAlreadyConfigured,
    IncorrectCredentials,
    IncorrectPassword,
    PasswordPolicyViolation,
    SignInThrottled,
    UserDisabled,
)
from calendar_sync.application.ports import (
    Clock,
    IdGenerator,
    PasswordHasher,
    Session,
    Sessions,
    SignInThrottle,
    UserDirectory,
)
from calendar_sync.domain.access import (
    InvalidEmail,
    Role,
    User,
    UserId,
    UserState,
    email_address,
)

PASSWORD_MINIMUM = 12


def require_password(password: str) -> str:
    if len(password) < PASSWORD_MINIMUM:
        raise PasswordPolicyViolation(
            f"password must contain at least {PASSWORD_MINIMUM} characters"
        )
    return password


@dataclass(slots=True)
class SetUpInstallation:
    """Create the first User, an Installation Administrator, and sign them in."""

    users: UserDirectory
    passwords: PasswordHasher
    sessions: Sessions
    ids: IdGenerator
    clock: Clock

    def execute(self, email: str, password: str) -> Session:
        now = self.clock.now()
        user = User(
            UserId(self.ids.new()),
            email_address(email),
            Role.INSTALLATION_ADMINISTRATOR,
            UserState.ACTIVE,
            now,
        )
        if not self.users.add_first(user, self.passwords.hash(require_password(password))):
            raise AdminAlreadyConfigured("Calendar Ghost is already set up; sign in instead")
        self.users.record_sign_in(user.id, now)
        return self.sessions.start(user.id)


@dataclass(slots=True)
class SignIn:
    """Start a session for the User an email and password name, counting failures."""

    users: UserDirectory
    passwords: PasswordHasher
    sessions: Sessions
    throttle: SignInThrottle
    clock: Clock
    _decoy: str = field(init=False, repr=False)
    """A hash checked when no User matches, so a wrong email takes as long as a wrong password."""

    def __post_init__(self) -> None:
        self._decoy = self.passwords.hash(secrets.token_urlsafe(16))

    def execute(self, email: str | None, password: str, client: str) -> Session:
        address = _normal_email(email)
        keys = (f"email:{address or ''}", f"client:{client}")
        wait = self.throttle.wait(keys)
        if wait > 0:
            raise SignInThrottled(wait)
        user = self._user(email, address)
        hashed = self.users.password_hash(user.id) if user is not None else None
        matches = self.passwords.verify(password, hashed or self._decoy)
        if user is None or hashed is None or not matches:
            self.throttle.failed(keys)
            raise IncorrectCredentials("that email and password do not match a User")
        if user.state is UserState.DISABLED:
            raise UserDisabled("an Installation Administrator has disabled this User")
        self.throttle.succeeded(keys)
        self.users.record_sign_in(user.id, self.clock.now())
        return self.sessions.start(user.id)

    def _user(self, email: str | None, address: str | None) -> User | None:
        if email is None:
            # Password alone signs in only the upgraded first User, until they add an email.
            return self.users.without_email()
        return self.users.by_email(address) if address is not None else None


def _normal_email(email: str | None) -> str | None:
    if email is None:
        return None
    try:
        return email_address(email)
    except InvalidEmail:
        return None


@dataclass(slots=True)
class SetOwnEmail:
    """Add the signed-in User's email, or change it after confirming their password."""

    users: UserDirectory
    passwords: PasswordHasher

    def execute(self, user_id: UserId, email: str, password: str | None) -> User:
        user = _existing(self.users, user_id)
        # The add-email step follows a sign-in by password alone, so it asks for nothing more.
        if not user.needs_email:
            _confirm(self.users, self.passwords, user_id, password)
        # Only the email is written, so a role or state an administrator changed since the read
        # above stands; the answer is the User as stored now.
        self.users.set_email(user_id, email_address(email))
        return _existing(self.users, user_id)


@dataclass(slots=True)
class SetNotificationEmail:
    """Whether the signed-in User's Incident Notifications also come by email."""

    users: UserDirectory

    def execute(self, user_id: UserId, notify_by_email: bool) -> User:
        _existing(self.users, user_id)
        self.users.set_notification_email(user_id, notify_by_email)
        return _existing(self.users, user_id)


@dataclass(slots=True)
class ChangeOwnPassword:
    """Replace the signed-in User's password and end their other sessions."""

    users: UserDirectory
    passwords: PasswordHasher
    sessions: Sessions

    def execute(self, user_id: UserId, current: str, new: str, session: str | None) -> None:
        _confirm(self.users, self.passwords, user_id, current)
        self.users.set_password_hash(user_id, self.passwords.hash(require_password(new)))
        self.sessions.end_all(user_id, keep=session)


def _existing(users: UserDirectory, user_id: UserId) -> User:
    user = users.get(user_id)
    if user is None:
        raise IncorrectCredentials("the signed-in User no longer exists")
    return user


def _confirm(
    users: UserDirectory, passwords: PasswordHasher, user_id: UserId, password: str | None
) -> None:
    hashed = users.password_hash(user_id)
    if password is None or hashed is None or not passwords.verify(password, hashed):
        raise IncorrectPassword("that is not your current password")
