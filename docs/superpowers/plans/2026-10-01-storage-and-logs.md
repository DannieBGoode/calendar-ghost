# Storage and Logs in Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Settings shows how much space the database and the logs use, and lets the
administrator download and purge the logs and clear Activity older than a chosen age.

**Architecture:**
- **Logs:** a rotating log file joins the stderr handler that `bootstrap/logs.py` already
  configures. An infrastructure `RotatingLogFiles` owns that handler and can report usage, stream
  the files and purge them.
- **Database:** an infrastructure `SqliteStorage` reports database usage and clears old Audit
  Entries in batches, keeping the protected ones, then compacts the file.
- **Application:** a `StorageAdministration` use case (`application/storage.py`) composes both
  through two small ports. It also serializes compaction with rule work through `RuleLocks`.
- **Interfaces:** a new admin-only router (`routes/storage.py`) exposes the use case, and Settings
  gains a Storage section.

**Tech Stack:**
- Backend: Python 3.12 with stdlib `logging.handlers.RotatingFileHandler`, `sqlite3`, FastAPI and
  pydantic.
- Frontend: React with TanStack Query and vitest.

**Spec:** `docs/superpowers/specs/2026-10-01-storage-and-logs-design.md`

**Branch:** create `DannieBGoode/storage-and-logs` from `DannieBGoode/rasppi5-rule-syncing-stuck`.
It builds on that branch's run logging (PR #33). Open its PR against `main` once #33 merges.

## Global Constraints

**Process and architecture**
- Follow `AGENTS.md`.
- Dependency boundaries are enforced by `lint-imports`. Application code may not import
  `sqlite3`, FastAPI or pydantic. Never add `ignore_imports`.

**Data and log content**
- Event content never reaches logs: only rule and run identifiers, operation names, counts,
  durations and statuses. The file handler formats the same records as stderr.
- Every `/api/v1/storage*` route is behind `require_admin`; `test_api_authorization.py` enforces
  this automatically.
- File paths are never taken from a request. They are resolved inside the log directory.

**Log files**
- Rotation: 5 MB (`5 * 1024 * 1024`) per file, current plus 4 rotated (`backupCount=4`). When the
  current file reaches 5 MB, the oldest file is deleted and a new current file starts.
- Default directory: `<database directory>/logs`. `CALENDAR_SYNC_LOG_DIR` overrides it, and an
  empty value turns file logging off.

**Clearing Activity**
- Allowed ages: exactly 30, 90, 180 and 365 days. Anything else is a 422.
- Kept regardless of age, per rule and source event:
  1. the latest entry;
  2. the latest entry at or before `rule_block_checks.audit_floor`;
  3. the latest entry that recorded a title (`event_title IS NOT NULL AND (event_title <> '' OR NOT event_cancelled)`).
- Deletion runs in batches of 5,000 rows, each its own transaction.
- `VACUUM` runs only while every rule's `RuleLocks.for_rule` lock is held. If those locks cannot
  all be acquired within 30 s, the answer is 409 with the detail `Old Activity was cleared, but
  its space could not be reclaimed while a rule is synchronizing. Try again when it finishes.`

**Quality**
- Coverage floor is 80%. All gates in `AGENTS.md` must pass.
- After any `web/` change, rebuild and commit `src/calendar_sync/interfaces/api/static/`.
- Each commit message ends with
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Unwritable log directory.** For example `/data/logs` exists as a file, or permission is
   denied. The service must still start and log to stderr, with one warning saying file logging is
   off. Covered in Task 1.
2. **Purging while another thread logs.** No exception, and later lines still reach the file.
   Covered in Task 1.
3. **A rotated file disappears between listing and reading during a download.** It is skipped and
   the download completes. Covered in Task 1.
4. **Clearing when nothing is old enough, or twice in a row.** Zero removed, no error, and the
   database is still compacted. Covered in Task 2 and Task 3.
5. **An installation with no Activity yet.** Usage reports zero entries and no oldest date, and
   Settings says "No Activity yet" instead of a broken date. Covered in Task 2 and Task 5.

---

### Task 1: Rotating log files

**Files:**
- Create: `src/calendar_sync/infrastructure/log_files.py`
- Modify: `src/calendar_sync/bootstrap/logs.py`
- Modify: `src/calendar_sync/bootstrap/config.py`
- Modify: `src/calendar_sync/bootstrap/container.py` (`service_container`, `Adapters`)
- Modify: `src/calendar_sync/application/ports.py` (add `LogUsage`, `LogFiles`)
- Test: `tests/adapters/test_log_files.py`, `tests/adapters/test_service_logging.py`

**Interfaces:**
- Produces, in `application/ports.py`:
  ```python
  @dataclass(frozen=True, slots=True)
  class LogUsage:
      bytes: int
      files: int
      oldest_at: datetime | None
      newest_at: datetime | None

  class LogFiles(Protocol):
      def usage(self) -> LogUsage: ...
      def chunks(self) -> Iterator[bytes]: ...
      def purge(self) -> None: ...
  ```
- Produces `infrastructure/log_files.py: RotatingLogFiles(directory: Path, max_bytes: int = 5 * 1024 * 1024, backups: int = 4)`, which implements `LogFiles` and adds `handler() -> logging.Handler`.
- Produces `bootstrap/logs.py: configure_logging(level: str, files: RotatingLogFiles | None = None) -> None`.
- Produces `Settings.log_directory: Path | None = None`. `from_environment` defaults it to
  `database_path.parent / "logs"`, and an empty `CALENDAR_SYNC_LOG_DIR` sets it to `None`.
- Produces `Adapters.log_files: LogFiles | None = None`.

- [ ] **Step 1: Write the failing tests** in `tests/adapters/test_log_files.py`

