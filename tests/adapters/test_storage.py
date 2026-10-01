import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from calendar_sync.application.ports import AuditAction, AuditEntry, AuditOutcome, RecordedEvent
from calendar_sync.domain.model import SyncReason
from calendar_sync.infrastructure.persistence.activity_queries import open_blocks
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
) -> int:
    with SqliteUnitOfWorkFactory(path, FixedClock())() as uow:
        uow.audit.append(
            AuditEntry(
                occurred_at=NOW - timedelta(days=days_ago),
                rule_id=rule().id,
                action=AuditAction.CONFLICT if blocked else AuditAction.UPDATE,
                outcome=AuditOutcome.BLOCKED if blocked else AuditOutcome.COMPLETED,
                source_event_id=event,
                reason=SyncReason.SOURCE_UNVERIFIABLE if blocked else SyncReason.SOURCE_CHANGED,
                run_id=f"run-{days_ago}",
                event=None if title is None else RecordedEvent(title=title, cancelled=cancelled),
            )
        )
        uow.commit()
    with sqlite3.connect(path) as connection:
        return int(connection.execute("SELECT MAX(id) FROM audit_entries").fetchone()[0])


def _ids(path: Path) -> list[int]:
    with sqlite3.connect(path) as connection:
        return [row[0] for row in connection.execute("SELECT id FROM audit_entries ORDER BY id")]


def _block_check(path: Path, floor: int) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO rule_block_checks (rule_id, audit_floor, checked_at) VALUES (?, ?, ?)",
            (rule().id.value, floor, NOW.isoformat()),
        )


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
    latest_a = _entry(path, 100, "a")  # older than the cutoff, but a's latest
    old_b = _entry(path, 120, "b")
    recent_b = _entry(path, 10, "b")
    storage = SqliteStorage(path)

    assert storage.clearable_activity(CUTOFF) == 2
    assert storage.clear_activity(CUTOFF) == 2

    assert _ids(path) == [latest_a, recent_b]
    assert old_a not in _ids(path)
    assert old_b not in _ids(path)


def test_clearing_keeps_what_a_persisting_block_check_reads(tmp_path: Path) -> None:
    path = _database(tmp_path)
    _entry(path, 300, "blocked-event", blocked=True)
    before_floor = _entry(path, 200, "blocked-event", blocked=True)
    _block_check(path, floor=before_floor)
    _entry(path, 5, "blocked-event", blocked=True)
    with sqlite3.connect(path) as connection:
        persisting = open_blocks(connection, after=before_floor, persisting=True)
        current = open_blocks(connection)

    SqliteStorage(path).clear_activity(CUTOFF)

    assert before_floor in _ids(path)
    with sqlite3.connect(path) as connection:
        assert open_blocks(connection, after=before_floor, persisting=True) == persisting
        assert open_blocks(connection) == current


def test_clearing_keeps_the_title_a_cancellation_is_named_from(tmp_path: Path) -> None:
    path = _database(tmp_path)
    titled = _entry(path, 200, "c", title="Offsite")
    untitled_cancellation = _entry(path, 150, "c", title="", cancelled=True)

    SqliteStorage(path).clear_activity(CUTOFF)

    assert _ids(path) == [titled, untitled_cancellation]


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
