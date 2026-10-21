"""A bounded identity sender survives cancellation without late readiness commits."""

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from calendar_sync.application.identity.identity_email import (
    DeliverIdentityEmailTest,
    EmailTest,
    EmailTestState,
    IdentityEmailDeliveryFailed,
    IdentityEmailSetup,
    IdentityEmailStorageUnavailable,
)
from calendar_sync.application.identity.password_reset import (
    DeliverPasswordReset,
    PreparedPasswordReset,
    ResetEmailRequest,
)
from calendar_sync.application.identity.ports import IssuedLink
from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.identity_mail_worker import IdentityMailWorker
from calendar_sync.infrastructure.persistence.connections import transaction
from tests.adapters.test_users_store import FIRST
from tests.application.test_identity_email import Sender, services
from tests.helpers import NOW
from tests.identity_email_fakes import MemoryIdentityEmailTests


class ResetSender:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_reset(self, recipient: str, token: str) -> None:
        self.sent.append(recipient)


class ResetStore:
    def issue_for_email(self, email: str) -> PreparedPasswordReset:
        return PreparedPasswordReset(email, IssuedLink("reset", "synthetic-token", NOW))


def test_reset_and_test_lanes_have_separate_capacity_and_fair_turns(tmp_path: Path) -> None:
    class OrderedSender(BarrierSender):
        def send_test(self, recipient: str) -> None:
            super().send_test(recipient)
            order.append("test")

        def send_reset(self, recipient: str, token: str) -> None:
            order.append("reset")

    async def run() -> None:
        users, tests, _, clock = services(tmp_path)
        sender = OrderedSender()
        worker = IdentityMailWorker(
            DeliverIdentityEmailTest(
                users, tests, IdentityEmailSetup("current", None), sender, clock
            ),
            tests,
            clock,
            reset_delivery=DeliverPasswordReset(
                ResetStore(), IdentityEmailSetup("current", None), sender
            ),
        )
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        worker.submit(tests.admit(FIRST.id, "current", NOW))
        await checkpoint(sender.started.is_set)
        for index in range(50):
            assert worker.submit_reset(ResetEmailRequest(f"{index}@example.test", "current"))
        assert not worker.submit_reset(ResetEmailRequest("full@example.test", "current"))
        for index in range(10):
            assert worker.submit(EmailTest(str(index), UserId(str(index)), 0, "current"))
        assert not worker.submit(EmailTest("full", UserId("full"), 0, "current"))
        # Every synthetic actor is eligible for this queue-scheduling test.
        for index in range(10):
            users.add(replace(FIRST, id=UserId(str(index)), email=f"{index}@example.test"), "hash")
        sender.release.set()
        await checkpoint(lambda: len(order) == 61)
        assert order[:21] == ["test", *[lane for _ in range(10) for lane in ("reset", "test")]]
        await stop(worker, task)
        assert not worker.submit_reset(ResetEmailRequest("stopped@example.test", "current"))

    from dataclasses import replace

    order: list[str] = []
    asyncio.run(run())


def test_cancelled_reset_preparation_cannot_send_on_restart(tmp_path: Path) -> None:
    class BlockedStore(ResetStore):
        def issue_for_email(self, email: str) -> PreparedPasswordReset:
            preparations.append(email)
            started.set()
            assert release.wait(5)
            return super().issue_for_email(email)

    started, release = threading.Event(), threading.Event()
    preparations: list[str] = []
    sender = ResetSender()
    worker, _, _ = worker_services(tmp_path)
    worker._reset_delivery = DeliverPasswordReset(
        BlockedStore(), IdentityEmailSetup("current", None), sender
    )

    async def run() -> None:
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        assert worker.submit_reset(ResetEmailRequest("private@example.test", "current"))
        await checkpoint(started.is_set)
        await stop(worker, task)
        restarted = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        assert worker.submit_reset(ResetEmailRequest("new@example.test", "current"))
        await asyncio.sleep(0.02)
        assert preparations == ["private@example.test"]
        release.set()
        await checkpoint(lambda: sender.sent == ["new@example.test"])
        assert preparations == ["private@example.test", "new@example.test"]
        await stop(worker, restarted)

    asyncio.run(run())


