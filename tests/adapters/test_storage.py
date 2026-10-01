import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from calendar_sync.application.activity import ActivityEntry, ActivityFilter
from calendar_sync.application.errors import StorageBusy
from calendar_sync.application.ports import AuditAction, AuditEntry, AuditOutcome, RecordedEvent
from calendar_sync.domain.model import SyncReason, TimedInterval
from calendar_sync.infrastructure.persistence.activity_queries import (
    SqliteActivityQueries,
    open_blocks,
)
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from calendar_sync.infrastructure.persistence.storage import SqliteStorage
from tests.fake_calendar import FixedClock
from tests.helpers import rule

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
CUTOFF = NOW - timedelta(days=90)


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "sync.db"
    initialize_database(path)
    with SqliteUnitOfWorkFactory(path, FixedClock())() as uow:
        uow.rules.add(rule())
        uow.commit()
    return path


def _entry(
    path: Path,
    days_ago: int,
    event: str | None,
    *,
    blocked: bool = False,
    title: str | None = "Standup",
    cancelled: bool = False,
    reason: SyncReason | None = None,
    time: TimedInterval | None = None,
) -> int:
    with SqliteUnitOfWorkFactory(path, FixedClock())() as uow:
        uow.audit.append(
            AuditEntry(
                occurred_at=NOW - timedelta(days=days_ago),
                rule_id=rule().id,
                action=AuditAction.CONFLICT if blocked else AuditAction.UPDATE,
                outcome=AuditOutcome.BLOCKED if blocked else AuditOutcome.COMPLETED,
                source_event_id=event,
                reason=reason
                or (SyncReason.SOURCE_UNVERIFIABLE if blocked else SyncReason.SOURCE_CHANGED),
                run_id=f"run-{days_ago}",
                event=(
                    None
                    if title is None
                    else RecordedEvent(title=title, time=time, cancelled=cancelled)
                ),
            )
        )
        uow.commit()
    with sqlite3.connect(path) as connection:
        return int(connection.execute("SELECT MAX(id) FROM audit_entries").fetchone()[0])


def _ids(path: Path) -> list[int]:
    with sqlite3.connect(path) as connection:
        return [row[0] for row in connection.execute("SELECT id FROM audit_entries ORDER BY id")]


def _time(days_ago: int) -> TimedInterval:
    start = NOW - timedelta(days=days_ago)
    return TimedInterval(start, start + timedelta(hours=1))


def test_usage_reports_size_reclaimable_space_and_activity(tmp_path: Path) -> None:
    path = _database(tmp_path)
    _entry(path, 200, "a")
    _entry(path, 10, "b")

    usage = SqliteStorage(path).usage()

    assert usage.bytes == path.stat().st_size
    assert 0 <= usage.reclaimable_bytes < usage.bytes
    assert usage.activity_entries == 2
    assert usage.oldest_activity_at == NOW - timedelta(days=200)


def test_usage_without_activity_has_no_oldest_entry(tmp_path: Path) -> None:
    usage = SqliteStorage(_database(tmp_path)).usage()

    assert (usage.activity_entries, usage.oldest_activity_at) == (0, None)


def test_clearing_removes_old_history_and_keeps_each_events_latest_entry(tmp_path: Path) -> None:
    path = _database(tmp_path)
    old_a = _entry(path, 200, "a")
    middle_a = _entry(path, 150, "a")
    latest_a = _entry(path, 100, "a")  # older than the cutoff, but a's latest before it
    # "b" has a single entry older than the cutoff: kept, because "recent_b" could read back to
    # it, even though "b" also has an entry newer than the cutoff.
    old_b = _entry(path, 120, "b")
    recent_b = _entry(path, 10, "b")
    storage = SqliteStorage(path)

    assert storage.clearable_activity(CUTOFF) == 2
    assert storage.clear_activity(CUTOFF) == 2

    assert _ids(path) == [latest_a, old_b, recent_b]
    assert old_a not in _ids(path)
    assert middle_a not in _ids(path)


