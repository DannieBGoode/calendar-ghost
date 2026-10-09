from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from itertools import zip_longest

from calendar_sync.application.errors import (
    ProviderFailure,
    ProviderFailureKind,
    RuleNotExecutable,
)
from calendar_sync.application.health import RunHealth
from calendar_sync.application.installation_health import (
    InstallationIncidentKind,
    InstallationNotifications,
    installation_incidents,
)
from calendar_sync.application.ports import (
    Clock,
    InstallationUnitOfWorkFactory,
    ScheduledRule,
    SchedulerHeartbeat,
    SchedulerProgress,
)
from calendar_sync.application.retry import with_retries
from calendar_sync.application.sync_run import SOURCE_CHANGE_RETENTION
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import SyncRule

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ScheduledServices:
    """What the scheduler runs one User's rules with; they see only that User's records."""

    execute_rule: ExecuteSyncRule
    health: RunHealth


class SyncScheduler:
    """Runs every enabled rule each interval, each with its owner's services (ADR 0029)."""

    def __init__(
        self,
        installation: InstallationUnitOfWorkFactory,
        services_for: Callable[[UserId], ScheduledServices],
        interval_seconds: int = 300,
        clock: Clock | None = None,
        concurrency: int = 4,
    ) -> None:
        self._installation = installation
        self._services_for = services_for
        self._interval_seconds = interval_seconds
        self._clock = clock or SystemClock()
        self._concurrency = concurrency
        # Read from request threads while the event loop writes; each is one attribute store.
        self._running_since = self._clock.now()
        self._pass_started_at: datetime | None = None
        self._last_completed_at: datetime | None = None
        self._last_pass_rule_ids: frozenset[str] = frozenset()

    async def run_forever(self) -> None:
        while True:
            # A pass that fails, such as on a database another operation holds locked, must not
            # end the loop: every rule would stop synchronizing until the service restarts.
            # Cancellation is a BaseException, so stopping the service still ends the loop.
            try:
                await self.run_once()
            except Exception:
                logger.exception("Scheduled pass failed; trying again at the next interval")
            await asyncio.sleep(self._interval_seconds)

    async def run_once(self) -> None:
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
        )

    async def _run_pass(self) -> frozenset[str]:
        """Runs every enabled rule once; returns the ids of the rules this pass listed."""
        now = self._clock.now()
        today = now.astimezone(UTC).date()
        with self._installation() as installation:
            # Values of paused and removed rules expire too, although no run of theirs does it.
            installation.forget_change_values(now - SOURCE_CHANGE_RETENTION)
            installation.commit()
            # Each rule's daily full pass is due from its own last one, so a restart or another
            # rule's failure never re-lists calendars that already completed today's pass.
            due = tuple(
                (scheduled, _full_pass_due(scheduled.last_full_succeeded_at, today))
                for scheduled in fairly_ordered(installation.scheduled_rules())
            )
        # Different rules run side by side, so one waiting on a slow provider does not hold up the
        # rest; the same rule never does, because each run holds that rule's lock.
        slots = asyncio.Semaphore(self._concurrency)

        async def run(scheduled: ScheduledRule, full: bool) -> None:
            async with slots:
                await asyncio.to_thread(self._execute_with_retry, scheduled, full)

        await asyncio.gather(*(run(scheduled, full) for scheduled, full in due))
        return frozenset(scheduled.rule.id.value for scheduled, _ in due)

    def _execute_with_retry(self, scheduled: ScheduledRule, full: bool = False) -> bool:
        rule = scheduled.rule
        services = self._services_for(scheduled.owner)
        # Every decision of this run, including its retries, is recorded above this entry, so a
        # run that turns out to list both calendars in full can stand in for the daily pass.
        floor = _audit_floor(services.health)
        started = self._clock.now()
        try:
            result = with_retries(lambda: services.execute_rule.execute(rule.id, full=full), _sleep)
        except RuleNotExecutable:
            # The rule was paused, edited, or removed after this pass listed it.
            return True
        except ProviderFailure as failure:
            services.health.record_failure(rule, failure, attempted_at=started)
            return False
        except Exception as error:
            logger.exception("Unexpected synchronization failure for rule %s", rule.id.value)
            services.health.record_failure(
                rule, ProviderFailure(ProviderFailureKind.INFRASTRUCTURE, error.__class__.__name__)
            )
            return False
        listed = full or result.listed_in_full
        _record_success(services.health, rule, floor if listed else None, result.run_id)
        return True


class SchedulerWatch:
    """Watches the scheduler from outside its loop, so a scheduler that stops completing passes
    is reported to the installation's channels once, when it stalls (ADR 0030)."""

    def __init__(
        self,
        heartbeat: SchedulerHeartbeat,
        notifications: InstallationNotifications,
        clock: Clock,
        interval_seconds: int = 60,
    ) -> None:
        self._heartbeat = heartbeat
        self._notifications = notifications
        self._clock = clock
        self._interval_seconds = interval_seconds
        self._open: frozenset[InstallationIncidentKind] = frozenset()

    async def run_forever(self) -> None:
        while True:
            try:
                self.check()
            except Exception:
                logger.exception("Could not check the scheduler; checking again shortly")
            await asyncio.sleep(self._interval_seconds)

    def check(self) -> None:
        """Notify each installation incident that has opened since the last check."""
        incidents = installation_incidents(self._heartbeat.progress(), self._clock.now())
        opened = [incident for incident in incidents if incident.kind not in self._open]
        self._open = frozenset(incident.kind for incident in incidents)
        for incident in opened:
            self._notifications.installation_incident_opened(incident)


def fairly_ordered(rules: Sequence[ScheduledRule]) -> tuple[ScheduledRule, ...]:
    """Rules taking turns between Users, so one User's many rules never hold up everyone else's.

    Each User's rules keep their order; the first of every User's comes before anyone's second.
    """
    by_owner: dict[UserId, list[ScheduledRule]] = {}
    for scheduled in rules:
        by_owner.setdefault(scheduled.owner, []).append(scheduled)
    turns = zip_longest(*by_owner.values())
    return tuple(scheduled for turn in turns for scheduled in turn if scheduled is not None)


def _audit_floor(health: RunHealth) -> int | None:
    try:
        return health.audit_floor()
    except Exception:
        logger.exception("Could not read the audit position before a run")
        return None


def _record_success(
    health: RunHealth, rule: SyncRule, full_pass_floor: int | None, run_id: str | None
) -> None:
    # The run succeeded; failing to record its health must not report it as failed.
    try:
        health.record_success(rule, full_pass_floor=full_pass_floor, full_pass_run=run_id)
    except Exception:
        logger.exception("Could not record the successful run of rule %s", rule.id.value)


def _sleep(delay: float) -> None:
    # Looked up on each call, so tests can replace time.sleep.
    time.sleep(delay)


def _full_pass_due(completed: datetime | None, today: date) -> bool:
    return completed is None or completed.astimezone(UTC).date() != today
