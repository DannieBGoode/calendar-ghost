"""Settings → Storage: what the installation keeps, and clearing what it no longer needs."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta

from calendar_sync.application.errors import (
    STORAGE_BUSY_MESSAGE,
    FileLoggingOff,
    InvalidActivityAge,
    StorageBusy,
)
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    Clock,
    DatabaseStorage,
    DatabaseUsage,
    LogFiles,
    LogUsage,
    UnitOfWorkFactory,
)
from calendar_sync.domain.model import SyncRuleId

logger = logging.getLogger(__name__)

ACTIVITY_AGES: tuple[int, ...] = (30, 90, 180, 365)
COMPACT_WAIT_SECONDS: float = 30.0


@dataclass(frozen=True, slots=True)
class StorageUsage:
    database: DatabaseUsage
    logs: LogUsage | None
    """None when the installation keeps no log files."""


@dataclass(frozen=True, slots=True)
class ClearedActivity:
    removed: int
    database: DatabaseUsage


@dataclass(slots=True)
class StorageAdministration:
    database: DatabaseStorage
    unit_of_work: UnitOfWorkFactory
    locks: RuleLocks
    clock: Clock
    logs: LogFiles | None = None
    compact_wait_seconds: float = COMPACT_WAIT_SECONDS

    def usage(self) -> StorageUsage:
        return StorageUsage(self.database.usage(), self.logs.usage() if self.logs else None)

    def clearable_activity(self, older_than_days: int) -> int:
        return self.database.clearable_activity(self._cutoff(older_than_days))

    def clear_activity(self, older_than_days: int) -> ClearedActivity:
        removed = self.database.clear_activity(self._cutoff(older_than_days))
        cleared = f"activity cleared older_than_days={older_than_days} removed={removed}"
        try:
            self._compact()
        except StorageBusy:
            # The entries are gone either way; only reclaiming their space waits for a retry.
            logger.warning("%s space=not reclaimed, a rule was busy", cleared)
            raise
        logger.info("%s space=reclaimed", cleared)
        return ClearedActivity(removed, self.database.usage())

    def log_chunks(self) -> Iterator[bytes]:
        return self._log_files().chunks()

    def purge_logs(self) -> None:
        self._log_files().purge()

    def _cutoff(self, older_than_days: int) -> datetime:
        if older_than_days not in ACTIVITY_AGES:
            *earlier, last = (str(age) for age in ACTIVITY_AGES)
            raise InvalidActivityAge(f"Choose {', '.join(earlier)} or {last} days")
        return self.clock.now() - timedelta(days=older_than_days)

    def _compact(self) -> None:
        """Compact while every rule's lock is held, a run in progress waited for, never cut off.

        A rule created while waiting is itself locked and re-checked, rather than compacting
        around it, so a "Sync now" on a brand-new rule can never run concurrently with `VACUUM`.
        """
        deadline = time.monotonic() + self.compact_wait_seconds
        with ExitStack() as held:
            locked: set[SyncRuleId] = set()
            pending = self._rule_ids()
            while pending:
                for rule_id in pending:
                    lock = self.locks.for_rule(rule_id)
                    if not lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
                        raise StorageBusy(STORAGE_BUSY_MESSAGE)
                    held.callback(lock.release)
                    locked.add(rule_id)
                pending = tuple(rule_id for rule_id in self._rule_ids() if rule_id not in locked)
            self.database.compact()

    def _rule_ids(self) -> tuple[SyncRuleId, ...]:
        with self.unit_of_work() as uow:
            return tuple(sorted((rule.id for rule in uow.rules.list()), key=lambda r: r.value))

    def _log_files(self) -> LogFiles:
        if self.logs is None:
            raise FileLoggingOff("This installation keeps no log files")
        return self.logs