def test_clearing_keeps_what_an_in_flight_persisting_check_reads(tmp_path: Path) -> None:
    """A persisting block check reads a `MAX(id)` floor taken just before the pass runs, not the

    floor stored from the rule's last check (`rule_block_checks.audit_floor`), which is always
    older. So the entry at or before that in-flight floor must survive clearing even when it is
    older than the cutoff.
    """
    path = _database(tmp_path)
    _entry(path, 300, "blocked-event", blocked=True)  # older than the cutoff
    with sqlite3.connect(path) as connection:
        floor = int(connection.execute("SELECT MAX(id) FROM audit_entries").fetchone()[0])
    _entry(path, 5, "blocked-event", blocked=True)  # written after the floor was taken
    with sqlite3.connect(path) as connection:
        persisting = open_blocks(connection, after=floor, persisting=True)
    assert persisting

    SqliteStorage(path).clear_activity(CUTOFF)

    with sqlite3.connect(path) as connection:
        assert open_blocks(connection, after=floor, persisting=True) == persisting


def test_clearing_keeps_the_title_a_cancellation_is_named_from(tmp_path: Path) -> None:
    path = _database(tmp_path)
    titled = _entry(path, 200, "c", title="Offsite")
    untitled_cancellation = _entry(path, 150, "c", title="", cancelled=True)

    SqliteStorage(path).clear_activity(CUTOFF)

    assert _ids(path) == [titled, untitled_cancellation]


def test_clearing_removes_a_removed_rules_old_entries_like_any_other(tmp_path: Path) -> None:
    path = _database(tmp_path)
    _entry(path, 200, "f")
    latest = _entry(path, 150, "f")  # the rule's only entry older than the cutoff after it
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM sync_rules WHERE id = ?", (rule().id.value,))
        connection.commit()

    assert SqliteStorage(path).clearable_activity(CUTOFF) == 1
    assert SqliteStorage(path).clear_activity(CUTOFF) == 1

    assert _ids(path) == [latest]


def test_clearing_runs_in_batches(tmp_path: Path) -> None:
    path = _database(tmp_path)
    for day in range(400, 300, -1):
        _entry(path, day, "d")
    storage = SqliteStorage(path, batch=7)

    assert storage.clear_activity(CUTOFF) == 99
    assert len(_ids(path)) == 1


def test_clearing_nothing_old_enough_is_not_an_error(tmp_path: Path) -> None:
    path = _database(tmp_path)
    _entry(path, 10, "e")
    storage = SqliteStorage(path)

    assert storage.clear_activity(CUTOFF) == 0
    assert storage.clear_activity(CUTOFF) == 0
    storage.compact()


def test_compacting_returns_cleared_space_to_the_filesystem(tmp_path: Path) -> None:
    path = _database(tmp_path)
    for day in range(2000, 100, -1):
        _entry(path, day, f"event-{day}", title="x" * 200)
        _entry(path, day, f"event-{day}", title="y" * 200)
    storage = SqliteStorage(path)
    storage.clear_activity(CUTOFF)
    before = path.stat().st_size

    storage.compact()

    assert path.stat().st_size < before
    assert storage.usage().reclaimable_bytes == 0


def test_compacting_a_locked_database_raises_storage_busy(tmp_path: Path) -> None:
    path = _database(tmp_path)
    storage = SqliteStorage(path, busy_timeout=0.2)
    blocker = sqlite3.connect(path)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(StorageBusy):
            storage.compact()
    finally:
        blocker.rollback()
        blocker.close()


class _BrokenConnection:
    """Stands in for a connection whose `VACUUM` fails for a reason other than contention."""

    def execute(self, *args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("no such table: audit_entries")

    def close(self) -> None:
        pass


def test_compacting_reraises_an_unrelated_operational_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _database(tmp_path)
    storage = SqliteStorage(path)
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: _BrokenConnection())

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        storage.compact()