```python
import logging
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from calendar_sync.bootstrap.logs import configure_logging
from calendar_sync.infrastructure.log_files import RotatingLogFiles


@pytest.fixture(autouse=True)
def _restore_logger() -> Iterator[None]:
    logger = logging.getLogger("calendar_sync")
    handlers, level = list(logger.handlers), logger.level
    # Each test configures from scratch, so its stderr handler writes to the captured stream.
    logger.handlers[:] = []
    yield
    for handler in logger.handlers:
        if handler not in handlers:
            handler.close()
    logger.handlers[:] = handlers
    logger.setLevel(level)


def _line(at: str, message: str) -> str:
    return f"{at} INFO calendar_sync.test {message}\n"


def test_records_reach_the_file_formatted_like_standard_error(tmp_path: Path) -> None:
    files = RotatingLogFiles(tmp_path / "logs")
    configure_logging("INFO", files)

    logging.getLogger("calendar_sync.test").info("run finished rule=r1 in 2s")

    text = (tmp_path / "logs" / "calendar-sync.log").read_text()
    assert text.endswith("INFO calendar_sync.test run finished rule=r1 in 2s\n")
    assert text[:20].endswith("Z")  # 2026-10-01T18:04:12Z


def test_rotation_keeps_at_most_four_older_files_and_drops_the_oldest(tmp_path: Path) -> None:
    files = RotatingLogFiles(tmp_path / "logs", max_bytes=200, backups=4)
    configure_logging("INFO", files)
    logger = logging.getLogger("calendar_sync.test")

    for number in range(60):
        logger.info("line %03d %s", number, "x" * 40)

    names = sorted(path.name for path in (tmp_path / "logs").iterdir())
    assert names == [
        "calendar-sync.log",
        "calendar-sync.log.1",
        "calendar-sync.log.2",
        "calendar-sync.log.3",
        "calendar-sync.log.4",
    ]
    everything = b"".join(files.chunks()).decode()
    assert "line 059" in everything
    assert "line 000" not in everything


def test_usage_counts_bytes_and_reads_the_first_and_last_line_times(tmp_path: Path) -> None:
    directory = tmp_path / "logs"
    directory.mkdir()
    (directory / "calendar-sync.log.1").write_text(
        _line("2026-09-12T08:00:00Z", "old") + _line("2026-09-13T08:00:00Z", "older")
    )
    (directory / "calendar-sync.log").write_text(_line("2026-10-01T18:04:12Z", "new"))
    files = RotatingLogFiles(directory)

    usage = files.usage()

    assert usage.files == 2
    assert usage.bytes == sum(path.stat().st_size for path in directory.iterdir())
    assert usage.oldest_at == datetime(2026, 9, 12, 8, tzinfo=UTC)
    assert usage.newest_at == datetime(2026, 10, 1, 18, 4, 12, tzinfo=UTC)


def test_usage_of_no_logs_is_empty(tmp_path: Path) -> None:
    usage = RotatingLogFiles(tmp_path / "logs").usage()

    assert (usage.bytes, usage.files, usage.oldest_at, usage.newest_at) == (0, 0, None, None)


def test_chunks_stream_the_oldest_file_first(tmp_path: Path) -> None:
    directory = tmp_path / "logs"
    directory.mkdir()
    (directory / "calendar-sync.log.2").write_text("first\n")
    (directory / "calendar-sync.log.1").write_text("second\n")
    (directory / "calendar-sync.log").write_text("third\n")

    assert b"".join(RotatingLogFiles(directory).chunks()) == b"first\nsecond\nthird\n"


def test_a_file_rotated_away_during_a_download_is_skipped(tmp_path: Path) -> None:
    directory = tmp_path / "logs"
    directory.mkdir()
    (directory / "calendar-sync.log.1").write_text("gone\n")
    (directory / "calendar-sync.log").write_text("kept\n")
    files = RotatingLogFiles(directory)
    chunks = files.chunks()
    (directory / "calendar-sync.log.1").unlink()

    assert b"".join(chunks) == b"kept\n"


def test_purge_empties_every_file_and_logging_continues(tmp_path: Path) -> None:
    files = RotatingLogFiles(tmp_path / "logs", max_bytes=200, backups=4)
    configure_logging("INFO", files)
    logger = logging.getLogger("calendar_sync.test")
    for number in range(30):
        logger.info("before purge %03d %s", number, "x" * 40)

    files.purge()
    logger.info("after purge")

    text = b"".join(files.chunks()).decode()
    assert "before purge" not in text
    assert "logs purged" in text
    assert text.endswith("after purge\n")
    assert [path.name for path in (tmp_path / "logs").iterdir()] == ["calendar-sync.log"]


def test_purge_while_another_thread_logs_raises_nothing(tmp_path: Path) -> None:
    files = RotatingLogFiles(tmp_path / "logs", max_bytes=2_000, backups=4)
    configure_logging("INFO", files)
    logger = logging.getLogger("calendar_sync.test")
    stop = threading.Event()

    def keep_logging() -> None:
        while not stop.is_set():
            logger.info("concurrent %s", "x" * 40)

    writer = threading.Thread(target=keep_logging)
    writer.start()
    try:
        for _ in range(20):
            files.purge()
    finally:
        stop.set()
        writer.join()
    logger.info("still writing")

    assert b"".join(files.chunks()).decode().endswith("still writing\n")


def test_an_unwritable_log_directory_leaves_standard_error_logging_working(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocked = tmp_path / "logs"
    blocked.write_text("a file where the directory should be")

    configure_logging("INFO", RotatingLogFiles(blocked))
    logging.getLogger("calendar_sync.test").info("service started")

    errors = capsys.readouterr().err
    assert "file logging is off" in errors
    assert "service started" in errors
```

Add to `tests/adapters/test_service_logging.py`:

```python
def test_log_directory_defaults_beside_the_database_and_can_be_turned_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CALENDAR_SYNC_DATABASE_PATH", str(tmp_path / "data" / "sync.db"))
    monkeypatch.delenv("CALENDAR_SYNC_LOG_DIR", raising=False)
    assert Settings.from_environment().log_directory == tmp_path / "data" / "logs"

    monkeypatch.setenv("CALENDAR_SYNC_LOG_DIR", str(tmp_path / "elsewhere"))
    assert Settings.from_environment().log_directory == tmp_path / "elsewhere"

    monkeypatch.setenv("CALENDAR_SYNC_LOG_DIR", "")
    assert Settings.from_environment().log_directory is None
```

(Import `Settings` from `calendar_sync.bootstrap.config` if the file does not already.)

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/pytest tests/adapters/test_log_files.py tests/adapters/test_service_logging.py -q`
Expected: ImportError for `calendar_sync.infrastructure.log_files`, and AttributeError for
`log_directory`.

- [ ] **Step 3: Add the ports** to `application/ports.py`, after `ProviderCallStats`. Add
  `Iterator` to the `collections.abc` import.

```python
@dataclass(frozen=True, slots=True)
class LogUsage:
    """What the service's own log files hold: their size, count, and first and last line times."""

    bytes: int
    files: int
    oldest_at: datetime | None
    newest_at: datetime | None


class LogFiles(Protocol):
    """The service's rotating log files. They carry no event content (AGENTS.md)."""

    def usage(self) -> LogUsage: ...

    def chunks(self) -> Iterator[bytes]:
        """Every file's bytes, oldest file first; a file rotated away meanwhile is skipped."""
        ...

    def purge(self) -> None:
        """Empty the logs, leaving one line that says they were purged."""
        ...
