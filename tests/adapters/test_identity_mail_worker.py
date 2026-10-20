"""A bounded identity sender survives cancellation without late readiness commits."""

import asyncio
import logging
import threading
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
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.identity_mail_worker import IdentityMailWorker
from tests.adapters.test_users_store import FIRST
from tests.application.test_identity_email import Sender, services
from tests.helpers import NOW
from tests.identity_email_fakes import MemoryIdentityEmailTests


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
        for value in (*secret.split(), str(FIRST.id), FIRST.email, attempt.id, attempt.fingerprint):
            assert value is not None
            assert value not in fields

    asyncio.run(run())
