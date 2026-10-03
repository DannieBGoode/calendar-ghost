# Persistence Seams Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the storage layer easier to maintain and test faithfully: every SQLite connection
in the shipped package opens in one place with the same settings, the in-memory and SQLite units of
work pass one shared contract for what use cases rely on, and the composition's `Adapters` holds
ports instead of concrete SQLite and Google classes.

**Revision 2 (after Codex review):** fixes the in-memory commit aliasing bug, widens the contract to
parent records, mapping and occurrence identity, and post-commit writes; closes a connection whose
configuration fails; uses `isinstance` narrowing for tests that need the concrete OAuth service and
account store; avoids `PT012`; stages files explicitly; keeps repository wording about installation
maintenance and test fidelity, not hosting.

**Architecture:** A new `infrastructure/persistence/connections.py` owns `sqlite3.connect`; every
adapter and `initialize_database` call it, and a source-scan test keeps it that way. A
`tests/contracts/persistence.py` suite, modelled on `tests/contracts/calendar_provider.py`, states
what the persistence ports promise and runs against both implementations; the in-memory one is
aligned to SQLite where they disagree. `bootstrap/container.py`'s `Adapters` fields become port
types. No tenant identifier, hosted concept, or schema change is introduced (ADR 0020).

**Tech Stack:** Python 3.12, sqlite3, pytest, mypy strict, ruff, import-linter.

**Spec:** No separate spec. The scope is items 5, 4, and 2 of the multi-tenant-preparation review
in this session: (5) one SQLite connection factory, (4) a persistence contract suite, (2) `Adapters`
typed by ports.

## Global Constraints

