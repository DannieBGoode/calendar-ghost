"""Nonsecret identity email readiness and its dedicated delivery port."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from calendar_sync.application.shared.errors import ApplicationError, InfrastructureFailure
from calendar_sync.domain.access import UserId


class IdentityEmailReason(StrEnum):
    SMTP_MISSING = "smtp_missing"
    SMTP_SECURITY = "smtp_security"
    ORIGIN_MISSING = "origin_missing"
    ORIGIN_INVALID = "origin_invalid"
    ORIGIN_INSECURE = "origin_insecure"
    MASTER_KEY_MISSING = "master_key_missing"


@dataclass(frozen=True, slots=True)
class IdentityEmailSetup:
    fingerprint: str | None
    reason: IdentityEmailReason | None


class IdentityEmailDeliveryFailed(InfrastructureFailure):
    """Delivery failed; no provider detail or recipient is exposed."""

    def __init__(self) -> None:
        super().__init__("Identity email delivery failed")


class IdentityTestSender(Protocol):
    def send_test(self, recipient: str) -> None: ...


@dataclass(frozen=True, slots=True)
class EmailTest:
    id: str
    actor: UserId
    generation: int
    fingerprint: str


@dataclass(frozen=True, slots=True)
class PreparedEmailTest:
    test: EmailTest
    recipient: str = field(repr=False)


class IdentityEmailTestThrottled(ApplicationError):
    """This administrator has already used their rolling-hour allowance."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("Identity email test allowance exhausted")
        self.retry_after = retry_after


class IdentityEmailStorageUnavailable(InfrastructureFailure):
    """The readiness store could not safely complete an operation."""

    def __init__(self) -> None:
        super().__init__("Identity email storage unavailable")


class IdentityEmailTests(Protocol):
    def tested_at(self, fingerprint: str) -> datetime | None: ...

    def admit(self, actor: UserId, fingerprint: str, at: datetime) -> EmailTest: ...

    def record_success(self, test: EmailTest, recipient: str, at: datetime) -> bool: ...

    def purge(self, before: datetime, limit: int) -> None: ...
