"""When scheduled passes, instant runs, and watch upkeep run, and how many at once; what each
does is application policy in `application/operations/scheduled_pass.py` and
`application/operations/instant_sync.py`."""

from __future__ import annotations

import asyncio
import contextvars
import logging
from collections.abc import Callable, Collection
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import datetime, timedelta
from functools import partial
from typing import Protocol

from calendar_sync.application.operations.installation_health import (
    InstallationIncidentWatch,
    InstallationNotifications,
)
from calendar_sync.application.operations.instant_sync import InstantRun
from calendar_sync.application.operations.ports import SchedulerHeartbeat, SchedulerProgress
from calendar_sync.application.operations.scheduled_pass import ScheduledPass, ScheduledRun
from calendar_sync.application.shared.ports import Clock
from calendar_sync.infrastructure.clock import SystemClock

logger = logging.getLogger(__name__)


class _Threads:
    """Worker threads of one loop's own.

    The event loop's default threads, which `asyncio.to_thread` takes, number min(32, CPUs + 4),
    as few as five on one CPU, and the Web API's requests use them too. A loop that took them
    could hold up a request, such as a Watch Notice its provider waits seconds for, and requests
    could hold up its runs.
    """

    def __init__(self, count: int, name: str) -> None:
        self._executor = ThreadPoolExecutor(max_workers=count, thread_name_prefix=name)

    async def run[T](self, work: Callable[[], T]) -> T:
        # As `asyncio.to_thread` does, the work sees the caller's context variables.
        context = contextvars.copy_context()
        return await asyncio.get_running_loop().run_in_executor(
            self._executor, partial(context.run, work)
        )


class SyncScheduler:
    """Runs a scheduled pass each interval, several rules at once (ADR 0029)."""

    def __init__(
        self,
        scheduled_pass: ScheduledPass,
        interval_seconds: int = 300,
        clock: Clock | None = None,
        concurrency: int = 4,
    ) -> None:
        self._pass = scheduled_pass
        self._interval_seconds = interval_seconds
        self._clock = clock or SystemClock()
        self._concurrency = concurrency
        # Its pass is listed before any rule runs, so one thread per rule run at once suffices.
        self._threads = _Threads(concurrency, "scheduler")
        # Read from request threads while the event loop writes; each is one attribute store.
        self._running_since = self._clock.now()
        self._pass_started_at: datetime | None = None
        self._last_completed_at: datetime | None = None
        self._last_pass_rule_ids: frozenset[str] = frozenset()
        # The first pass begins as soon as the loop starts.
        self._next_pass_at: datetime | None = self._running_since

    async def run_forever(self) -> None:
        while True:
            # A pass that fails, such as on a database another operation holds locked, must not
            # end the loop: every rule would stop synchronizing until the service restarts.
            # Cancellation is a BaseException, so stopping the service still ends the loop.
            try:
                await self.run_once()
            except Exception:
                logger.exception("Scheduled pass failed; trying again at the next interval")
            self._next_pass_at = self._clock.now() + timedelta(seconds=self._interval_seconds)
            await asyncio.sleep(self._interval_seconds)

    async def run_once(self) -> None:
        self._next_pass_at = None
        self._pass_started_at = self._clock.now()
        try:
            listed = await self._run_pass()
        except BaseException:
            self._pass_started_at = None
            raise
        # Publish the completion before clearing the running pass, so a request thread never
        # reads "no pass running" next to the previous completion and reports a false stall.
        self._last_pass_rule_ids = listed
        self._last_completed_at = self._clock.now()
        self._pass_started_at = None

    def progress(self) -> SchedulerProgress:
        return SchedulerProgress(
            self._running_since,
            self._pass_started_at,
            self._last_completed_at,
            self._last_pass_rule_ids,
            self._next_pass_at,
        )

    async def _run_pass(self) -> frozenset[str]:
        """Runs every enabled rule once; returns the ids of the rules this pass listed."""
        # In a worker thread: finishing a lapse may wait for a rule's lock.
        runs = await self._threads.run(self._pass.begin)
        # Different rules run side by side, so one waiting on a slow provider does not hold up the
        # rest; the same rule never does, because each run holds that rule's lock.
        slots = asyncio.Semaphore(self._concurrency)

        async def run(scheduled: ScheduledRun) -> None:
            async with slots:
                await self._threads.run(partial(self._pass.run, scheduled))

        # Checks of accounts an administrator's Cause stopped share the same slots, so a provider
        # that answers slowly, or not at all, holds up no rule.
        async def check(one: Callable[[], None]) -> None:
            async with slots:
                await self._threads.run(one)

        await asyncio.gather(
            *(run(scheduled) for scheduled in runs),
            *(
                check(partial(self._pass.check_administrator_fixes, owner))
                for owner in self._pass.checks_due()
            ),
        )
        return frozenset(scheduled.scheduled.rule.id.value for scheduled in runs)


