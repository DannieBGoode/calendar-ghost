"""Narrow proof store contract for a signed-in User changing their email."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from calendar_sync.application.identity.credentials import CredentialSnapshot
from calendar_sync.application.identity.identity_email import IdentityEmailReason
from calendar_sync.application.shared.errors import ApplicationError
from calendar_sync.domain.access import UserId


@dataclass(frozen=True, slots=True)
class PendingEmailChange:
    id: str
    email: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class EmailChangeCompletion:
    previous_email: str = field(repr=False)


class EmailChangeProofs(Protocol):
    def pending(self, user_id: UserId) -> PendingEmailChange | None: ...

    def request(
        self, expected: CredentialSnapshot, email: str, session: str
    ) -> PendingEmailChange: ...

    def cancel(self, user_id: UserId, request_id: str) -> None: ...

    def check(self, user_id: UserId, token: str) -> bool: ...

    def confirm(
        self, expected: CredentialSnapshot, token: str, session: str
    ) -> EmailChangeCompletion | None: ...


class EmailChangeUnavailable(ApplicationError):
    """The requested address cannot be used, without disclosing whose it is."""

    def __init__(self) -> None:
        super().__init__("Email change unavailable")


class EmailChangeConfigurationRequired(ApplicationError):
    """Identity email setup is incomplete or unsafe for an emailed proof."""

    def __init__(self, reason: IdentityEmailReason) -> None:
        super().__init__("Identity email configuration required")
        self.reason = reason