```

- [ ] **Step 4: Implement `infrastructure/log_files.py`**

```python
"""The service's own rotating log files, next to its database unless configured elsewhere.

They hold the same lines as standard error, so no event content reaches them either. At most
`backups + 1` files of `max_bytes` exist: the oldest file is deleted when the current one fills.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from calendar_sync.application.ports import LogUsage

FILE_NAME = "calendar-sync.log"
CHUNK_BYTES = 64 * 1024
# Lines start with the UTC time the stderr formatter writes, e.g. 2026-10-01T18:04:12Z.
TIMESTAMP_LENGTH = len("2026-10-01T18:04:12Z")

logger = logging.getLogger(__name__)


class RotatingLogFiles:
    def __init__(self, directory: Path, max_bytes: int = 5 * 1024 * 1024, backups: int = 4) -> None:
        self._directory = directory
        self._max_bytes = max_bytes
        self._backups = backups
        self._handler: RotatingFileHandler | None = None

    @property
    def directory(self) -> Path:
        return self._directory

    def handler(self) -> logging.Handler:
        """The handler writing the current file; raises OSError if the directory is unusable."""
        if self._handler is None:
            self._directory.mkdir(parents=True, exist_ok=True)
            self._handler = RotatingFileHandler(
                self._directory / FILE_NAME,
                maxBytes=self._max_bytes,
                backupCount=self._backups,
                encoding="utf-8",
            )
        return self._handler

    def files(self) -> list[Path]:
        """Existing log files, oldest first. Names are fixed; nothing comes from a request."""
        current = self._directory / FILE_NAME
        rotated = [
            current.with_name(f"{FILE_NAME}.{number}") for number in range(self._backups, 0, -1)
        ]
        return [path for path in (*rotated, current) if path.is_file()]

    def usage(self) -> LogUsage:
        paths = self.files()
        sizes = [_size(path) for path in paths]
        return LogUsage(
            bytes=sum(sizes),
            files=len(paths),
            oldest_at=next((at for path in paths if (at := _first_time(path))), None),
            newest_at=next((at for path in reversed(paths) if (at := _last_time(path))), None),
        )

    def chunks(self) -> Iterator[bytes]:
        for path in self.files():
            try:
                with path.open("rb") as file:
                    while chunk := file.read(CHUNK_BYTES):
                        yield chunk
            except FileNotFoundError:
                continue

    def purge(self) -> None:
        handler = self._handler
        if handler is not None:
            handler.acquire()
        try:
            for path in self.files():
                if path.name == FILE_NAME and handler is not None and handler.stream is not None:
                    handler.stream.seek(0)
                    handler.stream.truncate()
                else:
                    path.unlink(missing_ok=True)
        finally:
            if handler is not None:
                handler.release()
        logger.info("logs purged")


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _parse(line: bytes) -> datetime | None:
    try:
        stamp = line[:TIMESTAMP_LENGTH].decode()
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (UnicodeDecodeError, ValueError):
        return None


def _first_time(path: Path) -> datetime | None:
    try:
        with path.open("rb") as file:
            return _parse(file.readline())
    except FileNotFoundError:
        return None


def _last_time(path: Path) -> datetime | None:
    try:
        with path.open("rb") as file:
            file.seek(0, 2)
            size = file.tell()
            file.seek(max(0, size - 4096))
            lines = file.read().splitlines()
    except FileNotFoundError:
        return None
    return next((at for line in reversed(lines) if (at := _parse(line))), None)
```

- [ ] **Step 5: Attach the file handler in `bootstrap/logs.py`**

Replace `configure_logging` with the version below. Add `from calendar_sync.infrastructure.log_files import RotatingLogFiles`; bootstrap may import infrastructure.

```python
FILE_HANDLER = "calendar_sync.file"


def configure_logging(level: str, files: RotatingLogFiles | None = None) -> None:
    """Write `calendar_sync` records at `level` and above to standard error, and to `files`.

    Calling it again changes the level without adding a second handler, so no line is doubled. A
    log directory that cannot be used turns file logging off with one warning; the service runs.
    """
    logger = logging.getLogger(LOGGER)
    logger.setLevel(level.strip().upper())
    if not any(handler.get_name() == HANDLER for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.set_name(HANDLER)
        handler.setFormatter(_UtcFormatter())
        logger.addHandler(handler)
    if files is not None and not any(h.get_name() == FILE_HANDLER for h in logger.handlers):
        try:
            file_handler = files.handler()
        except OSError as error:
            logger.warning(
                "file logging is off: %s cannot be used (%s)",
                files.directory,
                error.__class__.__name__,
            )
        else:
            file_handler.set_name(FILE_HANDLER)
            file_handler.setFormatter(_UtcFormatter())
            logger.addHandler(file_handler)
    # Written here only, even when something else configures the root logger.
    logger.propagate = False
```

If `configure_logging` currently validates unknown levels (raises `ValueError`), keep that
behaviour exactly as it is now.

- [ ] **Step 6: Add the setting** in `bootstrap/config.py`

Add the field `log_directory: Path | None = None` after `log_level`. In `from_environment`, compute
it before `return cls(...)` and pass `log_directory=log_directory`:

```python
database_path = Path(os.environ.get("CALENDAR_SYNC_DATABASE_PATH", "./calendar-sync.db"))
configured_logs = os.environ.get("CALENDAR_SYNC_LOG_DIR")
log_directory = (
    database_path.parent / "logs"
    if configured_logs is None
    else (Path(configured_logs) if configured_logs.strip() else None)
)
```

Pass `database_path=database_path` too, instead of reading the variable twice.

- [ ] **Step 7: Wire it in `bootstrap/container.py`**

Add `log_files: LogFiles | None = None` to `Adapters`, importing `LogFiles` from ports. Change
`service_container`:

```python
def service_container() -> Container:
    """The running service's container, configured from the environment.

    Logging is configured first, so every line the service writes follows the configured level.
    """
    settings = Settings.from_environment()
    log_files = (
        RotatingLogFiles(settings.log_directory) if settings.log_directory is not None else None
    )
    configure_logging(settings.log_level, log_files)
    return compose(settings, replace(build_adapters(settings), log_files=log_files))
```

`build_container` stays as it is, so tests and the dev preview never write log files.

- [ ] **Step 8: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/adapters/test_log_files.py tests/adapters/test_service_logging.py -q`
Expected: all pass.

- [ ] **Step 9: Gates and commit**

Run `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/lint-imports && .venv/bin/pytest -q`.

```bash
git add src/calendar_sync tests
git commit -m "feat: keep the service's logs in rotating files beside the database"
```

---

### Task 2: Database usage and clearing old Activity in SQLite

**Files:**
- Create: `src/calendar_sync/infrastructure/persistence/storage.py`
- Modify: `src/calendar_sync/application/ports.py` (add `DatabaseUsage`, `DatabaseStorage`)
- Test: `tests/adapters/test_storage.py`

**Interfaces:**
- Produces, in `application/ports.py`:
  ```python
  @dataclass(frozen=True, slots=True)
  class DatabaseUsage:
      bytes: int
      reclaimable_bytes: int
      activity_entries: int
      oldest_activity_at: datetime | None

  class DatabaseStorage(Protocol):
      def usage(self) -> DatabaseUsage: ...
      def clearable_activity(self, before: datetime) -> int: ...
      def clear_activity(self, before: datetime) -> int: ...
      def compact(self) -> None: ...
  ```
- Produces `infrastructure/persistence/storage.py: SqliteStorage(database_path: Path, batch: int = 5000)`.

- [ ] **Step 1: Write the failing tests** in `tests/adapters/test_storage.py`

```python
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from calendar_sync.application.ports import AuditAction, AuditEntry, AuditOutcome, RecordedEvent
from calendar_sync.domain.model import SyncReason, SyncRuleId
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
    assert old_a not in _ids(path) and old_b not in _ids(path)


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
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/pytest tests/adapters/test_storage.py -q`
Expected: ImportError for `calendar_sync.infrastructure.persistence.storage`.

- [ ] **Step 3: Add the ports** to `application/ports.py`

```python
@dataclass(frozen=True, slots=True)
class DatabaseUsage:
    bytes: int
    reclaimable_bytes: int
    """Free pages the file keeps until it is compacted."""
    activity_entries: int
    oldest_activity_at: datetime | None


class DatabaseStorage(Protocol):
    """The installation's database, as Settings → Storage reports and trims it."""

    def usage(self) -> DatabaseUsage: ...

    def clearable_activity(self, before: datetime) -> int:
        """How many Audit Entries older than `before` clearing would remove."""
        ...

    def clear_activity(self, before: datetime) -> int:
        """Remove Audit Entries older than `before`, except those run health and naming read.

        Kept regardless of age, per rule and source event: the latest entry, the latest at or
        before the rule's last block check, and the latest that recorded a title.
        """
        ...

    def compact(self) -> None:
        """Return free pages to the filesystem. It briefly blocks every other writer."""
        ...
