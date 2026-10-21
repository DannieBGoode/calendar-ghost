"""Sign-up uses a separate volatile lane and bounded, scheduler-free maintenance."""

import asyncio
import threading
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from calendar_sync.application.identity.identity_email import EmailTest, IdentityEmailSetup
from calendar_sync.application.identity.password_reset import ResetEmailRequest
from calendar_sync.application.identity.registration import DeliverRegistration
from calendar_sync.application.identity.registration_ports import RegistrationEmailRequest
from calendar_sync.domain.access import RegistrationPolicy, UserId
from calendar_sync.infrastructure.identity_email import IdentitySmtp
from calendar_sync.infrastructure.identity_registration import RegistrationMaintenance
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.registration_admission import (
    SqliteRegistrationAdmission,
)
from calendar_sync.infrastructure.security import CredentialCipher
from tests.adapters.test_identity_mail_worker import checkpoint, stop, worker_services
from tests.adapters.test_registration_store import registration
from tests.adapters.test_users_store import FIRST


def test_three_lanes_are_fair_and_signup_cannot_exhaust_reset(tmp_path: Path) -> None:
    async def run() -> None:
        worker, _, _ = worker_services(tmp_path)
        worker._registrations = RegistrationMaintenance(Mock(), Mock(), Mock())
        worker._reset_delivery = Mock()
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        # Fill before the loop takes a turn. All three capacities are independent.
        for index in range(50):
            assert worker.submit_registration(
                RegistrationEmailRequest(f"{index}@example.test", "current")
            )
            assert worker.submit_reset(ResetEmailRequest(f"{index}@example.test", "current"))
        assert not worker.submit_registration(
            RegistrationEmailRequest("full@example.test", "current")
        )
        assert not worker.submit_reset(ResetEmailRequest("full@example.test", "current"))
        for index in range(10):
            assert worker.submit(EmailTest(str(index), UserId(str(index)), 0, "current"))
        assert not worker.submit(EmailTest("full", UserId("full"), 0, "current"))
        taken = [type(worker._take(asyncio.Event())) for _ in range(30)]
        assert taken == [
            kind
            for _ in range(10)
            for kind in (EmailTest, ResetEmailRequest, RegistrationEmailRequest)
        ]
        await stop(worker, task)
        assert not worker.submit_registration(
            RegistrationEmailRequest("stopped@example.test", "current")
        )

    asyncio.run(run())


def test_shutdown_generation_cannot_send(tmp_path: Path) -> None:
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    worker, _, _ = worker_services(tmp_path)
    delivery = Mock()

    def prepare(request: RegistrationEmailRequest) -> Mock:
        started.set()
        assert release.wait(5)
        finished.set()
        return Mock()

    delivery.prepare.side_effect = prepare
    worker._registrations = RegistrationMaintenance(delivery, Mock(), Mock())

    async def run() -> None:
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        assert worker.submit_registration(
            RegistrationEmailRequest("private@example.test", "current")
        )
        await checkpoint(started.is_set)
        # Preparation is off-loop: stop/restart remains responsive while its thread blocks.
        await stop(worker, task)
        restarted = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        release.set()
        await checkpoint(finished.is_set)
        await asyncio.sleep(0.02)
        delivery.send.assert_not_called()
        await stop(worker, restarted)

    asyncio.run(run())


