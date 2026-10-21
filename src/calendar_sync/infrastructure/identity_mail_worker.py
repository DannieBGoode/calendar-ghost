"""One bounded, volatile identity email sender, independent of synchronization."""

import asyncio
import logging
import threading
from collections import OrderedDict, deque
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from datetime import datetime, timedelta

from calendar_sync.application.identity.email_changes import (
    EmailChangedNotice,
    EmailChangeMailRequest,
)
from calendar_sync.application.identity.identity_email import (
    DeliverIdentityEmailTest,
    EmailTest,
    EmailTestState,
    IdentityEmailTests,
)
from calendar_sync.application.identity.password_reset import (
    DeliverPasswordReset,
    ResetEmailRequest,
)
from calendar_sync.application.identity.registration_ports import RegistrationEmailRequest
from calendar_sync.application.identity.reset_admission import ResetAdmission
from calendar_sync.application.shared.ports import Clock
from calendar_sync.domain.access import UserId
from calendar_sync.infrastructure.identity_email_changes import EmailChangeMaintenance
from calendar_sync.infrastructure.identity_registration import RegistrationMaintenance

logger = logging.getLogger(__name__)


class IdentityMailWorker:
    def __init__(
        self,
        delivery: DeliverIdentityEmailTest | None,
        tests: IdentityEmailTests,
        clock: Clock,
        *,
        reset_delivery: DeliverPasswordReset | None = None,
        reset_admission: ResetAdmission | None = None,
        email_changes: EmailChangeMaintenance | None = None,
        registrations: RegistrationMaintenance | None = None,
    ) -> None:
        self._delivery = delivery
        self._tests = tests
        self._clock = clock
        self._reset_delivery = reset_delivery
        self._reset_admission = reset_admission
        self._email_changes = email_changes
        self._registrations = registrations
        self._lock = threading.Lock()
        self._pending: deque[EmailTest | EmailChangeMailRequest | EmailChangedNotice] = deque()
        self._resets: deque[ResetEmailRequest] = deque()
        self._registrations_pending: deque[RegistrationEmailRequest] = deque()
        self._lane = 0
        self._generation = 0
        self._active: dict[UserId, EmailTestState] = {}
        self._finished: OrderedDict[UserId, tuple[EmailTestState, datetime]] = OrderedDict()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="identity-email")
        self._send: Future[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._running = False
        self._last_purge: datetime | None = None
        self._reset_cleanup_at: datetime | None = None
        self._change_cleanup_at: datetime | None = None
        self._test_cleanup_at: datetime | None = None
        self._registration_cleanup_at: datetime | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    def submit(self, test: EmailTest) -> bool:
        with self._lock:
            if (
                not self._running
                or self._delivery is None
                or test.actor in self._active
                or len(self._pending) >= 10
            ):
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

    def submit_reset(self, request: ResetEmailRequest) -> bool:
        with self._lock:
            if not self._running or self._reset_delivery is None or len(self._resets) >= 50:
                return False
            self._resets.append(request)
            assert self._loop is not None
            assert self._wake is not None
            self._loop.call_soon_threadsafe(self._wake.set)
            return True

    def submit_registration(self, request: RegistrationEmailRequest) -> bool:
        with self._lock:
            if (
                not self._running
                or self._registrations is None
                or self._registrations.delivery is None
                or len(self._registrations_pending) >= 50
            ):
                return False
            self._registrations_pending.append(request)
            assert self._loop is not None
            assert self._wake is not None
            self._loop.call_soon_threadsafe(self._wake.set)
            return True

    def submit_change(self, request: EmailChangeMailRequest) -> bool:
        return self._submit_security(request)

    def submit_notice(self, notice: EmailChangedNotice) -> bool:
        return self._submit_security(notice)

    def _submit_security(self, request: EmailChangeMailRequest | EmailChangedNotice) -> bool:
        with self._lock:
            if (
                not self._running
                or self._email_changes is None
                or self._email_changes.delivery is None
                or len(self._pending) >= 10
            ):
                return False
            self._pending.append(request)
            assert self._loop is not None
            assert self._wake is not None
            self._loop.call_soon_threadsafe(self._wake.set)
            return True

    def stop(self) -> None:
        """Close admission before cancellation; in-flight SMTP has no persistence authority."""
        with self._lock:
            self._running = False
            self._generation += 1
            self._pending.clear()
            self._resets.clear()
            self._registrations_pending.clear()
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
                more_cleanup = await self._purge()
                request = self._take(wake)
                if request is None:
                    if more_cleanup:
                        await asyncio.sleep(0)
                    else:
                        with suppress(TimeoutError):
                            await asyncio.wait_for(wake.wait(), timeout=3600)
                elif isinstance(request, ResetEmailRequest):
                    await self._deliver_reset(request)
                elif isinstance(request, RegistrationEmailRequest):
                    await self._deliver_registration(request)
                elif isinstance(request, EmailTest):
                    await self._deliver(request)
                else:
                    await self._deliver_change(request)
        finally:
            self.stop()
            with self._lock:
                self._loop = None
                self._wake = None

    def _take(
        self, wake: asyncio.Event
    ) -> (
        EmailTest
        | ResetEmailRequest
        | RegistrationEmailRequest
        | EmailChangeMailRequest
        | EmailChangedNotice
        | None
    ):
        with self._lock:
            lanes = (self._pending, self._resets, self._registrations_pending)
            if self._running:
                for offset in range(3):
                    lane = (self._lane + offset) % 3
                    if lanes[lane]:
                        self._lane = (lane + 1) % 3
                        request = lanes[lane].popleft()
                        if isinstance(request, EmailTest):
                            self._active[request.actor] = EmailTestState.SENDING
                        return request
            wake.clear()
            return None

    async def _deliver(self, test: EmailTest) -> None:
        assert self._delivery is not None
        accepted = False
        try:
            prepared = await asyncio.to_thread(self._delivery.prepare, test)
            if prepared is not None and self.running:
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

    async def _deliver_reset(self, request: ResetEmailRequest) -> None:
        with self._lock:
            if not self._running:
                return
            generation = self._generation
            self._send = self._executor.submit(self._send_reset, request, generation)
        try:
            await asyncio.shield(asyncio.wrap_future(self._send))
        except Exception:
            logger.warning("Identity password reset email failed")

    def _send_reset(self, request: ResetEmailRequest, generation: int) -> None:
        assert self._reset_delivery is not None
        with self._lock:
            if not self._running or self._generation != generation:
                return
        prepared = self._reset_delivery.prepare(request)
        with self._lock:
            if not self._running or self._generation != generation:
                return
        if prepared is not None:
            self._reset_delivery.send(prepared)

    async def _deliver_registration(self, request: RegistrationEmailRequest) -> None:
        with self._lock:
            if not self._running:
                return
            self._send = self._executor.submit(self._send_registration, request, self._generation)
        try:
            await asyncio.shield(asyncio.wrap_future(self._send))
        except Exception:
            logger.warning("Identity registration email failed")

    def _send_registration(self, request: RegistrationEmailRequest, generation: int) -> None:
        assert self._registrations is not None
        assert self._registrations.delivery is not None
        delivery = self._registrations.delivery
        with self._lock:
            if not self._running or self._generation != generation:
                return
        prepared = delivery.prepare(request)
        with self._lock:
            if not self._running or self._generation != generation:
                return
        if prepared is not None:
            delivery.send(prepared)

    async def _deliver_change(self, request: EmailChangeMailRequest | EmailChangedNotice) -> None:
        with self._lock:
            if not self._running:
                return
            self._send = self._executor.submit(self._send_change, request, self._generation)
        try:
            await asyncio.shield(asyncio.wrap_future(self._send))
        except Exception:
            logger.warning("Identity email change delivery failed")

    def _send_change(
        self, request: EmailChangeMailRequest | EmailChangedNotice, generation: int
    ) -> None:
        assert self._email_changes is not None
        assert self._email_changes.delivery is not None
        delivery = self._email_changes.delivery
        with self._lock:
            if not self._running or self._generation != generation:
                return
        prepared = (
            delivery.prepare(request) if isinstance(request, EmailChangeMailRequest) else None
        )
        with self._lock:
            if not self._running or self._generation != generation:
                return
        if isinstance(request, EmailChangedNotice):
            delivery.notice(request)
        elif prepared is not None:
            delivery.send(prepared)

    def _expire(self) -> None:
        before = self._clock.now() - timedelta(minutes=15)
        expired = [actor for actor, (_, at) in self._finished.items() if at <= before]
        for actor in expired:
            del self._finished[actor]
        while len(self._finished) > 100:
            self._finished.popitem(last=False)

    async def _purge(self) -> bool:
        now = self._clock.now()
        if self._last_purge is None or now - self._last_purge >= timedelta(hours=1):
            self._last_purge = now
            self._reset_cleanup_at = now
            self._change_cleanup_at = now
            self._registration_cleanup_at = now
            self._test_cleanup_at = now - timedelta(hours=1)
        cutoff = self._reset_cleanup_at
        # One bounded reset batch per fair mail turn; failures retry next hour.
        self._reset_cleanup_at = None
        if cutoff is not None and self._reset_admission is not None and self.running:
            with suppress(Exception):
                removed = await asyncio.to_thread(self._reset_admission.purge, cutoff, 500)
                if removed == 500:
                    self._reset_cleanup_at = cutoff
        await self._purge_changes()
        await self._purge_tests()
        await self._purge_registrations()
        return any(
            at is not None
            for at in (
                self._reset_cleanup_at,
                self._change_cleanup_at,
                self._test_cleanup_at,
                self._registration_cleanup_at,
            )
        )

    async def _purge_changes(self) -> None:
        cutoff, self._change_cleanup_at = self._change_cleanup_at, None
        if cutoff is not None and self._email_changes is not None and self.running:
            with suppress(Exception):
                removed = await asyncio.to_thread(self._email_changes.purge, cutoff, 500)
                if removed == 500:
                    self._change_cleanup_at = cutoff

    async def _purge_tests(self) -> None:
        cutoff, self._test_cleanup_at = self._test_cleanup_at, None
        if cutoff is not None and self.running:
            with suppress(Exception):
                removed = await asyncio.to_thread(self._tests.purge, cutoff, 500)
                if removed == 500:
                    self._test_cleanup_at = cutoff

    async def _purge_registrations(self) -> None:
        cutoff, self._registration_cleanup_at = self._registration_cleanup_at, None
        if cutoff is not None and self._registrations is not None and self.running:
            with suppress(Exception):
                more = await asyncio.to_thread(self._registrations.purge, cutoff, 500)
                if more:
                    self._registration_cleanup_at = cutoff
