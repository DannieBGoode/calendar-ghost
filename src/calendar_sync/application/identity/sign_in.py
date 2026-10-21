"""Who is signed in: setup, sign-in by email and password, and a User's own credentials.

ADR 0030: Users sign in with email and password. The first User of an upgraded installation has
no email and signs in by password alone until they add one.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from calendar_sync.application.identity.credentials import CredentialChanges, CredentialSnapshot
from calendar_sync.application.identity.errors import (
    AdminAlreadyConfigured,
    IncorrectCredentials,
    IncorrectPassword,
    PasswordPolicyViolation,
    SignInThrottled,
    UserDisabled,
)
from calendar_sync.application.identity.ports import (
    PasswordHasher,
    Session,
    Sessions,
    SignInCredentials,
    SignInThrottle,
    UserDirectory,
)
from calendar_sync.application.shared.ports import Clock, IdGenerator
from calendar_sync.domain.access import InvalidEmail, Role, User, UserId, UserState, email_address

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
        hashed = self.passwords.hash(require_password(password))
        if not self.users.add_first(user, hashed):
            raise AdminAlreadyConfigured("Calendar Ghost is already set up; sign in instead")
        session = start_session(self.sessions, user.id, hashed, user.email, 0)
        self.users.record_sign_in(user.id, now)
        return session


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
        facts = self._credentials(email, address)
        user = facts.user if facts else None
        hashed = facts.credential.password_hash if facts else None
        matches = self.passwords.verify(password, hashed or self._decoy)
        if user is None or hashed is None or not matches:
            self.throttle.failed(keys)
            raise IncorrectCredentials("that email and password do not match a User")
        if user.state is UserState.DISABLED:
            raise UserDisabled("an Installation Administrator has disabled this User")
        self.throttle.succeeded(keys)
        assert facts is not None
        session = start_session(
            self.sessions, user.id, hashed, facts.credential.email, facts.credential.revision
        )
        self.users.record_sign_in(user.id, self.clock.now())
        return session

    def _credentials(self, email: str | None, address: str | None) -> SignInCredentials | None:
        if email is None:
            # Password alone signs in only the upgraded first User, until they add an email.
            return self.users.sign_in_credentials(None)
        return self.users.sign_in_credentials(address) if address is not None else None


def start_session(
    sessions: Sessions, user_id: UserId, password_hash: str, email: str | None, revision: int
) -> Session:
    """A session for the User whose password was just checked against `password_hash`.

    Checking a password is slow, so an email or password change, reset, or disabling can land in
    between; the session starts only if none did, atomically with its start.
    """
    session = sessions.start(user_id, password_hash, email, revision)
    if session is None:
        raise IncorrectCredentials(
            "the credentials changed or the User was disabled; sign in again"
        )
    return session


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
    credentials: CredentialChanges

    def execute(self, user_id: UserId, email: str, password: str | None) -> User:
        expected = _current(self.credentials, user_id)
        user = _existing(self.users, user_id)
        # The add-email step follows a sign-in by password alone, so it asks for nothing more.
        if not user.needs_email:
            _confirm(expected, self.passwords, password)
        if not self.credentials.change_email(expected, email_address(email)):
            raise IncorrectCredentials("the credentials changed; sign in again")
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
class SetInstantSync:
    """Whether the signed-in User's rules run soon after a change is reported."""

    users: UserDirectory

    def execute(self, user_id: UserId, wanted: bool) -> User:
        _existing(self.users, user_id)
        self.users.set_instant_sync(user_id, wanted)
        return _existing(self.users, user_id)


@dataclass(slots=True)
class ChangeOwnPassword:
    """Replace the signed-in User's password and end their other sessions."""

    credentials: CredentialChanges
    passwords: PasswordHasher

    def execute(self, user_id: UserId, current: str, new: str, session: str | None) -> None:
        expected = _current(self.credentials, user_id)
        _confirm(expected, self.passwords, current)
        hashed = self.passwords.hash(require_password(new))
        if not self.credentials.change_password(expected, hashed, session):
            raise IncorrectCredentials("the credentials changed; sign in again")


def _existing(users: UserDirectory, user_id: UserId) -> User:
    user = users.get(user_id)
    if user is None:
        raise IncorrectCredentials("the signed-in User no longer exists")
    return user


def _current(credentials: CredentialChanges, user_id: UserId) -> CredentialSnapshot:
    expected = credentials.current(user_id)
    if expected is None:
        raise IncorrectCredentials("the signed-in User is no longer active")
    return expected


def _confirm(expected: CredentialSnapshot, passwords: PasswordHasher, password: str | None) -> None:
    if (
        password is None
        or len(password) > 1024
        or expected.password_hash is None
        or not passwords.verify(password, expected.password_hash)
    ):
        raise IncorrectPassword("that is not your current password")
