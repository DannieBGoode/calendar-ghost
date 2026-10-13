"""When scheduled passes run, and how many rules run at once; a pass itself is application
policy in `application/operations/scheduled_pass.py`."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import partial

from calendar_sync.application.operations.installation_health import (
    InstallationIncidentWatch,
    InstallationNotifications,
)
from calendar_sync.application.operations.ports import SchedulerHeartbeat, SchedulerProgress
from calendar_sync.application.operations.scheduled_pass import ScheduledPass, ScheduledRun
from calendar_sync.application.shared.ports import Clock
from calendar_sync.infrastructure.clock import SystemClock

logger = logging.getLogger(__name__)


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
        runs = await asyncio.to_thread(self._pass.begin)
        # Different rules run side by side, so one waiting on a slow provider does not hold up the
        # rest; the same rule never does, because each run holds that rule's lock.
        slots = asyncio.Semaphore(self._concurrency)

        async def run(scheduled: ScheduledRun) -> None:
            async with slots:
                await asyncio.to_thread(self._pass.run, scheduled)

        # Checks of accounts an administrator's Cause stopped share the same slots, so a provider
        # that answers slowly, or not at all, holds up no rule.
        async def check(one: Callable[[], None]) -> None:
            async with slots:
                await asyncio.to_thread(one)

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
