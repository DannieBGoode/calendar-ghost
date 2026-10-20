"""One bounded, volatile identity email sender, independent of synchronization."""

import asyncio
import logging
import threading
from collections import OrderedDict, deque
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from datetime import datetime, timedelta

from calendar_sync.application.identity.identity_email import (
    DeliverIdentityEmailTest,
    EmailTest,
    EmailTestState,
    IdentityEmailTests,
)
from calendar_sync.application.shared.ports import Clock
from calendar_sync.domain.access import UserId

logger = logging.getLogger(__name__)


class IdentityMailWorker:
    def __init__(
        self, delivery: DeliverIdentityEmailTest, tests: IdentityEmailTests, clock: Clock
    ) -> None:
        self._delivery = delivery
        self._tests = tests
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: deque[EmailTest] = deque()
        self._active: dict[UserId, EmailTestState] = {}
        self._finished: OrderedDict[UserId, tuple[EmailTestState, datetime]] = OrderedDict()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="identity-email")
        self._send: Future[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._running = False
        self._last_purge: datetime | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    def submit(self, test: EmailTest) -> bool:
        with self._lock:
            if not self._running or test.actor in self._active or len(self._pending) >= 10:
                return False
            self._pending.append(test)
            self._active[test.actor] = EmailTestState.QUEUED
            self._finished.pop(test.actor, None)
            assert self._loop is not None
            assert self._wake is not None
            self._loop.call_soon_threadsafe(self._wake.set)
            return True

    def state(self, actor: UserId) -> EmailTestState:
        with self._lock:
            self._expire()
            if actor in self._active:
                return self._active[actor]
            finished = self._finished.get(actor)
            return finished[0] if finished else EmailTestState.IDLE

    def stop(self) -> None:
        """Close admission before cancellation; in-flight SMTP has no persistence authority."""
        with self._lock:
            self._running = False
            self._pending.clear()
            self._active.clear()
            self._finished.clear()
            if self._loop is not None and self._wake is not None:
                self._loop.call_soon_threadsafe(self._wake.set)

    async def run_forever(self) -> None:
        with self._lock:
            if self._loop is not None:
                raise RuntimeError("Identity email worker is already running")
            self._loop = asyncio.get_running_loop()
            wake = self._wake = asyncio.Event()
            self._running = True
        try:
            # A cancelled lifespan's SMTP call can still be running. Rewrap its concurrent
            # future on this loop; never reuse an asyncio Future belonging to the old loop.
            if self._send is not None:
                with suppress(Exception):
                    await asyncio.shield(asyncio.wrap_future(self._send))
            while self.running:
                await self._purge()
                test = self._take(wake)
                if test is None:
                    with suppress(TimeoutError):
                        await asyncio.wait_for(wake.wait(), timeout=3600)
                else:
                    await self._deliver(test)
        finally:
            self.stop()
            with self._lock:
                self._loop = None
                self._wake = None

    def _take(self, wake: asyncio.Event) -> EmailTest | None:
        with self._lock:
            if not self._running or not self._pending:
                wake.clear()
                return None
            test = self._pending.popleft()
            self._active[test.actor] = EmailTestState.SENDING
            return test

    async def _deliver(self, test: EmailTest) -> None:
        accepted = False
        try:
            prepared = self._delivery.prepare(test)
            if prepared is not None:
                self._send = self._executor.submit(self._delivery.send, prepared)
                await asyncio.shield(asyncio.wrap_future(self._send))
                # Cancellation is delivered at the await above. SMTP threads only send;
                # only this live loop may make the atomic readiness write.
                with self._lock:
                    if self._running:
                        accepted = self._delivery.complete(prepared)
        except Exception:
            # Keep diagnostics independent of recipients, credentials, and exception text.
            logger.warning("Identity email test failed")
            accepted = False
        with self._lock:
            if self._running:
                self._active.pop(test.actor, None)
                state = EmailTestState.ACCEPTED if accepted else EmailTestState.FAILED
                self._finished[test.actor] = (state, self._clock.now())
                self._expire()

    def _expire(self) -> None:
        before = self._clock.now() - timedelta(minutes=15)
        expired = [actor for actor, (_, at) in self._finished.items() if at <= before]
        for actor in expired:
            del self._finished[actor]
        while len(self._finished) > 100:
            self._finished.popitem(last=False)

    async def _purge(self) -> None:
        now = self._clock.now()
        if self._last_purge is not None and now - self._last_purge < timedelta(hours=1):
            return
        self._last_purge = now
        try:
            while self.running:
                removed = self._tests.purge(now - timedelta(hours=1), 500)
                await asyncio.sleep(0)
                if removed < 500:
                    break
        except Exception:
            # A maintenance failure never authorizes delivery or changes readiness.
            return
