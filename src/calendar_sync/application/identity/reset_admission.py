"""Anonymous reset admission, separate from sign-in and Invitation allowances."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from calendar_sync.application.shared.errors import ApplicationError, InfrastructureFailure
from calendar_sync.application.shared.ports import Clock

ResetBoundary = Literal["request", "invalid-token", "completion"]
PURGE_BATCH = 500


class ResetNetworkThrottled(ApplicationError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Reset network allowance exhausted")
        self.retry_after = retry_after


class ResetGlobalThrottled(ApplicationError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Reset global allowance exhausted")
        self.retry_after = retry_after


class ResetAdmissionStorageUnavailable(InfrastructureFailure):
    def __init__(self) -> None:
        super().__init__("Reset admission storage unavailable")


class IdentityFrontGate(Protocol):
    def admit(self, network: str, boundary: ResetBoundary) -> None: ...

    def check_token(self, network: str, check: Callable[[], bool]) -> bool:
        """Check capacity/quota first; consume only a false callback, outside the mutex."""
        ...


class ResetAdmissionAttempts(Protocol):
    def admit(self, email: str, network: str) -> bool:
        """Atomically check all request budgets, recording only an admitted request.

        False silently suppresses email cooldown and email/pair exhaustion. Network/global
        exhaustion raises typed throttling, checked independently of any User or eligibility.
        """
        ...

    def check_invalid(self, network: str) -> None:
        """Read the invalid-token allowance before looking up a proof."""
        ...

    def record_invalid(self, network: str) -> None:
        """Atomically check and consume an invalid-token attempt, with no success refund."""
        ...

    def admit_completion(self, network: str) -> None:
        """Consume before any proof lookup or hashing, even for a valid proof."""
        ...

    def purge(self, before: datetime, limit: int) -> int:
        """Bounded cleanup of obsolete counters and expired/consumed/revoked reset proofs.

        Clamp the cutoff to the current clock so a caller cannot remove a live allowance.
        """
        ...


@dataclass(frozen=True, slots=True)
class ResetAdmission:
    gate: IdentityFrontGate
    attempts: ResetAdmissionAttempts | None
    clock: Clock

    def admit(self, email: str, network: str) -> bool:
        self.gate.admit(network, "request")
        if self.attempts is None:
            raise ResetAdmissionStorageUnavailable
        admitted = self.attempts.admit(email, network)
        if admitted:
            self._maintain()
        return admitted

    def check_token(self, network: str, check: Callable[[], bool]) -> bool:
        def checked() -> bool:
            if self.attempts is not None:
                self.attempts.check_invalid(network)
            return check()

        valid = self.gate.check_token(network, checked)
        if not valid and self.attempts is not None:
            self.attempts.record_invalid(network)
        self._maintain()
        return valid

    def admit_completion(self, network: str) -> None:
        self.gate.admit(network, "completion")
        if self.attempts is not None:
            self.attempts.admit_completion(network)
        self._maintain()

    def purge(self, before: datetime, limit: int) -> int:
        return self.attempts.purge(before, min(limit, PURGE_BATCH)) if self.attempts else 0

    def _maintain(self) -> None:
        self.purge(self.clock.now(), PURGE_BATCH)
