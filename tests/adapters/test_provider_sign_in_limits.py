from datetime import timedelta
from pathlib import Path

import pytest

from calendar_sync.application.identity.provider_sign_in_ports import ProviderSignInThrottled
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.provider_sign_in_limits import (
    Boundary,
    SqliteProviderSignInLimits,
)
from calendar_sync.infrastructure.security import CredentialCipher
from tests.fakes.oidc import FixedClock


@pytest.mark.parametrize(
    ("boundary", "limit"), [("begin", 20), ("callback", 20), ("confirmation", 10)]
)
def test_denied_flood_does_not_write(tmp_path: Path, boundary: Boundary, limit: int) -> None:
    path = tmp_path / "limits.db"
    initialize_database(path)
    clock = FixedClock()
    key = CredentialCipher.generate_key()
    service = SqliteProviderSignInLimits(path, key, clock)
    for _ in range(limit):
        service.admit("2001:db8::1", boundary)
    with transaction(path) as connection:
        before = connection.execute("SELECT COUNT(*) FROM provider_sign_in_attempts").fetchone()[0]
    for _ in range(100):
        with pytest.raises(ProviderSignInThrottled):
            service.admit("2001:db8::2", boundary)
    with transaction(path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM provider_sign_in_attempts").fetchone()[0]
            == before
        )
    restarted = SqliteProviderSignInLimits(path, key, clock)
    with pytest.raises(ProviderSignInThrottled):
        restarted.admit("2001:db8::3", boundary)
    clock.value += timedelta(minutes=15)
    restarted.admit("2001:db8::1", boundary)


def test_global_budget_and_purpose_separation(tmp_path: Path) -> None:
    path = tmp_path / "limits.db"
    initialize_database(path)
    service = SqliteProviderSignInLimits(path, CredentialCipher.generate_key(), FixedClock())
    for number in range(100):
        service.admit(f"192.0.2.{number}", "begin")
    with pytest.raises(ProviderSignInThrottled):
        service.admit("198.51.100.1", "begin")
    service.admit("198.51.100.1", "callback")
    service.admit("198.51.100.1", "confirmation")
    with transaction(path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM provider_sign_in_attempts").fetchone()[0]
            == 102
        )


def test_front_gate_refuses_new_networks_without_storage(tmp_path: Path) -> None:
    path = tmp_path / "limits.db"
    initialize_database(path)
    service = SqliteProviderSignInLimits(
        path, CredentialCipher.generate_key(), FixedClock(), capacity=1
    )
    service.admit("192.0.2.1", "begin")
    with transaction(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        # Storage is locked: a new network must still be refused by the front gate.
        with pytest.raises(ProviderSignInThrottled):
            service.admit("192.0.2.2", "begin")


def test_limit_wait_and_purge_are_bounded(tmp_path: Path) -> None:
    from calendar_sync.application.identity.provider_sign_in_ports import ProviderSignInUnavailable

    path = tmp_path / "limits.db"
    initialize_database(path)
    clock = FixedClock()
    service = SqliteProviderSignInLimits(path, CredentialCipher.generate_key(), clock)
    with transaction(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(ProviderSignInUnavailable):
            service.admit("192.0.2.1", "begin")
        connection.executemany(
            "INSERT INTO provider_sign_in_attempts(boundary, network_digest, admitted_at) "
            "VALUES ('begin', 'synthetic', ?)",
            [(clock.now().timestamp() - 3600,)] * 300,
        )
    assert service.purge(clock.now(), 1000) == 250
    assert service.purge(clock.now(), 1000) == 50
