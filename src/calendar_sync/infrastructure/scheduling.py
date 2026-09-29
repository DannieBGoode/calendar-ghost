from __future__ import annotations

import asyncio
import logging
import random
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from calendar_sync.application.errors import (
    ProviderFailure,
    ProviderFailureKind,
    RuleNotExecutable,
)
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import RuleRunOutcome, RunKind, UnitOfWorkFactory
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.domain.model import SyncRule, SyncRuleId, SyncRuleState
from calendar_sync.infrastructure.notifications import IncidentNotification, IncidentNotifier
from calendar_sync.infrastructure.persistence.activity_queries import open_blocks

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


_FAILURE_SUMMARIES = {
    ProviderFailureKind.AUTHENTICATION: "Google authorization expired",
    ProviderFailureKind.AUTHORIZATION: "Google calendar access was denied",
    ProviderFailureKind.RATE_LIMIT: "Google Calendar is limiting requests",
    ProviderFailureKind.TEMPORARY: "Google Calendar is temporarily unavailable",
    ProviderFailureKind.PERMANENT: "Google Calendar rejected synchronization",
    ProviderFailureKind.INFRASTRUCTURE: "Local synchronization infrastructure failed",
}


class SqliteRuleHealth:
    def __init__(
        self,
        database_path: Path,
        unit_of_work: UnitOfWorkFactory,
        notifier: IncidentNotifier | None = None,
        *,
        locks: RuleLocks | None = None,
    ) -> None:
        self._database_path = database_path
        self._unit_of_work = unit_of_work
        self._locks = locks or RuleLocks()
        self._notifier = notifier

    def audit_floor(self) -> int:
        """The newest audit entry now, taken before a daily pass so its decisions lie above it."""
        with sqlite3.connect(self._database_path) as connection:
            return int(
                connection.execute("SELECT COALESCE(MAX(id), 0) FROM audit_entries").fetchone()[0]
            )

    def record_success(self, rule: SyncRule, *, full_pass_floor: int | None = None) -> None:
        """Record a successful run; a daily pass also names the audit entry it began after."""
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._database_path) as connection:
            connection.execute("DELETE FROM rule_failures WHERE rule_id = ?", (rule.id.value,))
        self._resolve(f"provider:{rule.id.value}", now)
        if full_pass_floor is not None:
            self.record_full_pass(rule.id, full_pass_floor)

    def record_full_pass(self, rule_id: SyncRuleId, floor: int) -> None:
        """A full pass that began after audit entry `floor` decided every blocked event again.

        Blocks it repeated are persisting and open one Incident; blocks it did not repeat are no
        longer open. Scheduled daily passes and Reconcile Now both report here.
        """
        # Rule Removal holds this lock throughout, so a rule removed after its pass finished is
        # never given an incident no run could resolve.
        with self._locks.for_rule(rule_id):
            self._record_full_pass(rule_id, floor)

    def _record_full_pass(self, rule_id: SyncRuleId, floor: int) -> None:
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._database_path) as connection:
            if not connection.execute(
                "SELECT 1 FROM sync_rules WHERE id = ?", (rule_id.value,)
            ).fetchone():
                return
            persisting = len(
                open_blocks(connection, rule_id=rule_id.value, after=floor, persisting=True)
            )
            connection.execute(
                """
                INSERT INTO rule_block_checks (rule_id, audit_floor, checked_at)
                VALUES (?, ?, ?)
                ON CONFLICT(rule_id) DO UPDATE SET
                    audit_floor = excluded.audit_floor, checked_at = excluded.checked_at
                """,
                (rule_id.value, floor, now),
            )
        key = f"blocked:{rule_id.value}"
        if persisting:
            events = "1 event" if persisting == 1 else f"{persisting} events"
            verb = "was" if persisting == 1 else "were"
            self._open_incident(
                rule_id,
                "conflict",
                now,
                key=key,
                summary=(
                    f"{events} could not be synced and {verb} still blocked at the daily check."
                ),
            )
        else:
            self._resolve(key, now)

    def _resolve(self, key: str, now: str) -> None:
        with sqlite3.connect(self._database_path) as connection:
            connection.execute(
                """
                UPDATE incidents SET state = 'resolved', updated_at = ?, resolved_at = ?
                WHERE deduplication_key = ? AND state = 'open'
                """,
                (now, now, key),
            )

    def record_failure(self, rule: SyncRule, failure: ProviderFailure) -> None:
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO rule_failures(rule_id, consecutive_failures, last_category, updated_at)
                VALUES (?, 1, ?, ?)
                ON CONFLICT(rule_id) DO UPDATE SET
                    consecutive_failures = consecutive_failures + 1,
                    last_category = excluded.last_category,
                    updated_at = excluded.updated_at
                """,
                (rule.id.value, failure.kind.value, now),
            )
            count = int(
                connection.execute(
                    "SELECT consecutive_failures FROM rule_failures WHERE rule_id = ?",
                    (rule.id.value,),
                ).fetchone()[0]
            )

        needs_intervention = failure.kind in {
            ProviderFailureKind.AUTHENTICATION,
            ProviderFailureKind.AUTHORIZATION,
            ProviderFailureKind.PERMANENT,
            ProviderFailureKind.INFRASTRUCTURE,
        }
        if needs_intervention:
            self._degrade(rule)
        if needs_intervention or count >= 3:
            self._open_incident(rule.id, failure.kind.value, now)

    def _degrade(self, rule: SyncRule) -> None:
        if rule.state is not SyncRuleState.ENABLED:
            return
        with self._locks.for_writes(rule.id), self._unit_of_work() as uow:
            current = uow.rules.get(rule.id)
            if current is not None and current.state is SyncRuleState.ENABLED:
                uow.rules.save(current.degrade())
                uow.commit()

    def removal_blocked(self, rule_id: SyncRuleId, failure: ProviderFailure) -> None:
        self._open_incident(
            rule_id,
            failure.kind.value,
            datetime.now(UTC).isoformat(),
            key=f"removal:{rule_id.value}",
            summary=f"Rule Removal stopped: {_FAILURE_SUMMARIES[failure.kind]}",
        )

    def _open_incident(
        self,
        rule_id: SyncRuleId,
        category: str,
        occurred_at: str,
        *,
        key: str | None = None,
        summary: str | None = None,
    ) -> None:
        key = key or f"provider:{rule_id.value}"
        summary = summary or _FAILURE_SUMMARIES[ProviderFailureKind(category)]
        with sqlite3.connect(self._database_path) as connection:
            existing = connection.execute(
                "SELECT state FROM incidents WHERE deduplication_key = ?", (key,)
            ).fetchone()
            newly_opened = existing is None or existing[0] != "open"
            connection.execute(
                """
                INSERT INTO incidents (
                    id, deduplication_key, rule_id, category, state,
                    summary, opened_at, updated_at
                ) VALUES (?, ?, ?, ?, 'open', ?, ?, ?)
                ON CONFLICT(deduplication_key) DO UPDATE SET
                    category = excluded.category,
                    state = 'open',
                    summary = excluded.summary,
                    updated_at = excluded.updated_at,
                    resolved_at = NULL
                """,
                (
                    str(uuid.uuid4()),
                    key,
                    rule_id.value,
                    category,
                    summary,
                    occurred_at,
                    occurred_at,
                ),
            )
        if newly_opened and self._notifier is not None:
            self._notifier.notify(
                IncidentNotification(rule_id.value, category, summary, occurred_at)
            )


class SyncScheduler:
    def __init__(
        self,
        execute_rule: ExecuteSyncRule,
        unit_of_work: UnitOfWorkFactory,
        health: SqliteRuleHealth,
        interval_seconds: int = 300,
    ) -> None:
        self._execute_rule = execute_rule
        self._unit_of_work = unit_of_work
        self._health = health
        self._interval_seconds = interval_seconds

    async def run_forever(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self._interval_seconds)

    async def run_once(self) -> None:
        today = datetime.now(UTC).date()
        with self._unit_of_work() as uow:
            # Each rule's daily full pass is due from its own last one, so a restart or another
            # rule's failure never re-lists calendars that already completed today's pass.
            due = tuple(
                (rule, _full_pass_due(uow.run_outcomes.latest(rule.id, RunKind.SYNC), today))
                for rule in uow.rules.list()
                if rule.state is SyncRuleState.ENABLED
            )
        for rule, full in due:
            await asyncio.to_thread(self._execute_with_retry, rule, full)

    def _execute_with_retry(self, rule: SyncRule, full: bool = False) -> bool:
        # Every decision of a daily pass, including its retries, is recorded above this entry.
        floor = self._health.audit_floor() if full else None
        for attempt in range(3):
            try:
                self._execute_rule.execute(rule.id, full=full)
                self._health.record_success(rule, full_pass_floor=floor)
                return True
            except RuleNotExecutable:
                # The rule was paused, edited, or removed after this pass listed it.
                return True
            except ProviderFailure as failure:
                if not failure.retryable or attempt == 2:
                    self._health.record_failure(rule, failure)
                    return False
                base_delay = failure.retry_after_seconds or 2**attempt
                time.sleep(base_delay + random.uniform(0, 0.25))
            except Exception as error:
                logger.exception("Unexpected synchronization failure for rule %s", rule.id.value)
                self._health.record_failure(
                    rule,
                    ProviderFailure(
                        ProviderFailureKind.INFRASTRUCTURE,
                        error.__class__.__name__,
                    ),
                )
                return False
        return False


def _full_pass_due(latest: RuleRunOutcome | None, today: date) -> bool:
    completed = latest.last_full_succeeded_at if latest is not None else None
    return completed is None or completed.astimezone(UTC).date() != today
