import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from calendar_sync.application.errors import FileLoggingOff, InvalidActivityAge, StorageBusy
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import DatabaseUsage, LogUsage
from calendar_sync.application.storage import StorageAdministration
from calendar_sync.domain.model import SyncRule, SyncRuleId, SyncRuleState
from tests.fake_calendar import FixedClock
from tests.helpers import endpoint, rule

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
        database, RuleLocks(), FixedClock(), logs, compact_wait_seconds=wait
    )


def _second_rule() -> SyncRule:
    return SyncRule(
        id=SyncRuleId("rule-2"),
        source=endpoint("personal-account-2", "personal-calendar-2"),
        destination=endpoint("work-account-2", "work-calendar-2"),
        state=SyncRuleState.ENABLED,
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

    with pytest.raises(InvalidActivityAge, match="Choose 30, 90, 180 or 365 days"):
        storage.clear_activity(days)
    with pytest.raises(InvalidActivityAge, match="Choose 30, 90, 180 or 365 days"):
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


def test_compacting_with_no_rules_runs_straight_away() -> None:
    database = FakeDatabase()
    storage = _storage(database)

    storage.clear_activity(30)

    assert database.compactions == 1


def test_compacting_releases_the_first_lock_when_a_second_times_out() -> None:
    database = FakeDatabase()
    storage = _storage(database, wait=0.05)
    first_lock = storage.locks.for_rule(rule().id)
    second_lock = storage.locks.for_rule(_second_rule().id)
    second_lock.acquire()
    try:
        with pytest.raises(StorageBusy):
            storage.clear_activity(30)
        # The lock that timed out was never ours to release: it is still held, by this test.
        assert second_lock.locked()
        assert not first_lock.locked()
    finally:
        second_lock.release()

    assert database.compactions == 0


# Regression: PR #34 review: a rule created after the last check could start during VACUUM
def test_a_rule_first_run_while_compacting_waits_for_it_to_finish() -> None:
    database = FakeDatabase()
    storage = _storage(database, wait=1.0)
    blocked: list[bool] = []

    def _new_rule_runs_during_compaction() -> None:
        def first_run() -> None:
            lock = storage.locks.for_rule(_second_rule().id)
            acquired = lock.acquire(timeout=0.05)
            blocked.append(not acquired)
            if acquired:
                lock.release()

        thread = threading.Thread(target=first_run)
        thread.start()
        thread.join()

    database.compact = _new_rule_runs_during_compaction  # type: ignore[method-assign]

    storage.clear_activity(30)

    assert blocked == [True]
    assert not storage.locks.for_rule(_second_rule().id).locked()


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


# Regression: ISSUE-001: clearing Activity left no trace in the logs
# Found by /qa on 2026-10-01
# Report: .context/qa-reports/run-20261001T190652Z/qa-report-127.0.0.1-2026-10-01.md
def test_clearing_activity_is_logged_with_its_age_and_count(
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage = _storage(FakeDatabase())

    with caplog.at_level("INFO", logger="calendar_sync"):
        storage.clear_activity(90)

    assert "activity cleared older_than_days=90 removed=7 space=reclaimed" in caplog.text


def test_clearing_whose_space_stays_unreclaimed_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage = _storage(FakeDatabase(), wait=0.05)
    running = storage.locks.for_rule(rule().id)
    running.acquire()
    try:
        with caplog.at_level("INFO", logger="calendar_sync"), pytest.raises(StorageBusy):
            storage.clear_activity(30)
    finally:
        running.release()

    warnings = [record for record in caplog.records if record.levelname == "WARNING"]
    assert [record.getMessage() for record in warnings] == [
        "activity cleared older_than_days=30 removed=7 space=not reclaimed, a rule was busy"
    ]
