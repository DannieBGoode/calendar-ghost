"""Independent, bounded and durable email-change allowances."""

from datetime import timedelta
from pathlib import Path

import pytest

from calendar_sync.application.identity.email_change_admission import EmailChangeThrottled
from calendar_sync.infrastructure.persistence.email_change_admission import EmailChangeAdmission
from calendar_sync.infrastructure.security import (
    CredentialCipher,
    EmailChangeAdmissionDigests,
    ResetAdmissionDigests,
)
from tests.adapters.test_email_change_store import setup


def test_issuance_limits_survive_cancel_restart_and_hour_boundary(tmp_path: Path) -> None:
    path, clock, _h, _store, expected, session = setup(tmp_path)
    from calendar_sync.infrastructure.persistence.email_changes import SqliteEmailChangeProofs
    from tests.adapters.test_users_store import SequentialIds

    key = CredentialCipher.generate_key()
    store = SqliteEmailChangeProofs(path, SequentialIds(), clock, master_key=key)
    for index in range(5):
        pending = store.request(expected, f"target-{index}@example.test", session.token)
        store.cancel(expected.user_id, pending.id)
    store = SqliteEmailChangeProofs(path, SequentialIds(), clock, master_key=key)
    with pytest.raises(EmailChangeThrottled) as error:
        store.request(expected, "sixth@example.test", session.token)
    assert error.value.retry_after == 3600
    clock.moment += timedelta(hours=1)
    assert store.request(expected, "sixth@example.test", session.token)


def test_target_cooldown_across_users(tmp_path: Path) -> None:
    _path, clock, h, store, expected, session = setup(tmp_path)
    from tests.adapters.test_users_store import FIRST

    other = h.changes.current(FIRST.id)
    assert other
    other_session = h.sessions.start(
        other.user_id, other.password_hash, other.email, other.revision
    )
    assert other_session
    store.request(expected, "same@example.test", session.token)
    with pytest.raises(EmailChangeThrottled):
        store.request(other, "same@example.test", other_session.token)
    clock.moment += timedelta(seconds=60)
    assert store.request(other, "same@example.test", other_session.token)


@pytest.mark.parametrize(
    ("boundary", "limit"), [("request", 20), ("invalid", 20), ("completion", 10)]
)
def test_network_limits_restart_and_ipv6(tmp_path: Path, boundary: str, limit: int) -> None:
    path, clock, *_ = setup(tmp_path)
    key = CredentialCipher.generate_key()
    admission = EmailChangeAdmission(path, key, clock)

    def attempt(gate: EmailChangeAdmission, network: str) -> None:
        if boundary == "request":
            gate.admit_request(network)
        elif boundary == "invalid":
            assert not gate.check_token(network, lambda: False)
        else:
            gate.admit_completion(network)

    for _ in range(limit):
        attempt(admission, "2001:db8::1")
    restarted = EmailChangeAdmission(path, key, clock)
    with pytest.raises(EmailChangeThrottled):
        attempt(restarted, "2001:db8::2")
    clock.moment += timedelta(minutes=15)
    attempt(restarted, "2001:db8::2")


def test_valid_checks_do_not_consume_and_hmac_is_separate(tmp_path: Path) -> None:
    path, clock, *_ = setup(tmp_path)
    key = CredentialCipher.generate_key()
    admission = EmailChangeAdmission(path, key, clock)
    for _ in range(25):
        assert admission.check_token("127.0.0.1", lambda: True)
    assert EmailChangeAdmissionDigests(key).digest("network", "a") != ResetAdmissionDigests(
        key
    ).digest("network", "a")
    assert EmailChangeAdmissionDigests(key).digest("network", "a") != EmailChangeAdmissionDigests(
        key
    ).digest("target", "a")


def test_front_gate_capacity_and_refused_flood_do_not_touch_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from calendar_sync.infrastructure.persistence import email_change_admission

    path, clock, *_ = setup(tmp_path)
    admission = EmailChangeAdmission(path, CredentialCipher.generate_key(), clock, capacity=1)
    for _ in range(20):
        admission.admit_request("192.0.2.1")

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("front-gate refusal reached SQLite")

    monkeypatch.setattr(email_change_admission, "email_change_transaction", forbidden)
    for _ in range(25):
        with pytest.raises(EmailChangeThrottled):
            admission.admit_request("192.0.2.1")
        with pytest.raises(EmailChangeThrottled):
            admission.admit_request("192.0.2.2")