```

- [ ] **Step 4: Implement `infrastructure/persistence/storage.py`**

```python
"""Database usage, and clearing Activity older than an administrator-chosen age (ADR 0019)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from calendar_sync.application.ports import DatabaseUsage

# Entries clearing never removes. Each is the latest of its rule and source event in one sense:
# overall (open blocks), at or before the rule's last block check (persisting blocks), and among
# those that recorded a title (the name a cancellation without one is shown with).
_PROTECTED = """
    SELECT MAX(id) FROM audit_entries GROUP BY rule_id, source_event_id
    UNION
    SELECT MAX(a.id) FROM audit_entries a
    JOIN rule_block_checks c ON c.rule_id = a.rule_id
    WHERE a.id <= c.audit_floor
    GROUP BY a.rule_id, a.source_event_id
    UNION
    SELECT MAX(id) FROM audit_entries
    WHERE event_title IS NOT NULL AND (event_title <> '' OR NOT event_cancelled)
    GROUP BY rule_id, source_event_id
"""


class SqliteStorage:
    def __init__(self, database_path: Path, batch: int = 5000) -> None:
        self._database_path = database_path
        self._batch = batch

    def usage(self) -> DatabaseUsage:
        with closing(sqlite3.connect(self._database_path)) as connection:
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
            pages = int(connection.execute("PRAGMA page_count").fetchone()[0])
            free = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
            count, oldest = connection.execute(
                "SELECT COUNT(*), MIN(occurred_at) FROM audit_entries"
            ).fetchone()
        return DatabaseUsage(
            bytes=pages * page_size,
            reclaimable_bytes=free * page_size,
            activity_entries=int(count),
            oldest_activity_at=datetime.fromisoformat(oldest) if oldest else None,
        )

    def clearable_activity(self, before: datetime) -> int:
        with closing(sqlite3.connect(self._database_path)) as connection:
            # Interpolates only the constant protected-entries query.
            row = connection.execute(
                f"SELECT COUNT(*) FROM audit_entries WHERE occurred_at < ? "  # noqa: S608
                f"AND id NOT IN ({_PROTECTED})",
                (before.isoformat(),),
            ).fetchone()
        return int(row[0])

    def clear_activity(self, before: datetime) -> int:
        removed = 0
        with closing(sqlite3.connect(self._database_path)) as connection:
            # Chosen once, so batches never re-evaluate which entries are protected.
            connection.execute("DROP TABLE IF EXISTS temp.clearable")
            connection.execute(
                f"CREATE TEMP TABLE clearable AS SELECT id FROM audit_entries "  # noqa: S608
                f"WHERE occurred_at < ? AND id NOT IN ({_PROTECTED})",
                (before.isoformat(),),
            )
            connection.commit()
            while True:
                batch = [
                    row[0]
                    for row in connection.execute(
                        "SELECT id FROM temp.clearable ORDER BY id LIMIT ?", (self._batch,)
                    )
                ]
                if not batch:
                    return removed
                marks = ", ".join("?" for _ in batch)
                # One short write transaction per batch (AGENTS.md).
                with connection:
                    removed += connection.execute(
                        f"DELETE FROM audit_entries WHERE id IN ({marks})",  # noqa: S608
                        batch,
                    ).rowcount
                    connection.execute(
                        f"DELETE FROM temp.clearable WHERE id IN ({marks})",  # noqa: S608
                        batch,
                    )

    def compact(self) -> None:
        with closing(sqlite3.connect(self._database_path, isolation_level=None)) as connection:
            connection.execute("VACUUM")
```

Every f-string interpolates only the constant `_PROTECTED` query or `?` placeholders, and each
carries `# noqa: S608`, as `activity_queries.py` does.

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/adapters/test_storage.py -q`
Expected: all pass.

- [ ] **Step 6: Gates and commit**

```bash
git add src/calendar_sync tests
git commit -m "feat: report database usage and clear Activity older than a chosen age"
```

---

### Task 3: The storage use case

**Files:**
- Create: `src/calendar_sync/application/storage.py`
- Modify: `src/calendar_sync/application/errors.py`
- Test: `tests/application/test_storage.py`

**Interfaces:**
- Consumes: `DatabaseStorage`, `DatabaseUsage`, `LogFiles` and `LogUsage` (Tasks 1 and 2);
  `RuleLocks.for_rule(rule_id) -> threading.Lock`; `UnitOfWorkFactory` with
  `uow.rules.list() -> Sequence[SyncRule]`; `Clock.now()`.
- Produces in `application/errors.py`:
  - `class InvalidActivityAge(ApplicationError)`
  - `class StorageBusy(ApplicationError)`
  - `class FileLoggingOff(ApplicationError)`
- Produces in `application/storage.py`:
  ```python
  ACTIVITY_AGES: tuple[int, ...] = (30, 90, 180, 365)
  COMPACT_WAIT_SECONDS: float = 30.0

  @dataclass(frozen=True, slots=True)
  class StorageUsage:
      database: DatabaseUsage
      logs: LogUsage | None  # None when file logging is off

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

      def usage(self) -> StorageUsage: ...
      def clearable_activity(self, older_than_days: int) -> int: ...
      def clear_activity(self, older_than_days: int) -> ClearedActivity: ...
      def log_chunks(self) -> Iterator[bytes]: ...
      def purge_logs(self) -> None: ...
  ```

- [ ] **Step 1: Write the failing tests** in `tests/application/test_storage.py`

```python
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

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
```

Check `tests/fake_calendar.py` for `FixedClock` and `enabled_rule_factory`. The factory seeds
`rule()`, so `uow.rules.list()` returns it.

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/pytest tests/application/test_storage.py -q`
Expected: ImportError.

- [ ] **Step 3: Add the errors** to `application/errors.py`

```python
class InvalidActivityAge(ApplicationError):
    """Activity can be cleared only from one of the offered ages."""


class StorageBusy(ApplicationError):
    """Rule work kept the database from being compacted."""


class FileLoggingOff(ApplicationError):
    """The installation keeps no log files to read or purge."""
```

- [ ] **Step 4: Implement `application/storage.py`**

```python
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

ACTIVITY_AGES = (30, 90, 180, 365)
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
```

`log_chunks` must raise `FileLoggingOff` when it is called, not
lazily, so the route can answer 404 before streaming. That's why it returns the iterator instead
of being a generator.

- [ ] **Step 5: Run the tests and confirm they pass, then run the gates**

Run: `.venv/bin/pytest tests/application/test_storage.py -q && .venv/bin/lint-imports`
Expected: all pass, 4 contracts kept.

- [ ] **Step 6: Commit**

```bash
git add src/calendar_sync tests
git commit -m "feat: clear old Activity and purge logs without racing rule work"
```

---

### Task 4: Storage API

**Files:**
- Create: `src/calendar_sync/interfaces/api/routes/storage.py`
- Modify: `src/calendar_sync/interfaces/api/schemas.py`
- Modify: `src/calendar_sync/interfaces/api/app.py` (`ApiServices`, the router tuple)
- Modify: `src/calendar_sync/bootstrap/container.py` (`Container.storage`, `Adapters.database_storage`, `compose`)
- Test: `tests/adapters/test_storage_api.py`

**Interfaces:**
- Consumes `StorageAdministration` (Task 3) and `SqliteStorage` (Task 2).
- Produces these routes, all behind `require_admin`:
  - `GET /api/v1/storage` returns `StorageResponse`.
  - `GET /api/v1/storage/activity?older_than_days=N` returns `ClearableActivityResponse`; an
    invalid N gives 422.
  - `POST /api/v1/storage/activity/clear` takes body `{"older_than_days": N}` and returns
    `ClearedActivityResponse`. An invalid N gives 422 and busy gives 409.
  - `GET /api/v1/storage/logs` returns `text/plain` with
    `Content-Disposition: attachment; filename="calendar-sync-logs-YYYY-MM-DD.txt"`, or 404 when
    file logging is off.
  - `DELETE /api/v1/storage/logs` returns 204, or 404 when file logging is off.
- Schemas:
  ```python
  class DatabaseUsageResponse(BaseModel):
      bytes: int
      reclaimable_bytes: int
      activity_entries: int
      oldest_activity_at: str | None

  class LogUsageResponse(BaseModel):
      bytes: int
      files: int
      oldest_at: str | None
      newest_at: str | None

  class StorageResponse(BaseModel):
      database: DatabaseUsageResponse
      logs: LogUsageResponse | None
      activity_ages: list[int]

  class ClearableActivityResponse(BaseModel):
      older_than_days: int
      entries: int

  class ClearActivityRequest(BaseModel):
      older_than_days: int

  class ClearedActivityResponse(BaseModel):
      removed: int
      database: DatabaseUsageResponse
  ```

- [ ] **Step 1: Write the failing tests** in `tests/adapters/test_storage_api.py`

```python
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from calendar_sync.bootstrap.config import Settings
from calendar_sync.bootstrap.container import build_adapters, compose
from calendar_sync.infrastructure.log_files import RotatingLogFiles
from calendar_sync.interfaces.api.app import create_app

PASSWORD = "correct horse battery staple"


def _client(tmp_path: Path, *, file_logging: bool = True) -> TestClient:
    settings = Settings(tmp_path / "test.db")
    logs = tmp_path / "logs"
    if file_logging:
        logs.mkdir()
        (logs / "calendar-sync.log").write_text("2026-10-01T18:04:12Z INFO calendar_sync.x ok\n")
    adapters = replace(
        build_adapters(settings), log_files=RotatingLogFiles(logs) if file_logging else None
    )
    container = replace(compose(settings, adapters), scheduler=None)
    client = TestClient(create_app(container))
    assert client.post("/api/v1/setup/admin", json={"password": PASSWORD}).status_code == 200
    return client


def test_storage_reports_database_and_logs(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/api/v1/storage").json()

    assert body["database"]["bytes"] > 0
    assert body["database"]["activity_entries"] == 0
    assert body["database"]["oldest_activity_at"] is None
    assert body["logs"]["files"] == 1
    assert body["logs"]["newest_at"] == "2026-10-01T18:04:12+00:00"
    assert body["activity_ages"] == [30, 90, 180, 365]


def test_storage_without_file_logging_reports_no_logs(tmp_path: Path) -> None:
    client = _client(tmp_path, file_logging=False)

    assert client.get("/api/v1/storage").json()["logs"] is None
    assert client.get("/api/v1/storage/logs").status_code == 404
    assert client.delete("/api/v1/storage/logs").status_code == 404


def test_clearable_activity_is_counted_for_an_offered_age_only(tmp_path: Path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/v1/storage/activity", params={"older_than_days": 90}).json() == {
        "older_than_days": 90,
        "entries": 0,
    }
    assert client.get("/api/v1/storage/activity", params={"older_than_days": 7}).status_code == 422


def test_clearing_activity_answers_what_was_removed(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post("/api/v1/storage/activity/clear", json={"older_than_days": 30})

    assert response.status_code == 200
    assert response.json()["removed"] == 0
    assert client.post(
        "/api/v1/storage/activity/clear", json={"older_than_days": 1}
    ).status_code == 422


def test_clearing_while_a_rule_runs_is_a_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from calendar_sync.application.errors import StorageBusy
    from calendar_sync.application.storage import StorageAdministration

    def busy(self: StorageAdministration, older_than_days: int) -> object:
        raise StorageBusy("Old Activity was cleared, but its space could not be reclaimed")

    monkeypatch.setattr(StorageAdministration, "clear_activity", busy)

    response = _client(tmp_path).post(
        "/api/v1/storage/activity/clear", json={"older_than_days": 30}
    )

    assert response.status_code == 409
    assert response.json()["detail"].startswith("Old Activity was cleared")


def test_logs_download_as_one_dated_text_file(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/api/v1/storage/logs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="calendar-sync-logs-'
    )
    assert response.text.endswith("INFO calendar_sync.x ok\n")


def test_purging_logs_empties_them(tmp_path: Path) -> None:
    client = _client(tmp_path)

    assert client.delete("/api/v1/storage/logs").status_code == 204
    assert "calendar_sync.x ok" not in client.get("/api/v1/storage/logs").text
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/pytest tests/adapters/test_storage_api.py -q`
Expected: 404s or an AttributeError for `log_files` / `storage`.

- [ ] **Step 3: Compose it** in `bootstrap/container.py`

Make these changes:
1. Add `database_storage: DatabaseStorage` to `Adapters`. Its `build_adapters` value is
   `SqliteStorage(settings.database_path)`. Place it with the other required fields, before the
   defaulted ones.
2. Add `storage: StorageAdministration` to `Container`.
3. In `compose`, build `StorageAdministration(adapters.database_storage, unit_of_work, locks,
   clock, adapters.log_files)` and pass it as `storage=`.

Update every other place that constructs `Adapters(...)` directly: run
`grep -rn "Adapters(" src tests scripts` and add `database_storage=SqliteStorage(path)` there.

- [ ] **Step 4: Add the schemas** above to `interfaces/api/schemas.py`.

- [ ] **Step 5: Implement `interfaces/api/routes/storage.py`**

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse

from calendar_sync.application.errors import FileLoggingOff, InvalidActivityAge, StorageBusy
from calendar_sync.application.ports import DatabaseUsage, LogUsage
from calendar_sync.application.storage import ACTIVITY_AGES, StorageAdministration
from calendar_sync.interfaces.api.dependencies import app_services, require_admin
from calendar_sync.interfaces.api.schemas import (
    ClearableActivityResponse,
    ClearActivityRequest,
    ClearedActivityResponse,
    DatabaseUsageResponse,
    LogUsageResponse,
    StorageResponse,
)


class StorageServices(Protocol):
    @property
    def storage(self) -> StorageAdministration: ...


Services = Annotated[StorageServices, Depends(app_services)]
router = APIRouter()
ADMIN = [Depends(require_admin)]


@router.get("/api/v1/storage", response_model=StorageResponse, dependencies=ADMIN)
def storage_usage(services: Services) -> StorageResponse:
    usage = services.storage.usage()
    return StorageResponse(
        database=_database(usage.database),
        logs=_logs(usage.logs) if usage.logs is not None else None,
        activity_ages=list(ACTIVITY_AGES),
    )


@router.get(
    "/api/v1/storage/activity", response_model=ClearableActivityResponse, dependencies=ADMIN
)
def clearable_activity(
    services: Services, older_than_days: Annotated[int, Query()]
) -> ClearableActivityResponse:
    try:
        entries = services.storage.clearable_activity(older_than_days)
    except InvalidActivityAge as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    return ClearableActivityResponse(older_than_days=older_than_days, entries=entries)


@router.post(
    "/api/v1/storage/activity/clear",
    response_model=ClearedActivityResponse,
    dependencies=ADMIN,
)
def clear_activity(services: Services, payload: ClearActivityRequest) -> ClearedActivityResponse:
    try:
        cleared = services.storage.clear_activity(payload.older_than_days)
    except InvalidActivityAge as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    except StorageBusy as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    return ClearedActivityResponse(removed=cleared.removed, database=_database(cleared.database))


@router.get("/api/v1/storage/logs", dependencies=ADMIN)
def download_logs(services: Services) -> StreamingResponse:
    try:
        chunks = services.storage.log_chunks()
    except FileLoggingOff as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    name = f"calendar-sync-logs-{datetime.now(UTC):%Y-%m-%d}.txt"
    return StreamingResponse(
        chunks,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.delete(
    "/api/v1/storage/logs", status_code=status.HTTP_204_NO_CONTENT, dependencies=ADMIN
)
def purge_logs(services: Services) -> Response:
    try:
        services.storage.purge_logs()
    except FileLoggingOff as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _database(usage: DatabaseUsage) -> DatabaseUsageResponse:
    return DatabaseUsageResponse(
        bytes=usage.bytes,
        reclaimable_bytes=usage.reclaimable_bytes,
        activity_entries=usage.activity_entries,
        oldest_activity_at=(
            usage.oldest_activity_at.isoformat() if usage.oldest_activity_at else None
        ),
    )


def _logs(usage: LogUsage) -> LogUsageResponse:
    return LogUsageResponse(
        bytes=usage.bytes,
        files=usage.files,
        oldest_at=usage.oldest_at.isoformat() if usage.oldest_at else None,
        newest_at=usage.newest_at.isoformat() if usage.newest_at else None,
    )
```

The clearing routes are plain `def` routes: FastAPI runs them in its threadpool, so waiting up to
30 s for rule locks never blocks the event loop.

- [ ] **Step 6: Register the router** in `interfaces/api/app.py`

Import `storage` with the other route modules. Add `storage.StorageServices` to `ApiServices`,
and `storage` to the tuple in `for module in (...)`.

- [ ] **Step 7: Run the tests and confirm they pass**

Run: `.venv/bin/pytest tests/adapters/test_storage_api.py tests/adapters/test_api_authorization.py -q`
Expected: all pass. The authorization test now covers the five new routes and proves each one
requires an administrator.

- [ ] **Step 8: Full gates and commit**

```bash
.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/lint-imports && .venv/bin/pytest -q --cov --cov-fail-under=80
git add src/calendar_sync tests
git commit -m "feat: storage API for usage, clearing Activity, and the log files"
```

---

### Task 5: Settings → Storage

**Files:**
- Create: `web/src/lib/storage.ts`
- Create: `web/src/lib/storage.test.ts`
- Create: `web/src/components/destructive-confirmation.tsx` (moved out of `rule-details.tsx`)
- Modify: `web/src/features/rule-details.tsx` (import the moved component)
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/features/settings.tsx`
- Regenerate: `src/calendar_sync/interfaces/api/static/`

**Interfaces:**
- Consumes: the Task 4 routes and response shapes.
- Produces in `api.ts`:
  - types: `DatabaseUsage`, `LogUsage`, `StorageUsage`, `ClearableActivity`, `ClearedActivity`
    (fields exactly as the Task 4 schemas)
  - `api.storage()`, `api.clearableActivity(days)`, `api.clearActivity(days)`, `api.purgeLogs()`
  - `STORAGE_LOGS_URL = "/api/v1/storage/logs"`
- Produces in `lib/storage.ts`:
  - `formatBytes(bytes: number): string`
  - `activitySummary(usage: DatabaseUsage, locale?: string): string`
  - `logSummary(usage: LogUsage | null, locale?: string): string`
  - `clearActivityBody(entries: number, days: number): string`

- [ ] **Step 1: Write the failing tests** in `web/src/lib/storage.test.ts`

```ts
import { describe, expect, it } from "vitest"

import { activitySummary, clearActivityBody, formatBytes, logSummary } from "@/lib/storage"

describe("formatBytes", () => {
  it("uses binary units with one decimal above a kilobyte", () => {
    expect(formatBytes(0)).toBe("0 B")
    expect(formatBytes(512)).toBe("512 B")
    expect(formatBytes(1536)).toBe("1.5 KB")
    expect(formatBytes(48.2 * 1024 * 1024)).toBe("48.2 MB")
    expect(formatBytes(3 * 1024 ** 3)).toBe("3.0 GB")
  })
})

describe("activitySummary", () => {
  it("names the size, the entry count, and the oldest entry", () => {
    expect(
      activitySummary(
        {
          bytes: 48.2 * 1024 * 1024,
          reclaimable_bytes: 0,
          activity_entries: 61204,
          oldest_activity_at: "2026-06-12T09:00:00+00:00",
        },
        "en-GB",
      ),
    ).toBe("48.2 MB · 61,204 Activity entries since 12 Jun 2026")
  })

  it("says when there is no Activity yet", () => {
    expect(
      activitySummary(
        { bytes: 4096, reclaimable_bytes: 0, activity_entries: 0, oldest_activity_at: null },
        "en-GB",
      ),
    ).toBe("4.0 KB · No Activity yet")
  })
})

describe("logSummary", () => {
  it("names the size and the dates the logs cover", () => {
    expect(
      logSummary(
        {
          bytes: 7.9 * 1024 * 1024,
          files: 2,
          oldest_at: "2026-09-12T08:00:00+00:00",
          newest_at: "2026-10-01T18:04:12+00:00",
        },
        "en-GB",
      ),
    ).toBe("7.9 MB · 12 Sep – 1 Oct 2026")
  })

  it("explains when the installation keeps no log files", () => {
    expect(logSummary(null)).toBe("File logging is off. Container logs are still available.")
  })

  it("says when the logs are empty", () => {
    expect(logSummary({ bytes: 0, files: 0, oldest_at: null, newest_at: null })).toBe(
      "No log lines yet",
    )
  })
})

describe("clearActivityBody", () => {
  it("says how many entries go and that it cannot be undone", () => {
    expect(clearActivityBody(41880, 90)).toBe(
      "41,880 Activity entries older than 90 days will be removed. Each event's latest entry is kept. This cannot be undone.",
    )
    expect(clearActivityBody(1, 30)).toBe(
      "1 Activity entry older than 30 days will be removed. Each event's latest entry is kept. This cannot be undone.",
    )
    expect(clearActivityBody(0, 365)).toBe("Nothing is older than 365 days.")
  })
})
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `npm --prefix web run test -- storage`
Expected: the module `@/lib/storage` cannot be resolved.

- [ ] **Step 3: Add the API types and methods** to `web/src/lib/api.ts`

Types go with the other exported types; methods go inside `api`.

```ts
export type DatabaseUsage = {
  bytes: number
  reclaimable_bytes: number
  activity_entries: number
  oldest_activity_at: string | null
}
export type LogUsage = {
  bytes: number
  files: number
  oldest_at: string | null
  newest_at: string | null
}
export type StorageUsage = {
  database: DatabaseUsage
  logs: LogUsage | null
  activity_ages: number[]
}
export type ClearableActivity = { older_than_days: number; entries: number }
export type ClearedActivity = { removed: number; database: DatabaseUsage }
export const STORAGE_LOGS_URL = "/api/v1/storage/logs"

// inside `export const api = { ... }`
  storage: () => request<StorageUsage>("/api/v1/storage"),
  clearableActivity: (days: number) =>
    request<ClearableActivity>(`/api/v1/storage/activity?older_than_days=${days}`),
  clearActivity: (days: number) =>
    request<ClearedActivity>("/api/v1/storage/activity/clear", {
      method: "POST",
      body: JSON.stringify({ older_than_days: days }),
    }),
  purgeLogs: () => request<void>(STORAGE_LOGS_URL, { method: "DELETE" }),
```

- [ ] **Step 4: Implement `web/src/lib/storage.ts`**

```ts
import type { DatabaseUsage, LogUsage } from "@/lib/api"

const UNITS = ["KB", "MB", "GB", "TB"]

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${Math.round(bytes)} B`
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(1)} ${UNITS[unit]}`
}

function day(value: string, locale?: string, withYear = true): string {
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    ...(withYear ? { year: "numeric" } : {}),
    timeZone: "UTC",
  }).format(new Date(value))
}

export function activitySummary(usage: DatabaseUsage, locale?: string): string {
  const size = formatBytes(usage.bytes)
  if (usage.activity_entries === 0 || !usage.oldest_activity_at) return `${size} · No Activity yet`
  const count = usage.activity_entries.toLocaleString(locale ?? "en-US")
  const noun = usage.activity_entries === 1 ? "Activity entry" : "Activity entries"
  return `${size} · ${count} ${noun} since ${day(usage.oldest_activity_at, locale)}`
}

export function logSummary(usage: LogUsage | null, locale?: string): string {
  if (usage === null) return "File logging is off. Container logs are still available."
  if (usage.files === 0 || !usage.oldest_at || !usage.newest_at) return "No log lines yet"
  const sameYear = usage.oldest_at.slice(0, 4) === usage.newest_at.slice(0, 4)
  return `${formatBytes(usage.bytes)} · ${day(usage.oldest_at, locale, !sameYear)} – ${day(usage.newest_at, locale)}`
}

export function clearActivityBody(entries: number, days: number): string {
  if (entries === 0) return `Nothing is older than ${days} days.`
  const count = entries.toLocaleString("en-US")
  const noun = entries === 1 ? "Activity entry" : "Activity entries"
  return `${count} ${noun} older than ${days} days will be removed. Each event's latest entry is kept. This cannot be undone.`
}
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `npm --prefix web run test -- storage`
Expected: PASS.

- [ ] **Step 6: Move `DestructiveConfirmation`**

Cut `function DestructiveConfirmation(...)` from `web/src/features/rule-details.tsx` and paste it
into `web/src/components/destructive-confirmation.tsx` as `export function
DestructiveConfirmation`. Add an optional `confirmDisabled?: boolean` prop. It disables only the
confirm button (`disabled={pending || confirmDisabled}`), so Cancel stays usable while a count
loads. Move its imports with it: `useEffect`, `useRef`, `Trash2`, `Button`.
Then import it in `rule-details.tsx` from `@/components/destructive-confirmation`, and remove
imports that file no longer uses. `npm --prefix web run typecheck` must stay clean.

- [ ] **Step 7: Add the Storage section** to `web/src/features/settings.tsx`, after the
  Operations `</section>`

Add these imports:
- `Download` from `lucide-react`;
- `DestructiveConfirmation` from `@/components/destructive-confirmation`;
- `STORAGE_LOGS_URL` from `@/lib/api`;
- `activitySummary`, `clearActivityBody` and `logSummary` from `@/lib/storage`.

Render `<StorageSection />` and define the component in the same file:

```tsx
function StorageSection() {
  const queryClient = useQueryClient()
  const storage = useQuery({ queryKey: ["storage"], queryFn: api.storage })
  const [days, setDays] = useState(90)
  const [confirming, setConfirming] = useState<"activity" | "logs" | null>(null)
  const [message, setMessage] = useState("")
  const clearable = useQuery({
    queryKey: ["storage", "clearable", days],
    queryFn: () => api.clearableActivity(days),
    enabled: confirming === "activity",
  })
  const clear = useMutation({
    mutationFn: () => api.clearActivity(days),
    onSuccess: async (cleared) => {
      setConfirming(null)
      setMessage(
        cleared.removed === 0
          ? "Nothing was old enough to clear."
          : `${cleared.removed.toLocaleString("en-US")} Activity entries were cleared.`,
      )
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["storage"] }),
        queryClient.invalidateQueries({ queryKey: ["activity"] }),
      ])
    },
  })
  const purge = useMutation({
    mutationFn: api.purgeLogs,
    onSuccess: async () => {
      setConfirming(null)
      setMessage("The logs were purged.")
      await queryClient.invalidateQueries({ queryKey: ["storage"] })
    },
  })
  const busy = clear.isPending || purge.isPending
  const usage = storage.data

  return (
    <section className="settings-section" aria-labelledby="storage-title">
      <div className="section-heading">
        <div>
          <h2 id="storage-title">Storage</h2>
          <p>What this installation keeps, and clearing what it no longer needs.</p>
        </div>
      </div>
      {storage.isPending && <Skeleton className="h-24 w-full" />}
      {storage.error && (
        <div className="inline-error" role="alert">
          Storage usage could not load.
        </div>
      )}
      {usage && (
        <div className="settings-list">
          <div className="setting-row">
            <div>
              <h3>Database</h3>
              <p>{activitySummary(usage.database)}</p>
            </div>
            <div className="appearance-control">
              <NativeSelect
                id="activity-age"
                aria-label="Clear Activity older than"
                value={days}
                disabled={busy}
                onChange={(event) => setDays(Number(event.target.value))}
              >
                {usage.activity_ages.map((age) => (
                  <option key={age} value={age}>
                    Older than {age} days
                  </option>
                ))}
              </NativeSelect>
              <Button
                type="button"
                variant="outline"
                disabled={busy || usage.database.activity_entries === 0}
                aria-expanded={confirming === "activity"}
                aria-controls="clear-activity-confirmation"
                onClick={() => {
                  clear.reset()
                  setMessage("")
                  setConfirming("activity")
                }}
              >
                Clear Activity
              </Button>
            </div>
          </div>
          {confirming === "activity" && (
            <DestructiveConfirmation
              id="clear-activity-confirmation"
              title={`Clear Activity older than ${days} days?`}
              body={
                clearable.data
                  ? clearActivityBody(clearable.data.entries, days)
                  : "Counting the entries that would be removed…"
              }
              cancelLabel="Keep Activity"
              confirmLabel="Clear Activity"
              pendingLabel="Clearing…"
              pending={clear.isPending}
              confirmDisabled={!clearable.data || clearable.data.entries === 0}
              onConfirm={() => clear.mutate()}
              onCancel={() => setConfirming(null)}
            />
          )}
          <div className="setting-row">
            <div>
              <h3>Logs</h3>
              <p>{logSummary(usage.logs)}</p>
            </div>
            {usage.logs && (
              <div className="appearance-control">
                <Button variant="outline" asChild>
                  <a href={STORAGE_LOGS_URL} download>
                    <Download aria-hidden="true" /> Download
                  </a>
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy || usage.logs.files === 0}
                  aria-expanded={confirming === "logs"}
                  aria-controls="purge-logs-confirmation"
                  onClick={() => {
                    purge.reset()
                    setMessage("")
                    setConfirming("logs")
                  }}
                >
                  Purge logs
                </Button>
              </div>
            )}
          </div>
          {confirming === "logs" && (
            <DestructiveConfirmation
              id="purge-logs-confirmation"
              title="Purge the logs?"
              body="Every log line kept on this installation is deleted. Download them first if you may need them. This cannot be undone."
              cancelLabel="Keep logs"
              confirmLabel="Purge logs"
              pendingLabel="Purging…"
              pending={purge.isPending}
              onConfirm={() => purge.mutate()}
              onCancel={() => setConfirming(null)}
            />
          )}
        </div>
      )}
      {message && <p role="status">{message}</p>}
      {(clear.error || purge.error) && (
        <div className="inline-error" role="alert">
          {(clear.error ?? purge.error)?.message}
        </div>
      )}
    </section>
  )
}
```

If `appearance-control` doesn't lay out two controls side by side, add a
`.storage-actions { display: flex; gap: var(--space-2); flex-wrap: wrap; }` rule. Put it in
`web/src/index.css` (or wherever `.appearance-control` is defined), using that file's existing
spacing tokens, and use `className="storage-actions"` for both action groups.

- [ ] **Step 8: Gates, build, visual check**

Run: `npm --prefix web run typecheck && npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`.

Then check it visually, following the repository's preview workflow:
1. Run `.venv/bin/python scripts/dev_preview.py` in the background and sign in with
   `preview-password`.
2. Open Settings at desktop width and at 390 px width. Tab through Storage, open each
   confirmation, then cancel.
3. Save screenshots under `.context/`.

The dev preview builds its container with `build_container`, so Logs shows "File logging is off".
That is expected, and it is the state to check for that row. The database row shows the seeded
Activity.

- [ ] **Step 9: Commit**

```bash
git add web src/calendar_sync/interfaces/api/static
git commit -m "feat: Storage in Settings: database size, clearing old Activity, and logs"
```

---

### Task 6: Record the decision and update the docs

**Files:**
- Create: `docs/adr/0019-administrator-chosen-activity-retention.md`
- Modify: `docs/adr/0013-record-decisions-worth-explaining.md` and
  `docs/adr/0014-record-event-titles-on-audit-entries.md`. Change the "no retention limit"
  sentences to point to ADR 0019; leave the decisions themselves unedited.
- Modify: `CONTEXT.md` (Audit Entry / Activity retention)
- Modify: `docs/sync-model.md` (the retention paragraph, around line 167)
- Modify: `docs/deployment.md`:
  - `CALENDAR_SYNC_LOG_DIR`;
  - the log files under `/data/logs`;
  - backups keep cleared entries until they rotate;
  - line 62, about titles staying until their entries are deleted.
- Modify: `docs/troubleshooting.md`:
  - in the "Reading the logs" section, add that Settings → Storage → Download gets the same
    lines without SSH;
  - add a short "Database is large" note.
- Modify: `README.md`, where it describes retention and Settings.
- Modify: `.env.example`. Add `CALENDAR_SYNC_LOG_DIR=` with a comment: "empty turns file logging
  off; unset keeps logs beside the database".
- Modify: `CHANGELOG.md`, adding an `### Added` entry.

**Interfaces:** none.

- [ ] **Step 1: Write ADR 0019** in the format of `docs/adr/0017-record-source-changes.md`:
  Context, Decision, Consequences, Alternatives.
  - **Context:** Activity had no retention limit (ADR 0013, 0014). A Raspberry Pi installation
    grows without bound, and investigating needed SSH.
  - **Decision:** the administrator clears Activity older than 30, 90, 180 or 365 days. The three
    protected entries are kept per rule and source event, with why each is needed. Deletion runs
    in batches, then VACUUM runs under every rule's run lock, or 409 when busy. Removed rules'
    history is cleared like any other.
  - **Consequences:**
    - an old rename shown on a kept entry loses its earlier name once that entry is cleared;
    - backups keep cleared entries until they rotate;
    - incidents are unaffected.
  - **Alternatives:**
    - automatic retention (deferred; it can build on the same rules);
    - deleting by age with no protections (rejected: it breaks open blocks and persisting-block
      incidents);
    - hiding instead of deleting (rejected: it reclaims no space).

- [ ] **Step 2: Update the other docs** as listed above. Use `CONTEXT.md` terms: Audit Entry,
  Activity, Directional Sync Rule. Then run `.venv/bin/pytest tests/test_ubiquitous_language.py -q`;
  it must pass.

- [ ] **Step 3: Commit**

```bash
git add docs CONTEXT.md README.md CHANGELOG.md .env.example
git commit -m "docs: administrator-chosen Activity retention and the log files"
```

- [ ] **Step 4: Final verification**

Run every gate in `AGENTS.md`:
- backend: `ruff format --check`, `ruff check`, `mypy`, `lint-imports`, and `pytest --cov
  --cov-fail-under=80`;
- frontend: `typecheck`, `lint`, `test`, `build`.

Confirm `git status` is clean after the build, which means the static assets are committed.