- Follow `AGENTS.md`. Domain and application code must not import `sqlite3` (import-linter).
- No schema migration, no new environment variable, no API or Web UI change.
- Busy timeout stays 5 seconds (Python's current default) everywhere except `SqliteStorage.compact`,
  which keeps its configurable 30 seconds. WAL mode is out of scope: it changes what a backup must
  copy and needs its own review.
- Where SQLite and the in-memory unit of work disagree, SQLite is the production behavior: change
  the in-memory implementation. If SQLite looks wrong, stop and report rather than change it. The
  one planned SQLite change: `SqliteSyncRuleRepository.save` translates its unique-relationship
  `IntegrityError` into `DuplicateDirectionalRelationship`, as `add` already does, because the
  application cannot catch a `sqlite3` error.
- Do not add `# noqa: C901`, `PLR0912`, `PLR0913`, or `PLR0915`.
- Never write the avoided glossary terms (`tests/test_ubiquitous_language.py`); say "Drift" or
  "refused" rather than "conflict" in prose.
- Gates before handoff: `ruff format --check .`, `ruff check .`, `mypy`, `lint-imports`,
  `pytest --cov --cov-fail-under=80`.
- Stage files by explicit path in every commit; never `git add -A`.
- The one-connection rule covers the shipped package `src/calendar_sync`. `scripts/dev_preview.py`
  seeds a throwaway preview database and may keep its direct connections; say so in the scan test.
- Repository prose (docstrings, docs, CHANGELOG) describes these changes as installation
  maintenance and test fidelity. Do not mention hosting or tenants (ADR 0020).
- `pytest.raises` blocks hold one statement (`PT012`): move multi-statement bodies into a helper.
- Facts already true before this change, so not behavior changes: `initialize_database` runs with
  foreign keys on (`0001_initial.sql` sets the pragma, migration 0017 already copes);
  `SqliteUnitOfWork` already enables foreign keys and `sqlite3.Row`. The new enforcement applies to
  the adapters outside the unit of work: health, accounts, OAuth states, admin sessions, storage,
  and Activity reads.

## Review Focus

- A failure recorded for a rule removed meanwhile: with foreign keys now enforced,
  `SqliteRuleHealthRecords.record_failure` must not raise; it records nothing and reports one
  failure (Task 2 test).
- An existing installation that already holds an orphaned `rule_failures` row from a rule removed
  mid-run: recording another failure for that rule must not raise and must read as no history
  (Task 2 test pins it).
- A write that fails inside an adapter: the connection must roll back and close, never leave a
  write lock or an open handle (Task 1 helper tests; Task 2 adapter test).
- A migration that fails partway through an upgrade: its changes and version record must be
  absent, earlier migrations kept, and the database left unlocked (Task 2 test).
- Application tests that depended on the in-memory unit's insertion order: once memory lists rules,
  mappings, and occurrences in SQLite's order, any such test fails loudly and must be fixed to
  assert the SQLite order (Task 3, full suite run).
- Typing `Adapters` by ports: API tests that reach concrete methods (`accounts.save`,
  `google_oauth.calendars`, `verify_access`, `complete`, `_store_state`) must narrow with
  `isinstance` to the concrete class rather than widen the field type back (Task 4).
- A unit of work that commits and then keeps writing: the later writes must be discarded unless
  committed again. The in-memory unit gets this wrong today (Task 3 test and fix).

---

## File Structure

| File | Responsibility |
| --- | --- |
| Create `src/calendar_sync/infrastructure/persistence/connections.py` | The only `sqlite3.connect`: settings, transaction helper. |
| Modify `src/calendar_sync/infrastructure/persistence/sqlite.py` | `initialize_database` and `SqliteUnitOfWork` open through it. |
| Modify `.../persistence/health.py`, `accounts.py`, `authorization_states.py`, `storage.py`, `activity_queries.py`, `infrastructure/security.py` | Open through it; guard `record_failure`. |
| Create `tests/adapters/test_sqlite_connections.py` | Connection settings, closing, rollback, scan, regression tests. |
| Create `tests/contracts/persistence.py` | The persistence contract. |
| Create `tests/adapters/test_persistence_contract.py` | Runs it against memory and SQLite. |
| Modify `src/calendar_sync/infrastructure/persistence/memory.py` | Align with SQLite. |
| Modify `tests/adapters/test_sqlite.py`; delete `tests/adapters/test_memory_persistence.py` | Remove tests the contract now covers for both. |
| Modify `tests/adapters/test_storage.py` | `_BrokenConnection` fails only on `VACUUM`. |
| Modify `tests/application/*.py` as needed | Add the rule before writing its records (Task 3 Step 6). |
| Modify `src/calendar_sync/bootstrap/container.py`, `tests/adapters/test_api.py` | `Adapters` typed by ports. |
| Modify `docs/architecture.md`, `AGENTS.md`, `CHANGELOG.md` | Record the seams. |

---

### Task 1: The connection module

**Files:**
- Create: `src/calendar_sync/infrastructure/persistence/connections.py`
- Test: `tests/adapters/test_sqlite_connections.py`

**Interfaces:**
- Produces:
  - `BUSY_TIMEOUT_SECONDS: float = 5.0`
  - `open_connection(database_path: Path, *, timeout: float = BUSY_TIMEOUT_SECONDS, isolation_level: Literal["DEFERRED", "IMMEDIATE", "EXCLUSIVE"] | None = "DEFERRED") -> sqlite3.Connection` — caller closes it.
  - `transaction(database_path: Path) -> AbstractContextManager[sqlite3.Connection]` — commits on success, rolls back on exception, always closes.

- [ ] **Step 1: Write the failing tests**

```python
"""Every SQLite connection opens through one module, with the installation's settings."""

import sqlite3
from pathlib import Path

import pytest

from calendar_sync.infrastructure.persistence.connections import open_connection, transaction
from calendar_sync.infrastructure.persistence.sqlite import initialize_database


def _database(tmp_path: Path) -> Path:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    return database


def test_a_connection_enforces_foreign_keys_and_names_columns(tmp_path: Path) -> None:
    connection = open_connection(_database(tmp_path))
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        row = connection.execute("SELECT 1 AS answer").fetchone()
        assert row["answer"] == 1
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO sync_cursors(rule_id, cursor) VALUES ('missing-rule', 'c')"
            )
    finally:
        connection.close()


def test_a_transaction_commits_and_closes(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with transaction(database) as connection:
        connection.execute(
            "INSERT INTO oauth_states(state_hash, created_at, expires_at) VALUES ('h', 'a', 'b')"
        )

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    with transaction(database) as reader:
        assert reader.execute("SELECT COUNT(*) FROM oauth_states").fetchone()[0] == 1


def _write_then_fail(database: Path, opened: list[sqlite3.Connection]) -> None:
    with transaction(database) as connection:
        opened.append(connection)
        connection.execute(
            "INSERT INTO oauth_states(state_hash, created_at, expires_at) VALUES ('h', 'a', 'b')"
        )
        raise RuntimeError("stop")


def test_a_failed_transaction_rolls_back_and_closes(tmp_path: Path) -> None:
    database = _database(tmp_path)
    opened: list[sqlite3.Connection] = []

    with pytest.raises(RuntimeError):
        _write_then_fail(database, opened)

    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("SELECT 1")
    with transaction(database) as reader:
        assert reader.execute("SELECT COUNT(*) FROM oauth_states").fetchone()[0] == 0


def _orphan_at_commit(database: Path, opened: list[sqlite3.Connection]) -> None:
    with transaction(database) as connection:
        opened.append(connection)
        # Deferred, the foreign key is checked at commit, so the commit itself fails.
        connection.execute("PRAGMA defer_foreign_keys = ON")
        connection.execute("INSERT INTO sync_cursors(rule_id, cursor) VALUES ('missing', 'c')")


def test_a_transaction_whose_commit_fails_closes(tmp_path: Path) -> None:
    database = _database(tmp_path)
    opened: list[sqlite3.Connection] = []

    with pytest.raises(sqlite3.IntegrityError):
        _orphan_at_commit(database, opened)

    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("SELECT 1")


class _UnconfigurableConnection:
    """Stands in for a connection that opens but rejects its settings."""

    row_factory: object = None
    closed = False

    def execute(self, sql: str) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    def close(self) -> None:
        self.closed = True


def test_a_connection_that_cannot_be_configured_is_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unconfigurable = _UnconfigurableConnection()
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: unconfigurable)

    with pytest.raises(sqlite3.OperationalError):
        open_connection(tmp_path / "calendar-sync.db")

    assert unconfigurable.closed
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/adapters/test_sqlite_connections.py -q`
Expected: FAIL with `ModuleNotFoundError: ... persistence.connections`

- [ ] **Step 3: Implement**

```python
"""The one place that opens SQLite connections, so every adapter gets the same settings.

Foreign keys are enforced, rows are read by column name, and a writer waits up to the busy
timeout for another's lock.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal

BUSY_TIMEOUT_SECONDS = 5.0


def open_connection(
    database_path: Path,
    *,
    timeout: float = BUSY_TIMEOUT_SECONDS,
    isolation_level: Literal["DEFERRED", "IMMEDIATE", "EXCLUSIVE"] | None = "DEFERRED",
) -> sqlite3.Connection:
    """A connection with the installation's settings; the caller closes it."""
    connection = sqlite3.connect(database_path, timeout=timeout, isolation_level=isolation_level)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def transaction(database_path: Path) -> Iterator[sqlite3.Connection]:
    """One short transaction: committed when the block succeeds, rolled back if it raises.

    The connection is closed either way, so no handle or lock outlives the block.
    """
    with closing(open_connection(database_path)) as connection, connection:
        yield connection
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/pytest tests/adapters/test_sqlite_connections.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/infrastructure/persistence/connections.py tests/adapters/test_sqlite_connections.py
git commit -m "Open SQLite connections through one module"
```

---

### Task 2: Route every adapter through it

**Files:**
- Modify: `src/calendar_sync/infrastructure/persistence/sqlite.py` (`initialize_database` ~L86, `SqliteUnitOfWork.__enter__` ~L704)
- Modify: `src/calendar_sync/infrastructure/persistence/health.py` (every `sqlite3.connect`)
- Modify: `src/calendar_sync/infrastructure/persistence/accounts.py` (`_connect`, its `with` uses)
- Modify: `src/calendar_sync/infrastructure/persistence/authorization_states.py`
- Modify: `src/calendar_sync/infrastructure/persistence/storage.py`
- Modify: `src/calendar_sync/infrastructure/persistence/activity_queries.py` (`_reading`)
- Modify: `src/calendar_sync/infrastructure/security.py` (`SqliteAdminAuth._connect`, its `with` uses)
- Modify: `docs/architecture.md`, `AGENTS.md`, `CHANGELOG.md`
- Modify: `tests/adapters/test_storage.py` (`_BrokenConnection`)
- Test: `tests/adapters/test_sqlite_connections.py`

**Interfaces:**
- Consumes: `open_connection`, `transaction`, `BUSY_TIMEOUT_SECONDS` from Task 1.
- Produces: no new names. `SqliteRuleHealthRecords.record_failure` returns `1` for a rule that no
  longer exists and writes nothing.

- [ ] **Step 1: Write the failing tests** (append to `tests/adapters/test_sqlite_connections.py`)

```python
from calendar_sync.application.errors import ProviderFailureKind
from calendar_sync.infrastructure.persistence.health import SqliteRuleHealthRecords
from tests.helpers import NOW, rule

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "calendar_sync"


def test_only_the_connection_module_opens_sqlite() -> None:
    # The shipped package only; scripts/dev_preview.py seeds a throwaway preview database.
    opening = sorted(
        str(path.relative_to(SOURCE_ROOT))
        for path in SOURCE_ROOT.rglob("*.py")
        if "sqlite3.connect(" in path.read_text()
    )
    assert opening == ["infrastructure/persistence/connections.py"]


def test_consecutive_failures_of_an_existing_rule_are_counted(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with SqliteUnitOfWorkFactory(database)() as uow:
        uow.rules.add(rule())
        uow.commit()
    records = SqliteRuleHealthRecords(database)
    later = NOW + timedelta(minutes=5)

    assert records.record_failure(rule().id, ProviderFailureKind.TEMPORARY, NOW) == 1
    assert records.record_failure(rule().id, ProviderFailureKind.RATE_LIMIT, later) == 2

    with transaction(database) as connection:
        row = connection.execute("SELECT * FROM rule_failures").fetchone()
    assert (row["consecutive_failures"], row["last_category"], row["updated_at"]) == (
        2,
        "rate_limit",
        later.isoformat(),
    )


def test_a_failure_for_a_removed_rule_is_counted_without_a_record(tmp_path: Path) -> None:
    database = _database(tmp_path)
    records = SqliteRuleHealthRecords(database)

    assert records.record_failure(rule().id, ProviderFailureKind.TEMPORARY, NOW) == 1
    assert records.record_failure(rule().id, ProviderFailureKind.TEMPORARY, NOW) == 1
    with transaction(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM rule_failures").fetchone()[0] == 0


def test_an_orphaned_failure_count_from_an_earlier_release_is_left_alone(tmp_path: Path) -> None:
    database = _database(tmp_path)
    # Earlier releases wrote failures without enforcing foreign keys, so a row may outlive its rule.
    with closing(sqlite3.connect(database)) as legacy, legacy:
        legacy.execute(
            "INSERT INTO rule_failures(rule_id, consecutive_failures, last_category, updated_at) "
            "VALUES (?, 2, 'temporary', ?)",
            (rule().id.value, NOW.isoformat()),
        )

    records = SqliteRuleHealthRecords(database)
    later = NOW + timedelta(minutes=5)

    assert records.record_failure(rule().id, ProviderFailureKind.RATE_LIMIT, later) == 1
    assert records.record_failure(rule().id, ProviderFailureKind.RATE_LIMIT, later) == 1
    with transaction(database) as connection:
        row = connection.execute("SELECT * FROM rule_failures").fetchone()
    assert (row["consecutive_failures"], row["last_category"], row["updated_at"]) == (
        2,
        "temporary",
        NOW.isoformat(),
    )
```

def test_an_adapter_write_that_fails_releases_the_database(tmp_path: Path) -> None:
    database = _database(tmp_path)
    states = SqliteAuthorizationStates(database)
    states.store("state-1")

    with pytest.raises(sqlite3.IntegrityError) as failure:
        states.store("state-1")

    # The traceback keeps the failed call's frames alive, so a connection it left open, with its
    # write lock, would still be held here; a writer that does not wait proves it was released.
    assert failure.value is not None
    with closing(open_connection(database, timeout=0)) as writer, writer:
        writer.execute("DELETE FROM oauth_states")
    states.store("state-2")
    assert states.consume("state-2")


class _Text:
    def __init__(self, text: str) -> None:
        self._text = text

    def read_text(self) -> str:
        return self._text


class _MigrationsWithAFailure:
    """The shipped migrations, plus one that creates a table and then fails."""

    NAME = "9999_fails_halfway.sql"

    def __init__(self, shipped: Any) -> None:
        self._shipped = shipped

    def joinpath(self, name: str) -> Any:
        if name == self.NAME:
            return _Text("CREATE TABLE half_done (id INTEGER);\nINSERT INTO missing VALUES (1);")
        return self._shipped.joinpath(name)


def test_a_migration_that_fails_leaves_no_partial_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(tmp_path)
    with closing(open_connection(database)) as connection:
        applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
    shipped = sqlite_persistence.files
    monkeypatch.setattr(
        sqlite_persistence,
        "_FORWARD_MIGRATIONS",
        (*sqlite_persistence._FORWARD_MIGRATIONS, (9999, _MigrationsWithAFailure.NAME)),
    )
    monkeypatch.setattr(
        sqlite_persistence, "files", lambda package: _MigrationsWithAFailure(shipped(package))
    )

    with pytest.raises(sqlite3.OperationalError):
        initialize_database(database)

    with closing(open_connection(database, timeout=0)) as connection, connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
        versions = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
        # The database is not left locked by the failed upgrade.
        connection.execute("DELETE FROM oauth_states")
    assert "half_done" not in tables
    assert versions == applied
```

Add the imports `from typing import Any`,
`from calendar_sync.infrastructure.persistence import sqlite as sqlite_persistence`, and
`from calendar_sync.infrastructure.persistence.authorization_states import SqliteAuthorizationStates`.
Both new tests pin behavior that holds today and must survive the rewiring, so they pass before
Step 3 as well as after it.

Note: the scan test's own `sqlite3.connect(` literal lives under `tests/`, outside `SOURCE_ROOT`.
Add `from contextlib import closing`, `from datetime import timedelta`, and
`from calendar_sync.infrastructure.persistence.sqlite import SqliteUnitOfWorkFactory` to the
imports.

The orphan test asserts `1`, not `3`: a rule that no longer exists has no failure history.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/adapters/test_sqlite_connections.py -q`
Expected: the scan test FAILS listing seven modules; the existing-rule, adapter-failure, and
migration-failure tests PASS (they pin behavior the rewiring must keep); the removed-rule test FAILS (`2 != 1`: the orphan row is written and counted); the
orphan test FAILS (`3 != 1`).

- [ ] **Step 3: Route every connection**

Mechanical replacements:

- `with sqlite3.connect(self._database_path) as connection:` → `with transaction(self._database_path) as connection:` (health.py ×6, authorization_states.py ×2).
- `accounts.py` and `security.py`: delete `_connect`; replace `with self._connect() as connection:` with `with transaction(self._database_path) as connection:`. Keep `sqlite3` imported only where a type or `sqlite3.IntegrityError` is still named.
- `storage.py`: `closing(sqlite3.connect(self._database_path))` → `closing(open_connection(self._database_path))` (×3); `compact` uses `open_connection(self._database_path, isolation_level=None, timeout=self._busy_timeout)`. Keep `clear_activity`'s per-batch `with connection:` commits and `compact`'s autocommit `VACUUM` exactly as they are. Update `_BrokenConnection` in `tests/adapters/test_storage.py` so only a `VACUUM` statement raises and the `PRAGMA` succeeds; otherwise `test_compacting_reraises_an_unrelated_operational_error` would pass because configuration failed, not because `VACUUM` did.
- `activity_queries._reading`: `with closing(open_connection(database_path)) as connection:` and drop the now-redundant `row_factory` line; keep `create_function`.
- `sqlite.py`: `initialize_database` uses `with closing(open_connection(path)) as connection:` (its explicit `commit()` and `executescript` transactions already commit). `SqliteUnitOfWork.__enter__` uses `connection = open_connection(self._database_path)` and drops its own `row_factory` and `PRAGMA` lines.

- [ ] **Step 4: Guard `record_failure`**

Replace the body of `SqliteRuleHealthRecords.record_failure`:

```python
    def record_failure(self, rule_id: SyncRuleId, kind: ProviderFailureKind, at: datetime) -> int:
        """The rule's consecutive failures, counting this one; 1 for a rule removed meanwhile."""
        with transaction(self._database_path) as connection:
            # A rule removed while its run failed has no failures to count; inserting one for it
            # would break the foreign key, so nothing is recorded.
            connection.execute(
                """
                INSERT INTO rule_failures(rule_id, consecutive_failures, last_category, updated_at)
                SELECT ?, 1, ?, ? WHERE EXISTS (SELECT 1 FROM sync_rules WHERE id = ?)
                ON CONFLICT(rule_id) DO UPDATE SET
                    consecutive_failures = consecutive_failures + 1,
                    last_category = excluded.last_category,
                    updated_at = excluded.updated_at
                """,
                (rule_id.value, kind.value, at.isoformat(), rule_id.value),
            )
            # An orphaned row left by an earlier release is neither updated nor counted.
            row = connection.execute(
                """
                SELECT consecutive_failures FROM rule_failures
                WHERE rule_id = ? AND EXISTS (SELECT 1 FROM sync_rules WHERE id = ?)
                """,
                (rule_id.value, rule_id.value),
            ).fetchone()
        return 1 if row is None else int(row[0])
```

- [ ] **Step 5: Run the connection tests and the whole backend suite**

Run: `.venv/bin/pytest tests/adapters/test_sqlite_connections.py tests/adapters/test_sqlite.py tests/adapters/test_storage.py tests/adapters/test_storage_api.py -q && .venv/bin/pytest -q`
Expected: all pass. `test_sqlite.py`'s migration tests upgrade populated databases through the new
`initialize_database`; `test_storage*.py` cover usage, batched clearing, and compaction timeouts
through the new connections. There is no migration rollback path to test: rollback is restoring a
backup (ADR 0022). A failure elsewhere means some write relied on foreign keys being off: read it,
and report it rather than loosen the pragma.

- [ ] **Step 6: Document**

- `docs/architecture.md`, after "Transaction boundary", add:

```markdown
## Persistence

Every SQLite connection in the application opens through
`infrastructure/persistence/connections.py`: foreign keys are enforced, rows are read by column
name, a writer waits up to five seconds for another's lock, and `transaction()` commits, rolls back,
and closes in one block. A test fails if any other module under `src/calendar_sync` calls
`sqlite3.connect`, so a setting added there applies to every adapter.
```

- `AGENTS.md`, "Synchronization and persistence safety", add a bullet:
  `- Open SQLite connections only through infrastructure/persistence/connections.py.` (in backticks for the path).
- `CHANGELOG.md`, `## [Unreleased]`, add:

```markdown
### Fixed

- Every database connection now enforces foreign keys and closes when it is done, so a failure
  recorded for a rule removed meanwhile no longer leaves a stray failure count behind.
```

- [ ] **Step 7: Gates and commit**

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/lint-imports`

```bash
git add src/calendar_sync/infrastructure/persistence/sqlite.py \
  src/calendar_sync/infrastructure/persistence/health.py \
  src/calendar_sync/infrastructure/persistence/accounts.py \
  src/calendar_sync/infrastructure/persistence/authorization_states.py \
  src/calendar_sync/infrastructure/persistence/storage.py \
  src/calendar_sync/infrastructure/persistence/activity_queries.py \
  src/calendar_sync/infrastructure/security.py \
  tests/adapters/test_sqlite_connections.py tests/adapters/test_storage.py \
  docs/architecture.md AGENTS.md CHANGELOG.md
git commit -m "Route every SQLite connection through one module and enforce foreign keys"
```

---

### Task 3: The persistence contract

**Files:**
- Create: `tests/contracts/persistence.py`
- Create: `tests/adapters/test_persistence_contract.py`
- Modify: `src/calendar_sync/infrastructure/persistence/memory.py`
- Modify: `src/calendar_sync/infrastructure/persistence/sqlite.py` (`SqliteSyncRuleRepository.save` only)
- Modify: any `tests/application/*.py` that writes a rule's records without adding the rule (Step 6)
- Modify: `tests/adapters/test_sqlite.py` (delete `test_run_outcomes_keep_the_last_full_run_across_later_runs`, `_replay_factory`, `test_pending_exception_replays_follow_their_series_mapping`)
- Delete: `tests/adapters/test_memory_persistence.py` (each test is a contract case below)
- Modify: `docs/architecture.md`, `AGENTS.md`

**Interfaces:**
- Consumes: `transaction` from Task 1 (SQLite harness seeding).
- Produces: `PersistenceHarness`, `PersistenceContract` in `tests/contracts/persistence.py`.

- [ ] **Step 1: Write the contract**

`tests/contracts/persistence.py`:

```python
"""What every unit of work must honor, asked only through the persistence ports.

SQLite is what installations run; the in-memory unit of work stands in for it in application
tests. Both pass this suite, so the storage behavior it states holds for a use case tested in
memory; behavior it does not state may still differ. A subclass supplies a harness that records
Connected Accounts, which happens outside any unit of work.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

import pytest

from calendar_sync.application.errors import DuplicateDirectionalRelationship
from calendar_sync.application.ports import (
    CalendarAccess,
    ConnectedAccountState,
    DiscoveredCalendar,
    RulePreviewSummary,
    RuleRunOutcome,
    RunKind,
    UnitOfWorkFactory,
)
from calendar_sync.domain.changes import SourceObservation
from calendar_sync.domain.model import (
    CalendarEndpoint,
    CalendarId,
    ConnectedAccountId,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    OccurrenceMapping,
    OccurrenceMappingId,
    OccurrenceStart,
    OccurrenceState,
    ProjectionFingerprint,
    SyncRuleId,
    SyncRuleState,
    TimedInterval,
)
from tests.helpers import NOW, endpoint, rule, week_start

RULE = rule()
OTHER_RULE = replace(
    rule(), id=SyncRuleId("rule-0"), destination=endpoint("work-account", "other-calendar")
)
"""Sorts before RULE, so listing order is by identifier rather than by insertion."""
ACCOUNT = ConnectedAccountId("personal-account")


@dataclass(frozen=True, slots=True)
class PersistenceHarness:
    unit_of_work: UnitOfWorkFactory
    connect_account: Callable[[ConnectedAccountId], object]
    """Record a Connected Account, as authorizing it would outside any unit of work."""
    disconnect_account: Callable[[ConnectedAccountId], object]
    refused: tuple[type[Exception], ...]
    """What this storage raises for a record whose parent does not exist or is taken."""


def _mapping(name: str, rule_id: SyncRuleId = RULE.id, destination: str = "") -> EventMapping:
    return EventMapping(
        EventMappingId(name),
        rule_id,
        EventRef(RULE.source, EventId(f"source-{name}")),
        EventRef(RULE.destination, EventId(destination or f"destination-{name}")),
        "revision-1",
        ProjectionFingerprint("fingerprint"),
    )


def _occurrence(series: EventMapping, start: OccurrenceStart, name: str) -> OccurrenceMapping:
    return OccurrenceMapping(
        OccurrenceMappingId(name),
        series.id,
        start,
        EventRef(RULE.source, EventId(f"{series.source.event_id.value}_{name}")),
        EventRef(RULE.destination, EventId(f"{series.destination.event_id.value}_{name}")),
        OccurrenceState.CANCELLED,
        "revision-1",
    )


def _observation(ends_at: datetime = NOW, recurrence: tuple[str, ...] = ()) -> SourceObservation:
    return SourceObservation(
        revision="revision-1",
        title="Planning",
        time=TimedInterval(ends_at - timedelta(hours=1), ends_at),
        recurrence=recurrence,
    )


def _calendar(calendar_id: str, name: str) -> DiscoveredCalendar:
    return DiscoveredCalendar(calendar_id, name, CalendarAccess.OWNER, primary=False)


def _add_then_fail(unit_of_work: UnitOfWorkFactory) -> None:
    with unit_of_work() as uow:
        uow.rules.add(RULE)
        raise RuntimeError("stop")


def _commit_then_fail(unit_of_work: UnitOfWorkFactory) -> None:
    with unit_of_work() as uow:
        uow.rules.add(RULE)
        uow.commit()
        uow.rules.add(OTHER_RULE)
        raise RuntimeError("stop")


class PersistenceContract:
    @pytest.fixture
    def harness(self) -> PersistenceHarness:
        raise NotImplementedError

    # Units of work

    def test_writes_without_a_commit_are_discarded(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)

        with harness.unit_of_work() as uow:
            assert uow.rules.get(RULE.id) is None

    def test_a_unit_that_raises_discards_its_writes(self, harness: PersistenceHarness) -> None:
        with pytest.raises(RuntimeError):
            _add_then_fail(harness.unit_of_work)

        with harness.unit_of_work() as uow:
            assert uow.rules.get(RULE.id) is None

    def test_writes_after_a_commit_need_another_commit(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.commit()
            uow.rules.add(OTHER_RULE)

        with harness.unit_of_work() as uow:
            assert uow.rules.list() == (RULE,)

    def test_a_unit_that_raises_after_a_commit_keeps_what_it_committed(
        self, harness: PersistenceHarness
    ) -> None:
        with pytest.raises(RuntimeError):
            _commit_then_fail(harness.unit_of_work)

        with harness.unit_of_work() as uow:
            assert uow.rules.list() == (RULE,)

    def test_a_unit_reads_its_own_writes(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            assert uow.rules.get(RULE.id) == RULE

    # Directional Sync Rules

    def test_rules_round_trip_and_list_by_identifier(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            uow.commit()
        paused = replace(RULE, state=SyncRuleState.PAUSED)
        with harness.unit_of_work() as uow:
            uow.rules.save(paused)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.rules.list() == (OTHER_RULE, paused)
            assert uow.rules.get(RULE.id) == paused

    def test_a_second_rule_for_one_direction_is_refused(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            with pytest.raises(DuplicateDirectionalRelationship):
                uow.rules.add(replace(RULE, id=SyncRuleId("rule-2")))

    def test_moving_a_rule_onto_another_rules_direction_is_refused(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            with pytest.raises(DuplicateDirectionalRelationship):
                uow.rules.save(replace(OTHER_RULE, destination=RULE.destination))

    def test_saving_an_unknown_rule_fails(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow, pytest.raises(KeyError):
            uow.rules.save(RULE)

    def test_a_relationship_has_a_direction(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            assert uow.rules.relationship_exists(RULE.source, RULE.destination)
            assert not uow.rules.relationship_exists(RULE.destination, RULE.source)

    def test_removing_a_rule_takes_its_records_and_keeps_others(
        self, harness: PersistenceHarness
    ) -> None:
        series, other = _mapping("series"), _mapping("other", OTHER_RULE.id)
        source = EventRef(RULE.source, EventId("observed"))
        with harness.unit_of_work() as uow:
            for each, mapping in ((RULE, series), (OTHER_RULE, other)):
                uow.rules.add(each)
                uow.mappings.save(mapping)
                uow.replays.add(mapping.id)
                uow.cursors.save(each.id, "source-cursor")
                uow.destination_cursors.save(each.id, "destination-cursor")
                uow.run_outcomes.record(RuleRunOutcome(each.id, RunKind.SYNC, NOW, True))
                uow.previews.record(RulePreviewSummary(each.id, NOW, 1, 0))
                uow.observations.save(each.id, source, _observation(), NOW)
            uow.occurrences.save(_occurrence(series, week_start(1), "1"))
            uow.commit()

        with harness.unit_of_work() as uow:
            uow.rules.remove(RULE.id)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.rules.get(RULE.id) is None
            assert uow.mappings.for_rule(RULE.id) == ()
            assert uow.occurrences.for_series(series.id) == ()
            assert uow.replays.pending(RULE.id) == ()
            assert uow.cursors.get(RULE.id) is None
            assert uow.destination_cursors.get(RULE.id) is None
            assert uow.run_outcomes.latest(RULE.id, RunKind.SYNC) is None
            assert uow.previews.latest(RULE.id) is None
            assert uow.observations.get(RULE.id, source) is None
            assert uow.mappings.for_rule(OTHER_RULE.id) == (other,)
            assert uow.replays.pending(OTHER_RULE.id) == (other,)
            assert uow.cursors.get(OTHER_RULE.id) == "source-cursor"
            assert uow.previews.latest(OTHER_RULE.id) is not None
            assert uow.observations.get(OTHER_RULE.id, source) is not None

    def test_purging_a_rule_removes_it_with_its_mappings(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(_mapping("series"))
            uow.commit()
        with harness.unit_of_work() as uow:
            uow.rules.purge(RULE.id)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.rules.get(RULE.id) is None
            assert uow.mappings.count_for_rule(RULE.id) == 0

    # Event Mappings

    def test_mappings_are_found_by_source_destination_and_rule(
        self, harness: PersistenceHarness
    ) -> None:
        first, second, other = _mapping("b"), _mapping("a"), _mapping("c", OTHER_RULE.id)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.rules.add(OTHER_RULE)
            for mapping in (first, second, other):
                uow.mappings.save(mapping)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.mappings.for_source(RULE.id, first.source) == first
            assert uow.mappings.for_destination(RULE.id, first.destination) == first
            assert uow.mappings.for_destination(OTHER_RULE.id, first.destination) is None
            assert uow.mappings.for_rule(RULE.id) == (second, first)
            assert uow.mappings.count_for_rule(RULE.id) == 2

    def test_saving_a_mapping_again_updates_it(self, harness: PersistenceHarness) -> None:
        mapping = _mapping("series")
        updated = replace(
            mapping,
            source_revision="revision-2",
            projection_fingerprint=ProjectionFingerprint("new"),
        )
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(mapping)
            uow.mappings.save(updated)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.mappings.for_rule(RULE.id) == (updated,)

    def test_a_projection_mapped_to_another_source_is_refused(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(_mapping("first", destination="projection"))
            with pytest.raises(harness.refused):
                uow.mappings.save(_mapping("second", destination="projection"))

    def test_deleting_a_mapping_takes_its_occurrences_and_replay(
        self, harness: PersistenceHarness
    ) -> None:
        series = _mapping("series")
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(series)
            uow.occurrences.save(_occurrence(series, week_start(1), "1"))
            uow.replays.add(series.id)
            uow.commit()
        with harness.unit_of_work() as uow:
            uow.mappings.delete(series)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.occurrences.for_series(series.id) == ()
            assert uow.replays.pending(RULE.id) == ()

    # Occurrence Mappings and exception replays

    def test_occurrences_round_trip_in_start_order(self, harness: PersistenceHarness) -> None:
        timed, all_day = _mapping("timed"), _mapping("all-day")
        later = _occurrence(timed, week_start(2), "2")
        earlier = _occurrence(timed, week_start(1), "1")
        day = _occurrence(all_day, date(2026, 9, 1), "day")
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(timed)
            uow.mappings.save(all_day)
            for occurrence in (later, earlier, day):
                uow.occurrences.save(occurrence)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.occurrences.for_series(timed.id) == (earlier, later)
            assert uow.occurrences.get(all_day.id, date(2026, 9, 1)) == day
            assert uow.occurrences.get(all_day.id, date(2026, 9, 8)) is None

    def test_an_occurrence_needs_its_series_mapping(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            with pytest.raises(harness.refused):
                uow.occurrences.save(_occurrence(_mapping("missing"), week_start(1), "1"))

    def test_pending_replays_follow_their_series_mapping(self, harness: PersistenceHarness) -> None:
        kept, deleted = _mapping("kept"), _mapping("deleted")
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(kept)
            uow.mappings.save(deleted)
            uow.replays.add(kept.id)
            uow.replays.add(kept.id)
            uow.replays.add(deleted.id)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert [mapping.id for mapping in uow.replays.pending(RULE.id)] == [
                deleted.id,
                kept.id,
            ]
            uow.mappings.delete(deleted)
            uow.commit()
        with harness.unit_of_work() as uow:
            assert uow.replays.pending(RULE.id) == (kept,)
            uow.replays.remove(kept.id)
            uow.commit()
        with harness.unit_of_work() as uow:
            assert uow.replays.pending(RULE.id) == ()

    def test_a_replay_needs_its_series_mapping(self, harness: PersistenceHarness) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            with pytest.raises(harness.refused):
                uow.replays.add(EventMappingId("missing"))

    # Cursors, outcomes, previews

    def test_source_and_destination_cursors_are_kept_apart(
        self, harness: PersistenceHarness
    ) -> None:
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.cursors.save(RULE.id, "source-1")
            uow.destination_cursors.save(RULE.id, "destination-1")
            uow.cursors.save(RULE.id, "source-2")
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.cursors.get(RULE.id) == "source-2"
            assert uow.destination_cursors.get(RULE.id) == "destination-1"

    def test_run_outcomes_keep_the_last_successes_across_later_runs(
        self, harness: PersistenceHarness
    ) -> None:
        full = RuleRunOutcome(RULE.id, RunKind.SYNC, NOW, True, full_run=True)
        incremental = replace(full, completed_at=NOW + timedelta(days=1), full_run=False)
        failed = replace(full, completed_at=NOW + timedelta(days=2), succeeded=False)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.run_outcomes.record(full)
            uow.run_outcomes.record(incremental)
            # A failed full run leaves the daily pass due, so it must not count as completed.
            uow.run_outcomes.record(failed)
            uow.commit()

        with harness.unit_of_work() as uow:
            latest = uow.run_outcomes.latest(RULE.id, RunKind.SYNC)
            assert uow.run_outcomes.latest(RULE.id, RunKind.RECONCILIATION) is None
        assert latest is not None
        assert latest.completed_at == failed.completed_at
        assert not latest.succeeded
        assert latest.last_succeeded_at == incremental.completed_at
        assert latest.last_full_succeeded_at == full.completed_at

    def test_the_latest_preview_replaces_the_previous(self, harness: PersistenceHarness) -> None:
        later = RulePreviewSummary(RULE.id, NOW + timedelta(hours=1), 5, 2, 1, 3)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.previews.record(RulePreviewSummary(RULE.id, NOW, 1, 0))
            uow.previews.record(later)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.previews.latest(RULE.id) == later

    # Source Observations

    def test_stale_observations_are_forgotten_and_series_kept(
        self, harness: PersistenceHarness
    ) -> None:
        current = EventRef(RULE.source, EventId("current"))
        ended = EventRef(RULE.source, EventId("ended"))
        series = EventRef(RULE.source, EventId("series"))
        elsewhere = EventRef(endpoint("personal-account", "old-calendar"), EventId("elsewhere"))
        past = NOW - timedelta(days=100)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.observations.save(RULE.id, current, _observation(), NOW)
            uow.observations.save(RULE.id, ended, _observation(past), NOW)
            uow.observations.save(RULE.id, series, _observation(past, ("RRULE:FREQ=WEEKLY",)), NOW)
            uow.observations.save(RULE.id, elsewhere, _observation(), NOW)
            uow.commit()
        with harness.unit_of_work() as uow:
            uow.observations.forget_stale(RULE.id, RULE.source, NOW - timedelta(days=90))
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.observations.get(RULE.id, current) == _observation()
            assert uow.observations.get(RULE.id, ended) is None
            assert uow.observations.get(RULE.id, series) is not None
            assert uow.observations.get(RULE.id, elsewhere) is None

    # Connected Accounts and calendar names

    def test_only_a_disconnected_account_is_deleted(self, harness: PersistenceHarness) -> None:
        harness.connect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            assert uow.accounts.state(ACCOUNT) is ConnectedAccountState.CONNECTED
            assert not uow.accounts.delete_disconnected(ACCOUNT)
        harness.disconnect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            assert uow.accounts.state(ACCOUNT) is ConnectedAccountState.DISCONNECTED
            assert uow.accounts.delete_disconnected(ACCOUNT)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.accounts.state(ACCOUNT) is None
            assert not uow.accounts.delete_disconnected(ACCOUNT)

    def test_calendar_names_belong_to_an_existing_account_and_go_with_it(
        self, harness: PersistenceHarness
    ) -> None:
        family = CalendarEndpoint(ACCOUNT, CalendarId("family"))
        work = CalendarEndpoint(ACCOUNT, CalendarId("work"))
        missing = ConnectedAccountId("missing")
        harness.connect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            uow.calendar_names.remember(ACCOUNT, [_calendar("family", "Family")])
            uow.calendar_names.remember(missing, [_calendar("other", "Other")])
            uow.calendar_names.remember(ACCOUNT, [_calendar("family", "Household")])
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.calendar_names.names([family, work]) == {family: "Household"}
            assert uow.calendar_names.names([CalendarEndpoint(missing, CalendarId("other"))]) == {}
            assert uow.calendar_names.names([]) == {}
        harness.disconnect_account(ACCOUNT)
        with harness.unit_of_work() as uow:
            assert uow.accounts.delete_disconnected(ACCOUNT)
            uow.commit()
        with harness.unit_of_work() as uow:
            assert uow.calendar_names.names([family]) == {}

    # Records need their rule, and identities stay unique

    def test_records_of_a_rule_that_does_not_exist_are_refused(
        self, harness: PersistenceHarness
    ) -> None:
        source = EventRef(RULE.source, EventId("observed"))
        writes: tuple[Callable[[UnitOfWork], object], ...] = (
            lambda uow: uow.mappings.save(_mapping("series")),
            lambda uow: uow.cursors.save(RULE.id, "cursor"),
            lambda uow: uow.destination_cursors.save(RULE.id, "cursor"),
            lambda uow: uow.run_outcomes.record(RuleRunOutcome(RULE.id, RunKind.SYNC, NOW, True)),
            lambda uow: uow.previews.record(RulePreviewSummary(RULE.id, NOW, 1, 0)),
            lambda uow: uow.observations.save(RULE.id, source, _observation(), NOW),
        )
        for write in writes:
            with harness.unit_of_work() as uow, pytest.raises(harness.refused):
                write(uow)

    def test_a_second_mapping_for_one_source_is_refused(self, harness: PersistenceHarness) -> None:
        first = _mapping("first")
        again = replace(_mapping("second"), source=first.source)
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(first)
            with pytest.raises(harness.refused):
                uow.mappings.save(again)

    def test_saving_a_mapping_again_keeps_its_rule_and_source(
        self, harness: PersistenceHarness
    ) -> None:
        mapping = _mapping("series")
        moved = replace(
            mapping,
            source=EventRef(RULE.source, EventId("elsewhere")),
            destination=EventRef(RULE.destination, EventId("new-projection")),
            source_revision="revision-2",
        )
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(mapping)
            uow.mappings.save(moved)
            uow.commit()

        with harness.unit_of_work() as uow:
            # A mapping's rule and source never change; its projection and revision do.
            assert uow.mappings.for_rule(RULE.id) == (replace(moved, source=mapping.source),)
            assert uow.mappings.for_source(RULE.id, moved.source) is None

    def test_saving_an_occurrence_again_keeps_its_identifier(
        self, harness: PersistenceHarness
    ) -> None:
        series = _mapping("series")
        first = _occurrence(series, week_start(1), "1")
        renamed = replace(first, id=OccurrenceMappingId("other"), source_revision="revision-2")
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(series)
            uow.occurrences.save(first)
            uow.occurrences.save(renamed)
            uow.commit()

        with harness.unit_of_work() as uow:
            assert uow.occurrences.for_series(series.id) == (replace(renamed, id=first.id),)

    def test_one_occurrence_identifier_names_one_occurrence(
        self, harness: PersistenceHarness
    ) -> None:
        series = _mapping("series")
        first = _occurrence(series, week_start(1), "1")
        with harness.unit_of_work() as uow:
            uow.rules.add(RULE)
            uow.mappings.save(series)
            uow.occurrences.save(first)
            with pytest.raises(harness.refused):
                uow.occurrences.save(replace(first, original_start=week_start(2)))
```

Add `UnitOfWork` to the `calendar_sync.application.ports` import. Run `ruff format` on the new
files and wrap any line it leaves over 100 characters (`E501`).

- [ ] **Step 2: Write the runner**

`tests/adapters/test_persistence_contract.py`:

```python
"""The in-memory unit of work and SQLite honor the persistence contract."""

import sqlite3
from pathlib import Path

import pytest

from calendar_sync.application.ports import ConnectedAccountState
from calendar_sync.domain.model import ConnectedAccountId
from calendar_sync.infrastructure.persistence.connections import transaction
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteUnitOfWorkFactory,
    initialize_database,
)
from calendar_sync.infrastructure.security import CredentialCipher, HistoryCipher
from tests.contracts.persistence import PersistenceContract, PersistenceHarness
from tests.helpers import NOW


class TestInMemoryUnitOfWork(PersistenceContract):
    @pytest.fixture
    def harness(self) -> PersistenceHarness:
        factory = InMemoryUnitOfWorkFactory()

        def record(state: ConnectedAccountState) -> object:
            return lambda account_id: factory.state.accounts.__setitem__(account_id, state)

        return PersistenceHarness(
            factory,
            connect_account=record(ConnectedAccountState.CONNECTED),
            disconnect_account=record(ConnectedAccountState.DISCONNECTED),
            refused=(KeyError, ValueError),
        )


class TestSqliteUnitOfWork(PersistenceContract):
    @pytest.fixture
    def harness(self, tmp_path: Path) -> PersistenceHarness:
        database = tmp_path / "calendar-sync.db"
        initialize_database(database)

        def connect(account_id: ConnectedAccountId) -> None:
            with transaction(database) as connection:
                connection.execute(
                    """
                    INSERT INTO connected_accounts (
                        id, provider, display_name, email, encrypted_credentials, state,
                        created_at, updated_at
                    ) VALUES (?, 'google', 'Synthetic', ?, x'', 'connected', ?, ?)
                    """,
                    (
                        account_id.value,
                        f"{account_id.value}@example.test",
                        NOW.isoformat(),
                        NOW.isoformat(),
                    ),
                )

        def disconnect(account_id: ConnectedAccountId) -> None:
            with transaction(database) as connection:
                connection.execute(
                    "UPDATE connected_accounts SET state = 'disconnected' WHERE id = ?",
                    (account_id.value,),
                )

        return PersistenceHarness(
            # Source Observations are sealed, so the store needs a History Cipher to keep them.
            SqliteUnitOfWorkFactory(
                database, history=HistoryCipher(CredentialCipher.generate_key())
            ),
            connect_account=connect,
            disconnect_account=disconnect,
            refused=(sqlite3.IntegrityError,),
        )
```

Type the in-memory `record` helper precisely
(`Callable[[ConnectedAccountId], None]` built with a nested `def`) so mypy strict passes; the
lambda above shows intent only.

- [ ] **Step 3: Run to see which promises the in-memory unit breaks**

Run: `.venv/bin/pytest tests/adapters/test_persistence_contract.py -q`
Expected: `TestSqliteUnitOfWork` passes every case except
`test_moving_a_rule_onto_another_rules_direction_is_refused`, the planned SQLite change made in
Step 4. `TestInMemoryUnitOfWork` fails at least:
`test_rules_round_trip_and_list_by_identifier` (insertion order),
`test_a_second_rule_for_one_direction_is_refused` (no error),
`test_mappings_are_found_by_source_destination_and_rule` (insertion order),
`test_occurrences_round_trip_in_start_order` (insertion order),
`test_writes_after_a_commit_need_another_commit` and
`test_a_unit_that_raises_after_a_commit_keeps_what_it_committed` (commit aliases the working
state), `test_records_of_a_rule_that_does_not_exist_are_refused`,
`test_a_second_mapping_for_one_source_is_refused`,
`test_one_occurrence_identifier_names_one_occurrence`,
`test_saving_a_mapping_again_keeps_its_rule_and_source`,
`test_saving_an_occurrence_again_keeps_its_identifier`, and
`test_moving_a_rule_onto_another_rules_direction_is_refused`. On SQLite only the last fails (an
untranslated `sqlite3.IntegrityError`).
If any other SQLite case fails, the contract is wrong or SQLite has a bug: stop and report.

- [ ] **Step 4: Align the in-memory unit with SQLite** (`memory.py`)

```python
# InMemorySyncRuleRepository
    def list(self) -> tuple[SyncRule, ...]:
        return tuple(sorted(self._state.rules.values(), key=lambda rule: rule.id.value))

    def add(self, rule: SyncRule) -> None:
        # Mirror SQLite's primary key and its unique source-and-destination constraint.
        if rule.id in self._state.rules or self.relationship_exists(rule.source, rule.destination):
            raise DuplicateDirectionalRelationship(
                "a rule already exists for this source and destination"
            )
        self._state.rules[rule.id] = rule

# InMemoryEventMappingRepository
    def for_rule(self, rule_id: SyncRuleId) -> tuple[EventMapping, ...]:
        return tuple(
            sorted(
                (m for m in self._state.mappings.values() if m.rule_id == rule_id),
                key=lambda mapping: mapping.id.value,
            )
        )

# InMemoryOccurrenceMappingRepository
    def for_series(self, series_mapping_id: EventMappingId) -> tuple[OccurrenceMapping, ...]:
        # SQLite orders by the stored ISO text; one series' starts are all dates or all instants.
        return tuple(
            sorted(
                (m for key, m in self._state.occurrences.items() if key[0] == series_mapping_id),
                key=lambda mapping: mapping.original_start.isoformat(),
            )
        )
```

`InMemoryUnitOfWork.commit` must copy, not alias, so later writes stay uncommitted. Replace its
field-by-field assignments with:

```python
    def commit(self) -> None:
        assert self._working is not None
        # Copies, so writes after this commit stay in the unit until it commits again.
        for each in fields(MemoryState):
            setattr(self._target, each.name, deepcopy(getattr(self._working, each.name)))
        self._committed = True
```

(`from dataclasses import fields`.) Then mirror SQLite's remaining constraints in memory:

- A private `_require_rule(state, rule_id)` that raises `KeyError(rule_id)` when the rule is absent;
  call it from `InMemoryEventMappingRepository.save`, both cursor repositories' `save`,
  `InMemoryRuleRunOutcomeRepository.record`, `InMemoryRulePreviewRepository.record`, and
  `InMemorySourceObservationRepository.save`. `InMemorySyncCursorRepository` then takes the
  `MemoryState` and which cursor dictionary to use, e.g.
  `InMemorySyncCursorRepository(state, state.cursors)`.
- `InMemoryEventMappingRepository.save` raises `ValueError` when the mapping at
  `(rule_id, source)` exists under another `id` (SQLite's unique rule-and-source key). When a
  mapping with the same `id` already exists, it updates that mapping's destination, revision, and
  fingerprint and keeps its rule and source, as SQLite's `ON CONFLICT(id) DO UPDATE` does.
- `InMemoryOccurrenceMappingRepository.save`, when an occurrence already exists at the same
  `(series_mapping_id, original_start)`, keeps that occurrence's `id` and takes every other field
  from the saved one, as SQLite's `ON CONFLICT(series_mapping_id, original_start)` does.
- `InMemoryOccurrenceMappingRepository.save` raises `ValueError` when an occurrence with the same
  `id` exists under another `(series_mapping_id, original_start)` (SQLite's primary key).
- `InMemorySyncRuleRepository.save` raises `DuplicateDirectionalRelationship` when another rule
  already has the saved rule's source and destination.

And in SQLite, `SqliteSyncRuleRepository.save` wraps its `UPDATE` like `add` does:

```python
        try:
            cursor = self._connection.execute(...)  # the existing UPDATE, unchanged
        except sqlite3.IntegrityError as error:
            raise DuplicateDirectionalRelationship(
                "a rule already exists for this source and destination"
            ) from error
```

Application tests that wrote a mapping, cursor, outcome, preview, or observation without first
adding its rule now fail: add the rule in the test's setup, since SQLite would refuse the same
write. Do not relax the memory check.

Import `DuplicateDirectionalRelationship` from `calendar_sync.application.errors`. Before changing
`add`, run `grep -rn "KeyError" tests src | grep -i "rules.add\|add(rule"` — if a test expects
`KeyError` from a duplicate rule ID, update it to `DuplicateDirectionalRelationship`, which is what
SQLite raises.

Fix any further in-memory failure the same way: change memory, never SQLite, and add a one-line
comment naming the SQLite behavior it mirrors.

- [ ] **Step 5: Remove the tests the contract now covers for both**

- Delete `tests/adapters/test_memory_persistence.py` (cascade on mapping deletion, on rule removal,
  preview cascade, occurrence needs series: all contract cases).
- In `tests/adapters/test_sqlite.py`, delete `test_run_outcomes_keep_the_last_full_run_across_later_runs`,
  `_replay_factory`, and `test_pending_exception_replays_follow_their_series_mapping`; drop imports
  that become unused (`ruff check` reports them).

- [ ] **Step 6: Run the contract and the whole suite**

Run: `.venv/bin/pytest tests/adapters/test_persistence_contract.py -q && .venv/bin/pytest -q`
Expected: all pass. An application test that relied on memory's insertion order now fails: fix the
test's expectation to the identifier or start order SQLite returns, and note it in the commit.

- [ ] **Step 7: Document**

- `docs/architecture.md`, append to the "Persistence" section from Task 2:

```markdown
The in-memory unit of work that application tests use and the SQLite one both pass the persistence
contract in `tests/contracts/persistence.py`. It states, through the ports alone, the behavior use
cases rely on: writes are discarded until committed, rule removal takes a rule's records with it, a
record without its rule or series is refused, identities stay unique, and listings come back in a
fixed order. It does not make the two interchangeable in every respect; when a use case starts
relying on another storage behavior, add it to the contract.
```

- `AGENTS.md`, "Testing", add after the first paragraph: `When the persistence ports or either unit of work change, extend tests/contracts/persistence.py so the in-memory and SQLite units keep the same behavior.` (path in backticks).

- [ ] **Step 8: Gates and commit**

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/lint-imports`

```bash
git add tests/contracts/persistence.py tests/adapters/test_persistence_contract.py \
  src/calendar_sync/infrastructure/persistence/memory.py \
  src/calendar_sync/infrastructure/persistence/sqlite.py \
  tests/adapters/test_sqlite.py docs/architecture.md AGENTS.md
git rm tests/adapters/test_memory_persistence.py
# plus each application test file Step 6 had to fix, by path
git commit -m "Hold the in-memory and SQLite units of work to one persistence contract"
```

---

### Task 4: `Adapters` typed by ports

**Files:**
- Modify: `src/calendar_sync/bootstrap/container.py` (`Adapters` ~L141-166, `build_adapters` ~L193-235, `compose` ~L288-325)
- Modify: `tests/adapters/test_api.py` (seeding at ~L332, ~L452, ~L618)
- Modify: `docs/architecture.md`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Adapters.administrator: AdministratorAccess`,
  `Adapters.accounts: ConnectedAccountRepository | None`,
  `Adapters.authorization: AccountAuthorization | None` (renamed from `google_oauth`).

- [ ] **Step 1: Change the field types**

```python
    administrator: AdministratorAccess
    ...
    accounts: ConnectedAccountRepository | None = None
    authorization: AccountAuthorization | None = None
    """Connects and reauthorizes accounts through the provider's OAuth flow."""
```

Import `ConnectedAccountRepository` from `application.ports` (`AdministratorAccess` and
`AccountAuthorization` are already imported). Remove `SqliteConnectedAccountStore` and
`GoogleOAuthService` from the type-only uses; they stay imported where `build_adapters` constructs
them. In `build_adapters`, pass `authorization=google_oauth` instead of `google_oauth=google_oauth`
(the local `google_oauth` variable keeps its concrete type for `service_for` and the routing map).
In `compose`, read `adapters.authorization` in both places that read `adapters.google_oauth`.

- [ ] **Step 2: Run mypy to find concrete reaches**

Run: `.venv/bin/mypy`
Expected: errors only in `tests/adapters/test_api.py`: `adapters.google_oauth` no longer exists
(about 15 uses, which monkeypatch `verify_access`, `calendars`, `complete` and call
`_store_state`), and `adapters.accounts.save(...)` is not on the port. `disconnect()` and `list()`
are on `ConnectedAccountRepository` and need no change. If `src/` or `scripts/dev_preview.py`
errors, a use case needs a method its port lacks: report it rather than widen the type back.

- [ ] **Step 3: Narrow to the concrete classes in the API tests**

In `tests/adapters/test_api.py`, add near the other helpers:

```python
def _google(adapters: Adapters) -> GoogleOAuthService:
    """The installation's Google OAuth service, for replacing its calls to Google."""
    assert isinstance(adapters.authorization, GoogleOAuthService)
    return adapters.authorization


def _account_store(adapters: Adapters) -> SqliteConnectedAccountStore:
    """The installation's account store, for seeding accounts as authorizing them would."""
    assert isinstance(adapters.accounts, SqliteConnectedAccountStore)
    return adapters.accounts
```

Replace each `assert adapters.google_oauth is not None` followed by uses of `adapters.google_oauth`
with `google = _google(adapters)` and `google.<method>` (including
`monkeypatch.setattr(google, ...)` and `google._store_state(...)`). Replace each
`assert adapters.accounts is not None` before a `save(...)` with `store = _account_store(adapters)`
and `store.save(...)`; leave `disconnect`/`list` calls on `adapters.accounts` where mypy accepts
them. Import `Adapters`, `GoogleOAuthService`, and `SqliteConnectedAccountStore` if not already
imported.

- [ ] **Step 4: Run the gates**

Run: `.venv/bin/mypy && .venv/bin/pytest tests/adapters/test_api.py tests/test_dev_preview.py -q`
Expected: no mypy errors; tests pass.

Then `grep -rn "google_oauth" src tests scripts` must list only the local variable inside
`build_adapters` and route/test function names such as `start_google_oauth`.

- [ ] **Step 5: Document**

`docs/architecture.md`, in the composition paragraph after "Tests and the development preview
substitute adapters before `compose`, or use cases after it.", add: "`Adapters` holds ports rather
than concrete classes, so a substitute needs only to honor the port."

- [ ] **Step 6: Commit**

```bash
git add src/calendar_sync/bootstrap/container.py tests/adapters/test_api.py docs/architecture.md
git commit -m "Type the composed adapters by their ports"
```

---

### Task 5: Full verification

- [ ] **Step 1: Backend gate**

```sh
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80
```

Expected: every command exits 0. No frontend file changed, so the frontend gate does not apply.

- [ ] **Step 2: Confirm scope**

Run: `git diff origin/main --stat`
Expected: only the files listed in File Structure and in each task's **Files** block (including
`tests/adapters/test_storage.py`, `persistence/sqlite.py`, and any application tests Task 3 Step 6
repaired), plus this plan.
