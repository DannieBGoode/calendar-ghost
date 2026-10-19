"""A scheduled pass: what the scheduler does with every User's enabled rules each interval.

The scheduler adapter decides only when a pass starts and how many rules run at once. A pass
expires what is kept only for a while, finishes interrupted lapses, checks again the accounts an
administrator's Cause stopped, lists the rules due by their owner's Plan, chooses whose daily full
pass is due, runs each rule with its owner's services and retries, and records how each run went
(ADR 0029, ADR 0038).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from itertools import zip_longest
from typing import Protocol

from calendar_sync.application.operations.ports import CauseSighting, InstallationUnitOfWorkFactory
from calendar_sync.application.shared.ports import Clock
from calendar_sync.application.sync.errors import ProviderFailure, RuleNotExecutable
from calendar_sync.application.sync.health import RunHealth
from calendar_sync.application.sync.ports import ScheduledRule
from calendar_sync.application.sync.resource_use import first_counted_day
from calendar_sync.application.sync.retry import with_retries
from calendar_sync.application.sync.sync_run import SOURCE_CHANGE_RETENTION
from calendar_sync.application.sync.synchronization import SyncRunResult
from calendar_sync.application.sync.watch_ports import (
    EveryUserInstant,
    SyncCadencePolicy,
    cadences_of,
)
from calendar_sync.domain.access import UserId
from calendar_sync.domain.cadence import scheduled_run_due
from calendar_sync.domain.causes import ADMINISTRATOR_CAUSES
from calendar_sync.domain.model import SyncRule, SyncRuleId
from calendar_sync.domain.providers import ProviderFailureKind

logger = logging.getLogger(__name__)

RECHECK_INTERVAL = timedelta(hours=1)
"""How often a User's accounts an administrator's Cause stopped are checked again: often enough
that fixing it restarts them soon, rarely enough not to press the provider while it is not fixed.
The first pass after a start checks at once, as putting a new client secret in place restarts the
installation. The checks run beside the pass's rules, so a slow provider delays no rule, and the
rules a passing check restarts run at the next pass."""


class SyncRuns(Protocol):
    def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult: ...


class AdministratorFixes(Protocol):
    def execute(self) -> int:
        """Check again the accounts an administrator's Cause stopped; how many rules restarted."""
        ...


@dataclass(frozen=True, slots=True)
class ScheduledServices:
    """What a pass runs one User's rules with; they see only that User's records."""

    execute_rule: SyncRuns
    health: RunHealth
    administrator_fixes: AdministratorFixes | None = None
    """None where no access check can run, as without the installation master key."""


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
    cadence: SyncCadencePolicy = field(default_factory=EveryUserInstant)
    """Each User's Sync Cadence, read once per pass: a Plan's interval longer than a pass makes
    its rules due once per window of it (ADR 0038)."""
    _checked: dict[UserId, datetime] = field(default_factory=dict)
    """When each User's accounts an administrator's Cause stopped were last checked again."""
    _due: tuple[UserId, ...] = ()
    _listed: dict[SyncRuleId, datetime] = field(default_factory=dict, init=False)
    """When the pass that last listed each enabled rule began. A rule not listed since the start
    counts from its last run, read once, so Sync Now and instant runs never move it."""

    def begin(self) -> tuple[ScheduledRun, ...]:
        """Prepare a pass, then list its runs: the enabled rules due at it of every User who is
        not disabled, taking turns between Users. A rule is due once per window of its Plan's
        interval, and at every pass while it never ran, is failing, was previewed since its last
        run, or awaits reprojection (`scheduled_run_due`)."""
        now = self.clock.now()
        today = now.astimezone(UTC).date()
        with self.installation() as installation:
            # Values of paused and removed rules expire too, although no run of theirs does it.
            installation.forget_change_values(now - SOURCE_CHANGE_RETENTION)
            installation.forget_provider_calls(first_counted_day(today))
            installation.commit()
            # Before listing the pass's rules, so a rule resumed here can run in this same pass.
            for owner in installation.users_with_unfinished_lapses():
                self._finish_lapses(owner)
            self._due = self._choose_checks(installation.failure_causes(now - RECHECK_INTERVAL))
            rules = installation.scheduled_rules()
        # A failed read falls back to the default cadence, which is due at every pass.
        cadences = cadences_of(self.cadence, {scheduled.owner for scheduled in rules})
        listed = {
            scheduled.rule.id: self._listed.get(scheduled.rule.id, scheduled.last_run_at)
            for scheduled in rules
        }
        due = [
            scheduled
            for scheduled in rules
            if scheduled_run_due(
                cadences[scheduled.owner].poll_every,
                scheduled.rule.id.value,
                now,
                listed[scheduled.rule.id],
                always_due=scheduled.always_due,
                full_pass_due=_full_pass_due(scheduled.last_full_succeeded_at, today),
            )
        ]
        # Rules no longer enabled are forgotten; one not listed keeps the last run it counts from,
        # and every listed one counts from this pass.
        self._listed = {rule_id: at for rule_id, at in listed.items() if at is not None}
        self._listed.update((scheduled.rule.id, now) for scheduled in due)
        # Each rule's daily full pass is due from its own last one, so a restart or another
        # rule's failure never re-lists calendars that already completed today's pass.
        return tuple(
            ScheduledRun(scheduled, _full_pass_due(scheduled.last_full_succeeded_at, today))
            for scheduled in fairly_ordered(due)
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

    def checks_due(self) -> tuple[UserId, ...]:
        """The Users whose accounts an administrator's Cause stopped this pass checks again, once;
        the scheduler runs each beside the pass's rules (RECHECK_INTERVAL)."""
        due, self._due = self._due, ()
        return due

    def check_administrator_fixes(self, owner: UserId) -> None:
        """Check one User's accounts again; a failure waits for the next interval."""
        try:
            fixes = self.services_for(owner).administrator_fixes
            if fixes is not None:
                fixes.execute()
        except Exception:
            logger.exception(
                "Checking accounts an administrator's cause stopped failed; trying again later"
            )

    def _choose_checks(self, sightings: Sequence[CauseSighting]) -> tuple[UserId, ...]:
        """Users with an open administrator's Cause not checked within RECHECK_INTERVAL, counted
        as checked from now."""
        now = self.clock.now()
        stopped = {s.user for s in sightings if s.open and s.cause in ADMINISTRATOR_CAUSES}
        never = datetime.min.replace(tzinfo=UTC)
        due = tuple(
            owner
            for owner in sorted(stopped, key=lambda user: user.value)
            if now - self._checked.get(owner, never) >= RECHECK_INTERVAL
        )
        for owner in due:
            self._checked[owner] = now
        return due

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