def test_cleanup_failure_does_not_revoke_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from calendar_sync.application.identity.email_change_admission import (
        EmailChangeStorageUnavailable,
    )

    path, clock, *_ = setup(tmp_path)
    admission = EmailChangeAdmission(path, CredentialCipher.generate_key(), clock)

    def failed(*args: object) -> int:
        raise EmailChangeStorageUnavailable

    monkeypatch.setattr(admission, "purge", failed)
    admission.admit_request("192.0.2.1")
    admission.admit_completion("192.0.2.1")
    assert not admission.check_token("192.0.2.1", lambda: False)


def test_purge_is_bounded_preserves_live_allowances_and_contains_only_digests(
    tmp_path: Path,
) -> None:
    from calendar_sync.infrastructure.persistence.connections import transaction

    path, clock, _h, store, expected, session = setup(tmp_path)
    admission = EmailChangeAdmission(path, CredentialCipher.generate_key(), clock)
    store.request(expected, "private@example.test", session.token)
    admission.admit_completion("192.0.2.1")
    with transaction(path) as connection:
        network = tuple(
            connection.execute("SELECT * FROM email_change_network_attempts").fetchone()
        )
        issuance = tuple(connection.execute("SELECT * FROM email_change_attempts").fetchone())
        assert "192.0.2.1" not in repr(network)
        assert "private@example.test" not in repr(issuance)
        connection.executemany(
            "INSERT INTO email_change_network_attempts(boundary, network_digest, admitted_at) "
            "VALUES ('request', 'old-digest', ?)",
            [(clock.now().timestamp() - 901,)] * 600,
        )
    assert admission.purge(clock.now() + timedelta(days=10), 900) == 500
    assert admission.purge(clock.now(), 500) == 100
    assert admission.purge(clock.now(), 500) == 0
    clock.moment += timedelta(hours=1)
    assert admission.purge(clock.now(), 500) == 2


def test_concurrent_requests_share_user_allowance(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    _path, _clock, _h, store, expected, session = setup(tmp_path)

    def request(index: int) -> bool:
        try:
            store.request(expected, f"concurrent-{index}@example.test", session.token)
            return True
        except EmailChangeThrottled:
            return False

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(request, range(6))) == 5


def test_reset_admission_is_independent_and_capacity_survives_restart(tmp_path: Path) -> None:
    from calendar_sync.infrastructure.persistence.reset_admission import SqliteResetAdmission

    path, clock, *_ = setup(tmp_path)
    key = CredentialCipher.generate_key()
    admission = EmailChangeAdmission(path, key, clock, capacity=1)
    reset = SqliteResetAdmission(path, key, clock)
    for _ in range(10):
        admission.admit_completion("192.0.2.1")
    reset.admit_completion("192.0.2.1")
    restarted = EmailChangeAdmission(path, key, clock, capacity=1)
    with pytest.raises(EmailChangeThrottled):
        restarted.admit_completion("192.0.2.2")
    with pytest.raises(EmailChangeThrottled):
        restarted.admit_completion("192.0.2.1")


def test_email_admission_lock_failure_is_bounded(tmp_path: Path) -> None:
    import time

    from calendar_sync.application.identity.email_change_admission import (
        EmailChangeStorageUnavailable,
    )
    from calendar_sync.infrastructure.persistence.connections import transaction

    path, clock, *_ = setup(tmp_path)
    admission = EmailChangeAdmission(path, CredentialCipher.generate_key(), clock)
    with transaction(path) as locked:
        locked.execute("BEGIN IMMEDIATE")
        start = time.monotonic()
        with pytest.raises(EmailChangeStorageUnavailable):
            admission.admit_request("192.0.2.1")
        assert time.monotonic() - start < 0.5


def test_success_does_not_refund_issuance(tmp_path: Path) -> None:
    _path, _clock, h, store, expected, session = setup(tmp_path)
    for index in range(5):
        pending = store.request(expected, f"issued-{index}@example.test", session.token)
    prepared = store.prepare(pending.id)
    assert prepared
    assert store.confirm(expected, prepared.token, session.token)
    current = h.changes.current(expected.user_id)
    assert current
    with pytest.raises(EmailChangeThrottled):
        store.request(current, "sixth@example.test", session.token)
