"""Recovery admission orchestrates memory and durable boundaries without User lookup."""

from collections.abc import Callable
from datetime import datetime

import pytest

from calendar_sync.application.identity.reset_admission import (
    ResetAdmission,
    ResetAdmissionStorageUnavailable,
    ResetNetworkThrottled,
)
from calendar_sync.infrastructure.identity_front_gate import MemoryIdentityFrontGate
from tests.adapters.test_password_reset_store import ResetClock


class Attempts:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def admit(self, email: str, network: str) -> bool:
        self.calls.append("request")
        return True

    def check_invalid(self, network: str) -> None:
        self.calls.append("precheck")

    def record_invalid(self, network: str) -> None:
        self.calls.append("invalid")

    def admit_completion(self, network: str) -> None:
        self.calls.append("completion")

    def purge(self, before: datetime, limit: int) -> int:
        self.calls.append("purge")
        assert limit == 500
        return 0


def test_front_gate_denied_flood_never_writes() -> None:
    clock = ResetClock()
    attempts = Attempts()
    admission = ResetAdmission(MemoryIdentityFrontGate(clock), attempts, clock)
    for _ in range(20):
        assert admission.admit("synthetic@example.test", "192.0.2.1")
    calls = list(attempts.calls)
    for _ in range(100):
        with pytest.raises(ResetNetworkThrottled):
            admission.admit("other@example.test", "192.0.2.1")
    assert attempts.calls == calls


def test_administrator_reset_without_master_key_uses_memory_limits() -> None:
    clock = ResetClock()
    admission = ResetAdmission(MemoryIdentityFrontGate(clock), None, clock)
    assert admission.check_token("192.0.2.1", lambda: True)
    admission.admit_completion("192.0.2.1")
    for _ in range(20):
        assert not admission.check_token("192.0.2.1", lambda: False)
    with pytest.raises(ResetNetworkThrottled):
        admission.check_token("192.0.2.1", lambda: True)
    for _ in range(9):
        admission.admit_completion("192.0.2.1")
    with pytest.raises(ResetNetworkThrottled):
        admission.admit_completion("192.0.2.1")
    with pytest.raises(ResetAdmissionStorageUnavailable):
        admission.admit("synthetic@example.test", "192.0.2.2")
    assert admission.purge(clock.now(), 500) == 0


def test_invalid_callback_is_checked_then_counted_and_valid_is_not_counted() -> None:
    clock = ResetClock()
    attempts = Attempts()
    admission = ResetAdmission(MemoryIdentityFrontGate(clock), attempts, clock)

    def check(valid: bool) -> Callable[[], bool]:
        def callback() -> bool:
            attempts.calls.append("lookup")
            return valid

        return callback

    assert admission.check_token("192.0.2.1", check(True))
    assert attempts.calls == ["precheck", "lookup", "purge"]
    attempts.calls.clear()
    assert not admission.check_token("192.0.2.1", check(False))
    assert attempts.calls == ["precheck", "lookup", "invalid", "purge"]
    attempts.calls.clear()
    admission.admit_completion("192.0.2.1")
    assert attempts.calls == ["completion", "purge"]
