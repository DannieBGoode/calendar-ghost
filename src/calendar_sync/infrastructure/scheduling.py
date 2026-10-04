from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime

from calendar_sync.application.errors import (
    ProviderFailure,
    ProviderFailureKind,
    RuleNotExecutable,
)
from calendar_sync.application.health import RunHealth
from calendar_sync.application.ports import (
    Clock,
    RuleRunOutcome,
    RunKind,
    SchedulerProgress,
    UnitOfWorkFactory,
)
from calendar_sync.application.retry import with_retries
from calendar_sync.application.sync_run import SOURCE_CHANGE_RETENTION
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.domain.model import SyncRule, SyncRuleState

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class SyncScheduler:
    def __init__(
        self,
        execute_rule: ExecuteSyncRule,
        unit_of_work: UnitOfWorkFactory,
        health: RunHealth,
        interval_seconds: int = 300,
        clock: Clock | None = None,
    ) -> None:
        self._execute_rule = execute_rule
        self._unit_of_work = unit_of_work
        self._health = health
        self._interval_seconds = interval_seconds
        self._clock = clock or SystemClock()
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
        with self._unit_of_work() as uow:
            # Values of paused and removed rules expire too, although no run of theirs does it.
            uow.audit.forget_change_values(now - SOURCE_CHANGE_RETENTION)
            uow.commit()
            # Each rule's daily full pass is due from its own last one, so a restart or another
            # rule's failure never re-lists calendars that already completed today's pass.
            due = tuple(
                (rule, _full_pass_due(uow.run_outcomes.latest(rule.id, RunKind.SYNC), today))
                for rule in uow.rules.list()
                if rule.state is SyncRuleState.ENABLED
            )
        for rule, full in due:
            await asyncio.to_thread(self._execute_with_retry, rule, full)
        return frozenset(rule.id.value for rule, _ in due)

    def _execute_with_retry(self, rule: SyncRule, full: bool = False) -> bool:
        # Every decision of this run, including its retries, is recorded above this entry, so a
        # run that turns out to list both calendars in full can stand in for the daily pass.
        floor = self._audit_floor()
        try:
            result = with_retries(lambda: self._execute_rule.execute(rule.id, full=full), _sleep)
        except RuleNotExecutable:
            # The rule was paused, edited, or removed after this pass listed it.
            return True
        except ProviderFailure as failure:
            self._health.record_failure(rule, failure)
            return False
        except Exception as error:
            logger.exception("Unexpected synchronization failure for rule %s", rule.id.value)
            self._health.record_failure(
                rule, ProviderFailure(ProviderFailureKind.INFRASTRUCTURE, error.__class__.__name__)
            )
            return False
        listed = full or result.listed_in_full
        self._record_success(rule, floor if listed else None, result.run_id)
        return True

    def _audit_floor(self) -> int | None:
        try:
            return self._health.audit_floor()
        except Exception:
            logger.exception("Could not read the audit position before a run")
            return None

    def _record_success(
        self, rule: SyncRule, full_pass_floor: int | None, run_id: str | None
    ) -> None:
        # The run succeeded; failing to record its health must not report it as failed.
        try:
            self._health.record_success(rule, full_pass_floor=full_pass_floor, full_pass_run=run_id)
        except Exception:
            logger.exception("Could not record the successful run of rule %s", rule.id.value)


def _sleep(delay: float) -> None:
    # Looked up on each call, so tests can replace time.sleep.
    time.sleep(delay)


def _full_pass_due(latest: RuleRunOutcome | None, today: date) -> bool:
    completed = latest.last_full_succeeded_at if latest is not None else None
    return completed is None or completed.astimezone(UTC).date() != today