def test_cleanup_backlog_gives_both_mail_lanes_a_turn(tmp_path: Path) -> None:
    from unittest.mock import Mock

    order: list[str] = []

    class SenderWithOrder(Sender):
        def send_test(self, recipient: str) -> None:
            order.append("test")

        def send_reset(self, recipient: str, token: str) -> None:
            order.append("reset")

    def purge(before: datetime, limit: int) -> int:
        assert limit == 500
        order.append("purge")
        return 500 if order.count("purge") < 3 else 0

    async def run() -> None:
        users, tests, _, clock = services(tmp_path)
        sender = SenderWithOrder()
        admission = Mock()
        admission.purge.side_effect = purge
        worker = IdentityMailWorker(
            DeliverIdentityEmailTest(
                users, tests, IdentityEmailSetup("current", None), sender, clock
            ),
            tests,
            clock,
            reset_delivery=DeliverPasswordReset(
                ResetStore(), IdentityEmailSetup("current", None), sender
            ),
            reset_admission=admission,
        )
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        assert worker.submit(tests.admit(FIRST.id, "current", NOW))
        assert worker.submit_reset(ResetEmailRequest("private@example.test", "current"))
        await checkpoint(lambda: order.count("purge") == 3)
        assert order == ["purge", "test", "purge", "reset", "purge"]
        await stop(worker, task)

    asyncio.run(run())


