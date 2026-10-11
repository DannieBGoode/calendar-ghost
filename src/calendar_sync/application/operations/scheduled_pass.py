"""A scheduled pass: what the scheduler does with every User's enabled rules each interval.

The scheduler adapter decides only when a pass starts and how many rules run at once. A pass
expires what is kept only for a while, finishes interrupted lapses, chooses whose daily full pass
is due, runs each rule with its owner's services and retries, and records how each run went
(ADR 0029).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from itertools import zip_longest
from typing import Protocol

from calendar_sync.application.operations.ports import InstallationUnitOfWorkFactory
from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.errors import ProviderFailure, RuleNotExecutable
from calendar_sync.application.sync.health import RunHealth
from calendar_sync.application.sync.ports import ScheduledRule
from calendar_sync.application.sync.resource_use import first_counted_day
from calendar_sync.application.sync.retry import with_retries
from calendar_sync.application.sync.sync_run import SOURCE_CHANGE_RETENTION
from calendar_sync.application.sync.synchronization import SyncRunResult
from calendar_sync.domain.access import UserId
from calendar_sync.domain.model import SyncRule, SyncRuleId
from calendar_sync.domain.providers import ProviderFailureKind

logger = logging.getLogger(__name__)


class SyncRuns(Protocol):
    def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult: ...


@dataclass(frozen=True, slots=True)
class ScheduledServices:
    """What a pass runs one User's rules with; they see only that User's records."""

    execute_rule: SyncRuns
    health: RunHealth


@dataclass(frozen=True, slots=True)
class ScheduledRun:
    """One rule a pass runs, and whether that run lists both calendars in full."""

    scheduled: ScheduledRule
    full: bool


@dataclass(slots=True)
class ScheduledPass:
    installation: InstallationUnitOfWorkFactory
    services_for: Callable[[UserId], ScheduledServices]
    clock: Clock

    def begin(self) -> tuple[ScheduledRun, ...]:
        """Prepare a pass, then list its runs: every enabled rule of every User who is not
        disabled, taking turns between Users."""
        now = self.clock.now()
        today = now.astimezone(UTC).date()
        with self.installation() as installation:
            # Values of paused and removed rules expire too, although no run of theirs does it.
            installation.forget_change_values(now - SOURCE_CHANGE_RETENTION)
            installation.forget_provider_calls(first_counted_day(today))
            installation.commit()
            # Before listing the pass's rules, so a rule resumed here runs in this same pass.
            for owner in installation.users_with_unfinished_lapses():
                self._finish_lapses(owner)
            # Each rule's daily full pass is due from its own last one, so a restart or another
            # rule's failure never re-lists calendars that already completed today's pass.
            return tuple(
                ScheduledRun(scheduled, _full_pass_due(scheduled.last_full_succeeded_at, today))
                for scheduled in fairly_ordered(installation.scheduled_rules())
            )

    def run(self, scheduled: ScheduledRun) -> bool:
        """Run one rule, retrying what may pass, and record how it went; False when it failed."""
        rule, full = scheduled.scheduled.rule, scheduled.full
        services = self.services_for(scheduled.scheduled.owner)
        # Every decision of this run, including its retries, is recorded above this entry, so a
        # run that turns out to list both calendars in full can stand in for the daily pass.
        floor = _audit_floor(services.health)
        started = self.clock.now()
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

    def _finish_lapses(self, owner: UserId) -> None:
        """Finish what an interrupted lapse or restoration left; a failure waits for a pass."""
        try:
            self.services_for(owner).health.finish_interrupted_lapses()
        except Exception:
            logger.exception(
                "Finishing an interrupted lapse or restoration failed; trying again next pass"
            )


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