class SchedulerWatch:
    """Watches the scheduler from outside its loop, so each installation incident, such as a
    scheduler that stops completing passes, is reported to the installation's channels once,
    when it opens (ADR 0030)."""

    def __init__(
        self,
        heartbeat: SchedulerHeartbeat,
        notifications: InstallationNotifications,
        clock: Clock,
        interval_seconds: int = 60,
        incidents: InstallationIncidentWatch | None = None,
    ) -> None:
        self._heartbeat = heartbeat
        self._notifications = notifications
        self._clock = clock
        self._interval_seconds = interval_seconds
        self._incidents = incidents or InstallationIncidentWatch()

    async def run_forever(self) -> None:
        while True:
            try:
                self.check()
            except Exception:
                logger.exception("Could not check the scheduler; checking again shortly")
            await asyncio.sleep(self._interval_seconds)

    def check(self) -> None:
        """Notify each installation incident that has opened since the last check."""
        for incident in self._incidents.opened(self._heartbeat.progress(), self._clock.now()):
            self._notifications.installation_incident_opened(incident)


class InstantRuns(Protocol):
    """What the dispatcher asks of `InstantDispatch`."""

    def due(self, reserved: Collection[str]) -> tuple[tuple[InstantRun, ...], datetime | None]: ...

    def run(self, item: InstantRun) -> None: ...


class InstantSyncDispatcher:
    """Starts instant runs as Watch Notices make them due (ADR 0036).

    The notice route wakes it, on the event loop, once the inbox recorded a notice. Otherwise it
    looks again when the next pending request becomes due, and at least every
    `longest_sleep_seconds`. A rule it queued stays reserved until its run ends, so it never runs
    one rule twice at once, and at most `concurrency` runs go together, apart from the
    scheduler's. A run meeting a rule a scheduled or manual run holds waits for the rule's lock.
    Requests are durable: stopping loses none.
    """

    def __init__(
        self,
        dispatch: InstantRuns,
        concurrency: int = 2,
        clock: Clock | None = None,
        longest_sleep_seconds: float = 60.0,
    ) -> None:
        self._dispatch = dispatch
        self._concurrency = concurrency
        self._clock = clock or SystemClock()
        self._longest_sleep = longest_sleep_seconds
        # One more than its runs, so a look for due runs never waits behind them.
        self._threads = _Threads(concurrency + 1, "instant-sync")
        self._reserved: set[str] = set()
        self._runs: set[asyncio.Task[None]] = set()
        # Set while the loop runs; wake() reads them from request threads.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._woken: asyncio.Event | None = None

    def wake(self) -> None:
        """Look for due runs now; safe from any thread. Before the loop starts there is nothing
        to wake: its first look finds every pending request."""
        loop, woken = self._loop, self._woken
        if loop is None or woken is None:
            return
        # The loop may close while the service stops; the request stays durable.
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(woken.set)

    async def run_forever(self) -> None:
        woken = asyncio.Event()
        self._woken, self._loop = woken, asyncio.get_running_loop()
        slots = asyncio.Semaphore(self._concurrency)
        try:
            while True:
                # Cleared before looking, so a wake during the look is not lost.
                woken.clear()
                delay = await self._start_due(slots)
                with suppress(TimeoutError):
                    await asyncio.wait_for(woken.wait(), delay)
        finally:
            self._woken, self._loop = None, None
            for task in self._runs:
                task.cancel()

    async def _start_due(self, slots: asyncio.Semaphore) -> float:
        """Start every due run; how long to wait before looking again."""
        try:
            runs, next_due = await self._threads.run(
                partial(self._dispatch.due, frozenset(self._reserved))
            )
        except Exception as error:
            # Instant Sync logs only an error's class: a provider's text, which the error may
            # carry along, can quote a token or a registration address.
            logger.error(
                "Choosing instant runs failed; looking again shortly (%s)",
                error.__class__.__name__,
            )
            return self._longest_sleep
        for item in runs:
            rule_id = item.scheduled.scheduled.rule.id.value
            self._reserved.add(rule_id)
            task = asyncio.create_task(self._run(item, rule_id, slots))
            self._runs.add(task)
            task.add_done_callback(self._runs.discard)
        if next_due is None:
            return self._longest_sleep
        wait = (next_due - self._clock.now()).total_seconds()
        return min(max(wait, 0.0), self._longest_sleep)

    async def _run(self, item: InstantRun, rule_id: str, slots: asyncio.Semaphore) -> None:
        try:
            async with slots:
                await self._threads.run(partial(self._dispatch.run, item))
        except Exception as error:
            logger.error(
                "Instant run of rule %s failed; Scheduled Sync runs it meanwhile (%s)",
                rule_id,
                error.__class__.__name__,
            )
        finally:
            self._reserved.discard(rule_id)
            # A notice that came during the run may have made the rule due again.
            if self._woken is not None:
                self._woken.set()


class WatchCycle(Protocol):
    """One upkeep cycle across every User, as `WatchUpkeep.run` does it."""

    def run(self) -> None: ...


class WatchKeeper:
    """Runs watch upkeep every interval in a worker thread of its own, so slow provider calls
    never delay a rule's run or the scheduler's heartbeat (ADR 0036)."""

    def __init__(self, upkeep: WatchCycle, interval_seconds: int = 300) -> None:
        self._upkeep = upkeep
        self._interval_seconds = interval_seconds
        self._threads = _Threads(1, "watch-upkeep")

    async def run_forever(self) -> None:
        while True:
            # As for the scheduler: a failed cycle must not end the loop, and cancellation,
            # a BaseException, still stops it.
            try:
                await self._threads.run(self._upkeep.run)
            except Exception as error:
                logger.error(
                    "Watch upkeep failed; trying again at the next interval (%s)",
                    error.__class__.__name__,
                )
            await asyncio.sleep(self._interval_seconds)