def test_reset_preparation_lock_does_not_block_event_loop(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    database = tmp_path / "busy.db"
    adapters = build_adapters(Settings(database))
    adapters.users.add(FIRST, "hash")
    sender = ResetSender()
    worker, _, _ = worker_services(tmp_path)
    worker._reset_delivery = DeliverPasswordReset(
        adapters.self_service_resets, IdentityEmailSetup("current", None), sender
    )

    async def run() -> None:
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        # Wait until maintenance finishes so this measures preparation's lock budget.
        await asyncio.sleep(0.02)
        with transaction(database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            started = time.monotonic()
            assert worker.submit_reset(ResetEmailRequest(FIRST.email or "", "current"))
            ticks = 0
            while not caplog.records:
                ticks += 1
                await asyncio.sleep(0.005)
                assert time.monotonic() - started < 1
            elapsed = time.monotonic() - started
            assert 0.08 <= elapsed < 0.5
            assert ticks >= 5
        assert sender.sent == []
        with transaction(database) as connection:
            assert (
                connection.execute("SELECT COUNT(*) FROM password_reset_links").fetchone()[0] == 0
            )
        await stop(worker, task)

    asyncio.run(run())
    assert [record.getMessage() for record in caplog.records] == [
        "Identity password reset email failed"
    ]


def test_hourly_reset_purge_runs_off_loop_and_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import Mock

    class AdvancingClock:
        at = NOW

        def now(self) -> datetime:
            return self.at

    async def run() -> None:
        worker, tests, _ = worker_services(tmp_path)
        clock = AdvancingClock()
        worker._clock = clock
        admission = Mock()
        main_thread = threading.get_ident()
        observed: list[tuple[datetime, int]] = []

        def purge(before: datetime, limit: int) -> int:
            assert threading.get_ident() != main_thread
            observed.append((before, limit))
            return 500 if len(observed) == 1 else 0

        admission.purge.side_effect = purge
        worker._reset_admission = admission
        original = tests.purge

        def test_purge(before: datetime, limit: int) -> int:
            assert threading.get_ident() != main_thread
            return original(before, limit)

        monkeypatch.setattr(tests, "purge", test_purge)
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: len(observed) == 2)
        assert observed == [(NOW, 500), (NOW, 500)]
        clock.at += timedelta(hours=1)
        assert worker.submit(EmailTest("wake", FIRST.id, 0, "stale"))
        await checkpoint(lambda: len(observed) == 3)
        assert observed[-1] == (clock.at, 500)
        await stop(worker, task)

    asyncio.run(run())


def test_keyed_unconfigured_lifespan_purges_without_scheduler_or_smtp(tmp_path: Path) -> None:
    from dataclasses import replace
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from calendar_sync.bootstrap.container import compose
    from calendar_sync.infrastructure.security import CredentialCipher
    from calendar_sync.interfaces.api.app import create_app

    database = tmp_path / "maintenance.db"
    settings = Settings(database, master_key=CredentialCipher.generate_key())
    adapters = build_adapters(settings)
    adapters.users.add(FIRST, "synthetic")
    with transaction(database) as connection:
        connection.executemany(
            "INSERT INTO reset_request_attempts(boundary, network_digest, admitted_at) "
            "VALUES ('completion', ?, 0)",
            [(f"synthetic-digest-{index}",) for index in range(1201)],
        )
        connection.executemany(
            "INSERT INTO email_change_network_attempts(boundary, network_digest, admitted_at) "
            "VALUES ('completion', ?, 0)",
            [(f"synthetic-digest-{index}",) for index in range(1201)],
        )
        connection.executemany(
            "INSERT INTO email_change_attempts(user_id, target_digest, admitted_at) "
            "VALUES (?, ?, 0)",
            [(FIRST.id.value, f"synthetic-digest-{index}") for index in range(1201)],
        )
        connection.executemany(
            "INSERT INTO email_change_proofs(id, user_id, proposed_email, credential_revision, "
            "created_at, expires_at) VALUES (?, ?, 'new@example.test', 0, ?, ?)",
            [
                (
                    f"expired-{index}",
                    FIRST.id.value,
                    "2000-01-01T00:00:00+00:00",
                    "2000-01-02T00:00:00+00:00",
                )
                for index in range(1201)
            ],
        )
    container = replace(compose(settings, adapters), scheduler=None, scheduler_watch=None)
    worker = container.identity_mail_worker
    assert worker is not None

    def remaining() -> int:
        with transaction(database) as connection:
            return sum(
                int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in (
                    "reset_request_attempts",
                    "email_change_network_attempts",
                    "email_change_attempts",
                    "email_change_proofs",
                )
            )

    with patch("calendar_sync.infrastructure.identity_email.smtplib.SMTP") as smtp:
        with TestClient(create_app(container)):
            deadline = time.monotonic() + 5
            while remaining():
                assert time.monotonic() < deadline
                time.sleep(0.005)
            assert worker.running
            assert not worker.submit(EmailTest("no-send", FIRST.id, 0, "stale"))
            assert not worker.submit_reset(ResetEmailRequest("private@example.test", "stale"))
            assert not container.identity_email.configured
        assert not worker.running
        smtp.assert_not_called()


def test_composed_request_reaches_current_user_with_committed_proof(tmp_path: Path) -> None:
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from calendar_sync.bootstrap.container import compose
    from calendar_sync.infrastructure.security import CredentialCipher
    from calendar_sync.interfaces.api.app import create_app

    database = tmp_path / "composed.db"
    delivered = threading.Event()
    recipients: list[str] = []

    class CommittedSender(Sender):
        def send_reset(self, recipient: str, token: str) -> None:
            with transaction(database) as connection:
                connection.execute("BEGIN IMMEDIATE")
                proof = connection.execute(
                    "SELECT created_by, created_at, expires_at FROM password_reset_links"
                ).fetchone()
                assert proof["created_by"] is None
                assert datetime.fromisoformat(proof["expires_at"]) - datetime.fromisoformat(
                    proof["created_at"]
                ) == timedelta(hours=1)
            assert adapters.password_resets.owner(token, adapters.clock.now()) == FIRST.id
            recipients.append(recipient)
            delivered.set()

    settings = Settings(
        database,
        master_key=CredentialCipher.generate_key(),
        smtp_host="localhost",
        smtp_sender="ghost@example.test",
        smtp_recipient="operator@example.test",
        public_url="https://ghost.test",
    )
    adapters = build_adapters(settings)
    adapters.users.add(replace(FIRST, notify_by_email=False), "synthetic")
    adapters = replace(
        adapters, identity_email=replace(adapters.identity_email, sender=CommittedSender())
    )
    container = replace(compose(settings, adapters), scheduler=None, scheduler_watch=None)
    with TestClient(create_app(container)):
        container.identity_email.request_reset.execute(FIRST.email or "", "192.0.2.1")
        assert delivered.wait(5)
    assert recipients == [FIRST.email]


@pytest.mark.parametrize("phase", ["prepare", "send"])
def test_reset_failure_is_lossy_and_logs_no_secrets(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, phase: str
) -> None:
    from unittest.mock import Mock

    async def run() -> None:
        worker, tests, _ = worker_services(tmp_path)
        sender = Mock()
        resets = Mock(wraps=ResetStore())
        secret = "private@example.test synthetic-token synthetic-password body"
        if phase == "prepare":
            resets.issue_for_email.side_effect = RuntimeError(secret)
        else:
            sender.send_reset.side_effect = RuntimeError(secret)
        worker._reset_delivery = DeliverPasswordReset(
            resets, IdentityEmailSetup("current", None), sender
        )
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        assert worker.submit_reset(ResetEmailRequest("private@example.test", "current"))
        await checkpoint(lambda: len(caplog.records) == 1)
        # No retry, readiness write, or public delivery status accompanies a failure.
        await asyncio.sleep(0.02)
        assert resets.issue_for_email.call_count == 1
        assert sender.send_reset.call_count == (phase == "send")
        assert tests.readiness is None
        await stop(worker, task)
        fields = repr(vars(caplog.records[0]))
        assert caplog.records[0].getMessage() == "Identity password reset email failed"
        assert caplog.records[0].exc_info is None
        assert all(value not in fields for value in secret.split())

    asyncio.run(run())


class BarrierSender(Sender):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.fail = False

    def send_test(self, recipient: str) -> None:
        self.started.set()
        assert self.release.wait(5), "test did not release SMTP barrier"
        super().send_test(recipient)
        self.finished.set()
        if self.fail:
            raise IdentityEmailDeliveryFailed


async def checkpoint(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0)


def worker_services(
    tmp_path: Path,
) -> tuple[IdentityMailWorker, MemoryIdentityEmailTests, BarrierSender]:
    users, tests, _, clock = services(tmp_path)
    sender = BarrierSender()
    delivery = DeliverIdentityEmailTest(
        users, tests, IdentityEmailSetup("current", None), sender, clock
    )
    return IdentityMailWorker(delivery, tests, clock), tests, sender


async def stop(worker: IdentityMailWorker, task: asyncio.Task[None]) -> None:
    worker.stop()
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def test_enqueue_is_not_success(tmp_path: Path) -> None:
    async def run() -> None:
        worker, tests, sender = worker_services(tmp_path)
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        assert worker.submit(tests.admit(FIRST.id, "current", NOW))
        await checkpoint(sender.started.is_set)
        assert tests.tested_at("current") is None
        assert worker.state(FIRST.id) is EmailTestState.SENDING
        await stop(worker, task)
        sender.release.set()

    asyncio.run(run())


def test_test_queue_capacity_and_duplicate_actor(tmp_path: Path) -> None:
    async def run() -> None:
        worker, _, sender = worker_services(tmp_path)
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        first = EmailTest("first", FIRST.id, 0, "current")
        assert worker.submit(first)
        await checkpoint(sender.started.is_set)
        assert not worker.submit(first)
        for index in range(10):
            assert worker.submit(EmailTest(str(index), UserId(str(index)), 0, "current"))
        assert not worker.submit(EmailTest("full", UserId("full"), 0, "current"))
        await stop(worker, task)
        assert worker.state(FIRST.id) is EmailTestState.IDLE
        assert not worker.submit(first)
        sender.release.set()

    asyncio.run(run())


def test_slow_mail_does_not_block_api_or_other_tasks(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def run() -> None:
        worker, tests, sender = worker_services(tmp_path)
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        # FastAPI synchronous endpoints submit from a worker thread.
        assert await asyncio.to_thread(worker.submit, tests.admit(FIRST.id, "current", NOW))
        await checkpoint(sender.started.is_set)
        assert await asyncio.to_thread(worker.state, FIRST.id) is EmailTestState.SENDING
        progressed = asyncio.Event()
        asyncio.get_running_loop().call_soon(progressed.set)
        await progressed.wait()
        sender.release.set()
        await checkpoint(lambda: worker.state(FIRST.id) is EmailTestState.ACCEPTED)
        assert tests.tested_at("current") == NOW
        await stop(worker, task)

    asyncio.run(run())
    assert not caplog.records


def test_shutdown_during_send_never_records_late_success(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def run() -> None:
        worker, tests, sender = worker_services(tmp_path)
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        worker.submit(tests.admit(FIRST.id, "current", NOW))
        await checkpoint(sender.started.is_set)
        await stop(worker, task)
        sender.release.set()
        await checkpoint(sender.finished.is_set)
        assert tests.tested_at("current") is None

    asyncio.run(run())
    assert not caplog.records


def test_restart_drops_pending_without_refunding_allowance(tmp_path: Path) -> None:
    class RestartSender(BarrierSender):
        def __init__(self) -> None:
            super().__init__()
            self.second_started = threading.Event()
            self.second_release = threading.Event()

        def send_test(self, recipient: str) -> None:
            if self.finished.is_set():
                self.second_started.set()
                assert self.second_release.wait(5)
            super().send_test(recipient)

    users, tests, _, clock = services(tmp_path)
    sender = RestartSender()
    delivery = DeliverIdentityEmailTest(
        users, tests, IdentityEmailSetup("current", None), sender, clock
    )
    worker = IdentityMailWorker(delivery, tests, clock)

    async def first_lifespan() -> None:
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        worker.submit(tests.admit(FIRST.id, "current", NOW))
        await checkpoint(sender.started.is_set)
        worker.submit(EmailTest("pending", UserId("pending"), 0, "current"))
        await stop(worker, task)

    asyncio.run(first_lifespan())

    async def second_lifespan() -> None:
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        assert worker.state(UserId("pending")) is EmailTestState.IDLE
        assert len(tests.attempts) == 1
        assert worker.submit(tests.admit(FIRST.id, "current", NOW))
        # An old send finishes on a new loop. Its completion cannot mark readiness.
        assert len(sender.recipients) == 0
        sender.release.set()
        await checkpoint(sender.second_started.is_set)
        assert tests.tested_at("current") is None
        sender.second_release.set()
        await checkpoint(lambda: worker.state(FIRST.id) is EmailTestState.ACCEPTED)
        assert len(sender.recipients) == 2
        assert len(tests.attempts) == 2
        await stop(worker, task)

    asyncio.run(second_lifespan())


def test_setup_reset_during_send_stays_unready(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def run() -> None:
        worker, tests, sender = worker_services(tmp_path)
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        worker.submit(tests.admit(FIRST.id, "current", NOW))
        await checkpoint(sender.started.is_set)
        tests.return_to_setup()
        sender.release.set()
        await checkpoint(lambda: worker.state(FIRST.id) is EmailTestState.FAILED)
        assert tests.tested_at("current") is None
        await stop(worker, task)

    asyncio.run(run())
    assert not caplog.records


def test_transient_failure_preserves_previous_success(tmp_path: Path) -> None:
    async def run() -> None:
        worker, tests, sender = worker_services(tmp_path)
        tests.readiness = ("current", NOW - timedelta(days=1))
        sender.fail = True
        sender.release.set()
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        worker.submit(tests.admit(FIRST.id, "current", NOW))
        await checkpoint(lambda: worker.state(FIRST.id) is EmailTestState.FAILED)
        assert tests.tested_at("current") == NOW - timedelta(days=1)
        await stop(worker, task)

    asyncio.run(run())


def test_send_success_with_failed_storage_stays_unready(tmp_path: Path) -> None:
    class FailedStore(MemoryIdentityEmailTests):
        def record_success(self, test: EmailTest, recipient: str, at: datetime) -> bool:
            raise IdentityEmailStorageUnavailable

    async def run() -> None:
        users, _, _, clock = services(tmp_path)
        tests = FailedStore({FIRST.id: FIRST})
        sender = BarrierSender()
        sender.release.set()
        delivery = DeliverIdentityEmailTest(
            users, tests, IdentityEmailSetup("current", None), sender, clock
        )
        worker = IdentityMailWorker(delivery, tests, clock)
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        assert worker.submit(tests.admit(FIRST.id, "current", NOW))
        await checkpoint(lambda: worker.state(FIRST.id) is EmailTestState.FAILED)
        assert sender.recipients == [FIRST.email]
        assert tests.tested_at("current") is None
        await stop(worker, task)

    asyncio.run(run())


def test_status_capacity_expiry_and_hourly_purge(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class AdvancingClock:
        at = NOW

        def now(self) -> datetime:
            return self.at

    class PurgeStore(MemoryIdentityEmailTests):
        def __init__(self) -> None:
            super().__init__({FIRST.id: FIRST})
            self.calls: list[tuple[datetime, int]] = []
            self.batches = [500, 500, 1]

        def purge(self, before: datetime, limit: int) -> int:
            self.calls.append((before, limit))
            return self.batches.pop(0) if self.batches else 0

    async def run() -> None:
        users, _, _, _ = services(tmp_path)
        clock = AdvancingClock()
        tests = PurgeStore()
        sender = Sender()
        delivery = DeliverIdentityEmailTest(
            users, tests, IdentityEmailSetup("current", None), sender, clock
        )
        worker = IdentityMailWorker(delivery, tests, clock)
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: len(tests.calls) == 3)
        assert tests.calls == [(NOW - timedelta(hours=1), 500)] * 3
        # Invalid dispatches still finish, but the status cache must remain bounded.
        for index in range(101):
            actor = UserId(str(index))
            assert worker.submit(EmailTest(str(index), actor, 0, "stale"))

            def finished(current: UserId = actor) -> bool:
                return worker.state(current) is EmailTestState.FAILED

            await checkpoint(finished)
        assert worker.state(UserId("0")) is EmailTestState.IDLE
        assert worker.state(UserId("1")) is EmailTestState.FAILED
        assert len(tests.calls) == 3
        clock.at += timedelta(minutes=15)
        assert worker.state(UserId("100")) is EmailTestState.IDLE
        clock.at += timedelta(minutes=45)
        assert worker.submit(EmailTest("hour", UserId("hour"), 0, "stale"))
        await checkpoint(lambda: len(tests.calls) == 4)
        assert tests.calls[-1] == (NOW, 500)
        await stop(worker, task)

    asyncio.run(run())
    assert not caplog.records


def test_stopping_worker_rejects_overlapping_loop_ownership(tmp_path: Path) -> None:
    async def run() -> None:
        worker, tests, sender = worker_services(tmp_path)
        first = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        worker.submit(tests.admit(FIRST.id, "current", NOW))
        await checkpoint(sender.started.is_set)
        worker.stop()
        second = asyncio.create_task(worker.run_forever())
        try:
            await asyncio.sleep(0)
            assert second.done()
            with pytest.raises(RuntimeError, match="already running"):
                await second
        finally:
            if not second.done():
                await stop(worker, second)
            await stop(worker, first)
            sender.release.set()

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["prepare", "send", "complete"])
def test_delivery_failures_log_only_a_safe_category(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    secret = "synthetic-password-token smtp.private.example body recipient@example.test"

    def fail(*args: object) -> None:
        raise RuntimeError(secret)

    async def run() -> None:
        worker, tests, sender = worker_services(tmp_path)
        if phase == "prepare":
            monkeypatch.setattr(DeliverIdentityEmailTest, "prepare", fail)
        elif phase == "send":
            monkeypatch.setattr(sender, "send_test", fail)
        else:
            monkeypatch.setattr(tests, "record_success", fail)
        sender.release.set()
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        attempt = tests.admit(FIRST.id, "current", NOW)
        assert worker.submit(attempt)
        await checkpoint(lambda: worker.state(FIRST.id) is EmailTestState.FAILED)
        assert tests.tested_at("current") is None
        assert sender.recipients == ([FIRST.email] if phase == "complete" else [])
        await stop(worker, task)
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.name == "calendar_sync.infrastructure.identity_mail_worker"
        assert record.levelno == logging.WARNING
        assert record.getMessage() == "Identity email test failed"
        assert record.args == ()
        assert record.exc_info is None
        assert record.exc_text is None
        assert record.stack_info is None
        # Inspect every field, including logging arguments and traceback attachments.
        fields = repr(vars(record))
        for value in (
            *secret.split(),
            FIRST.id.value,
            FIRST.email,
            attempt.id,
            attempt.fingerprint,
        ):
            assert value is not None
            assert value not in fields

    asyncio.run(run())


def test_security_lane_is_bounded_and_fair(tmp_path: Path) -> None:
    from unittest.mock import Mock

    from calendar_sync.application.identity.email_changes import (
        EmailChangedNotice,
        EmailChangeMailRequest,
        PreparedEmailChange,
    )
    from calendar_sync.infrastructure.identity_email_changes import (
        EmailChangeDelivery,
        EmailChangeMaintenance,
    )

    order: list[str] = []

    class OrderedSender(BarrierSender):
        def send_test(self, recipient: str) -> None:
            super().send_test(recipient)
            order.append("test")

        def send_reset(self, recipient: str, token: str) -> None:
            order.append("reset")

        def send_email_change(self, recipient: str, token: str) -> None:
            order.append("change")

        def send_email_changed(self, recipient: str) -> None:
            order.append("notice")

    async def run() -> None:
        users, tests, _, clock = services(tmp_path)
        sender = OrderedSender()
        proofs = Mock()
        proofs.prepare.return_value = PreparedEmailChange("new@example.test", "synthetic-token")
        worker = IdentityMailWorker(
            DeliverIdentityEmailTest(
                users, tests, IdentityEmailSetup("current", None), sender, clock
            ),
            tests,
            clock,
            reset_delivery=DeliverPasswordReset(
                ResetStore(), IdentityEmailSetup("current", None), sender
            ),
            email_changes=EmailChangeMaintenance(
                EmailChangeDelivery(proofs, IdentityEmailSetup("current", None), sender),
                proofs,
                Mock(),
            ),
        )
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        assert worker.submit(tests.admit(FIRST.id, "current", NOW))
        await checkpoint(sender.started.is_set)
        for index in range(5):
            assert worker.submit_change(EmailChangeMailRequest(str(index), "current"))
            assert worker.submit_notice(EmailChangedNotice("old@example.test"))
        assert not worker.submit(EmailTest("full", UserId("full"), 0, "current"))
        assert not worker.submit_change(EmailChangeMailRequest("full", "current"))
        assert not worker.submit_notice(EmailChangedNotice("full@example.test"))
        for index in range(50):
            assert worker.submit_reset(ResetEmailRequest(f"{index}@example.test", "current"))
        assert not worker.submit_reset(ResetEmailRequest("full@example.test", "current"))
        sender.release.set()
        await checkpoint(lambda: len(order) == 61)
        assert order[:21] == [
            "test",
            *[kind for _ in range(5) for kind in ("reset", "change", "reset", "notice")],
        ]
        await stop(worker, task)
        assert not worker.submit_change(EmailChangeMailRequest("stopped", "current"))
        assert not worker.submit_notice(EmailChangedNotice("stopped@example.test"))

    asyncio.run(run())


def test_change_preparation_is_off_loop_and_stopped_generation_cannot_send(tmp_path: Path) -> None:
    from unittest.mock import Mock

    from calendar_sync.application.identity.email_changes import (
        EmailChangeMailRequest,
        PreparedEmailChange,
    )
    from calendar_sync.infrastructure.identity_email_changes import (
        EmailChangeDelivery,
        EmailChangeMaintenance,
    )

    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    sender = Mock()
    proofs = Mock()

    def prepare(request_id: str) -> PreparedEmailChange:
        started.set()
        assert release.wait(5)
        finished.set()
        return PreparedEmailChange("new@example.test", "synthetic-token")

    proofs.prepare.side_effect = prepare
    worker, _, _ = worker_services(tmp_path)
    worker._email_changes = EmailChangeMaintenance(
        EmailChangeDelivery(proofs, IdentityEmailSetup("current", None), sender), proofs, Mock()
    )

    async def run() -> None:
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        assert worker.submit_change(EmailChangeMailRequest("pending", "current"))
        await checkpoint(started.is_set)
        await asyncio.sleep(0)
        await stop(worker, task)
        restarted = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        release.set()
        await checkpoint(finished.is_set)
        await asyncio.sleep(0.02)
        sender.send_email_change.assert_not_called()
        await stop(worker, restarted)

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["change", "notice", "prepare"])
def test_email_change_failure_is_lossy_and_private(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, kind: str
) -> None:
    from unittest.mock import Mock

    from calendar_sync.application.identity.email_changes import (
        EmailChangedNotice,
        EmailChangeMailRequest,
        PreparedEmailChange,
    )
    from calendar_sync.infrastructure.identity_email_changes import (
        EmailChangeDelivery,
        EmailChangeMaintenance,
    )

    secret = "private@example.test synthetic-token synthetic-password provider-marker body"
    sender, proofs = Mock(), Mock()
    proofs.prepare.return_value = PreparedEmailChange("private@example.test", "synthetic-token")
    if kind == "prepare":
        proofs.prepare.side_effect = RuntimeError(secret)
    sender.send_email_change.side_effect = RuntimeError(secret)
    sender.send_email_changed.side_effect = RuntimeError(secret)
    worker, _, _ = worker_services(tmp_path)
    worker._email_changes = EmailChangeMaintenance(
        EmailChangeDelivery(proofs, IdentityEmailSetup("current", None), sender), proofs, Mock()
    )

    async def run() -> None:
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: worker.running)
        if kind in {"change", "prepare"}:
            assert worker.submit_change(EmailChangeMailRequest("pending", "current"))
        else:
            assert worker.submit_notice(EmailChangedNotice("private@example.test"))
        await checkpoint(lambda: len(caplog.records) == 1)
        await asyncio.sleep(0.02)
        assert sender.send_email_change.call_count == (kind == "change")
        assert sender.send_email_changed.call_count == (kind == "notice")
        assert all(value not in repr(vars(caplog.records[0])) for value in secret.split())
        assert caplog.records[0].exc_info is None
        await stop(worker, task)

    asyncio.run(run())


def test_email_change_cleanup_has_bounded_fair_turns_without_smtp(tmp_path: Path) -> None:
    from unittest.mock import Mock

    from calendar_sync.infrastructure.identity_email_changes import EmailChangeMaintenance

    async def run() -> None:
        _, tests, _, clock = services(tmp_path)
        proofs, admission, reset = Mock(), Mock(), Mock()
        proofs.purge.side_effect = [500, 500, 1, 0]
        admission.purge.side_effect = [500, 0, 0, 0]
        reset.purge.side_effect = [500, 0, 0]
        calls: list[str] = []

        def record(label: str, batches: list[int]) -> Callable[[datetime, int], int]:
            def purge(before: datetime, limit: int) -> int:
                assert limit == 500
                calls.append(label)
                return batches.pop(0)

            return purge

        proofs.purge.side_effect = record("proofs", [500, 500, 1])
        admission.purge.side_effect = record("admission", [500, 0, 0])
        reset.purge.side_effect = record("reset", [500, 0])
        worker = IdentityMailWorker(
            None,
            tests,
            clock,
            reset_admission=reset,
            email_changes=EmailChangeMaintenance(None, proofs, admission),
        )
        task = asyncio.create_task(worker.run_forever())
        await checkpoint(lambda: proofs.purge.call_count == 3)
        assert calls == [
            "reset",
            "proofs",
            "admission",
            "reset",
            "proofs",
            "admission",
            "proofs",
            "admission",
        ]
        assert proofs.purge.call_args.args == (clock.now(), 500)
        assert not worker.submit(EmailTest("no-send", FIRST.id, 0, "current"))
        await stop(worker, task)

    asyncio.run(run())
