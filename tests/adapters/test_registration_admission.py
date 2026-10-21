"""Registration allowances are durable, bounded and independent of recovery."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from time import monotonic
from typing import cast
from unittest.mock import patch

import pytest

from calendar_sync.application.identity.registration_admission import (
    RegistrationGlobalThrottled,
    RegistrationNetworkThrottled,
)
from calendar_sync.application.identity.registration_ports import RegistrationStorageUnavailable
from calendar_sync.infrastructure.identity_front_gate import MemoryIdentityFrontGate
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.registration_admission import (
    SqliteRegistrationAdmission,
)
from calendar_sync.infrastructure.security import (
    CredentialCipher,
    RegistrationAdmissionDigests,
    ResetAdmissionDigests,
)
from tests.adapters.test_registration_store import registration
from tests.adapters.test_users_store import MovableClock

MASTER = CredentialCipher.generate_key()


def admission(tmp_path: Path) -> SqliteRegistrationAdmission:
    database, clock, _, _, _ = registration(tmp_path)
    return SqliteRegistrationAdmission(database, MASTER, clock)


def test_exact_limits_cooldown_and_generic_suppression(tmp_path: Path) -> None:
    gate = admission(tmp_path)
    assert gate.admit_durable("new@example.test", "192.0.2.1")
    assert not gate.admit_durable("new@example.test", "192.0.2.2")
    for index in range(1, 5):
        cast(MovableClock, gate._clock).moment += timedelta(seconds=60)
        assert gate.admit_durable("new@example.test", f"192.0.2.{index}")
    cast(MovableClock, gate._clock).moment += timedelta(seconds=60)
    assert not gate.admit_durable("new@example.test", "192.0.2.99")
    assert gate.admit_durable("pair@example.test", "192.0.2.1")
    for expected in [True, False]:
        cast(MovableClock, gate._clock).moment += timedelta(seconds=60)
        assert gate.admit_durable("pair@example.test", "192.0.2.1") is expected
    for index in range(20):
        assert gate.admit_durable(f"{index}@example.test", "198.51.100.1")
    with pytest.raises(RegistrationNetworkThrottled) as error:
        gate.admit_durable("excess@example.test", "198.51.100.1")
    assert error.value.retry_after == 900
    # Successful checks refund neither invalid attempts nor password completions.
    for _ in range(20):
        assert not gate.check_token("203.0.113.1", lambda: False)
    with pytest.raises(RegistrationNetworkThrottled):
        gate.check_token("203.0.113.1", lambda: True)
    for _ in range(10):
        gate.admit_completion("203.0.113.2")
    with pytest.raises(RegistrationNetworkThrottled):
        gate.admit_completion("203.0.113.2")
    from calendar_sync.infrastructure.persistence.reset_admission import SqliteResetAdmission

    reset = SqliteResetAdmission(gate._database, MASTER, gate._clock)
    assert reset.admit("new@example.test", "198.51.100.1")


def test_concurrent_limits_survive_restart_and_clock_rollback(tmp_path: Path) -> None:
    gate = admission(tmp_path)
    restarted = SqliteRegistrationAdmission(gate._database, MASTER, gate._clock)
    with ThreadPoolExecutor(max_workers=8) as pool:
        allowed = list(
            pool.map(
                lambda i: restarted.admit_durable("same@example.test", f"192.0.2.{i}"), range(8)
            )
        )
    assert sum(allowed) == 1
    cast(MovableClock, gate._clock).moment -= timedelta(minutes=1)
    assert not gate.admit_durable("same@example.test", "192.0.2.99")
    for index in range(99):
        assert gate.admit_durable(f"{index}@example.test", f"198.51.100.{index}")
    with pytest.raises(RegistrationGlobalThrottled):
        gate.admit_durable("excess@example.test", "203.0.113.1")


def test_ipv6_network_and_capacity(tmp_path: Path) -> None:
    gate = admission(tmp_path)
    gate._gate = MemoryIdentityFrontGate(gate._clock, capacity=1)
    for _ in range(20):
        gate.admit_front("2001:db8:1::1")
    with pytest.raises(RegistrationNetworkThrottled):
        gate.admit_front("2001:db8:1::2")
    with pytest.raises(RegistrationNetworkThrottled):
        gate.admit_front("2001:db8:2::1")
    cast(MovableClock, gate._clock).moment += timedelta(minutes=15)
    gate.admit_front("2001:db8:2::1")


def test_front_gate_denial_never_opens_sqlite(tmp_path: Path) -> None:
    gate = admission(tmp_path)
    for _ in range(20):
        gate.admit_front("192.0.2.1")
    with (
        patch(
            "calendar_sync.infrastructure.persistence.registration_admission.transaction",
            side_effect=AssertionError("denied request opened SQLite"),
        ),
        pytest.raises(RegistrationNetworkThrottled),
    ):
        gate.admit_front("192.0.2.1")


def test_hmac_purpose_separation() -> None:
    key = CredentialCipher.generate_key()
    signup, reset = RegistrationAdmissionDigests(key), ResetAdmissionDigests(key)
    assert signup.digest("email", "same") != reset.digest("email", "same")
    assert signup.digest("email", "same") != signup.digest("network", "same")
    assert signup.digest("pair", "a", "bc") != signup.digest("pair", "ab", "c")


def test_lock_contention_rolls_back_within_short_timeout(tmp_path: Path) -> None:
    gate = admission(tmp_path)
    with transaction(gate._database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        started = monotonic()
        with pytest.raises(RegistrationStorageUnavailable):
            gate.admit_durable("new@example.test", "192.0.2.1")
        assert monotonic() - started < 0.5
    assert gate.admit_durable("new@example.test", "192.0.2.1")


def test_cleanup_failure_preserves_committed_admission(tmp_path: Path) -> None:
    gate = admission(tmp_path)
    with (
        patch(
            "calendar_sync.infrastructure.persistence.registration_admission.purge_registration_proofs",
            side_effect=RuntimeError("maintenance failure"),
        ),
        patch.object(gate, "purge", wraps=gate.purge) as counters,
    ):
        assert gate.admit_durable("new@example.test", "192.0.2.1")
    counters.assert_called_once_with(gate._clock.now(), 250)
    assert not gate.admit_durable("new@example.test", "192.0.2.1")
