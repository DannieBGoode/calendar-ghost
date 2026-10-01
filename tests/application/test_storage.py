from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from calendar_sync.application.errors import FileLoggingOff, InvalidActivityAge, StorageBusy
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import DatabaseUsage, LogUsage
from calendar_sync.application.storage import StorageAdministration
from tests.fake_calendar import FixedClock, enabled_rule_factory
from tests.helpers import rule

USAGE = DatabaseUsage(bytes=4096, reclaimable_bytes=0, activity_entries=3, oldest_activity_at=None)


@dataclass
class FakeDatabase:
    cleared_before: list[datetime] = field(default_factory=list)
    compactions: int = 0

    def usage(self) -> DatabaseUsage:
        return USAGE

    def clearable_activity(self, before: datetime) -> int:
        return 7

    def clear_activity(self, before: datetime) -> int:
        self.cleared_before.append(before)
        return 7

    def compact(self) -> None:
        self.compactions += 1


@dataclass
class FakeLogs:
    purged: int = 0

    def usage(self) -> LogUsage:
        return LogUsage(10, 1, None, None)

    def chunks(self) -> Iterator[bytes]:
        yield b"line\n"

    def purge(self) -> None:
        self.purged += 1


def _storage(
    database: FakeDatabase, logs: FakeLogs | None = None, wait: float = 0.05
) -> StorageAdministration:
    return StorageAdministration(
        database,
        enabled_rule_factory(),
        RuleLocks(),
        FixedClock(),
        logs,
        compact_wait_seconds=wait,
    )


def test_clearing_uses_the_chosen_age_and_compacts() -> None:
    database = FakeDatabase()
    storage = _storage(database)

    cleared = storage.clear_activity(90)

    assert cleared.removed == 7
    assert database.cleared_before == [FixedClock().now() - timedelta(days=90)]
    assert database.compactions == 1


@pytest.mark.parametrize("days", [0, 1, 29, 31, 366, -90])
def test_only_the_offered_ages_can_be_cleared(days: int) -> None:
    storage = _storage(FakeDatabase())

    with pytest.raises(InvalidActivityAge):
        storage.clear_activity(days)
    with pytest.raises(InvalidActivityAge):
        storage.clearable_activity(days)


def test_compacting_waits_for_running_rule_work_then_reports_busy() -> None:
    database = FakeDatabase()
    storage = _storage(database, wait=0.05)
    running = storage.locks.for_rule(rule().id)
    running.acquire()
    try:
        with pytest.raises(StorageBusy):
            storage.clear_activity(30)
    finally:
        running.release()

    # Entries were already cleared; only the space was not reclaimed.
    assert len(database.cleared_before) == 1
    assert database.compactions == 0
    assert not running.locked()


def test_compacting_holds_every_rule_lock_and_releases_them() -> None:
    held: list[bool] = []
    database = FakeDatabase()
    storage = _storage(database)
    lock = storage.locks.for_rule(rule().id)
    database.compact = lambda: held.append(lock.locked())  # type: ignore[method-assign]

    storage.clear_activity(30)

    assert held == [True]
    assert not lock.locked()


def test_clearing_twice_is_not_an_error() -> None:
    storage = _storage(FakeDatabase())

    storage.clear_activity(365)
    storage.clear_activity(365)


def test_logs_need_file_logging() -> None:
    storage = _storage(FakeDatabase(), logs=None)

    assert storage.usage().logs is None
    with pytest.raises(FileLoggingOff):
        storage.purge_logs()
    with pytest.raises(FileLoggingOff):
        list(storage.log_chunks())


def test_purging_logs_purges_the_files() -> None:
    logs = FakeLogs()
    storage = _storage(FakeDatabase(), logs)

    storage.purge_logs()

    assert logs.purged == 1
    assert b"".join(storage.log_chunks()) == b"line\n"
