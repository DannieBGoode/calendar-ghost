"""Nonsecret identity email readiness and its dedicated delivery port."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from calendar_sync.application.identity.administration import (
    AdministratorRequired,
    require_administrator,
)
from calendar_sync.application.identity.ports import UserDirectory
from calendar_sync.application.shared.errors import ApplicationError, InfrastructureFailure
from calendar_sync.application.shared.ports import Clock
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

    def purge(self, before: datetime, limit: int) -> int:
        """Delete at most `limit` expired attempts; return the number deleted."""
        ...


class IdentityEmailNotConfigured(ApplicationError):
    def __init__(self) -> None:
        super().__init__("Identity email is not configured")


class IdentityEmailQueueBusy(ApplicationError):
    def __init__(self) -> None:
        super().__init__("Identity email test queue is busy")


class EmailTestState(StrEnum):
    IDLE = "idle"
    QUEUED = "queued"
    SENDING = "sending"
    ACCEPTED = "accepted"
    FAILED = "failed"


class IdentityEmailQueue(Protocol):
    def submit(self, test: EmailTest) -> bool: ...

    def state(self, actor: UserId) -> EmailTestState: ...


@dataclass(frozen=True, slots=True)
class IdentityEmailStatus:
    configured: bool
    unavailable_reason: IdentityEmailReason | None
    tested_at: datetime | None
    test_state: EmailTestState


@dataclass(frozen=True, slots=True)
class ShowIdentityEmail:
    users: UserDirectory
    tests: IdentityEmailTests
    setup: IdentityEmailSetup
    queue: IdentityEmailQueue

    def execute(self, actor: UserId) -> IdentityEmailStatus:
        require_administrator(self.users, actor)
        fingerprint = self.setup.fingerprint
        return IdentityEmailStatus(
            fingerprint is not None,
            self.setup.reason,
            self.tests.tested_at(fingerprint) if fingerprint is not None else None,
            self.queue.state(actor),
        )


@dataclass(frozen=True, slots=True)
class RequestIdentityEmailTest:
    users: UserDirectory
    tests: IdentityEmailTests
    setup: IdentityEmailSetup
    queue: IdentityEmailQueue
    clock: Clock

    def execute(self, actor: UserId) -> None:
        require_administrator(self.users, actor)
        if self.setup.fingerprint is None:
            raise IdentityEmailNotConfigured
        if self.queue.state(actor) in {EmailTestState.QUEUED, EmailTestState.SENDING}:
            raise IdentityEmailQueueBusy
        test = self.tests.admit(actor, self.setup.fingerprint, self.clock.now())
        if not self.queue.submit(test):
            raise IdentityEmailQueueBusy


@dataclass(frozen=True, slots=True)
class DeliverIdentityEmailTest:
    users: UserDirectory
    tests: IdentityEmailTests
    setup: IdentityEmailSetup
    sender: IdentityTestSender
    clock: Clock

    def prepare(self, test: EmailTest) -> PreparedEmailTest | None:
        if test.fingerprint != self.setup.fingerprint:
            return None
        try:
            user = require_administrator(self.users, test.actor)
        except AdministratorRequired:
            return None
        return PreparedEmailTest(test, user.email) if user.email is not None else None

    def send(self, prepared: PreparedEmailTest) -> None:
        self.sender.send_test(prepared.recipient)

    def complete(self, prepared: PreparedEmailTest) -> bool:
        if prepared.test.fingerprint != self.setup.fingerprint:
            return False
        return self.tests.record_success(prepared.test, prepared.recipient, self.clock.now())