def test_clearing_keeps_what_activity_reads_across_the_cutoff(tmp_path: Path) -> None:
    path = _database(tmp_path)
    # A repair repeated by every run of the same event: the oldest copy is older than the cutoff;
    # the later two are newer and each is compared against the previous one to tell whether it
    # repeats.
    _entry(path, 100, "repeat", reason=SyncReason.PROJECTION_MISSING)
    repeat_2 = _entry(path, 80, "repeat", reason=SyncReason.PROJECTION_MISSING)
    repeat_3 = _entry(path, 10, "repeat", reason=SyncReason.PROJECTION_MISSING)
    # A cancellation recorded without a title, named from the event's last titled entry, which is
    # older than the cutoff.
    _entry(path, 200, "offsite-event", title="Offsite")
    cancelled_mid = _entry(path, 50, "offsite-event", title="", cancelled=True)
    # An event whose newer entry moved from a time only the older, pre-cutoff entry recorded.
    _entry(path, 300, "moved-event", time=_time(300))
    moved_new = _entry(path, 20, "moved-event", time=_time(20))

    kept_ids = (repeat_2, repeat_3, cancelled_mid, moved_new)
    queries = SqliteActivityQueries(path)

    def _snapshot() -> dict[int, ActivityEntry]:
        return {
            entry.id: entry
            for entry in queries.entries(ActivityFilter(limit=1000))
            if entry.id in kept_ids
        }

    before = _snapshot()
    assert before[repeat_2].repeated is True
    assert before[repeat_3].repeated is True
    cancelled_event = before[cancelled_mid].event
    assert cancelled_event is not None
    assert cancelled_event.title == "Offsite"
    moved_event = before[moved_new].event
    assert moved_event is not None
    assert moved_event.moved_from is not None

    SqliteStorage(path).clear_activity(CUTOFF)

    assert _snapshot() == before


# Regression: Codex review P2 — clearing deadlocked with a concurrent writer
# Found by /codex review on 2026-10-01
def test_clearing_waits_for_a_concurrent_writer_instead_of_failing(tmp_path: Path) -> None:
    path = _database(tmp_path)
    for day in range(200, 100, -1):
        _entry(path, day, "busy-event")
    writer = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    # A sync run's write is in progress when clearing starts, and commits a moment later.
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("UPDATE sync_rules SET state = state")
    committed = threading.Event()

    def commit_soon() -> None:
        time.sleep(0.3)
        writer.execute("COMMIT")
        committed.set()

    thread = threading.Thread(target=commit_soon)
    thread.start()
    try:
        removed = SqliteStorage(path).clear_activity(CUTOFF)
    finally:
        thread.join()
        writer.close()

    assert committed.is_set()
    assert removed == 99


# Regression: PR #34 review — after the clock stepped back, clearing removed the entry a recent
# one is compared with, because protection picked entries by time while Activity walks by id.
def test_clearing_after_the_clock_stepped_back_keeps_what_recent_entries_compare_with(
    tmp_path: Path,
) -> None:
    path = _database(tmp_path)
    _entry(path, 200, "renamed", title="Weekly sync")
    renamed = _entry(path, 10, "renamed", title="Team sync")
    # The clock stepped back past the cutoff before the next run.
    _entry(path, 150, "renamed", title="Team sync")
    latest = _entry(path, 5, "renamed", title="Team sync")
    # Untitled, so only the previous entry by id, not a titled one, tells whether it repeats.
    _entry(path, 200, "repeat", reason=SyncReason.PROJECTION_MISSING, title=None)
    repeated = _entry(path, 10, "repeat", reason=SyncReason.PROJECTION_MISSING, title=None)
    _entry(path, 150, "repeat", reason=SyncReason.SOURCE_CHANGED, title=None)
    kept_ids = (renamed, latest, repeated)
    queries = SqliteActivityQueries(path)

    def _snapshot() -> dict[int, ActivityEntry]:
        return {
            entry.id: entry
            for entry in queries.entries(ActivityFilter(limit=1000))
            if entry.id in kept_ids
        }

    before = _snapshot()
    renamed_event = before[renamed].event
    assert renamed_event is not None
    assert renamed_event.renamed_from == "Weekly sync"
    assert before[repeated].repeated is True

    SqliteStorage(path).clear_activity(CUTOFF)

    assert _snapshot() == before


# Regression: PR #34 review — with the clock stepped back past the cutoff, clearing between a
# pass and its block check removed the earlier block the check compares with.
def test_clearing_keeps_what_a_block_check_reads_when_the_new_block_looks_old(
    tmp_path: Path,
) -> None:
    path = _database(tmp_path)
    _entry(path, 200, "blocked-event", blocked=True)
    with sqlite3.connect(path) as connection:
        floor = int(connection.execute("SELECT MAX(id) FROM audit_entries").fetchone()[0])
    # The pass repeats the block, but the clock stepped back, so it looks older than the cutoff.
    _entry(path, 150, "blocked-event", blocked=True)
    with sqlite3.connect(path) as connection:
        before = open_blocks(connection, after=floor, persisting=True)
    assert before

    SqliteStorage(path).clear_activity(CUTOFF)

    with sqlite3.connect(path) as connection:
        assert open_blocks(connection, after=floor, persisting=True) == before
