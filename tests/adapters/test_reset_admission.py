"""Rolling reset counters are anonymous, transactional, and durable."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest

from calendar_sync.application.identity.reset_admission import (
    ResetAdmission,
    ResetAdmissionStorageUnavailable,
    ResetGlobalThrottled,
    ResetNetworkThrottled,
)
from calendar_sync.infrastructure.identity_front_gate import MemoryIdentityFrontGate
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.migrations import initialize_database
from calendar_sync.infrastructure.persistence.reset_admission import SqliteResetAdmission
from calendar_sync.infrastructure.security import CredentialCipher, ResetAdmissionDigests
from tests.adapters.test_password_reset_store import ResetClock, _sqlite_identity
from tests.adapters.test_users_store import FIRST, SECOND

KEY = CredentialCipher.generate_key()


def store(tmp_path: Path) -> tuple[Path, ResetClock, SqliteResetAdmission]:
    path = tmp_path / "admission.db"
    initialize_database(path)
    clock = ResetClock()
    return path, clock, SqliteResetAdmission(path, KEY, clock)


def count(path: Path) -> int:
    with transaction(path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM reset_request_attempts").fetchone()[0])


def test_email_five_per_hour_and_sixty_second_cooldown(tmp_path: Path) -> None:
    path, clock, attempts = store(tmp_path)
    for index in range(5):
        assert attempts.admit("person@example.test", f"192.0.2.{index}")
        assert not attempts.admit("person@example.test", "198.51.100.1")
        clock.moment += timedelta(seconds=60)
    assert not attempts.admit("person@example.test", "198.51.100.1")
    assert count(path) == 5
    clock.moment += timedelta(seconds=3300)
    assert attempts.admit("person@example.test", "198.51.100.1")


def test_pair_limit_is_two_per_rolling_hour(tmp_path: Path) -> None:
    path, clock, attempts = store(tmp_path)
    assert attempts.admit("person@example.test", "192.0.2.1")
    clock.moment += timedelta(seconds=60)
    assert attempts.admit("person@example.test", "192.0.2.1")
    clock.moment += timedelta(seconds=60)
    assert not attempts.admit("person@example.test", "192.0.2.1")
    assert attempts.admit("person@example.test", "192.0.2.2")
    assert count(path) == 3
    clock.moment += timedelta(seconds=3480)
    assert attempts.admit("person@example.test", "192.0.2.1")


def test_network_twenty_per_fifteen_minutes_is_account_independent(tmp_path: Path) -> None:
    path, clock, attempts = store(tmp_path)
    for index in range(20):
        assert attempts.admit(f"unknown-{index}@example.test", "192.0.2.1")
    with pytest.raises(ResetNetworkThrottled) as error:
        attempts.admit("another-unknown@example.test", "192.0.2.1")
    assert error.value.retry_after == 900
    assert count(path) == 20
    clock.moment += timedelta(minutes=15)
    assert attempts.admit("another-unknown@example.test", "192.0.2.1")


def test_two_networks_can_exhaust_global_reset_budget(tmp_path: Path) -> None:
    path, clock, h = _sqlite_identity(tmp_path)
    attempts = SqliteResetAdmission(path, KEY, clock)
    start = clock.now()
    for batch in range(5):
        clock.moment = start + timedelta(minutes=15 * (batch // 2))
        network = "192.0.2.1" if batch % 2 == 0 else "192.0.2.2"
        for index in range(20):
            assert attempts.admit(f"unknown-{batch}-{index}@example.test", network)
    assert count(path) == 100
    for email in (SECOND.email or "", "not-a-user@example.test"):
        with pytest.raises(ResetGlobalThrottled) as error:
            attempts.admit(email, "192.0.2.2")
        assert error.value.retry_after == 1800
    # Global email exhaustion changes neither hand-delivered link issuance nor completion.
    link = h.links.issue(SECOND.id, FIRST.id, clock.now())
    admission = ResetAdmission(MemoryIdentityFrontGate(clock), attempts, clock)
    assert admission.check_token(
        "192.0.2.2", lambda: h.links.owner(link.token, clock.now()) is not None
    )
    admission.admit_completion("192.0.2.2")
    assert h.links.reset(link.token, "new-hash") == SECOND.id


def test_limits_survive_restart_and_concurrent_admission(tmp_path: Path) -> None:
    path, clock, _ = store(tmp_path)

    def admit(index: int) -> bool:
        attempts = SqliteResetAdmission(path, KEY, clock)
        try:
            return attempts.admit(f"unknown-{index}@example.test", "192.0.2.1")
        except ResetNetworkThrottled:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(admit, range(40))) == 20
    assert count(path) == 20
    with pytest.raises(ResetNetworkThrottled):
        SqliteResetAdmission(path, KEY, clock).admit("unknown-new@example.test", "192.0.2.1")


@pytest.mark.parametrize(("boundary", "limit"), [("invalid-token", 20), ("completion", 10)])
def test_boundary_limits_persist_without_smtp_and_do_not_refund(
    tmp_path: Path, boundary: str, limit: int
) -> None:
    path, clock, attempts = store(tmp_path)
    for _ in range(limit):
        if boundary == "invalid-token":
            attempts.check_invalid("192.0.2.1")
            attempts.record_invalid("192.0.2.1")
        else:
            attempts.admit_completion("192.0.2.1")
    reopened = SqliteResetAdmission(path, KEY, clock)
    blocked = reopened.check_invalid if boundary == "invalid-token" else reopened.admit_completion
    with pytest.raises(ResetNetworkThrottled) as error:
        blocked("192.0.2.1")
    assert error.value.retry_after == 900
    assert count(path) == limit
    clock.moment += timedelta(minutes=15)
    if boundary == "invalid-token":
        reopened.record_invalid("192.0.2.1")
    else:
        reopened.admit_completion("192.0.2.1")


def test_valid_checks_never_consume_invalid_allowance_and_completion_counts_valid(
    tmp_path: Path,
) -> None:
    path, clock, attempts = store(tmp_path)
    admission = ResetAdmission(MemoryIdentityFrontGate(clock), attempts, clock)
    for _ in range(50):
        assert admission.check_token("192.0.2.1", lambda: True)
    assert count(path) == 0
    for _ in range(10):
        admission.admit_completion("192.0.2.1")
    with pytest.raises(ResetNetworkThrottled):
        admission.admit_completion("192.0.2.1")
    assert count(path) == 10


def test_storage_lock_is_one_hundred_ms_and_does_not_increment(tmp_path: Path) -> None:
    path, _, attempts = store(tmp_path)
    with transaction(path) as locked:
        locked.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        with pytest.raises(
            ResetAdmissionStorageUnavailable, match="Reset admission storage unavailable"
        ):
            attempts.admit("private@example.test", "192.0.2.1")
        elapsed = time.monotonic() - started
    assert 0.08 <= elapsed < 0.5
    assert count(path) == 0


@pytest.mark.parametrize("operation", ["request", "invalid", "completion", "precheck", "purge"])
def test_storage_fault_is_generic_and_rolls_back(tmp_path: Path, operation: str) -> None:
    path, clock, attempts = store(tmp_path)
    with transaction(path) as connection:
        connection.execute(
            "CREATE TRIGGER refuse_counter BEFORE INSERT ON reset_request_attempts "
            "BEGIN SELECT RAISE(ABORT, 'private-sqlite-fault'); END"
        )
        if operation in {"precheck", "purge"}:
            connection.execute("DROP TABLE reset_request_attempts")

    def attempt() -> None:
        if operation == "request":
            attempts.admit("private@example.test", "192.0.2.1")
        elif operation == "invalid":
            attempts.record_invalid("192.0.2.1")
        elif operation == "completion":
            attempts.admit_completion("192.0.2.1")
        elif operation == "precheck":
            attempts.check_invalid("192.0.2.1")
        else:
            attempts.purge(clock.now(), 500)

    with pytest.raises(ResetAdmissionStorageUnavailable) as error:
        attempt()
    assert "private" not in str(error.value)
    assert error.value.__cause__ is None
    if operation not in {"precheck", "purge"}:
        assert count(path) == 0


def test_digests_have_purpose_category_and_unambiguous_pair_framing() -> None:
    digests = ResetAdmissionDigests(KEY)
    assert digests.digest("email", "same") != digests.digest("network", "same")
    assert digests.digest("pair", "ab", "c") != digests.digest("pair", "a", "bc")
    assert digests.digest("email", "same") == ResetAdmissionDigests(KEY).digest("email", "same")
    assert digests.digest("email", "same") != ResetAdmissionDigests(
        CredentialCipher.generate_key()
    ).digest("email", "same")


def test_counter_schema_contains_only_hmac_digests_and_time(tmp_path: Path) -> None:
    path, _, attempts = store(tmp_path)
    assert attempts.admit("private@example.test", "2001:db8:abcd:1234::1")
    attempts.record_invalid("192.0.2.1")
    attempts.admit_completion("192.0.2.1")
    with transaction(path) as connection:
        rows = [dict(row) for row in connection.execute("SELECT * FROM reset_request_attempts")]
        assert set(rows[0]) == {
            "id",
            "boundary",
            "admitted_at",
            "email_digest",
            "network_digest",
            "pair_digest",
        }
        assert len(str(rows[0]["email_digest"])) == 64
        for row in rows[1:]:
            assert row["email_digest"] is None
            assert row["pair_digest"] is None
        assert "private@example.test" not in str(rows)
        assert "2001:db8" not in str(rows)
        assert "192.0.2.1" not in str(rows)


def test_purge_is_bounded_never_deletes_live_allowance_and_cleans_proofs(tmp_path: Path) -> None:
    path, clock, h = _sqlite_identity(tmp_path)
    attempts = SqliteResetAdmission(path, KEY, clock)
    for index in range(3):
        assert attempts.admit(f"person-{index}@example.test", "192.0.2.1")
    link = h.links.issue(SECOND.id, FIRST.id, clock.now())
    assert attempts.purge(clock.now() + timedelta(days=20), 500) == 0
    assert h.links.reset(link.token, "new-hash") == SECOND.id
    assert attempts.purge(clock.now(), 500) == 1
    clock.moment += timedelta(hours=1)
    assert attempts.purge(clock.now(), 2) == 2
    assert count(path) == 1
    assert attempts.purge(clock.now(), 500) == 1
    assert attempts.purge(clock.now(), 500) == 0
    assert attempts.purge(clock.now(), 0) == 0


def test_identity_traffic_runs_bounded_maintenance(tmp_path: Path) -> None:
    path, clock, attempts = store(tmp_path)
    admission = ResetAdmission(MemoryIdentityFrontGate(clock), attempts, clock)
    assert admission.admit("first@example.test", "192.0.2.1")
    clock.moment += timedelta(days=1)
    assert admission.admit("second@example.test", "192.0.2.1")
    assert count(path) == 1


@pytest.mark.parametrize(("boundary", "cap"), [("invalid-token", 20), ("completion", 10)])
def test_durable_boundary_concurrent_admission_is_exact(
    tmp_path: Path, boundary: str, cap: int
) -> None:
    path, clock, _ = store(tmp_path)

    def consume(_: int) -> bool:
        reopened = SqliteResetAdmission(path, KEY, clock)
        action = (
            reopened.record_invalid if boundary == "invalid-token" else reopened.admit_completion
        )
        try:
            action("192.0.2.1")
        except ResetNetworkThrottled:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(consume, range(30))) == cap
    assert count(path) == cap


def test_dropped_queue_work_and_proof_success_never_refund_request(tmp_path: Path) -> None:
    path, clock, h = _sqlite_identity(tmp_path)
    attempts = SqliteResetAdmission(path, KEY, clock)
    assert attempts.admit(SECOND.email or "", "192.0.2.1")
    prepared = h.public.issue_for_email(SECOND.email or "")
    assert prepared is not None
    assert h.links.reset(prepared.link.token, "new-hash") == SECOND.id
    assert not attempts.admit(SECOND.email or "", "192.0.2.2")
    clock.moment += timedelta(seconds=60)
    # This admitted request is deliberately never submitted to a delivery queue.
    assert attempts.admit(SECOND.email or "", "192.0.2.1")
    clock.moment += timedelta(seconds=60)
    reopened = SqliteResetAdmission(path, KEY, clock)
    assert not reopened.admit(SECOND.email or "", "192.0.2.1")
    assert count(path) == 2


def test_rollback_of_clock_does_not_refund_live_counters(tmp_path: Path) -> None:
    _, clock, attempts = store(tmp_path)
    for index in range(20):
        assert attempts.admit(f"person-{index}@example.test", "192.0.2.1")
    clock.moment -= timedelta(minutes=15)
    with pytest.raises(ResetNetworkThrottled) as error:
        attempts.admit("other@example.test", "192.0.2.1")
    assert error.value.retry_after == 1800


def test_purge_batch_cannot_exceed_five_hundred(tmp_path: Path) -> None:
    path, clock, attempts = store(tmp_path)
    with transaction(path) as connection:
        connection.executemany(
            "INSERT INTO reset_request_attempts(boundary, network_digest, admitted_at) "
            "VALUES ('invalid-token', 'synthetic-digest', ?)",
            [(clock.now().timestamp() - 3600,) for _ in range(501)],
        )
    assert attempts.purge(clock.now(), 1000) == 500
    assert count(path) == 1
    assert attempts.purge(clock.now(), 1000) == 1


def test_ipv6_rotation_shares_durable_network_budget(tmp_path: Path) -> None:
    _, _, attempts = store(tmp_path)
    for value in range(20):
        assert attempts.admit(f"person-{value}@example.test", f"2001:db8:1234:abcd::{value:x}")
    with pytest.raises(ResetNetworkThrottled):
        attempts.admit("another@example.test", "2001:db8:1234:abcd::ffff")
    assert attempts.admit("another@example.test", "2001:db8:1234:abce::ffff")


def test_administrator_reset_without_master_key_uses_memory_limits(tmp_path: Path) -> None:
    path, clock, h = _sqlite_identity(tmp_path)
    link = h.links.issue(SECOND.id, FIRST.id, clock.now())
    admission = ResetAdmission(MemoryIdentityFrontGate(clock), None, clock)
    assert admission.check_token(
        "192.0.2.1", lambda: h.links.owner(link.token, clock.now()) == SECOND.id
    )
    admission.admit_completion("192.0.2.1")
    assert h.links.reset(link.token, "new-hash") == SECOND.id
    for _ in range(20):
        assert not admission.check_token(
            "192.0.2.1", lambda: h.links.owner("invalid-synthetic-proof", clock.now()) is not None
        )
    with pytest.raises(ResetNetworkThrottled):
        admission.check_token("192.0.2.1", lambda: pytest.fail("lookup after throttle"))
    assert count(path) == 0


@pytest.mark.parametrize("status", ["expired", "revoked"])
def test_purge_removes_only_obsolete_proofs(tmp_path: Path, status: str) -> None:
    path, clock, h = _sqlite_identity(tmp_path)
    attempts = SqliteResetAdmission(path, KEY, clock)
    first = h.links.issue(SECOND.id, FIRST.id, clock.now())
    if status == "expired":
        clock.moment = first.expires_at
        prepared = h.public.issue_for_email(SECOND.email or "")
        assert prepared is not None
        live = prepared.link
    else:
        live = h.links.issue(SECOND.id, FIRST.id, clock.now())
    assert attempts.purge(clock.now(), 500) == 1
    assert h.links.owner(live.token, clock.now()) == SECOND.id
    with transaction(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM password_reset_links").fetchone()[0] == 1
