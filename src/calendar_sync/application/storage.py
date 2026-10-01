"""Settings → Storage: what the installation keeps, and clearing what it no longer needs."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta

from calendar_sync.application.errors import FileLoggingOff, InvalidActivityAge, StorageBusy
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    Clock,
    DatabaseStorage,
    DatabaseUsage,
    LogFiles,
    LogUsage,
    UnitOfWorkFactory,
)

ACTIVITY_AGES: tuple[int, ...] = (30, 90, 180, 365)
COMPACT_WAIT_SECONDS = 30.0
BUSY = (
    "Old Activity was cleared, but its space could not be reclaimed while a rule is "
    "synchronizing. Try again when it finishes."
)


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
        self._compact()
        return ClearedActivity(removed, self.database.usage())

    def log_chunks(self) -> Iterator[bytes]:
        return self._log_files().chunks()

    def purge_logs(self) -> None:
        self._log_files().purge()

    def _cutoff(self, older_than_days: int) -> datetime:
        if older_than_days not in ACTIVITY_AGES:
            raise InvalidActivityAge(
                f"Activity can be cleared after {', '.join(map(str, ACTIVITY_AGES))} days"
            )
        return self.clock.now() - timedelta(days=older_than_days)

    def _compact(self) -> None:
        """Compact while no rule runs; a run in progress is waited for, never interrupted."""
        with self.unit_of_work() as uow:
            rule_ids = sorted((rule.id for rule in uow.rules.list()), key=lambda item: item.value)
        deadline = time.monotonic() + self.compact_wait_seconds
        with ExitStack() as held:
            for rule_id in rule_ids:
                lock = self.locks.for_rule(rule_id)
                if not lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
                    raise StorageBusy(BUSY)
                held.callback(lock.release)
            self.database.compact()

    def _log_files(self) -> LogFiles:
        if self.logs is None:
            raise FileLoggingOff("This installation keeps no log files")
        return self.logs
