"""Bound anonymous identity traffic before any persistent write."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from calendar_sync.application.identity.reset_admission import ResetNetworkThrottled
from calendar_sync.infrastructure.identity_front_gate import MemoryIdentityFrontGate, client_network
from tests.adapters.test_password_reset_store import ResetClock


def test_front_gate_capacity_refuses_without_eviction() -> None:
    clock = ResetClock()
    gate = MemoryIdentityFrontGate(clock, capacity=2)
    for _ in range(20):
        gate.admit("192.0.2.1", "request")
    gate.admit("192.0.2.2", "completion")
    with pytest.raises(ResetNetworkThrottled):
        gate.admit("192.0.2.3", "request")
    with pytest.raises(ResetNetworkThrottled):
        gate.admit("192.0.2.1", "request")
    clock.moment += timedelta(minutes=15)
    gate.admit("192.0.2.3", "request")


def test_front_gate_concurrent_capacity() -> None:
    gate = MemoryIdentityFrontGate(ResetClock(), capacity=10)

    def admit(value: int) -> bool:
        try:
            gate.admit(f"192.0.2.{value}", "request")
        except ResetNetworkThrottled:
            return False
        return True

    with ThreadPoolExecutor(max_workers=16) as pool:
        assert sum(pool.map(admit, range(100))) == 10


def test_front_gate_default_capacity_is_ten_thousand() -> None:
    gate = MemoryIdentityFrontGate(ResetClock())
    for value in range(10_000):
        gate.admit(f"2001:db8:{value:x}::", "request")
    with pytest.raises(ResetNetworkThrottled):
        gate.admit("192.0.2.1", "completion")


def test_front_gate_boundaries_and_windows_are_independent() -> None:
    clock = ResetClock()
    gate = MemoryIdentityFrontGate(clock)
    for _ in range(20):
        gate.admit("192.0.2.1", "request")
    for _ in range(10):
        gate.admit("192.0.2.1", "completion")
    for _ in range(20):
        assert not gate.check_token("192.0.2.1", lambda: False)
    for boundary in ("request", "invalid-token", "completion"):
        with pytest.raises(ResetNetworkThrottled) as error:
            gate.admit("192.0.2.1", boundary)
        assert error.value.retry_after == 900
    clock.moment += timedelta(minutes=15)
    gate.admit("192.0.2.1", "request")
    gate.admit("192.0.2.1", "completion")
    assert not gate.check_token("192.0.2.1", lambda: False)


def test_valid_token_checks_do_not_consume_invalid_budget() -> None:
    gate = MemoryIdentityFrontGate(ResetClock())
    for _ in range(40):
        assert gate.check_token("192.0.2.1", lambda: True)
    for _ in range(20):
        assert not gate.check_token("192.0.2.1", lambda: False)
    with pytest.raises(ResetNetworkThrottled):
        gate.check_token("192.0.2.1", lambda: pytest.fail("lookup after throttle"))


def test_ipv6_64_grouping() -> None:
    assert client_network("2001:db8:abcd:1234::1") == "2001:db8:abcd:1234::/64"
    assert client_network("2001:db8:abcd:1234:ffff::2") == client_network("2001:db8:abcd:1234::1")
    assert client_network("2001:db8:abcd:1235::1") != client_network("2001:db8:abcd:1234::1")
    assert client_network("::ffff:192.0.2.1") == client_network("192.0.2.1")
    gate = MemoryIdentityFrontGate(ResetClock())
    for value in range(20):
        gate.admit(f"2001:db8:abcd:1234::{value:x}", "request")
    with pytest.raises(ResetNetworkThrottled):
        gate.admit("2001:db8:abcd:1234::ff", "request")


@pytest.mark.parametrize("value", ["", "nonsense", "192.0.2.1:123", "fe80::1%en0", "2001:db8::/32"])
def test_malformed_clients_share_unknown_key(value: str) -> None:
    assert client_network(value) == "unknown"


def test_token_callback_runs_outside_inventory_mutex() -> None:
    gate = MemoryIdentityFrontGate(ResetClock())
    with ThreadPoolExecutor(max_workers=1) as pool:

        def callback() -> bool:
            pool.submit(gate.admit, "192.0.2.2", "completion").result(timeout=1)
            return True

        assert gate.check_token("192.0.2.1", callback)


def test_concurrent_invalid_callbacks_admit_exactly_twenty() -> None:
    from threading import Barrier

    gate = MemoryIdentityFrontGate(ResetClock())
    ready = Barrier(24)

    def callback() -> bool:
        ready.wait(timeout=2)
        return False

    def check(_: int) -> bool:
        try:
            assert not gate.check_token("192.0.2.1", callback)
        except ResetNetworkThrottled:
            return False
        return True

    with ThreadPoolExecutor(max_workers=24) as pool:
        assert sum(pool.map(check, range(24))) == 20
