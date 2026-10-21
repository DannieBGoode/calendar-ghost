"""Narrow contracts for verified joining; pending proofs belong to no User."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from calendar_sync.application.identity.ports import IssuedLink
from calendar_sync.application.shared.errors import ApplicationError, InfrastructureFailure
from calendar_sync.domain.access import User

ReadinessReason = Literal["identity_email_not_configured", "identity_email_not_tested"]


@dataclass(frozen=True, slots=True)
class PendingRegistration:
    email: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class PreparedRegistration:
    recipient: str = field(repr=False)
    link: IssuedLink = field(repr=False)


@dataclass(frozen=True, slots=True)
class RegistrationEmailRequest:
    email: str = field(repr=False)
    fingerprint: str
    invitation_token: str | None = field(default=None, repr=False)


class RegistrationEmailQueue(Protocol):
    def submit_registration(self, request: RegistrationEmailRequest) -> bool: ...


class IdentityRegistrationSender(Protocol):
    def send_registration(self, recipient: str, token: str) -> None: ...


@dataclass(frozen=True, slots=True)
class OpenRegistrationStatus:
    available: bool
    reason: ReadinessReason | None


class RegistrationUnavailable(ApplicationError):
    """A live proof cannot finish until Open's identity email is operational again."""


class RegistrationStorageUnavailable(InfrastructureFailure):
    def __init__(self) -> None:
        super().__init__("Registration storage unavailable")


class OpenRegistrationUnavailable(ApplicationError):
    def __init__(self, reason: ReadinessReason) -> None:
        super().__init__("Open registration requires tested identity email")
        self.reason = reason


class InvitationVerificationRequired(ApplicationError):
    """An Invitation under Open must finish through verified registration."""


class RegistrationReadiness(Protocol):
    def status(self) -> OpenRegistrationStatus: ...

    def public_available(self) -> bool: ...


class RegistrationProofs(Protocol):
    def issue(
        self, email: str, invitation_token: str | None, fingerprint: str
    ) -> PreparedRegistration | None: ...

    def check(self, token: str, fingerprint: str | None) -> PendingRegistration | None: ...

    def complete(self, token: str, password_hash: str, fingerprint: str | None) -> User | None: ...

    def purge(self, before: datetime, limit: int) -> int: ...