@pytest.mark.parametrize("change", ["none", "fingerprint", "policy", "parent", "email"])
def test_prepare_rechecks_eligibility(tmp_path: Path, change: str) -> None:
    from calendar_sync.infrastructure.persistence.registration import SqliteInvitations
    from tests.adapters.test_registration_store import RandomIds

    database, clock, users, settings, proofs = registration(tmp_path)
    invitations = SqliteInvitations(database, RandomIds(), clock)
    invitation = invitations.issue(FIRST.id, clock.now())
    assert invitation
    sender = Mock()
    delivery = DeliverRegistration(proofs, IdentityEmailSetup("current", None), sender)
    if change == "policy":
        settings.set_policy(RegistrationPolicy.INVITATION_ONLY, actor=FIRST.id, fingerprint=None)
    elif change == "parent":
        invitations.revoke(invitation.id, clock.now())
    elif change == "email":
        users.set_email(FIRST.id, "new@example.test")
    request = RegistrationEmailRequest(
        "new@example.test", "stale" if change == "fingerprint" else "current", invitation.token
    )
    prepared = delivery.prepare(request)
    if change == "none":
        assert prepared
        # SMTP may acquire the writer lock because issuance has already committed.
        with transaction(database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            delivery.send(prepared)
        sender.send_registration.assert_called_once_with(prepared.recipient, prepared.link.token)
    else:
        assert prepared is None
        sender.send_registration.assert_not_called()


@pytest.mark.parametrize("failure", ["prepare", "send"])
def test_failure_logs_have_no_identity_content(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, failure: str
) -> None:
    delivery = Mock()
    secret = "private@example.test synthetic-token synthetic-password provider-marker body"
    getattr(delivery, failure).side_effect = RuntimeError(secret)
    worker, _, _ = worker_services(tmp_path)
    worker._registrations = RegistrationMaintenance(delivery, Mock(), Mock())

    async def run() -> None:
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        assert worker.submit_registration(
            RegistrationEmailRequest("private@example.test", "current")
        )
        await checkpoint(lambda: bool(caplog.records))
        assert all(word not in repr(vars(caplog.records[0])) for word in secret.split())
        assert caplog.records[0].exc_info is None
        await stop(worker, task)

    asyncio.run(run())


def test_cleanup_within_day_without_scheduler_or_smtp(tmp_path: Path) -> None:
    database, clock, _, _, proofs = registration(tmp_path)
    gate = SqliteRegistrationAdmission(database, CredentialCipher.generate_key(), clock)
    # More than 500 obsolete records in each store must drain over multiple turns.
    with transaction(gate._database) as connection:
        connection.executemany(
            "INSERT INTO registration_proofs(token_hash, email, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            [
                (
                    f"{i:064x}",
                    "new@example.test",
                    (gate._clock.now() - timedelta(days=2)).isoformat(),
                    (gate._clock.now() - timedelta(days=1)).isoformat(),
                )
                for i in range(1001)
            ],
        )
        connection.executemany(
            "INSERT INTO registration_request_attempts(boundary, admitted_at, network_digest) "
            "VALUES ('invalid-token', ?, 'obsolete')",
            [(gate._clock.now().timestamp() - 7200,)] * 1001,
        )
    worker, _, _ = worker_services(tmp_path / "worker")
    worker._clock = gate._clock
    worker._registrations = RegistrationMaintenance(None, proofs, gate)

    async def run() -> None:
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        # Continuing invalid traffic consumes only its own allowance, never proof retention.
        for index in range(5):
            assert not gate.check_token(f"192.0.2.{index}", lambda: False)
            await asyncio.sleep(0)

        def drained() -> bool:
            with transaction(gate._database) as connection:
                # Independent half-batches commit separately; observe both stores.
                return tuple(
                    connection.execute(
                        "SELECT (SELECT COUNT(*) FROM registration_proofs), "
                        "(SELECT COUNT(*) FROM registration_request_attempts)"
                    ).fetchone()
                ) == (0, 5)

        await checkpoint(drained)
        with transaction(gate._database) as connection:
            assert (
                connection.execute("SELECT COUNT(*) FROM registration_request_attempts").fetchone()[
                    0
                ]
                == 5
            )
        await stop(worker, task)

    asyncio.run(run())


@pytest.mark.parametrize("full", ["proofs", "counters"])
def test_counter_backlog_cannot_starve_proofs(full: str) -> None:
    proofs, counters = Mock(), Mock()
    maintenance = RegistrationMaintenance(None, proofs, counters)
    proofs.purge.return_value = 250 if full == "proofs" else 1
    counters.purge.return_value = 250 if full == "counters" else 1
    assert maintenance.purge(FIRST.created_at, 1000)
    proofs.purge.assert_called_once_with(FIRST.created_at, 250)
    counters.purge.assert_called_once_with(FIRST.created_at, 250)
    proofs.purge.side_effect = RuntimeError("store failure")
    counters.purge.return_value = 250
    assert maintenance.purge(FIRST.created_at, 500)
    assert counters.purge.call_count == 2


def test_verification_mail_has_validated_origin_and_literal_deadline() -> None:
    smtp = IdentitySmtp("localhost", 25, "ghost@example.test", "", "", False, "https://ghost.test/")
    with patch.object(IdentitySmtp, "_send") as send:
        smtp.send_registration("new@example.test", "synthetic-token")
    assert "https://ghost.test/verify-email#synthetic-token" in send.call_args.args[2]
    assert "within 24 hours" in send.call_args.args[2]
