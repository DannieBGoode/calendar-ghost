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
from calendar_sync.application.ports import UnitOfWorkFactory
from calendar_sync.application.synchronization import ExecuteSyncRule
from calendar_sync.domain.model import SyncRule, SyncRuleState
from calendar_sync.infrastructure.notifications import IncidentNotification, IncidentNotifier

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class SqliteRuleHealth:
    def __init__(
        self,
        database_path: Path,
        unit_of_work: UnitOfWorkFactory,
        notifier: IncidentNotifier | None = None,
    ) -> None:
        self._database_path = database_path
        self._unit_of_work = unit_of_work
        self._notifier = notifier

    def record_success(self, rule: SyncRule) -> None:
        now = datetime.now(UTC).isoformat()
        key = f"provider:{rule.id.value}"
        with sqlite3.connect(self._database_path) as connection:
            connection.execute("DELETE FROM rule_failures WHERE rule_id = ?", (rule.id.value,))
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
            self._open_incident(rule, failure.kind, now)

    def _degrade(self, rule: SyncRule) -> None:
        if rule.state is not SyncRuleState.ENABLED:
            return
        with self._unit_of_work() as uow:
            current = uow.rules.get(rule.id)
            if current is not None and current.state is SyncRuleState.ENABLED:
                uow.rules.save(current.degrade())
                uow.commit()

    def _open_incident(self, rule: SyncRule, kind: ProviderFailureKind, occurred_at: str) -> None:
        key = f"provider:{rule.id.value}"
        summary = {
            ProviderFailureKind.AUTHENTICATION: "Google authorization expired",
            ProviderFailureKind.AUTHORIZATION: "Google calendar access was denied",
            ProviderFailureKind.RATE_LIMIT: "Google Calendar is limiting requests",
            ProviderFailureKind.TEMPORARY: "Google Calendar is temporarily unavailable",
            ProviderFailureKind.PERMANENT: "Google Calendar rejected synchronization",
            ProviderFailureKind.INFRASTRUCTURE: "Local synchronization infrastructure failed",
        }[kind]
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
                    rule.id.value,
                    kind.value,
                    summary,
                    occurred_at,
                    occurred_at,
                ),
            )
        if newly_opened and self._notifier is not None:
            self._notifier.notify(
                IncidentNotification(rule.id.value, kind.value, summary, occurred_at)
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
        self._last_full_reconciliation: date | None = None

    async def run_forever(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self._interval_seconds)

    async def run_once(self) -> None:
        with self._unit_of_work() as uow:
            enabled = tuple(
                rule for rule in uow.rules.list() if rule.state is SyncRuleState.ENABLED
            )
        today = datetime.now(UTC).date()
        full = self._last_full_reconciliation != today
        successful = []
        for rule in enabled:
            successful.append(await asyncio.to_thread(self._execute_with_retry, rule, full))
        if full and enabled and all(successful):
            self._last_full_reconciliation = today

    def _execute_with_retry(self, rule: SyncRule, full: bool = False) -> bool:
        for attempt in range(3):
            try:
                self._execute_rule.execute(rule.id, full=full)
                self._health.record_success(rule)
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
