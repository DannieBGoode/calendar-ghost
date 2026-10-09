"""Users and who may do what on an installation (ADR 0029, ADR 0030)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from calendar_sync.domain.errors import DomainValidationError

EMAIL_LIMIT = 254
"""The longest address SMTP can deliver to."""
# One @, something before it, and a dotted domain after it; nothing that is whitespace.
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class InvalidEmail(DomainValidationError):
    """Not an email address a User can sign in with."""


def email_address(raw: str) -> str:
    """A User's email, trimmed and in lower case so it signs in however it is typed."""
    address = raw.strip().lower()
    if len(address) > EMAIL_LIMIT or _EMAIL.fullmatch(address) is None:
        raise InvalidEmail("enter an email address such as name@example.com")
    return address


@dataclass(frozen=True, slots=True)
class UserId:
    """The User every Connected Account, rule, token, Incident, and Audit Entry belongs to."""

    value: str

    def __post_init__(self) -> None:
        if not self.value or self.value.isspace():
            raise DomainValidationError("user id must not be empty")


class Role(StrEnum):
    INSTALLATION_ADMINISTRATOR = "installation_administrator"
    USER = "user"


class UserState(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    """Stopped from signing in; their rules are held until they are enabled again."""


@dataclass(frozen=True, slots=True)
class User:
    """A person who signs in to the installation; what they own, no other User sees."""

    id: UserId
    email: str | None
    """None only for the first User of an upgraded installation, until they add one."""
    role: Role
    state: UserState
    created_at: datetime
    last_sign_in_at: datetime | None = None
    language: str | None = None
    notify_by_email: bool = True
    """Whether their Incident Notifications are also emailed when the installation sends email."""

    @property
    def needs_email(self) -> bool:
        return self.email is None

    @property
    def administers(self) -> bool:
        """Whether they hold the Installation Administrator role."""
        return self.role is Role.INSTALLATION_ADMINISTRATOR

    def with_email(self, email: str) -> User:
        return replace(self, email=email_address(email))


class RegistrationPolicy(StrEnum):
    """Who may become a User (ADR 0030). Open, for the Hosted Service, arrives with sign-up."""

    ONLY_ME = "only_me"
    INVITATION_ONLY = "invitation_only"

    @classmethod
    def default(cls) -> RegistrationPolicy:
        return cls.ONLY_ME

    @property
    def lets_people_join(self) -> bool:
        return self is not RegistrationPolicy.ONLY_ME


class OnlyMeNeedsOneUser(DomainValidationError):
    """Only Me is chosen again only while no other User exists."""


def require_registration_change(policy: RegistrationPolicy, users: int) -> None:
    """Refuse Only Me while the installation has Users besides the one choosing it."""
    if policy is RegistrationPolicy.ONLY_ME and users > 1:
        raise OnlyMeNeedsOneUser("delete the other Users before choosing Only Me again")


LINK_LIFETIME = timedelta(days=7)
"""How long an Invitation or a Password Reset Link can be used, once."""


def link_expiry(issued_at: datetime) -> datetime:
    return issued_at + LINK_LIFETIME


class LastAdministrator(DomainValidationError):
    """The installation keeps at least one Installation Administrator who may sign in."""


def require_another_administrator(users: Iterable[User], leaving: UserId) -> None:
    """Refuse when `leaving` is the last active Installation Administrator."""
    if not any(
        user.administers and user.state is UserState.ACTIVE and user.id != leaving for user in users
    ):
        raise LastAdministrator("another Installation Administrator must remain")
