"""Users and who may do what on an installation (ADR 0029, ADR 0030)."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
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
