"""Mail checkpoints let executor threads advance without extending their deadline."""

import asyncio
import selectors
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import call, patch

import pytest

from tests.adapters.test_identity_mail_worker import checkpoint


class ReadyPollSelector(selectors.DefaultSelector):
    """A ready poll need not suspend Python execution or hand off the GIL."""

    def select(self, timeout: float | None = None) -> list[tuple[selectors.SelectorKey, int]]:
        if timeout == 0:
            return []
        return super().select(timeout)


def test_checkpoint_allows_executor_thread_progress_between_ready_polls() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from tests.adapters.test_identity_mail_checkpoint import "
            "_check_executor_thread_progress; _check_executor_thread_progress()",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _check_executor_thread_progress() -> None:
    started, release = threading.Event(), threading.Event()

    def deliver() -> str:
        started.set()
        assert release.wait(5), "checkpoint test did not release executor"
        return "delivered"

    async def run() -> None:
        with ThreadPoolExecutor(max_workers=1) as executor:
            delivery = executor.submit(deliver)
            assert started.wait(5), "checkpoint test executor did not start"
            previous_interval = sys.getswitchinterval()
            try:
                # Remove incidental interpreter preemption: the checkpoint must
                # allow the real executor thread to finish after its release.
                sys.setswitchinterval(10)
                release.set()
                await checkpoint(delivery.done)
            finally:
                sys.setswitchinterval(previous_interval)
                release.set()
            assert delivery.result() == "delivered"

    # Own and close the selector; no running application loop is patched.
    with asyncio.Runner(
        loop_factory=lambda: asyncio.SelectorEventLoop(ReadyPollSelector())
    ) as runner:
        runner.run(run())


def test_checkpoint_times_out_unfinished_work_with_the_existing_deadline() -> None:
    async def run() -> None:
        with patch("asyncio.timeout", wraps=asyncio.timeout) as timeout:
            pending = asyncio.create_task(checkpoint(lambda: False))
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(pending, timeout=6)
        assert timeout.call_args_list == [call(5)]
        # The helper's deadline fired, rather than the outer guard cancelling it.
        assert not pending.cancelled()

    asyncio.run(run())
