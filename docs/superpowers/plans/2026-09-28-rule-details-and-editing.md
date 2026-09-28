# Rule Details, Policy Editing, and Rule Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Installation Administrator open a Directional Sync Rule at `/rules/{id}`, see everything it does, change its Transformation Policy or All-Day Sync Policy as a Material Rule Change, and remove or replace it with an explicit choice about its Managed Projections.

**Architecture:**
- **Domain.** `SyncRule` decides the state after an edit and after removal, and carries a persisted `reprojection_required` flag.
- **Application.** New use cases `ChangeSyncRulePolicy`, `GetSyncRuleDetails`, `RemoveSyncRule`, and `ReplaceSyncRuleCalendars` run through the ports.
- **Sync run.** `ExecuteSyncRule` reprojects every mapping when the flag is set, and records a Run Outcome.
- **Locking.** `RuleLocks` is one per-rule lock shared by synchronization and removal.
- **Persistence.** SQLite migration 3 adds the flag and a `rule_run_outcomes` table.
- **HTTP.** New admin-only routes expose the use cases.
- **Web.** A new React `RuleDetailsView` is reachable from each rule row.

**Tech Stack:** Python 3.12, FastAPI, SQLite, pytest, React 19, TypeScript, TanStack Query, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-28-rule-details-and-editing-design.md`

## Global Constraints

- Domain decisions go in `src/calendar_sync/domain/`. Use cases go in `src/calendar_sync/application/`, which uses only `application/ports.py` protocols. HTTP goes in `src/calendar_sync/interfaces/`. Wiring goes only in `bootstrap/container.py`.
- Every new `/api/v1/rules/...` route uses `dependencies=[Depends(require_admin)]`.
- Editing never calls the `CalendarProvider`. Only preview (reads), synchronization, and Rule Removal in `delete` mode write. Provider writes keep `sendUpdates=none`, which is already enforced in `GoogleCalendarProvider`.
- Update or deletion requires a valid Event Mapping plus ownership checks. A source that cannot be verified never authorizes deletion. Cursors advance only after the whole run succeeds.
- Keep write transactions short. Commit after each provider write, and never hold a write lock across a provider call.
- Event titles, descriptions, and locations are never persisted in SQLite, audit entries, run outcomes, or logs. Run outcomes store counts, timestamps, and a failure-kind code only.
- Schema changes are forward-only migrations that go through `_FORWARD_MIGRATIONS`. Each needs SQLite-backed tests, plus upgrade and rollback notes in `docs/deployment.md`.
- The migration file is `0003_rule_editing.sql`, version `3`.
- `ProjectionHandling` values are exactly `"delete"` and `"detach"`. The API requires an explicit value. Only the UI defaults to `"delete"`.
- Use the domain terms exactly: Directional Sync Rule, Material Rule Change, Rule Preview, Rule Removal, Rule Replacement, Detached Event, Managed Projection, Event Mapping.
- The UI must work with the keyboard, label every control, use `role="alert"` for errors and `role="status"` for results, stack at the existing `max-width: 800px` breakpoint, and show the privacy and destructive effects before the confirm button.
- After any `web/` change, run `npm --prefix web run build` and commit the regenerated `src/calendar_sync/interfaces/api/static/`.
- Backend gate: `.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80`
- Frontend gate: `npm --prefix web run typecheck && npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

These are the conditions most likely to bite an administrator that the task tests must pin down. Each has a test in the task named.

1. **The rule is edited while a Sync Run is in progress.** The run must not clear `reprojection_required`, so the next run still rewrites projections under the new policy. Task 3 covers this.
2. **Rule Removal in `delete` mode fails partway through.** For example, Google returns 403 on the third projection. The rule must stay in the Disabled state with the remaining mappings, and a retry, even one using `detach`, must finish. Task 5 covers this.
3. **Replacement targets an existing relationship.** The request must fail before anything is deleted. Task 5 covers this.
4. **Delete is requested while the destination account is disconnected.** The request is rejected with no state change and no provider call. `detach` still works. Tasks 5 and 6 cover this.
5. **An odd rule id appears in the URL.** Examples are `/rules/a%2Fb`, `/rules/%E0%A4%A`, and `/rules/x/y`. The id must round-trip safely, or fall back to the list without throwing. Task 7 covers this.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/calendar_sync/domain/model.py` (modify) | `ProjectionHandling`, `SyncRule.reprojection_required`, `change_policy`, `complete_reprojection`, `begin_removal` (replaces the unused `disable`) |
| `src/calendar_sync/application/ports.py` (modify) | `RunKind`, `RuleRunOutcome`, `RuleRunOutcomeRepository`, `AccountAuthorizations`; `SyncRuleRepository.remove`; `EventMappingRepository.count_for_rule`; `UnitOfWork.run_outcomes` |
| `src/calendar_sync/application/errors.py` (modify) | `RuleNotFound`, `NotACalendarChange`, `RemovalRequiresProvider`, `RemovalRequiresAuthorization`, `RemovalInterrupted` |
| `src/calendar_sync/application/locking.py` (create) | `RuleLocks` |
| `src/calendar_sync/application/synchronization.py` (modify) | Reprojection sweep, guarded flag clear, run outcomes, shared locks |
| `src/calendar_sync/application/reconciliation.py` (modify) | Records the reconciliation outcome |
| `src/calendar_sync/application/rules.py` (modify) | `ChangeSyncRulePolicy`, `GetSyncRuleDetails`, `SyncRuleDetails`, `ReplaceSyncRuleCalendars`, `RuleReplacement` |
| `src/calendar_sync/application/removal.py` (create) | `RemoveSyncRule`, `RemovalResult` |
| `src/calendar_sync/infrastructure/persistence/0003_rule_editing.sql` (create) | Migration 3 |
| `src/calendar_sync/infrastructure/persistence/sqlite.py` (modify) | Column, `remove`, `count_for_rule`, `SqliteRuleRunOutcomeRepository` |
| `src/calendar_sync/infrastructure/persistence/memory.py` (modify) | The same capabilities in memory |
| `src/calendar_sync/infrastructure/google/oauth.py` (modify) | `SqliteConnectedAccountStore.is_connected` |
| `src/calendar_sync/infrastructure/identifiers.py` (create) | `UuidIdGenerator` |
| `src/calendar_sync/bootstrap/container.py` (modify) | Wiring |
| `src/calendar_sync/interfaces/api/schemas.py`, `app.py` (modify) | Routes and schemas |
| `web/src/lib/navigation.ts` (modify) | `AppLocation`, rule paths, `isPlainLeftClick` |
| `web/src/lib/rule-change.ts` (create) | Pure consequence, label, and outcome copy |
| `web/src/lib/api.ts` (modify) | Types and calls |
| `web/src/App.tsx` (modify) | Location state |
| `web/src/features/dashboard.tsx` (modify) | Routes to details, row link, preview-required note |
| `web/src/features/rule-details.tsx` (create) | `RuleDetailsView` |
| `web/src/index.css` (modify) | Details layout |
| Docs | `CONTEXT.md`, `docs/domain-model.md`, `docs/sync-model.md`, `docs/deployment.md`, `docs/adr/0010-rule-removal-and-calendar-replacement.md`, `CHANGELOG.md`, `README.md` |

---

### Task 1: Domain lifecycle for Material Rule Change and Rule Removal

**Files:**
- Modify: `src/calendar_sync/domain/model.py` (`PrivacyPolicy` area and `SyncRule`)
- Test: `tests/domain/test_model.py`

**Interfaces:**
- Produces the following:
  - `ProjectionHandling(StrEnum)` with `DELETE = "delete"` and `DETACH = "detach"`.
  - The field `SyncRule.reprojection_required: bool = False`, as the last field.
  - `SyncRule.change_policy(transformation: TransformationPolicy) -> SyncRule`.
  - `SyncRule.complete_reprojection() -> SyncRule`.
  - `SyncRule.begin_removal() -> SyncRule`. It replaces `disable()`, which has no callers.

- [ ] **Step 1: Write the failing tests** (append to `tests/domain/test_model.py`, adding imports as needed)

```python
import pytest

from calendar_sync.domain.errors import InvalidStateTransition
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    PrivacyPolicy,
    SyncRuleState,
    TransformationPolicy,
)
from tests.helpers import rule

DETAILS = TransformationPolicy(privacy=PrivacyPolicy.COPY_DETAILS)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (SyncRuleState.DRAFT, SyncRuleState.DRAFT),
        (SyncRuleState.DRY_RUN_VALIDATED, SyncRuleState.DRAFT),
        (SyncRuleState.ENABLED, SyncRuleState.PAUSED),
        (SyncRuleState.PAUSED, SyncRuleState.PAUSED),
        (SyncRuleState.DEGRADED, SyncRuleState.DEGRADED),
    ],
)
def test_material_policy_change_requires_a_new_preview(
    before: SyncRuleState, after: SyncRuleState
) -> None:
    changed = rule(state=before).change_policy(DETAILS)

    assert changed.state is after
    assert changed.transformation == DETAILS
    assert changed.reprojection_required is True


def test_unchanged_policy_is_not_a_material_change() -> None:
    enabled = rule(state=SyncRuleState.ENABLED)

    assert enabled.change_policy(enabled.transformation) == enabled


def test_policy_change_preserves_busy_title_and_endpoints() -> None:
    original = rule(state=SyncRuleState.ENABLED)

    changed = original.change_policy(
        TransformationPolicy(all_day=AllDaySyncPolicy.EXCLUDE, busy_title="Busy")
    )

    assert changed.source == original.source
    assert changed.destination == original.destination
    assert changed.initial_lookback_days == original.initial_lookback_days


def test_rule_with_incomplete_removal_cannot_change_policy() -> None:
    with pytest.raises(InvalidStateTransition):
        rule(state=SyncRuleState.DISABLED).change_policy(DETAILS)


def test_changed_rule_cannot_be_enabled_until_previewed_again() -> None:
    changed = rule(state=SyncRuleState.ENABLED).change_policy(DETAILS)

    with pytest.raises(InvalidStateTransition):
        changed.enable()
    assert changed.mark_dry_run_validated().enable().state is SyncRuleState.ENABLED


def test_completed_reprojection_clears_the_flag() -> None:
    changed = rule().change_policy(DETAILS)

    assert changed.complete_reprojection().reprojection_required is False


@pytest.mark.parametrize("state", list(SyncRuleState))
def test_removal_can_begin_from_every_state_and_is_inert(state: SyncRuleState) -> None:
    removing = rule(state=state).begin_removal()

    assert removing.state is SyncRuleState.DISABLED
    with pytest.raises(InvalidStateTransition):
        removing.enable()
    with pytest.raises(InvalidStateTransition):
        removing.mark_dry_run_validated()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/domain/test_model.py -q`
Expected: FAIL with `AttributeError: 'SyncRule' object has no attribute 'change_policy'`

- [ ] **Step 3: Implement** in `src/calendar_sync/domain/model.py`

After `AllDaySyncPolicy`:

```python
class ProjectionHandling(StrEnum):
    """What Rule Removal does with mapped Managed Projections."""

    DELETE = "delete"
    DETACH = "detach"
```

In `SyncRule`, add the field after `state`:

```python
    reprojection_required: bool = False
```

Replace `disable()` with the following:

```python
    def change_policy(self, transformation: TransformationPolicy) -> Self:
        """Apply a Material Rule Change; the rule must pass a new Rule Preview afterwards."""
        if self.state is SyncRuleState.DISABLED:
            raise InvalidStateTransition("cannot change a rule while its removal is incomplete")
        if transformation == self.transformation:
            return self
        if self.state in {SyncRuleState.ENABLED, SyncRuleState.PAUSED}:
            state = SyncRuleState.PAUSED
        elif self.state is SyncRuleState.DEGRADED:
            state = SyncRuleState.DEGRADED
        else:
            state = SyncRuleState.DRAFT
        return replace(
            self, transformation=transformation, state=state, reprojection_required=True
        )

    def complete_reprojection(self) -> Self:
        return replace(self, reprojection_required=False)

    def begin_removal(self) -> Self:
        """Disabled marks a Rule Removal that started and has not finished."""
        return replace(self, state=SyncRuleState.DISABLED)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/domain -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/domain/model.py tests/domain/test_model.py
git commit -m "feat: model material rule changes and rule removal in the domain"
```

---

### Task 2: Ports, migration 3, and persistence adapters

**Files:**
- Modify: `src/calendar_sync/application/ports.py`
- Create: `src/calendar_sync/infrastructure/persistence/0003_rule_editing.sql`
- Modify: `src/calendar_sync/infrastructure/persistence/sqlite.py`
- Modify: `src/calendar_sync/infrastructure/persistence/memory.py`
- Modify: `src/calendar_sync/infrastructure/google/oauth.py` (`SqliteConnectedAccountStore`)
- Test: `tests/adapters/test_sqlite.py`, `tests/adapters/test_google_oauth_storage.py`

**Interfaces:**
- Consumes `SyncRule.reprojection_required` from Task 1.
- Produces these in `application/ports.py`:

```python
class RunKind(StrEnum):
    SYNC = "sync"
    RECONCILIATION = "reconciliation"


@dataclass(frozen=True, slots=True)
class RuleRunOutcome:
    rule_id: SyncRuleId
    kind: RunKind
    completed_at: datetime
    succeeded: bool
    full_run: bool = False
    created: int = 0
    updated: int = 0
    deleted: int = 0
    conflicts: int = 0
    checked_mappings: int = 0
    drift: int = 0
    failure_kind: str | None = None


class RuleRunOutcomeRepository(Protocol):
    def record(self, outcome: RuleRunOutcome) -> None: ...

    def latest(self, rule_id: SyncRuleId, kind: RunKind) -> RuleRunOutcome | None: ...


class AccountAuthorizations(Protocol):
    def is_connected(self, account_id: ConnectedAccountId) -> bool: ...
```

- It also produces `SyncRuleRepository.remove(rule_id: SyncRuleId) -> None`, which deletes the rule, cascades its data, and resolves the rule's open incidents in SQLite. It produces `EventMappingRepository.count_for_rule(rule_id: SyncRuleId) -> int` and `UnitOfWork.run_outcomes: RuleRunOutcomeRepository`.
- It also produces `SqliteConnectedAccountStore.is_connected(account_id) -> bool`.

- [ ] **Step 1: Write the failing tests** (append to `tests/adapters/test_sqlite.py`)

```python
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

from calendar_sync.application.ports import AuditEntry, RuleRunOutcome, RunKind
from calendar_sync.domain.model import PrivacyPolicy, SyncRuleState, TransformationPolicy


def _mapping(event_id: str = "source-event") -> EventMapping:
    return EventMapping(
        EventMappingId(f"mapping-{event_id}"),
        rule().id,
        EventRef(rule().source, EventId(event_id)),
        EventRef(rule().destination, EventId(f"destination-{event_id}")),
        "revision-1",
        ProjectionFingerprint("fingerprint"),
    )


def test_migration_3_upgrades_a_version_2_installation_with_rules(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    with SqliteUnitOfWorkFactory(database)() as uow:
        uow.rules.add(rule())
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE rule_run_outcomes")
        connection.execute("ALTER TABLE sync_rules DROP COLUMN reprojection_required")
        connection.execute("DELETE FROM schema_migrations WHERE version = 3")

    initialize_database(database)
    initialize_database(database)

    with SqliteUnitOfWorkFactory(database)() as uow:
        restored = uow.rules.get(rule().id)
    with sqlite3.connect(database) as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations")]
    assert restored is not None
    assert restored.reprojection_required is False
    assert versions.count(3) == 1


def test_reprojection_flag_round_trips(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    changed = rule().change_policy(TransformationPolicy(privacy=PrivacyPolicy.COPY_DETAILS))
    with factory() as uow:
        uow.rules.add(rule())
        uow.rules.save(changed)
        uow.commit()

    with factory() as uow:
        assert uow.rules.get(rule().id) == changed


def test_run_outcomes_keep_the_latest_per_kind(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    first = RuleRunOutcome(rule().id, RunKind.SYNC, datetime(2026, 9, 1, tzinfo=UTC), True, created=2)
    second = replace(first, completed_at=datetime(2026, 9, 2, tzinfo=UTC), succeeded=False,
                     created=0, failure_kind="rate_limit")
    with factory() as uow:
        uow.rules.add(rule())
        uow.run_outcomes.record(first)
        uow.run_outcomes.record(second)
        uow.commit()

    with factory() as uow:
        assert uow.run_outcomes.latest(rule().id, RunKind.SYNC) == second
        assert uow.run_outcomes.latest(rule().id, RunKind.RECONCILIATION) is None


def test_rule_removal_cascades_resolves_incidents_and_keeps_audit(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    with factory() as uow:
        uow.rules.add(rule())
        uow.mappings.save(_mapping())
        uow.cursors.save(rule().id, "cursor")
        uow.run_outcomes.record(
            RuleRunOutcome(rule().id, RunKind.SYNC, datetime(2026, 9, 1, tzinfo=UTC), True)
        )
        uow.audit.append(
            AuditEntry(datetime(2026, 9, 1, tzinfo=UTC), rule().id, "create", "completed")
        )
        uow.commit()
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO incidents (id, deduplication_key, rule_id, category, state,
                summary, opened_at, updated_at)
            VALUES ('i-1', 'provider:rule-1', 'rule-1', 'temporary', 'open', 's', 't', 't')
            """
        )

    with factory() as uow:
        assert uow.mappings.count_for_rule(rule().id) == 1
        uow.rules.remove(rule().id)
        uow.commit()

    with factory() as uow:
        assert uow.rules.get(rule().id) is None
        assert uow.mappings.count_for_rule(rule().id) == 0
        assert uow.cursors.get(rule().id) is None
        assert uow.run_outcomes.latest(rule().id, RunKind.SYNC) is None
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT state FROM incidents").fetchone()[0] == "resolved"
        assert connection.execute("SELECT COUNT(*) FROM audit_entries").fetchone()[0] == 1


def test_memory_adapter_supports_removal_counts_and_outcomes() -> None:
    from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory

    factory = InMemoryUnitOfWorkFactory()
    with factory() as uow:
        uow.rules.add(rule(state=SyncRuleState.PAUSED))
        uow.mappings.save(_mapping())
        uow.run_outcomes.record(
            RuleRunOutcome(rule().id, RunKind.SYNC, datetime(2026, 9, 1, tzinfo=UTC), True)
        )
        uow.commit()
    with factory() as uow:
        assert uow.mappings.count_for_rule(rule().id) == 1
        assert uow.run_outcomes.latest(rule().id, RunKind.SYNC) is not None
        uow.rules.remove(rule().id)
        uow.commit()
    assert factory.state.rules == {}
    assert factory.state.mappings == {}
    assert factory.state.outcomes == {}
```

Append to `tests/adapters/test_google_oauth_storage.py`. Reuse that file's existing store construction helper, or construct one as shown below:

```python
def test_connected_account_authorization_reflects_disconnection(tmp_path: Path) -> None:
    database = tmp_path / "test.db"
    initialize_database(database)
    store = SqliteConnectedAccountStore(database, CredentialCipher(CredentialCipher.generate_key()))
    account = store.save("Work", "work@example.test", '{"refresh_token":"synthetic"}')

    assert store.is_connected(account.id) is True
    store.disconnect(account.id)
    assert store.is_connected(account.id) is False
    assert store.is_connected(ConnectedAccountId("missing")) is False
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/adapters/test_sqlite.py tests/adapters/test_google_oauth_storage.py -q`
Expected: FAIL. `RuleRunOutcome` cannot be imported, and `is_connected` does not exist.

- [ ] **Step 3: Implement**

`src/calendar_sync/infrastructure/persistence/0003_rule_editing.sql`:

```sql
ALTER TABLE sync_rules ADD COLUMN reprojection_required INTEGER NOT NULL DEFAULT 0;

CREATE TABLE rule_run_outcomes (
    rule_id TEXT NOT NULL REFERENCES sync_rules(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('sync', 'reconciliation')),
    completed_at TEXT NOT NULL,
    succeeded INTEGER NOT NULL,
    full_run INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0,
    conflicts INTEGER NOT NULL DEFAULT 0,
    checked_mappings INTEGER NOT NULL DEFAULT 0,
    drift INTEGER NOT NULL DEFAULT 0,
    failure_kind TEXT,
    PRIMARY KEY (rule_id, kind)
);
```

In `application/ports.py`, add the Interfaces block above. It needs `from enum import StrEnum` and `ConnectedAccountId` in the model import. Also add the following:

```python
class SyncRuleRepository(Protocol):
    ...
    def remove(self, rule_id: SyncRuleId) -> None: ...


class EventMappingRepository(Protocol):
    ...
    def count_for_rule(self, rule_id: SyncRuleId) -> int: ...


class UnitOfWork(Protocol):
    ...
    run_outcomes: RuleRunOutcomeRepository
```

In `sqlite.py`, make these changes:
- Set `_FORWARD_MIGRATIONS = ((2, "0002_account_avatar.sql"), (3, "0003_rule_editing.sql"))`.
- In `add` and `save`, add `reprojection_required` to the column lists. `add` has 11 placeholders. `save` has `... state = ?, reprojection_required = ? WHERE id = ?`.
- In `_rule_values`, append `int(rule.reprojection_required)`.
- In `_rule_from_row`, add `reprojection_required=bool(row["reprojection_required"])`.
- Add the new methods and repository below:

```python
    def remove(self, rule_id: SyncRuleId) -> None:
        now = datetime.now(UTC).isoformat()
        self._connection.execute(
            """
            UPDATE incidents SET state = 'resolved', updated_at = ?, resolved_at = ?
            WHERE rule_id = ? AND state = 'open'
            """,
            (now, now, rule_id.value),
        )
        self._connection.execute("DELETE FROM sync_rules WHERE id = ?", (rule_id.value,))
```

```python
    def count_for_rule(self, rule_id: SyncRuleId) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM event_mappings WHERE rule_id = ?", (rule_id.value,)
        ).fetchone()
        return int(row[0])
```

```python
class SqliteRuleRunOutcomeRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def record(self, outcome: RuleRunOutcome) -> None:
        self._connection.execute(
            """
            INSERT INTO rule_run_outcomes (
                rule_id, kind, completed_at, succeeded, full_run, created, updated,
                deleted, conflicts, checked_mappings, drift, failure_kind
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_id, kind) DO UPDATE SET
                completed_at = excluded.completed_at,
                succeeded = excluded.succeeded,
                full_run = excluded.full_run,
                created = excluded.created,
                updated = excluded.updated,
                deleted = excluded.deleted,
                conflicts = excluded.conflicts,
                checked_mappings = excluded.checked_mappings,
                drift = excluded.drift,
                failure_kind = excluded.failure_kind
            """,
            (
                outcome.rule_id.value,
                outcome.kind.value,
                outcome.completed_at.isoformat(),
                int(outcome.succeeded),
                int(outcome.full_run),
                outcome.created,
                outcome.updated,
                outcome.deleted,
                outcome.conflicts,
                outcome.checked_mappings,
                outcome.drift,
                outcome.failure_kind,
            ),
        )

    def latest(self, rule_id: SyncRuleId, kind: RunKind) -> RuleRunOutcome | None:
        row = self._connection.execute(
            "SELECT * FROM rule_run_outcomes WHERE rule_id = ? AND kind = ?",
            (rule_id.value, kind.value),
        ).fetchone()
        if row is None:
            return None
        return RuleRunOutcome(
            rule_id=rule_id,
            kind=kind,
            completed_at=datetime.fromisoformat(str(row["completed_at"])),
            succeeded=bool(row["succeeded"]),
            full_run=bool(row["full_run"]),
            created=int(row["created"]),
            updated=int(row["updated"]),
            deleted=int(row["deleted"]),
            conflicts=int(row["conflicts"]),
            checked_mappings=int(row["checked_mappings"]),
            drift=int(row["drift"]),
            failure_kind=str(row["failure_kind"]) if row["failure_kind"] is not None else None,
        )
```

In `SqliteUnitOfWork`, declare `run_outcomes: RuleRunOutcomeRepository` and set `self.run_outcomes = SqliteRuleRunOutcomeRepository(connection)` in `__enter__`.

In `memory.py`, make these changes:
- `MemoryState` gains `outcomes: dict[tuple[SyncRuleId, RunKind], RuleRunOutcome] = field(default_factory=dict)`.
- `commit` also copies `self._target.outcomes = self._working.outcomes`.
- `__enter__` sets `self.run_outcomes = InMemoryRuleRunOutcomeRepository(self._working)`.
- Add the class and methods below:

```python
class InMemoryRuleRunOutcomeRepository:
    def __init__(self, state: MemoryState) -> None:
        self._state = state

    def record(self, outcome: RuleRunOutcome) -> None:
        self._state.outcomes[(outcome.rule_id, outcome.kind)] = outcome

    def latest(self, rule_id: SyncRuleId, kind: RunKind) -> RuleRunOutcome | None:
        return self._state.outcomes.get((rule_id, kind))
```

In `InMemorySyncRuleRepository`:

```python
    def remove(self, rule_id: SyncRuleId) -> None:
        self._state.rules.pop(rule_id, None)
        self._state.mappings = {
            key: mapping for key, mapping in self._state.mappings.items() if key[0] != rule_id
        }
        self._state.cursors.pop(rule_id, None)
        self._state.destination_cursors.pop(rule_id, None)
        self._state.outcomes = {
            key: outcome for key, outcome in self._state.outcomes.items() if key[0] != rule_id
        }
```

In `InMemoryEventMappingRepository`:

```python
    def count_for_rule(self, rule_id: SyncRuleId) -> int:
        return sum(1 for key in self._state.mappings if key[0] == rule_id)
```

In `oauth.py`, `SqliteConnectedAccountStore`:

```python
    def is_connected(self, account_id: ConnectedAccountId) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state FROM connected_accounts WHERE id = ?", (account_id.value,)
            ).fetchone()
        return row is not None and str(row["state"]) == "connected"
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest -q && .venv/bin/mypy`
Expected: all tests PASS, and mypy reports no issues.

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/application/ports.py src/calendar_sync/infrastructure tests/adapters
git commit -m "feat: persist reprojection state, run outcomes, and rule removal"
```

---

### Task 3: Shared rule locks, reprojection, and run outcomes in synchronization and reconciliation

**Files:**
- Create: `src/calendar_sync/application/locking.py`
- Modify: `src/calendar_sync/application/synchronization.py`, `src/calendar_sync/application/reconciliation.py`, `src/calendar_sync/bootstrap/container.py` (the `ReconcileSyncRule` clock only)
- Test: `tests/application/test_execute_sync_rule.py`, `tests/application/test_reconcile_sync_rule.py`

**Interfaces:**
- Consumes the Task 1 flag and methods, and the Task 2 `uow.run_outcomes`, `RuleRunOutcome`, and `RunKind`.
- Produces `RuleLocks.for_rule(rule_id: SyncRuleId) -> threading.Lock`. It also produces `ExecuteSyncRule(unit_of_work, provider, decisions, fingerprinter, clock, locks: RuleLocks = RuleLocks())`, where `locks` is a dataclass field with `default_factory=RuleLocks`, and `ReconcileSyncRule(unit_of_work, provider, projector, reconciliation, clock)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/application/test_execute_sync_rule.py`)

```python
from pathlib import Path

from calendar_sync.application.ports import RunKind
from calendar_sync.domain.model import PrivacyPolicy, TransformationPolicy
from calendar_sync.infrastructure.persistence.sqlite import (
    SqliteUnitOfWorkFactory,
    initialize_database,
)

DETAILS = TransformationPolicy(privacy=PrivacyPolicy.COPY_DETAILS)


def _use_case(unit_of_work, provider) -> ExecuteSyncRule:  # type: ignore[no-untyped-def]
    fingerprinter = ProjectionFingerprinter()
    return ExecuteSyncRule(
        unit_of_work,
        provider,
        SyncDecisionService(EventProjector(), fingerprinter),
        fingerprinter,
        FixedClock(),
    )


def _mapped_busy_projection(provider: FakeCalendarProvider, source: CalendarEvent) -> EventMapping:
    provider.destination = replace(
        event("managed-destination", calendar=rule().destination, title="Busy"),
        description="",
        location="",
        managed_origin=ManagedOrigin(rule().id, source.reference),
    )
    return EventMapping(
        EventMappingId("mapping-1"),
        rule().id,
        source.reference,
        provider.destination.reference,
        source.revision,
        ProjectionFingerprint("busy-fingerprint"),
    )


def test_policy_change_reprojects_mappings_outside_the_window_and_clears_the_flag() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    changed = replace(rule().change_policy(DETAILS), state=SyncRuleState.ENABLED)
    unit_of_work.state.rules[rule().id] = changed
    unit_of_work.state.cursors[rule().id] = "source-before"
    unit_of_work.state.destination_cursors[rule().id] = "destination-before"
    source = event()
    provider = FakeCalendarProvider(source)
    provider.source_changes = ()  # the source ended before the Initial Sync Window
    mapping = _mapped_busy_projection(provider, source)
    unit_of_work.state.mappings[(rule().id, source.reference)] = mapping

    result = _use_case(unit_of_work, provider).execute(rule().id)

    assert provider.requested_cursors == [None, None]
    assert result.updated == 1
    assert provider.destination is not None
    assert provider.destination.title == "Private appointment"
    assert unit_of_work.state.rules[rule().id].reprojection_required is False
    outcome = unit_of_work.state.outcomes[(rule().id, RunKind.SYNC)]
    assert outcome.succeeded and outcome.full_run and outcome.updated == 1


def test_unverifiable_source_during_reprojection_is_a_conflict_not_a_deletion() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = replace(
        rule().change_policy(DETAILS), state=SyncRuleState.ENABLED
    )
    mapped_source = event("vanished-source")
    provider = FakeCalendarProvider(event("unrelated"))
    provider.source_changes = ()
    unit_of_work.state.mappings[(rule().id, mapped_source.reference)] = _mapped_busy_projection(
        provider, mapped_source
    )

    result = _use_case(unit_of_work, provider).execute(rule().id)

    assert result.conflicts == 1
    assert provider.deleted == 0
    assert (rule().id, mapped_source.reference) in unit_of_work.state.mappings
    assert unit_of_work.state.audit[-1].outcome == "blocked"


def test_edit_during_a_run_keeps_reprojection_pending(tmp_path: Path) -> None:
    database = tmp_path / "calendar-sync.db"
    initialize_database(database)
    factory = SqliteUnitOfWorkFactory(database)
    with factory() as uow:
        uow.rules.add(replace(rule().change_policy(DETAILS), state=SyncRuleState.ENABLED))
        uow.commit()

    class EditingProvider(FakeCalendarProvider):
        edited = False

        def changes(self, source, cursor, not_ended_before):  # type: ignore[no-untyped-def]
            if not self.edited:
                self.edited = True
                with factory() as concurrent:
                    current = concurrent.rules.get(rule().id)
                    assert current is not None
                    concurrent.rules.save(current.change_policy(TransformationPolicy()))
                    concurrent.commit()
            return super().changes(source, cursor, not_ended_before)

    provider = EditingProvider(event())
    provider.source_changes = ()

    _use_case(factory, provider).execute(rule().id)

    with factory() as uow:
        current = uow.rules.get(rule().id)
    assert current is not None
    assert current.reprojection_required is True
    assert current.state is SyncRuleState.PAUSED


def test_changed_rule_does_not_synchronize_until_enabled_again() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule().change_policy(DETAILS)

    with pytest.raises(RuleNotExecutable):
        _use_case(unit_of_work, FakeCalendarProvider(event())).execute(rule().id)
    assert unit_of_work.state.outcomes == {}


def test_failed_run_records_failure_kind_without_detail() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    provider = FakeCalendarProvider(event())
    provider.failure = ProviderFailure(ProviderFailureKind.RATE_LIMIT, "quota for person@x")

    with pytest.raises(ProviderFailure):
        _use_case(unit_of_work, provider).execute(rule().id)

    outcome = unit_of_work.state.outcomes[(rule().id, RunKind.SYNC)]
    assert outcome.succeeded is False
    assert outcome.failure_kind == "rate_limit"
```

Append to `tests/application/test_reconcile_sync_rule.py`. Also add `FixedClock()` as the last constructor argument in that file's existing `ReconcileSyncRule(...)` calls, and import `FixedClock` from `tests.application.test_execute_sync_rule`:

```python
def test_reconciliation_records_its_outcome() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    provider = FakeCalendarProvider(event())
    fingerprinter = ProjectionFingerprinter()

    report = ReconcileSyncRule(
        unit_of_work, provider, EventProjector(), ReconciliationService(fingerprinter), FixedClock()
    ).execute(rule().id)

    outcome = unit_of_work.state.outcomes[(rule().id, RunKind.RECONCILIATION)]
    assert outcome.succeeded is True
    assert outcome.checked_mappings == report.checked_mappings
    assert outcome.drift == len(report.drift)
```

(If `test_reconcile_sync_rule.py` defines its own provider or clock fixtures, use those instead of importing.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/application -q`
Expected: FAIL. The flag is not honored, and `outcomes` is empty.

- [ ] **Step 3: Implement**

`src/calendar_sync/application/locking.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from calendar_sync.domain.model import SyncRuleId


@dataclass(slots=True)
class RuleLocks:
    """Serializes every operation that writes on behalf of one Directional Sync Rule."""

    _locks: dict[SyncRuleId, Lock] = field(default_factory=dict)
    _guard: Lock = field(default_factory=Lock)

    def for_rule(self, rule_id: SyncRuleId) -> Lock:
        with self._guard:
            return self._locks.setdefault(rule_id, Lock())
```

Make these changes in `synchronization.py`:
- Remove `_rule_locks`, `_locks_guard`, and `_rule_lock`.
- Add the field `locks: RuleLocks = field(default_factory=RuleLocks)` after `clock`.
- Import `contextlib.suppress`, `ProviderFailure`, `ProviderFailureKind`, `RuleRunOutcome`, `RunKind`, and `RuleLocks`.

```python
    def execute(self, rule_id: SyncRuleId, *, full: bool = False) -> SyncRunResult:
        with self.locks.for_rule(rule_id):
            try:
                return self._execute_serialized(rule_id, full=full)
            except RuleNotExecutable:
                raise
            except ProviderFailure as failure:
                self._record_failure(rule_id, full, failure.kind.value)
                raise
            except Exception:
                self._record_failure(rule_id, full, ProviderFailureKind.INFRASTRUCTURE.value)
                raise

    def _record_failure(self, rule_id: SyncRuleId, full: bool, kind: str) -> None:
        # Recording evidence must never replace the failure the scheduler classifies.
        with suppress(Exception), self.unit_of_work() as uow:
            if uow.rules.get(rule_id) is not None:
                uow.run_outcomes.record(
                    RuleRunOutcome(
                        rule_id, RunKind.SYNC, self.clock.now(), False, full, failure_kind=kind
                    )
                )
                uow.commit()
```

In `_execute_serialized`, set `reproject = rule.reprojection_required` and `full_run = full or reproject`. Use `full_run` for both cursor reads. Keep a `handled: set[EventRef]`, and add `source_event.reference` after each source-batch event and `mapping.source` after each destination repair. Before saving the cursors, insert the sweep:

```python
            if reproject:
                for mapping in uow.mappings.for_rule(rule.id):
                    if mapping.source in handled:
                        continue
                    authoritative_source = self.provider.get_event(mapping.source)
                    if authoritative_source is None:
                        counts[SyncAction.CONFLICT] += 1
                        uow.audit.append(
                            AuditEntry(
                                occurred_at=self.clock.now(),
                                rule_id=rule.id,
                                action=SyncAction.CONFLICT.value,
                                outcome="blocked",
                                source_event_id=mapping.source.event_id.value,
                                destination_event_id=mapping.destination.event_id.value,
                                detail="source could not be verified during reprojection",
                            )
                        )
                        uow.commit()
                        continue
                    self._synchronize_event(
                        uow,
                        rule,
                        authoritative_source,
                        counts,
                        destination_loaded=False,
                        actual_destination=None,
                    )
                    uow.commit()
```

Replace the final cursor block with the following:

```python
            uow.cursors.save(rule.id, changes.next_cursor)
            uow.destination_cursors.save(rule.id, destination_changes.next_cursor)
            if reproject:
                current = uow.rules.get(rule.id)
                if (
                    current is not None
                    and current.reprojection_required
                    and current.material_signature == rule.material_signature
                ):
                    uow.rules.save(current.complete_reprojection())
            uow.run_outcomes.record(
                RuleRunOutcome(
                    rule.id,
                    RunKind.SYNC,
                    self.clock.now(),
                    True,
                    full_run,
                    created=counts[SyncAction.CREATE],
                    updated=counts[SyncAction.UPDATE],
                    deleted=counts[SyncAction.DELETE],
                    conflicts=counts[SyncAction.CONFLICT],
                )
            )
            uow.commit()
```

In `reconciliation.py`, add the field `clock: Clock`. Wrap the provider work so that a `ProviderFailure` records `RuleRunOutcome(rule.id, RunKind.RECONCILIATION, now, False, failure_kind=failure.kind.value)` and re-raises. On success, record the following:

```python
        report = self.reconciliation.reconcile(rule, mappings, expected, actual)
        with self.unit_of_work() as uow:
            uow.run_outcomes.record(
                RuleRunOutcome(
                    rule.id,
                    RunKind.RECONCILIATION,
                    self.clock.now(),
                    True,
                    full_run=True,
                    checked_mappings=report.checked_mappings,
                    drift=len(report.drift),
                )
            )
            uow.commit()
        return report
```

In `container.py`, pass `SystemClock()` as the fifth argument to `ReconcileSyncRule(...)`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest -q && .venv/bin/mypy && .venv/bin/ruff check .`
Expected: PASS. The existing `test_execute_sync_rule.py` concurrency test still passes, because the per-rule lock behaves the same.

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/application src/calendar_sync/bootstrap/container.py tests/application
git commit -m "feat: reproject managed projections after a material rule change"
```

---

### Task 4: `ChangeSyncRulePolicy` and `GetSyncRuleDetails`

**Files:**
- Modify: `src/calendar_sync/application/errors.py`, `src/calendar_sync/application/rules.py`
- Test: `tests/application/test_rules.py` (create)

**Interfaces:**
- Consumes Tasks 1 and 2.
- Produces the following:
  - `RuleNotFound(ApplicationError)`.
  - `ChangeSyncRulePolicy(unit_of_work, clock).execute(rule_id: SyncRuleId, privacy: PrivacyPolicy, all_day: AllDaySyncPolicy) -> SyncRule`.
  - `SyncRuleDetails(rule: SyncRule, mapping_count: int, last_sync: RuleRunOutcome | None, last_reconciliation: RuleRunOutcome | None)`.
  - `GetSyncRuleDetails(unit_of_work).execute(rule_id) -> SyncRuleDetails`.

- [ ] **Step 1: Write the failing tests** in `tests/application/test_rules.py`

```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from calendar_sync.application.errors import RuleNotFound
from calendar_sync.application.ports import RuleRunOutcome, RunKind
from calendar_sync.application.rules import ChangeSyncRulePolicy, GetSyncRuleDetails
from calendar_sync.domain.errors import InvalidStateTransition
from calendar_sync.domain.model import (
    AllDaySyncPolicy,
    PrivacyPolicy,
    SyncRuleId,
    SyncRuleState,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.helpers import NOW, rule


class FixedClock:
    def now(self) -> datetime:
        return NOW


def test_changing_an_enabled_rule_pauses_it_and_audits_without_google_writes() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.ENABLED)

    changed = ChangeSyncRulePolicy(unit_of_work, FixedClock()).execute(
        rule().id, PrivacyPolicy.COPY_DETAILS, AllDaySyncPolicy.INCLUDE
    )

    stored = unit_of_work.state.rules[rule().id]
    assert stored == changed
    assert stored.state is SyncRuleState.PAUSED
    assert stored.reprojection_required is True
    assert unit_of_work.state.audit[-1].action == "policy_changed"
    assert unit_of_work.state.audit[-1].detail == "privacy=copy_details, all_day=include"


def test_saving_the_same_policy_keeps_the_rule_enabled() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.ENABLED)

    unchanged = ChangeSyncRulePolicy(unit_of_work, FixedClock()).execute(
        rule().id, PrivacyPolicy.BUSY_ONLY, AllDaySyncPolicy.INCLUDE
    )

    assert unchanged.state is SyncRuleState.ENABLED
    assert unit_of_work.state.audit == []


def test_policy_change_is_blocked_for_missing_or_removing_rules() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule(state=SyncRuleState.DISABLED)
    use_case = ChangeSyncRulePolicy(unit_of_work, FixedClock())

    with pytest.raises(RuleNotFound):
        use_case.execute(SyncRuleId("missing"), PrivacyPolicy.BUSY_ONLY, AllDaySyncPolicy.INCLUDE)
    with pytest.raises(InvalidStateTransition):
        use_case.execute(rule().id, PrivacyPolicy.COPY_DETAILS, AllDaySyncPolicy.INCLUDE)


def test_details_report_mapping_count_and_latest_outcomes() -> None:
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule()
    synced = RuleRunOutcome(rule().id, RunKind.SYNC, datetime(2026, 9, 1, tzinfo=UTC), True)
    unit_of_work.state.outcomes[(rule().id, RunKind.SYNC)] = synced

    details = GetSyncRuleDetails(unit_of_work).execute(rule().id)

    assert details.rule == rule()
    assert details.mapping_count == 0
    assert details.last_sync == synced
    assert details.last_reconciliation is None
    with pytest.raises(RuleNotFound):
        GetSyncRuleDetails(unit_of_work).execute(SyncRuleId("missing"))
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/application/test_rules.py -q`
Expected: FAIL with an `ImportError` for `RuleNotFound`.

- [ ] **Step 3: Implement**

`errors.py`:

```python
class RuleNotFound(ApplicationError):
    """The requested Directional Sync Rule does not exist."""
```

`rules.py` (keep `CreateSyncRule`):

```python
from dataclasses import dataclass, replace

from calendar_sync.application.errors import DuplicateDirectionalRelationship, RuleNotFound
from calendar_sync.application.ports import (
    AuditEntry,
    Clock,
    RuleRunOutcome,
    RunKind,
    UnitOfWorkFactory,
)
from calendar_sync.domain.model import AllDaySyncPolicy, PrivacyPolicy, SyncRule, SyncRuleId


@dataclass(slots=True)
class ChangeSyncRulePolicy:
    """Saves a Material Rule Change without writing to any calendar provider."""

    unit_of_work: UnitOfWorkFactory
    clock: Clock

    def execute(
        self, rule_id: SyncRuleId, privacy: PrivacyPolicy, all_day: AllDaySyncPolicy
    ) -> SyncRule:
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if rule is None:
                raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
            changed = rule.change_policy(
                replace(rule.transformation, privacy=privacy, all_day=all_day)
            )
            if changed == rule:
                return rule
            uow.rules.save(changed)
            uow.audit.append(
                AuditEntry(
                    occurred_at=self.clock.now(),
                    rule_id=rule.id,
                    action="policy_changed",
                    outcome="completed",
                    detail=f"privacy={privacy.value}, all_day={all_day.value}",
                )
            )
            uow.commit()
        return changed


@dataclass(frozen=True, slots=True)
class SyncRuleDetails:
    rule: SyncRule
    mapping_count: int
    last_sync: RuleRunOutcome | None
    last_reconciliation: RuleRunOutcome | None


@dataclass(slots=True)
class GetSyncRuleDetails:
    unit_of_work: UnitOfWorkFactory

    def execute(self, rule_id: SyncRuleId) -> SyncRuleDetails:
        with self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if rule is None:
                raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
            return SyncRuleDetails(
                rule=rule,
                mapping_count=uow.mappings.count_for_rule(rule_id),
                last_sync=uow.run_outcomes.latest(rule_id, RunKind.SYNC),
                last_reconciliation=uow.run_outcomes.latest(rule_id, RunKind.RECONCILIATION),
            )
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/application -q && .venv/bin/mypy`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/application tests/application/test_rules.py
git commit -m "feat: change rule policy as a material rule change and read rule details"
```

---

### Task 5: `RemoveSyncRule` and `ReplaceSyncRuleCalendars`

**Files:**
- Create: `src/calendar_sync/application/removal.py`, `src/calendar_sync/infrastructure/identifiers.py`
- Modify: `src/calendar_sync/application/errors.py`, `src/calendar_sync/application/rules.py`
- Test: `tests/application/test_remove_sync_rule.py` (create)

**Interfaces:**
- Consumes `RuleLocks` (Task 3), the `uow.rules.remove` and `AccountAuthorizations` ports (Task 2), `ProjectionHandling` and `begin_removal` (Task 1), `CreateSyncRule`, and `RuleNotFound` (Task 4).
- Produces the following:
  - `RemovalResult(deleted: int, detached: int)`.
  - `RemoveSyncRule(unit_of_work, provider: CalendarProvider | None, accounts: AccountAuthorizations | None, clock, locks: RuleLocks).execute(rule_id, handling: ProjectionHandling) -> RemovalResult`.
  - `RuleReplacement(rule: SyncRule, removal: RemovalResult)`.
  - `ReplaceSyncRuleCalendars(unit_of_work, remove_rule: RemoveSyncRule, create_rule: CreateSyncRule, ids: IdGenerator).execute(rule_id, source: CalendarEndpoint, destination: CalendarEndpoint, handling) -> RuleReplacement`.
  - The errors `NotACalendarChange`, `RemovalRequiresProvider`, `RemovalRequiresAuthorization`, and `RemovalInterrupted(processed: int, remaining: int, failure: ProviderFailure)`.
  - `UuidIdGenerator().new() -> str`.

- [ ] **Step 1: Write the failing tests** in `tests/application/test_remove_sync_rule.py`

```python
from __future__ import annotations

from dataclasses import replace

import pytest

from calendar_sync.application.errors import (
    DuplicateDirectionalRelationship,
    NotACalendarChange,
    ProviderFailure,
    ProviderFailureKind,
    RemovalInterrupted,
    RemovalRequiresAuthorization,
    RemovalRequiresProvider,
)
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.removal import RemoveSyncRule
from calendar_sync.application.rules import CreateSyncRule, ReplaceSyncRuleCalendars
from calendar_sync.domain.model import (
    ConnectedAccountId,
    EventId,
    EventMapping,
    EventMappingId,
    EventRef,
    PrivacyPolicy,
    ProjectionFingerprint,
    ProjectionHandling,
    SyncRule,
    SyncRuleId,
    SyncRuleState,
    TransformationPolicy,
)
from calendar_sync.infrastructure.persistence.memory import InMemoryUnitOfWorkFactory
from tests.application.test_execute_sync_rule import FakeCalendarProvider, FixedClock
from tests.helpers import endpoint, event, rule


class Accounts:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected

    def is_connected(self, account_id: ConnectedAccountId) -> bool:
        return self.connected


class RecordingProvider(FakeCalendarProvider):
    def __init__(self, fail_on_call: int | None = None) -> None:
        super().__init__(event())
        self.deleted_refs: list[EventRef] = []
        self.fail_on_call = fail_on_call

    def delete_projection(self, destination, source, rule_id, operation_key):  # type: ignore[no-untyped-def]
        if self.fail_on_call is not None and len(self.deleted_refs) + 1 == self.fail_on_call:
            raise ProviderFailure(ProviderFailureKind.AUTHORIZATION, "denied")
        self.deleted_refs.append(destination)


class Ids:
    def new(self) -> str:
        return "replacement-rule"


def _with_mappings(count: int, state: SyncRuleState = SyncRuleState.ENABLED):  # type: ignore[no-untyped-def]
    unit_of_work = InMemoryUnitOfWorkFactory()
    unit_of_work.state.rules[rule().id] = rule(state=state)
    for index in range(count):
        source = EventRef(rule().source, EventId(f"source-{index}"))
        unit_of_work.state.mappings[(rule().id, source)] = EventMapping(
            EventMappingId(f"mapping-{index}"),
            rule().id,
            source,
            EventRef(rule().destination, EventId(f"destination-{index}")),
            "revision-1",
            ProjectionFingerprint("fingerprint"),
        )
    return unit_of_work


def _remover(unit_of_work, provider=None, accounts=None) -> RemoveSyncRule:  # type: ignore[no-untyped-def]
    return RemoveSyncRule(
        unit_of_work,
        provider if provider is not None else RecordingProvider(),
        accounts if accounts is not None else Accounts(),
        FixedClock(),
        RuleLocks(),
    )


def test_delete_removes_each_mapped_projection_then_the_rule() -> None:
    unit_of_work = _with_mappings(2)
    provider = RecordingProvider()

    result = _remover(unit_of_work, provider).execute(rule().id, ProjectionHandling.DELETE)

    assert (result.deleted, result.detached) == (2, 0)
    assert len(provider.deleted_refs) == 2
    assert unit_of_work.state.rules == {}
    assert unit_of_work.state.mappings == {}
    assert [entry.action for entry in unit_of_work.state.audit] == [
        "remove_projection",
        "remove_projection",
        "rule_removed",
    ]


def test_detach_makes_no_provider_calls_even_without_authorization() -> None:
    unit_of_work = _with_mappings(2)
    provider = RecordingProvider()

    result = RemoveSyncRule(
        unit_of_work, None, None, FixedClock(), RuleLocks()
    ).execute(rule().id, ProjectionHandling.DETACH)

    assert (result.deleted, result.detached) == (0, 2)
    assert provider.deleted_refs == []
    assert unit_of_work.state.rules == {}


def test_delete_is_blocked_when_destination_is_disconnected_or_provider_missing() -> None:
    unit_of_work = _with_mappings(1)

    with pytest.raises(RemovalRequiresAuthorization):
        _remover(unit_of_work, accounts=Accounts(connected=False)).execute(
            rule().id, ProjectionHandling.DELETE
        )
    with pytest.raises(RemovalRequiresProvider):
        RemoveSyncRule(unit_of_work, None, None, FixedClock(), RuleLocks()).execute(
            rule().id, ProjectionHandling.DELETE
        )
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.ENABLED
    assert len(unit_of_work.state.mappings) == 1


def test_interrupted_delete_leaves_rule_inert_and_retry_completes() -> None:
    unit_of_work = _with_mappings(3)

    with pytest.raises(RemovalInterrupted) as interrupted:
        _remover(unit_of_work, RecordingProvider(fail_on_call=2)).execute(
            rule().id, ProjectionHandling.DELETE
        )

    assert (interrupted.value.processed, interrupted.value.remaining) == (1, 2)
    assert unit_of_work.state.rules[rule().id].state is SyncRuleState.DISABLED
    assert len(unit_of_work.state.mappings) == 2

    result = _remover(unit_of_work).execute(rule().id, ProjectionHandling.DETACH)

    assert result.detached == 2
    assert unit_of_work.state.rules == {}


def test_replacement_rejects_a_duplicate_relationship_before_removing_anything() -> None:
    unit_of_work = _with_mappings(1)
    new_destination = endpoint("work-account", "other-calendar")
    unit_of_work.state.rules[SyncRuleId("existing")] = SyncRule(
        SyncRuleId("existing"), rule().source, new_destination
    )
    provider = RecordingProvider()
    replace_rule = ReplaceSyncRuleCalendars(
        unit_of_work, _remover(unit_of_work, provider), CreateSyncRule(unit_of_work), Ids()
    )

    with pytest.raises(DuplicateDirectionalRelationship):
        replace_rule.execute(rule().id, rule().source, new_destination, ProjectionHandling.DELETE)

    assert provider.deleted_refs == []
    assert rule().id in unit_of_work.state.rules


def test_replacement_rejects_unchanged_calendars() -> None:
    unit_of_work = _with_mappings(0)
    replace_rule = ReplaceSyncRuleCalendars(
        unit_of_work, _remover(unit_of_work), CreateSyncRule(unit_of_work), Ids()
    )

    with pytest.raises(NotACalendarChange):
        replace_rule.execute(
            rule().id, rule().source, rule().destination, ProjectionHandling.DELETE
        )


def test_replacement_removes_the_rule_and_creates_a_draft_with_the_same_policy() -> None:
    unit_of_work = _with_mappings(1)
    details = TransformationPolicy(privacy=PrivacyPolicy.COPY_DETAILS)
    unit_of_work.state.rules[rule().id] = replace(rule(), transformation=details)
    new_destination = endpoint("work-account", "other-calendar")
    replace_rule = ReplaceSyncRuleCalendars(
        unit_of_work, _remover(unit_of_work), CreateSyncRule(unit_of_work), Ids()
    )

    replacement = replace_rule.execute(
        rule().id, rule().source, new_destination, ProjectionHandling.DETACH
    )

    assert replacement.removal.detached == 1
    assert list(unit_of_work.state.rules) == [SyncRuleId("replacement-rule")]
    assert replacement.rule.state is SyncRuleState.DRAFT
    assert replacement.rule.transformation == details
    assert replacement.rule.destination == new_destination
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/application/test_remove_sync_rule.py -q`
Expected: FAIL with an `ImportError`.

- [ ] **Step 3: Implement**

`errors.py` additions:

```python
class NotACalendarChange(ApplicationError):
    """A Rule Replacement was requested with the rule's current calendars."""


class RemovalRequiresProvider(ApplicationError):
    """Deleting projections needs a configured Google adapter."""


class RemovalRequiresAuthorization(ApplicationError):
    """Deleting projections needs an authorized destination account."""


@dataclass(frozen=True, slots=True)
class RemovalInterrupted(ApplicationError):
    processed: int
    remaining: int
    failure: ProviderFailure

    def __str__(self) -> str:
        total = self.processed + self.remaining
        return (
            f"removal stopped after {self.processed} of {total} projections because Google "
            f"reported {self.failure.kind.value}; retry to continue"
        )
```

(Place `RemovalInterrupted` after `ProviderFailure`.)

`src/calendar_sync/application/removal.py`:

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from calendar_sync.application.errors import (
    ProviderFailure,
    RemovalInterrupted,
    RemovalRequiresAuthorization,
    RemovalRequiresProvider,
    RuleNotFound,
)
from calendar_sync.application.locking import RuleLocks
from calendar_sync.application.ports import (
    AccountAuthorizations,
    AuditEntry,
    CalendarProvider,
    Clock,
    UnitOfWorkFactory,
)
from calendar_sync.domain.model import EventMapping, ProjectionHandling, SyncRuleId


@dataclass(frozen=True, slots=True)
class RemovalResult:
    deleted: int
    detached: int


@dataclass(slots=True)
class RemoveSyncRule:
    """Permanently removes a rule after deleting or detaching its mapped projections."""

    unit_of_work: UnitOfWorkFactory
    provider: CalendarProvider | None
    accounts: AccountAuthorizations | None
    clock: Clock
    locks: RuleLocks

    def execute(self, rule_id: SyncRuleId, handling: ProjectionHandling) -> RemovalResult:
        with self.locks.for_rule(rule_id), self.unit_of_work() as uow:
            rule = uow.rules.get(rule_id)
            if rule is None:
                raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
            if handling is ProjectionHandling.DELETE:
                if self.provider is None or self.accounts is None:
                    raise RemovalRequiresProvider(
                        "configure Google OAuth and the installation master key before "
                        "deleting projections"
                    )
                if not self.accounts.is_connected(rule.destination.connected_account_id):
                    raise RemovalRequiresAuthorization(
                        "reauthorize the destination account before deleting projections, "
                        "or keep them as detached events"
                    )
            uow.rules.save(rule.begin_removal())
            uow.commit()

            mappings = uow.mappings.for_rule(rule.id)
            deleted = 0
            for mapping in mappings:
                if handling is ProjectionHandling.DELETE:
                    assert self.provider is not None
                    try:
                        self.provider.delete_projection(
                            mapping.destination,
                            mapping.source,
                            rule.id,
                            _operation_key(mapping),
                        )
                    except ProviderFailure as failure:
                        raise RemovalInterrupted(
                            deleted, len(mappings) - deleted, failure
                        ) from failure
                    deleted += 1
                uow.mappings.delete(mapping)
                uow.audit.append(self._projection_entry(mapping, handling))
                if handling is ProjectionHandling.DELETE:
                    uow.commit()

            detached = len(mappings) - deleted
            uow.rules.remove(rule.id)
            uow.audit.append(
                AuditEntry(
                    occurred_at=self.clock.now(),
                    rule_id=rule.id,
                    action="rule_removed",
                    outcome="completed",
                    detail=f"{deleted} projections deleted, {detached} kept as detached events",
                )
            )
            uow.commit()
        return RemovalResult(deleted, detached)

    def _projection_entry(self, mapping: EventMapping, handling: ProjectionHandling) -> AuditEntry:
        deleting = handling is ProjectionHandling.DELETE
        return AuditEntry(
            occurred_at=self.clock.now(),
            rule_id=mapping.rule_id,
            action="remove_projection" if deleting else "detach_projection",
            outcome="completed",
            source_event_id=mapping.source.event_id.value,
            destination_event_id=mapping.destination.event_id.value,
            detail=(
                "managed projection deleted during rule removal"
                if deleting
                else "mapping removed; projection kept as a detached event"
            ),
        )


def _operation_key(mapping: EventMapping) -> str:
    raw = "|".join((mapping.rule_id.value, mapping.id.value, "remove"))
    return hashlib.sha256(raw.encode()).hexdigest()
```

Append to `rules.py`:

```python
@dataclass(frozen=True, slots=True)
class RuleReplacement:
    rule: SyncRule
    removal: RemovalResult


@dataclass(slots=True)
class ReplaceSyncRuleCalendars:
    """Rule Replacement: Rule Removal followed by a new Draft with the same policy."""

    unit_of_work: UnitOfWorkFactory
    remove_rule: RemoveSyncRule
    create_rule: CreateSyncRule
    ids: IdGenerator

    def execute(
        self,
        rule_id: SyncRuleId,
        source: CalendarEndpoint,
        destination: CalendarEndpoint,
        handling: ProjectionHandling,
    ) -> RuleReplacement:
        with self.unit_of_work() as uow:
            current = uow.rules.get(rule_id)
            if current is None:
                raise RuleNotFound(f"sync rule {rule_id.value} does not exist")
            duplicate = uow.rules.relationship_exists(source, destination)
        if (source, destination) == (current.source, current.destination):
            raise NotACalendarChange("the calendars are unchanged; edit the policy instead")
        replacement = SyncRule(
            id=SyncRuleId(self.ids.new()),
            source=source,
            destination=destination,
            transformation=current.transformation,
            initial_lookback_days=current.initial_lookback_days,
        )
        if duplicate:
            raise DuplicateDirectionalRelationship(
                "a rule already exists for this source and destination"
            )
        removal = self.remove_rule.execute(rule_id, handling)
        self.create_rule.execute(replacement)
        return RuleReplacement(replacement, removal)
```

The imports in `rules.py` add `NotACalendarChange`, `IdGenerator`, `RemovalResult` and `RemoveSyncRule` from `calendar_sync.application.removal`, plus `CalendarEndpoint` and `ProjectionHandling`.

`src/calendar_sync/infrastructure/identifiers.py`:

```python
import uuid


class UuidIdGenerator:
    def new(self) -> str:
        return str(uuid.uuid4())
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/application -q && .venv/bin/mypy && .venv/bin/ruff check .`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync/application src/calendar_sync/infrastructure/identifiers.py tests/application/test_remove_sync_rule.py
git commit -m "feat: add rule removal and calendar replacement use cases"
```

---

### Task 6: Container wiring and HTTP routes

**Files:**
- Modify: `src/calendar_sync/bootstrap/container.py`, `src/calendar_sync/interfaces/api/schemas.py`, `src/calendar_sync/interfaces/api/app.py`
- Test: `tests/adapters/test_api.py`

**Interfaces:**
- Consumes Tasks 3 through 5.
- Produces these `Container` fields: `rule_locks: RuleLocks`, `change_sync_rule_policy: ChangeSyncRulePolicy`, `get_sync_rule_details: GetSyncRuleDetails`, `remove_sync_rule: RemoveSyncRule`, and `replace_sync_rule_calendars: ReplaceSyncRuleCalendars`. These are always constructed, and the provider or accounts is `None` without a master key.
- Produces these JSON shapes:
  - `RuleResponse` adds `reprojection_required: bool`.
  - `RuleDetailResponse(RuleResponse)` adds `initial_lookback_days: int`, `mapping_count: int`, `last_sync: RunOutcomeResponse | None`, and `last_reconciliation: RunOutcomeResponse | None`.
  - `RunOutcomeResponse` has `completed_at: str`, `succeeded: bool`, `full_run: bool`, `created: int`, `updated: int`, `deleted: int`, `conflicts: int`, `checked_mappings: int`, `drift: int`, and `failure_kind: str | None`.
  - `RemovalResponse` has `deleted: int` and `detached: int`.
  - `RuleReplacementResponse` has `rule: RuleResponse`, `deleted: int`, and `detached: int`.

- [ ] **Step 1: Write the failing tests** (append to `tests/adapters/test_api.py`)

```python
PASSWORD = {"password": "correct horse battery staple"}


def _client_with_rule(tmp_path: Path, state: SyncRuleState = SyncRuleState.ENABLED) -> TestClient:
    container = build_container(Settings(tmp_path / "test.db"))
    with container.unit_of_work() as uow:
        uow.rules.add(rule(state=state))
        uow.commit()
    return TestClient(create_app(container))


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/rules/rule-1"),
        ("PATCH", "/api/v1/rules/rule-1"),
        ("DELETE", "/api/v1/rules/rule-1?projections=detach"),
        ("POST", "/api/v1/rules/rule-1/replace"),
    ],
)
def test_rule_management_routes_require_an_administrator(
    tmp_path: Path, method: str, path: str
) -> None:
    with _client_with_rule(tmp_path) as client:
        assert client.request(method, path, json={}).status_code == 401


def test_rule_details_include_policy_state_mapping_count_and_outcomes(tmp_path: Path) -> None:
    with _client_with_rule(tmp_path) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        details = client.get("/api/v1/rules/rule-1")
        missing = client.get("/api/v1/rules/missing")

    assert details.status_code == 200
    assert details.json()["initial_lookback_days"] == 30
    assert details.json()["mapping_count"] == 0
    assert details.json()["reprojection_required"] is False
    assert details.json()["last_sync"] is None
    assert missing.status_code == 404


def test_policy_edit_pauses_rule_and_blocks_enable_until_previewed(tmp_path: Path) -> None:
    with _client_with_rule(tmp_path) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        edited = client.patch(
            "/api/v1/rules/rule-1",
            json={"privacy_policy": "copy_details", "sync_all_day_events": True},
        )
        enable = client.post("/api/v1/rules/rule-1/enable")
        unknown = client.patch(
            "/api/v1/rules/rule-1",
            json={"privacy_policy": "everything", "sync_all_day_events": True},
        )

    assert edited.status_code == 200
    assert edited.json()["state"] == "paused"
    assert edited.json()["privacy_policy"] == "copy_details"
    assert edited.json()["reprojection_required"] is True
    assert enable.status_code == 409
    assert unknown.status_code == 422


def test_rule_removal_requires_an_explicit_choice_and_detach_removes_the_rule(
    tmp_path: Path,
) -> None:
    with _client_with_rule(tmp_path) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        unspecified = client.delete("/api/v1/rules/rule-1")
        delete_without_google = client.delete("/api/v1/rules/rule-1?projections=delete")
        detached = client.delete("/api/v1/rules/rule-1?projections=detach")
        after = client.get("/api/v1/rules/rule-1")

    assert unspecified.status_code == 422
    assert delete_without_google.status_code == 503
    assert detached.status_code == 200
    assert detached.json() == {"deleted": 0, "detached": 0}
    assert after.status_code == 404


def test_delete_removal_is_blocked_for_a_disconnected_destination(tmp_path: Path) -> None:
    container = replace(
        build_container(Settings(tmp_path / "test.db", master_key=CredentialCipher.generate_key())),
        scheduler=None,
    )
    assert container.connected_accounts is not None
    account = container.connected_accounts.save(
        "Work", "work@example.test", '{"refresh_token":"synthetic-secret"}'
    )
    container.connected_accounts.disconnect(account.id)
    with container.unit_of_work() as uow:
        uow.rules.add(
            SyncRule(
                SyncRuleId("rule-1"),
                endpoint("personal", "personal-calendar"),
                endpoint(account.id.value, "work-calendar"),
                state=SyncRuleState.PAUSED,
            )
        )
        uow.commit()

    with TestClient(create_app(container)) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        blocked = client.delete("/api/v1/rules/rule-1?projections=delete")
        state = client.get("/api/v1/rules/rule-1").json()["state"]

    assert blocked.status_code == 409
    assert state == "paused"


def test_replacement_creates_a_new_draft_and_rejects_unchanged_calendars(tmp_path: Path) -> None:
    unchanged = {
        "source": {"connected_account_id": "personal-account", "calendar_id": "personal-calendar"},
        "destination": {"connected_account_id": "work-account", "calendar_id": "work-calendar"},
        "projections": "detach",
    }
    changed = {
        **unchanged,
        "destination": {"connected_account_id": "work-account", "calendar_id": "team-calendar"},
    }
    with _client_with_rule(tmp_path) as client:
        client.post("/api/v1/setup/admin", json=PASSWORD)
        rejected = client.post("/api/v1/rules/rule-1/replace", json=unchanged)
        replaced = client.post("/api/v1/rules/rule-1/replace", json=changed)
        rules = client.get("/api/v1/rules").json()

    assert rejected.status_code == 422
    assert replaced.status_code == 201
    assert replaced.json()["rule"]["state"] == "draft"
    assert replaced.json()["rule"]["destination"]["calendar_id"] == "team-calendar"
    assert [item["id"] for item in rules] == [replaced.json()["rule"]["id"]]
```

Also extend the parametrized list in `test_frontend_fallback_serves_each_application_section` with `"/rules/rule-1"`.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/adapters/test_api.py -q`
Expected: FAIL with 405 or 404 on the new routes.

- [ ] **Step 3: Implement**

`schemas.py`:

```python
from typing import Literal

ProjectionChoice = Literal["delete", "detach"]


class RuleResponse(BaseModel):
    id: str
    source: CalendarEndpointPayload
    destination: CalendarEndpointPayload
    privacy_policy: str
    sync_all_day_events: bool
    state: str
    reprojection_required: bool


class RunOutcomeResponse(BaseModel):
    completed_at: str
    succeeded: bool
    full_run: bool
    created: int
    updated: int
    deleted: int
    conflicts: int
    checked_mappings: int
    drift: int
    failure_kind: str | None


class RuleDetailResponse(RuleResponse):
    initial_lookback_days: int
    mapping_count: int
    last_sync: RunOutcomeResponse | None
    last_reconciliation: RunOutcomeResponse | None


class UpdateRulePolicyRequest(BaseModel):
    privacy_policy: str
    sync_all_day_events: bool


class ReplaceRuleRequest(BaseModel):
    source: CalendarEndpointPayload
    destination: CalendarEndpointPayload
    projections: ProjectionChoice


class RemovalResponse(BaseModel):
    deleted: int
    detached: int


class RuleReplacementResponse(BaseModel):
    rule: RuleResponse
    deleted: int
    detached: int
```

Make these changes in `container.py`:
- Build `rule_locks = RuleLocks()` before the master-key branch.
- Pass `locks=rule_locks` to `ExecuteSyncRule`.
- Keep `provider: GoogleCalendarProvider | None = None`, assigned inside the branch.
- After the branch, add the following:

```python
    create_sync_rule = CreateSyncRule(unit_of_work)
    remove_sync_rule = RemoveSyncRule(unit_of_work, provider, accounts, SystemClock(), rule_locks)
```

Then pass these to `Container(...)`:

```python
        create_sync_rule=create_sync_rule,
        rule_locks=rule_locks,
        change_sync_rule_policy=ChangeSyncRulePolicy(unit_of_work, SystemClock()),
        get_sync_rule_details=GetSyncRuleDetails(unit_of_work),
        remove_sync_rule=remove_sync_rule,
        replace_sync_rule_calendars=ReplaceSyncRuleCalendars(
            unit_of_work, remove_sync_rule, create_sync_rule, UuidIdGenerator()
        ),
```

Add the fields to the `Container` dataclass after `create_sync_rule`.

In `app.py`, update `_rule_response` to include `reprojection_required=rule.reprojection_required`, and add the helpers and routes below, placed before the `static_directory` block:

```python
def _privacy(value: str) -> PrivacyPolicy:
    try:
        return PrivacyPolicy(value)
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown privacy policy") from error


def _outcome_response(outcome: RuleRunOutcome | None) -> RunOutcomeResponse | None:
    if outcome is None:
        return None
    return RunOutcomeResponse(
        completed_at=outcome.completed_at.isoformat(),
        succeeded=outcome.succeeded,
        full_run=outcome.full_run,
        created=outcome.created,
        updated=outcome.updated,
        deleted=outcome.deleted,
        conflicts=outcome.conflicts,
        checked_mappings=outcome.checked_mappings,
        drift=outcome.drift,
        failure_kind=outcome.failure_kind,
    )


def _removal_http_error(error: ApplicationError) -> HTTPException:
    if isinstance(error, RuleNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(error))
    if isinstance(error, RemovalRequiresProvider):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error))
    if isinstance(error, RemovalInterrupted):
        return HTTPException(status.HTTP_424_FAILED_DEPENDENCY, str(error))
    if isinstance(error, NotACalendarChange):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
    return HTTPException(status.HTTP_409_CONFLICT, str(error))
```

(`_removal_http_error` maps `RemovalRequiresAuthorization` and `DuplicateDirectionalRelationship` to 409.)

Inside `create_app`:

```python
    @app.get(
        "/api/v1/rules/{rule_id}",
        response_model=RuleDetailResponse,
        dependencies=[Depends(require_admin)],
    )
    def rule_details(rule_id: str) -> RuleDetailResponse:
        try:
            details = resolved.get_sync_rule_details.execute(SyncRuleId(rule_id))
        except RuleNotFound as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
        return RuleDetailResponse(
            **_rule_response(details.rule).model_dump(),
            initial_lookback_days=details.rule.initial_lookback_days,
            mapping_count=details.mapping_count,
            last_sync=_outcome_response(details.last_sync),
            last_reconciliation=_outcome_response(details.last_reconciliation),
        )

    @app.patch(
        "/api/v1/rules/{rule_id}",
        response_model=RuleResponse,
        dependencies=[Depends(require_admin)],
    )
    def change_rule_policy(rule_id: str, request: UpdateRulePolicyRequest) -> RuleResponse:
        privacy = _privacy(request.privacy_policy)
        all_day = (
            AllDaySyncPolicy.INCLUDE if request.sync_all_day_events else AllDaySyncPolicy.EXCLUDE
        )
        try:
            rule = resolved.change_sync_rule_policy.execute(SyncRuleId(rule_id), privacy, all_day)
        except RuleNotFound as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
        except InvalidStateTransition as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        return _rule_response(rule)

    @app.delete(
        "/api/v1/rules/{rule_id}",
        response_model=RemovalResponse,
        dependencies=[Depends(require_admin)],
    )
    async def remove_rule(rule_id: str, projections: ProjectionChoice) -> RemovalResponse:
        try:
            result = await asyncio.to_thread(
                resolved.remove_sync_rule.execute,
                SyncRuleId(rule_id),
                ProjectionHandling(projections),
            )
        except ApplicationError as error:
            raise _removal_http_error(error) from error
        return RemovalResponse(deleted=result.deleted, detached=result.detached)

    @app.post(
        "/api/v1/rules/{rule_id}/replace",
        response_model=RuleReplacementResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_admin)],
    )
    async def replace_rule_calendars(
        rule_id: str, request: ReplaceRuleRequest
    ) -> RuleReplacementResponse:
        try:
            replacement = await asyncio.to_thread(
                resolved.replace_sync_rule_calendars.execute,
                SyncRuleId(rule_id),
                _endpoint(request.source),
                _endpoint(request.destination),
                ProjectionHandling(request.projections),
            )
        except DomainValidationError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
        except ApplicationError as error:
            raise _removal_http_error(error) from error
        return RuleReplacementResponse(
            rule=_rule_response(replacement.rule),
            deleted=replacement.removal.deleted,
            detached=replacement.removal.detached,
        )
```

Also replace the inline privacy parsing in `create_rule` with `privacy = _privacy(request.privacy_policy)`, to keep it DRY.

- [ ] **Step 4: Run the full backend gate**

Run: `.venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80`
Expected: PASS with coverage ≥ 80%.

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync tests/adapters/test_api.py
git commit -m "feat: expose rule details, policy editing, removal, and replacement routes"
```

---

### Task 7: Bookmarkable rule location and API client

**Files:**
- Modify: `web/src/lib/navigation.ts`, `web/src/lib/navigation.test.ts`, `web/src/lib/api.ts`, `web/src/App.tsx`, `web/src/features/dashboard.tsx` (the `Dashboard` signature only)

**Interfaces:**
- Produces the following:
  - `type AppLocation = { view: AppView; ruleId: string | null }`.
  - `appLocationFromPathname(pathname: string): AppLocation`.
  - `appPathForRule(ruleId: string): string`.
  - `appPathForLocation(location: AppLocation): string`.
  - `isPlainLeftClick(event: { button: number; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; altKey: boolean }): boolean`.
- It produces these in `api.ts`:
  - `Rule.reprojection_required: boolean`.
  - `type ProjectionHandling = "delete" | "detach"`.
  - `type RunOutcome`.
  - `type RuleDetail = Rule & { initial_lookback_days: number; mapping_count: number; last_sync: RunOutcome | null; last_reconciliation: RunOutcome | null }`.
  - The calls `api.rule(id)`, `api.updateRulePolicy(id, payload)`, `api.removeRule(id, projections)`, and `api.replaceRuleCalendars(id, payload)`.
- `Dashboard` props become `{ location: AppLocation; onViewChange: (view: AppView) => void; onOpenRule: (ruleId: string) => void }`.

- [ ] **Step 1: Write the failing tests** (append to `web/src/lib/navigation.test.ts` and update its import)

```ts
import {
  appLocationFromPathname,
  appPathForLocation,
  appPathForRule,
  appPathForView,
  appViewFromPathname,
  isKnownAppPath,
  isPlainLeftClick,
} from "./navigation"

describe("rule detail URLs", () => {
  it.each(["rule-1", "a/b", "ünï code", "550e8400-e29b-41d4-a716-446655440000"])(
    "round-trips rule id %s",
    (ruleId) => {
      const path = appPathForRule(ruleId)
      expect(appLocationFromPathname(path)).toEqual({ view: "rules", ruleId })
      expect(appPathForLocation({ view: "rules", ruleId })).toBe(path)
      expect(isKnownAppPath(path)).toBe(true)
    },
  )

  it("accepts a trailing slash", () => {
    expect(appLocationFromPathname("/rules/rule-1/")).toEqual({ view: "rules", ruleId: "rule-1" })
  })

  it.each(["/rules/x/y", "/rules/%E0%A4%A", "/rules/%20", "/rulesx/1"])(
    "falls back safely for %s",
    (path) => {
      expect(appLocationFromPathname(path).ruleId).toBeNull()
      expect(isKnownAppPath(path)).toBe(false)
    },
  )

  it("keeps section URLs working", () => {
    expect(appLocationFromPathname("/rules")).toEqual({ view: "rules", ruleId: null })
    expect(appViewFromPathname("/rules/rule-1")).toBe("rules")
    expect(appPathForLocation({ view: "settings", ruleId: null })).toBe(appPathForView("settings"))
  })

  it("only intercepts plain left clicks", () => {
    const plain = { button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false }
    expect(isPlainLeftClick(plain)).toBe(true)
    expect(isPlainLeftClick({ ...plain, metaKey: true })).toBe(false)
    expect(isPlainLeftClick({ ...plain, button: 1 })).toBe(false)
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm --prefix web run test -- navigation`
Expected: FAIL, because `appLocationFromPathname` is not exported.

- [ ] **Step 3: Implement**

`web/src/lib/navigation.ts` (full file):

```ts
export type AppView = "overview" | "rules" | "activity" | "settings"
export type AppLocation = { view: AppView; ruleId: string | null }

export const APP_VIEW_PATHS: Record<AppView, string> = {
  overview: "/overview",
  rules: "/rules",
  activity: "/activity",
  settings: "/settings",
}

const PATH_VIEWS = new Map(
  Object.entries(APP_VIEW_PATHS).map(([view, path]) => [path, view as AppView]),
)
const RULE_PATH = /^\/rules\/([^/]+)$/

function normalize(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname
}

function ruleIdFromPath(pathname: string): string | null {
  const match = RULE_PATH.exec(pathname)
  if (!match) return null
  try {
    const ruleId = decodeURIComponent(match[1])
    return ruleId.trim() ? ruleId : null
  } catch {
    return null
  }
}

export function appLocationFromPathname(pathname: string): AppLocation {
  const normalized = normalize(pathname)
  const ruleId = ruleIdFromPath(normalized)
  if (ruleId !== null) return { view: "rules", ruleId }
  return { view: PATH_VIEWS.get(normalized) ?? "overview", ruleId: null }
}

export function appViewFromPathname(pathname: string): AppView {
  return appLocationFromPathname(pathname).view
}

export function appPathForView(view: AppView): string {
  return APP_VIEW_PATHS[view]
}

export function appPathForRule(ruleId: string): string {
  return `${APP_VIEW_PATHS.rules}/${encodeURIComponent(ruleId)}`
}

export function appPathForLocation(location: AppLocation): string {
  return location.ruleId === null ? appPathForView(location.view) : appPathForRule(location.ruleId)
}

export function isKnownAppPath(pathname: string): boolean {
  const normalized = normalize(pathname)
  return PATH_VIEWS.has(normalized) || ruleIdFromPath(normalized) !== null
}

export function isPlainLeftClick(event: {
  button: number
  metaKey: boolean
  ctrlKey: boolean
  shiftKey: boolean
  altKey: boolean
}): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey
}
```

Note that the `"/rules/%20"` case decodes to `" "`, which `trim()` rejects.

`api.ts` additions:

```ts
export type ProjectionHandling = "delete" | "detach"
export type RunOutcome = {
  completed_at: string
  succeeded: boolean
  full_run: boolean
  created: number
  updated: number
  deleted: number
  conflicts: number
  checked_mappings: number
  drift: number
  failure_kind: string | null
}
export type RuleDetail = Rule & {
  initial_lookback_days: number
  mapping_count: number
  last_sync: RunOutcome | null
  last_reconciliation: RunOutcome | null
}
export type RulePolicyPayload = {
  privacy_policy: "busy_only" | "copy_details"
  sync_all_day_events: boolean
}
export type RuleEndpointPayload = { connected_account_id: string; calendar_id: string }
```

Add `reprojection_required: boolean` to `Rule`, and add these to the `api` object:

```ts
  rule: (ruleId: string) => request<RuleDetail>(`/api/v1/rules/${encodeURIComponent(ruleId)}`),
  updateRulePolicy: (ruleId: string, payload: RulePolicyPayload) =>
    request<Rule>(`/api/v1/rules/${encodeURIComponent(ruleId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  removeRule: (ruleId: string, projections: ProjectionHandling) =>
    request<{ deleted: number; detached: number }>(
      `/api/v1/rules/${encodeURIComponent(ruleId)}?projections=${projections}`,
      { method: "DELETE" },
    ),
  replaceRuleCalendars: (
    ruleId: string,
    payload: {
      source: RuleEndpointPayload
      destination: RuleEndpointPayload
      projections: ProjectionHandling
    },
  ) =>
    request<{ rule: Rule; deleted: number; detached: number }>(
      `/api/v1/rules/${encodeURIComponent(ruleId)}/replace`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
```

Make these changes in `App.tsx` (`AuthenticatedApp`):
- Replace the `view` state with `const [location, setLocation] = useState<AppLocation>(() => appLocationFromPathname(window.location.pathname))`.
- Add `navigate(next: AppLocation)`, which pushes `appPathForLocation(next)` when the path differs (same condition as today), sets the location, closes the mobile nav, and calls `window.scrollTo(0, 0)`.
- Make `changeView(view)` call `navigate({ view, ruleId: null })`, and add `openRule(ruleId)`, which calls `navigate({ view: "rules", ruleId })`.
- In the popstate handler, call `setLocation(appLocationFromPathname(...))`.
- Have the unknown-path replacement use `appPathForLocation(appLocationFromPathname(...))`.
- Make `followSectionLink` use `isPlainLeftClick`.
- Base nav `active` and `aria-current` on `location.view`.
- Render `<Dashboard location={location} onViewChange={changeView} onOpenRule={openRule} />`.

In `dashboard.tsx`, change the `Dashboard` signature to the new props and set `const view = location.view` inside. Rendering the details view happens in Task 9, so for now just keep `location.ruleId` unused by rendering `RulesView` as before.

- [ ] **Step 4: Verify**

Run: `npm --prefix web run test && npm --prefix web run typecheck && npm --prefix web run lint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src
git commit -m "feat: add bookmarkable rule detail locations and rule management API client"
```

---

### Task 8: Consequence and outcome copy (`rule-change.ts`)

**Files:**
- Create: `web/src/lib/rule-change.ts`, `web/src/lib/rule-change.test.ts`

**Interfaces:**
- Consumes `RulePolicyPayload`, `ProjectionHandling`, and `RunOutcome` from `api.ts`.
- Produces the following:
  - `policyChanged(current: RulePolicyPayload, next: RulePolicyPayload): boolean`.
  - `policyChangeConsequences(input: { state: string; current: RulePolicyPayload; next: RulePolicyPayload; mappingCount: number; destination: string }): string[]`.
  - `removalConsequence(handling: ProjectionHandling, mappingCount: number, destination: string): string`.
  - `removalConfirmLabel(handling: ProjectionHandling, mappingCount: number): string`.
  - `ruleStateLabel(state: string): string`.
  - `runOutcomeSummary(outcome: RunOutcome | null, kind: "sync" | "reconciliation"): string`.
  - `plural(count: number, singular: string, pluralForm?: string): string`.

- [ ] **Step 1: Write the failing tests** in `web/src/lib/rule-change.test.ts`

```ts
import { describe, expect, it } from "vitest"

import {
  policyChanged,
  policyChangeConsequences,
  removalConfirmLabel,
  removalConsequence,
  ruleStateLabel,
  runOutcomeSummary,
} from "./rule-change"

const busy = { privacy_policy: "busy_only", sync_all_day_events: true } as const
const details = { privacy_policy: "copy_details", sync_all_day_events: true } as const

describe("policy change consequences", () => {
  it("detects changes", () => {
    expect(policyChanged(busy, busy)).toBe(false)
    expect(policyChanged(busy, details)).toBe(true)
  })

  it("warns before exposing event details", () => {
    const lines = policyChangeConsequences({
      state: "enabled",
      current: busy,
      next: details,
      mappingCount: 37,
      destination: "Family",
    })
    expect(lines[0]).toBe("Synchronization pauses now. Preview the rule, then enable it again.")
    expect(lines).toContain(
      "37 existing projections in Family will show event titles, descriptions, and locations after the next run.",
    )
    expect(lines.at(-1)).toBe("Nothing changes in Google Calendar until the rule is enabled again.")
  })

  it("explains redaction and all-day exclusion", () => {
    const lines = policyChangeConsequences({
      state: "draft",
      current: details,
      next: { privacy_policy: "busy_only", sync_all_day_events: false },
      mappingCount: 1,
      destination: "Work",
    })
    expect(lines[0]).toBe("The rule returns to draft. Preview it before enabling it.")
    expect(lines).toContain(
      "1 existing projection in Work will be rewritten as “Busy”, removing titles, descriptions, and locations.",
    )
    expect(lines).toContain("All-day projections in Work will be deleted on the next run.")
  })

  it("describes degraded recovery", () => {
    const [first] = policyChangeConsequences({
      state: "degraded",
      current: busy,
      next: { ...busy, sync_all_day_events: false },
      mappingCount: 0,
      destination: "Work",
    })
    expect(first).toBe(
      "The rule stays stopped until recovery. Its recovery preview also validates the new policy.",
    )
  })
})

describe("rule removal copy", () => {
  it("names the destructive effect", () => {
    expect(removalConfirmLabel("delete", 37)).toBe("Remove rule and delete 37 projections")
    expect(removalConfirmLabel("detach", 1)).toBe("Remove rule and keep 1 event")
    expect(removalConfirmLabel("delete", 0)).toBe("Remove rule")
    expect(removalConsequence("delete", 2, "Family")).toBe(
      "2 Managed Projections will be deleted from Family. Source events are not changed. This cannot be undone.",
    )
    expect(removalConsequence("detach", 2, "Family")).toBe(
      "2 projections stay in Family as ordinary events that are no longer updated or deleted. This cannot be undone.",
    )
  })
})

describe("state and outcome labels", () => {
  it("labels removal in progress", () => {
    expect(ruleStateLabel("disabled")).toBe("Removal incomplete")
    expect(ruleStateLabel("dry_run_validated")).toBe("Preview passed")
  })

  it("summarizes outcomes without provider detail", () => {
    expect(runOutcomeSummary(null, "sync")).toBe("Not run yet")
    const base = {
      completed_at: "2026-09-28T10:00:00+00:00",
      succeeded: true,
      full_run: false,
      created: 2,
      updated: 1,
      deleted: 0,
      conflicts: 0,
      checked_mappings: 42,
      drift: 0,
      failure_kind: null,
    }
    expect(runOutcomeSummary(base, "sync")).toBe("Succeeded: 2 created, 1 updated, 0 deleted")
    expect(runOutcomeSummary({ ...base, conflicts: 1 }, "sync")).toBe(
      "Succeeded: 2 created, 1 updated, 0 deleted, 1 conflict",
    )
    expect(runOutcomeSummary(base, "reconciliation")).toBe("Consistent: 42 mappings checked")
    expect(runOutcomeSummary({ ...base, drift: 3 }, "reconciliation")).toBe(
      "3 differences found in 42 mappings",
    )
    expect(
      runOutcomeSummary({ ...base, succeeded: false, failure_kind: "authentication" }, "sync"),
    ).toBe("Failed: Google authorization expired")
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm --prefix web run test -- rule-change`
Expected: FAIL because the module is not found.

- [ ] **Step 3: Implement** `web/src/lib/rule-change.ts`

```ts
import type { ProjectionHandling, RulePolicyPayload, RunOutcome } from "@/lib/api"

export function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralForm}`
}

export function policyChanged(current: RulePolicyPayload, next: RulePolicyPayload): boolean {
  return (
    current.privacy_policy !== next.privacy_policy ||
    current.sync_all_day_events !== next.sync_all_day_events
  )
}

function stateConsequence(state: string): string {
  if (state === "enabled") return "Synchronization pauses now. Preview the rule, then enable it again."
  if (state === "paused") return "The rule stays paused. Preview it before enabling it again."
  if (state === "degraded") {
    return "The rule stays stopped until recovery. Its recovery preview also validates the new policy."
  }
  return "The rule returns to draft. Preview it before enabling it."
}

export function policyChangeConsequences({
  state,
  current,
  next,
  mappingCount,
  destination,
}: {
  state: string
  current: RulePolicyPayload
  next: RulePolicyPayload
  mappingCount: number
  destination: string
}): string[] {
  const lines = [stateConsequence(state)]
  const existing = `${plural(mappingCount, "existing projection")} in ${destination}`
  if (current.privacy_policy === "busy_only" && next.privacy_policy === "copy_details") {
    lines.push(
      mappingCount > 0
        ? `${existing} will show event titles, descriptions, and locations after the next run.`
        : `New projections in ${destination} will show event titles, descriptions, and locations.`,
    )
  }
  if (current.privacy_policy === "copy_details" && next.privacy_policy === "busy_only") {
    lines.push(
      `${existing} will be rewritten as “Busy”, removing titles, descriptions, and locations.`,
    )
  }
  if (current.sync_all_day_events && !next.sync_all_day_events) {
    lines.push(`All-day projections in ${destination} will be deleted on the next run.`)
  }
  if (!current.sync_all_day_events && next.sync_all_day_events) {
    lines.push(`All-day source events will be added to ${destination} on the next run.`)
  }
  lines.push("Nothing changes in Google Calendar until the rule is enabled again.")
  return lines
}

export function removalConsequence(
  handling: ProjectionHandling,
  mappingCount: number,
  destination: string,
): string {
  if (handling === "delete") {
    return `${plural(mappingCount, "Managed Projection")} will be deleted from ${destination}. Source events are not changed. This cannot be undone.`
  }
  return `${plural(mappingCount, "projection")} stay in ${destination} as ordinary events that are no longer updated or deleted. This cannot be undone.`
}

export function removalConfirmLabel(handling: ProjectionHandling, mappingCount: number): string {
  if (mappingCount === 0) return "Remove rule"
  return handling === "delete"
    ? `Remove rule and delete ${plural(mappingCount, "projection")}`
    : `Remove rule and keep ${plural(mappingCount, "event")}`
}

const STATE_LABELS: Record<string, string> = {
  draft: "Draft",
  dry_run_validated: "Preview passed",
  enabled: "Enabled",
  paused: "Paused",
  degraded: "Stopped",
  disabled: "Removal incomplete",
}

export function ruleStateLabel(state: string): string {
  return STATE_LABELS[state] ?? state.replaceAll("_", " ")
}

const FAILURE_LABELS: Record<string, string> = {
  authentication: "Google authorization expired",
  authorization: "Google calendar access was denied",
  rate_limit: "Google Calendar was limiting requests",
  temporary: "Google Calendar was temporarily unavailable",
  permanent: "Google Calendar rejected the request",
}

export function runOutcomeSummary(
  outcome: RunOutcome | null,
  kind: "sync" | "reconciliation",
): string {
  if (outcome === null) return "Not run yet"
  if (!outcome.succeeded) {
    return `Failed: ${FAILURE_LABELS[outcome.failure_kind ?? ""] ?? "Local synchronization failed"}`
  }
  if (kind === "reconciliation") {
    return outcome.drift === 0
      ? `Consistent: ${plural(outcome.checked_mappings, "mapping")} checked`
      : `${plural(outcome.drift, "difference")} found in ${plural(outcome.checked_mappings, "mapping")}`
  }
  const counts = `${outcome.created} created, ${outcome.updated} updated, ${outcome.deleted} deleted`
  return outcome.conflicts > 0
    ? `Succeeded: ${counts}, ${plural(outcome.conflicts, "conflict")}`
    : `Succeeded: ${counts}`
}
```

- [ ] **Step 4: Verify**

Run: `npm --prefix web run test && npm --prefix web run lint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/rule-change.ts web/src/lib/rule-change.test.ts
git commit -m "feat: describe rule change and removal consequences before confirmation"
```

---

### Task 9: `RuleDetailsView`, the rule-row link, and styles

**Files:**
- Create: `web/src/features/rule-details.tsx`, `web/src/lib/rule-details.test.ts`
- Create: `web/src/components/rule-endpoint.tsx` (moved `RuleEndpoint`) and `web/src/components/dashboard-skeleton.tsx` (moved `DashboardSkeleton`), shared so `rule-details.tsx` and `dashboard.tsx` never import each other
- Modify: `web/src/features/dashboard.tsx` (route, row link, preview-required note, state label, imports of the moved components), `web/src/lib/rule-recovery.test.ts` (read `../components/rule-endpoint.tsx?raw` for the `avatarUrl={account?.avatar_url}` assertion), `web/src/index.css`

**Interfaces:**
- Consumes Tasks 7 and 8, plus `AccountAvatar` and `ruleEndpointLabel` from PR #4.
- Produces `RuleDetailsView({ ruleId, onViewChange, onOpenRule }: { ruleId: string; onViewChange: (view: AppView) => void; onOpenRule: (ruleId: string) => void })`.

- [ ] **Step 1: Write the failing source-contract test** `web/src/lib/rule-details.test.ts` (this follows the `?raw` pattern in `rule-recovery.test.ts`)

```ts
import { describe, expect, it } from "vitest"

import dashboardSource from "../features/dashboard.tsx?raw"
import detailsSource from "../features/rule-details.tsx?raw"

describe("Rule Details presentation", () => {
  it("defaults Rule Removal to deleting mapped projections and confirms separately", () => {
    expect(detailsSource).toContain('useState<ProjectionHandling>("delete")')
    expect(detailsSource).toContain("removalConfirmLabel(")
    expect(detailsSource).toContain('role="radiogroup"')
    expect(detailsSource).toContain("Removal incomplete")
  })

  it("shows consequences before saving a Material Rule Change", () => {
    expect(detailsSource).toContain("policyChangeConsequences(")
    expect(detailsSource).toContain("disabled={!changed || update.isPending}")
  })

  it("links every rule row to its details and renders the details route", () => {
    expect(dashboardSource).toContain("appPathForRule(rule.id)")
    expect(dashboardSource).toContain("<RuleDetailsView")
    expect(dashboardSource).toContain("Preview required")
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm --prefix web run test -- rule-details`
Expected: FAIL, because `rule-details.tsx` does not exist.

- [ ] **Step 3: Implement**

In `dashboard.tsx`, make these changes:
- Move `RuleEndpoint` (same body, `export function`) to `web/src/components/rule-endpoint.tsx` and `DashboardSkeleton` to `web/src/components/dashboard-skeleton.tsx` with their imports, and import both back.
- Import `RuleDetailsView` from `@/features/rule-details`, `appPathForRule` and `isPlainLeftClick` from `@/lib/navigation`, and `ruleStateLabel` from `@/lib/rule-change`.
- In `Dashboard`, before the `view === "rules"` line, add the following:

```tsx
  if (view === "rules" && location.ruleId !== null) {
    return (
      <RuleDetailsView ruleId={location.ruleId} onViewChange={onViewChange} onOpenRule={onOpenRule} />
    )
  }
  if (view === "rules") {
    return (
      <RulesView rules={rules.data} dashboard={dashboard.data} onViewChange={onViewChange} onOpenRule={onOpenRule} />
    )
  }
```

`RulesView` gains `onOpenRule: (ruleId: string) => void`. In each row:
- Replace the badge text `rule.state.replaceAll("_", " ")` with `ruleStateLabel(rule.state)`.
- After `.rule-policy`, add the note below:

```tsx
                  {rule.reprojection_required && ["draft", "paused", "degraded"].includes(rule.state) && (
                    <p className="preview-result" role="status">
                      Preview required. The policy changed; existing projections are rewritten on the
                      next run after you enable the rule.
                    </p>
                  )}
```

- As the last child of `.rule-actions`, add this:

```tsx
                  <Button variant="ghost" asChild>
                    <a
                      href={appPathForRule(rule.id)}
                      onClick={(event) => {
                        if (!isPlainLeftClick(event)) return
                        event.preventDefault()
                        onOpenRule(rule.id)
                      }}
                      aria-label={`View details for the rule from ${ruleEndpointLabel(rule.source.calendar_id, sourceAccount, calendarsByAccount.get(rule.source.connected_account_id)).calendar} to ${ruleEndpointLabel(rule.destination.calendar_id, destinationAccount, calendarsByAccount.get(rule.destination.connected_account_id)).calendar}`}
                    >
                      View details <ArrowRight aria-hidden="true" />
                    </a>
                  </Button>
```

`web/src/features/rule-details.tsx`:

```tsx
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, ArrowRight, CircleDot, RefreshCw, ShieldAlert, Trash2 } from "lucide-react"
import { useEffect, useRef, useState, type FormEvent } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { NativeSelect } from "@/components/ui/native-select"
import { DashboardSkeleton } from "@/components/dashboard-skeleton"
import { RuleEndpoint } from "@/components/rule-endpoint"
import {
  api,
  type ConnectedAccount,
  type DiscoveredCalendar,
  type ProjectionHandling,
  type RuleDetail,
  type RulePolicyPayload,
} from "@/lib/api"
import { appPathForView, isPlainLeftClick, type AppView } from "@/lib/navigation"
import { ruleEndpointLabel } from "@/lib/rule-endpoint"
import {
  plural,
  policyChanged,
  policyChangeConsequences,
  removalConfirmLabel,
  removalConsequence,
  ruleStateLabel,
  runOutcomeSummary,
} from "@/lib/rule-change"

type Props = {
  ruleId: string
  onViewChange: (view: AppView) => void
  onOpenRule: (ruleId: string) => void
}

export function RuleDetailsView({ ruleId, onViewChange, onOpenRule }: Props) {
  const rule = useQuery({ queryKey: ["rule", ruleId], queryFn: () => api.rule(ruleId), retry: false })
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts })
  const heading = useRef<HTMLHeadingElement>(null)
  const accountIds = rule.data
    ? [...new Set([rule.data.source.connected_account_id, rule.data.destination.connected_account_id])]
    : []
  const connectedIds = accountIds.filter(
    (id) => accounts.data?.find((account) => account.id === id)?.state === "connected",
  )
  const calendarQueries = useQueries({
    queries: connectedIds.map((accountId) => ({
      queryKey: ["calendars", accountId],
      queryFn: () => api.calendars(accountId),
      staleTime: 5 * 60 * 1000,
    })),
  })
  const calendarsByAccount = new Map(
    connectedIds.map((accountId, index) => [accountId, calendarQueries[index]?.data]),
  )

  useEffect(() => {
    if (rule.data) heading.current?.focus()
  }, [rule.data?.id])

  const back = (
    <a
      className="back-link"
      href={appPathForView("rules")}
      onClick={(event) => {
        if (!isPlainLeftClick(event)) return
        event.preventDefault()
        onViewChange("rules")
      }}
    >
      <ArrowLeft aria-hidden="true" /> All rules
    </a>
  )

  if (rule.isPending || accounts.isPending) return <DashboardSkeleton />
  if (rule.error || accounts.error) {
    const missing = rule.error && "status" in rule.error && rule.error.status === 404
    return (
      <section className="page-section" role="alert">
        {back}
        <h1>{missing ? "This rule no longer exists" : "Rule details could not load"}</h1>
        <p className="page-intro">
          {missing
            ? "It may have been removed or replaced. Return to the rules list to continue."
            : "Check that the local service is running, then try again."}
        </p>
        {!missing && (
          <Button variant="outline" onClick={() => void rule.refetch()}>
            <RefreshCw aria-hidden="true" /> Try again
          </Button>
        )}
      </section>
    )
  }

  const detail = rule.data
  const accountsById = new Map((accounts.data ?? []).map((account) => [account.id, account]))
  const sourceAccount = accountsById.get(detail.source.connected_account_id)
  const destinationAccount = accountsById.get(detail.destination.connected_account_id)
  const destinationName = ruleEndpointLabel(
    detail.destination.calendar_id,
    destinationAccount,
    calendarsByAccount.get(detail.destination.connected_account_id),
  ).calendar
  const removing = detail.state === "disabled"

  return (
    <div className="page-section rule-details">
      {back}
      <div className="page-heading-row">
        <div>
          <p className="page-context">Directional Sync Rule</p>
          <h1 ref={heading} tabIndex={-1}>Rule details</h1>
          <div className="rule-direction rule-details-direction">
            <RuleEndpoint
              account={sourceAccount}
              accountId={detail.source.connected_account_id}
              calendarId={detail.source.calendar_id}
              calendars={calendarsByAccount.get(detail.source.connected_account_id)}
              role="Source"
            />
            <ArrowRight aria-hidden="true" />
            <RuleEndpoint
              account={destinationAccount}
              accountId={detail.destination.connected_account_id}
              calendarId={detail.destination.calendar_id}
              calendars={calendarsByAccount.get(detail.destination.connected_account_id)}
              role="Destination"
            />
          </div>
        </div>
        <Badge variant={detail.state === "enabled" ? "healthy" : removing || detail.state === "degraded" ? "attention" : "neutral"}>
          {removing || detail.state === "degraded" ? <ShieldAlert aria-hidden="true" /> : <CircleDot aria-hidden="true" />}
          {ruleStateLabel(detail.state)}
        </Badge>
      </div>

      {detail.reprojection_required && ["draft", "paused", "degraded"].includes(detail.state) && (
        <div className="rule-recovery-note" role="status">
          <ShieldAlert aria-hidden="true" />
          <p>
            <strong>Preview required.</strong> The policy changed. Preview this rule from the rules
            list, then enable it; {plural(detail.mapping_count, "existing projection")} will be
            rewritten on the next run.
          </p>
        </div>
      )}

      <section className="rule-section" aria-labelledby="rule-facts-title">
        <h2 id="rule-facts-title">What this rule does</h2>
        <dl className="rule-facts">
          <div><dt>Event information</dt><dd>{detail.privacy_policy === "busy_only" ? "Busy only: titles, descriptions, and locations are hidden" : "Title, description, and location are copied"}</dd></div>
          <div><dt>All-day events</dt><dd>{detail.sync_all_day_events ? "Included" : "Excluded; timed events only"}</dd></div>
          <div><dt>Initial window</dt><dd>Events ending in the last {detail.initial_lookback_days} days or later</dd></div>
          <div><dt>Managed projections</dt><dd>{plural(detail.mapping_count, "Event Mapping")}</dd></div>
        </dl>
      </section>

      <section className="rule-section" aria-labelledby="rule-runs-title">
        <h2 id="rule-runs-title">Recent runs</h2>
        <dl className="rule-facts">
          <OutcomeFact label="Last synchronization" outcome={detail.last_sync} kind="sync" />
          <OutcomeFact label="Last reconciliation" outcome={detail.last_reconciliation} kind="reconciliation" />
        </dl>
      </section>

      {!removing && <PolicyEditor detail={detail} destinationName={destinationName} />}
      {!removing && (
        <CalendarReplacement
          detail={detail}
          accounts={accounts.data ?? []}
          destinationName={destinationName}
          destinationConnected={destinationAccount?.state === "connected"}
          onReplaced={onOpenRule}
        />
      )}
      <RuleRemoval
        detail={detail}
        destinationName={destinationName}
        destinationConnected={destinationAccount?.state === "connected"}
        onRemoved={() => onViewChange("rules")}
      />
    </div>
  )
}

function OutcomeFact({ label, outcome, kind }: { label: string; outcome: RuleDetail["last_sync"]; kind: "sync" | "reconciliation" }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {runOutcomeSummary(outcome, kind)}
        {outcome && (
          <time dateTime={outcome.completed_at} className="rule-fact-time">
            {new Date(outcome.completed_at).toLocaleString()}
          </time>
        )}
      </dd>
    </div>
  )
}

function useRuleInvalidation(ruleId: string) {
  const queryClient = useQueryClient()
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["rule", ruleId] }),
      queryClient.invalidateQueries({ queryKey: ["rules"] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      queryClient.invalidateQueries({ queryKey: ["activity"] }),
      queryClient.invalidateQueries({ queryKey: ["accounts"] }),
    ])
}

function PolicyEditor({ detail, destinationName }: { detail: RuleDetail; destinationName: string }) {
  const invalidate = useRuleInvalidation(detail.id)
  const current: RulePolicyPayload = {
    privacy_policy: detail.privacy_policy,
    sync_all_day_events: detail.sync_all_day_events,
  }
  const [open, setOpen] = useState(false)
  const [next, setNext] = useState<RulePolicyPayload>(current)
  const changed = policyChanged(current, next)
  const update = useMutation({
    mutationFn: () => api.updateRulePolicy(detail.id, next),
    onSuccess: async () => {
      await invalidate()
      setOpen(false)
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    if (changed) update.mutate()
  }

  return (
    <section className="rule-section" aria-labelledby="policy-title">
      <div className="section-heading">
        <div>
          <h2 id="policy-title">Projection policy</h2>
          <p>Changing it is a Material Rule Change and needs a new preview.</p>
        </div>
        <Button variant="outline" onClick={() => { setNext(current); setOpen((value) => !value) }} aria-expanded={open} aria-controls="policy-form">
          {open ? "Cancel" : "Change policy"}
        </Button>
      </div>
      {open && (
        <form id="policy-form" className="rule-edit-form" onSubmit={submit}>
          <div className="field-stack">
            <Label htmlFor="edit-privacy-policy">Event information</Label>
            <NativeSelect
              id="edit-privacy-policy"
              value={next.privacy_policy}
              onChange={(event) => setNext({ ...next, privacy_policy: event.target.value as RulePolicyPayload["privacy_policy"] })}
            >
              <option value="busy_only">Busy only (recommended)</option>
              <option value="copy_details">Copy title, description, and location</option>
            </NativeSelect>
          </div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={next.sync_all_day_events}
              onChange={(event) => setNext({ ...next, sync_all_day_events: event.target.checked })}
            />
            <span><strong>Sync all-day events</strong><small>Turn this off to synchronize timed events only.</small></span>
          </label>
          {changed && (
            <div className="consequence-panel" role="status" aria-live="polite">
              <h3>What happens when you save</h3>
              <ul>
                {policyChangeConsequences({
                  state: detail.state,
                  current,
                  next,
                  mappingCount: detail.mapping_count,
                  destination: destinationName,
                }).map((line) => <li key={line}>{line}</li>)}
              </ul>
            </div>
          )}
          {update.error && <div className="inline-error" role="alert">{update.error.message}</div>}
          <div className="form-actions">
            <Button type="submit" disabled={!changed || update.isPending}>
              {update.isPending ? "Saving…" : "Save policy change"}
            </Button>
          </div>
        </form>
      )}
    </section>
  )
}

function ProjectionChoice({
  name,
  value,
  onChange,
  mappingCount,
  destinationName,
  deleteAvailable,
}: {
  name: string
  value: ProjectionHandling
  onChange: (value: ProjectionHandling) => void
  mappingCount: number
  destinationName: string
  deleteAvailable: boolean
}) {
  return (
    <fieldset className="projection-choice">
      <legend>Existing projections</legend>
      <div role="radiogroup" aria-describedby={`${name}-consequence`}>
        <label className="radio-row">
          <input type="radio" name={name} value="delete" checked={value === "delete"} disabled={!deleteAvailable} onChange={() => onChange("delete")} />
          <span>
            <strong>Delete {plural(mappingCount, "projection")} from {destinationName} (recommended)</strong>
            <small>{deleteAvailable ? "Only events this rule manages are deleted." : "Reauthorize the destination account in Settings to delete projections."}</small>
          </span>
        </label>
        <label className="radio-row">
          <input type="radio" name={name} value="detach" checked={value === "detach"} onChange={() => onChange("detach")} />
          <span>
            <strong>Keep them as ordinary events</strong>
            <small>They stay in {destinationName} and are never updated or deleted again.</small>
          </span>
        </label>
      </div>
      <p id={`${name}-consequence`} className="consequence-text">{removalConsequence(value, mappingCount, destinationName)}</p>
    </fieldset>
  )
}

function CalendarReplacement({
  detail,
  accounts,
  destinationName,
  destinationConnected,
  onReplaced,
}: {
  detail: RuleDetail
  accounts: ConnectedAccount[]
  destinationName: string
  destinationConnected: boolean
  onReplaced: (ruleId: string) => void
}) {
  const invalidate = useRuleInvalidation(detail.id)
  const connected = accounts.filter((account) => account.state === "connected")
  const [open, setOpen] = useState(false)
  const [sourceAccount, setSourceAccount] = useState(detail.source.connected_account_id)
  const [sourceCalendar, setSourceCalendar] = useState(detail.source.calendar_id)
  const [destinationAccount, setDestinationAccount] = useState(detail.destination.connected_account_id)
  const [destinationCalendar, setDestinationCalendar] = useState(detail.destination.calendar_id)
  const [handling, setHandling] = useState<ProjectionHandling>(destinationConnected ? "delete" : "detach")
  const sourceCalendars = useQuery({
    queryKey: ["calendars", sourceAccount],
    queryFn: () => api.calendars(sourceAccount),
    enabled: open && connected.some((account) => account.id === sourceAccount),
  })
  const destinationCalendars = useQuery({
    queryKey: ["calendars", destinationAccount],
    queryFn: () => api.calendars(destinationAccount),
    enabled: open && connected.some((account) => account.id === destinationAccount),
  })
  const unchanged =
    sourceAccount === detail.source.connected_account_id &&
    sourceCalendar === detail.source.calendar_id &&
    destinationAccount === detail.destination.connected_account_id &&
    destinationCalendar === detail.destination.calendar_id
  const sameEndpoint = sourceAccount === destinationAccount && sourceCalendar === destinationCalendar
  const replace = useMutation({
    mutationFn: () =>
      api.replaceRuleCalendars(detail.id, {
        source: { connected_account_id: sourceAccount, calendar_id: sourceCalendar },
        destination: { connected_account_id: destinationAccount, calendar_id: destinationCalendar },
        projections: handling,
      }),
    onSuccess: async (result) => {
      await invalidate()
      onReplaced(result.rule.id)
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!unchanged && !sameEndpoint) replace.mutate()
  }

  return (
    <section className="rule-section" aria-labelledby="replace-title">
      <div className="section-heading">
        <div>
          <h2 id="replace-title">Calendars</h2>
          <p>Changing a calendar removes this rule and creates a new draft with the same policy.</p>
        </div>
        <Button variant="outline" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-controls="replace-form">
          {open ? "Cancel" : "Change calendars"}
        </Button>
      </div>
      {open && (
        <form id="replace-form" className="rule-edit-form" onSubmit={submit}>
          <EndpointFields
            legend="Source calendar"
            idPrefix="replace-source"
            accounts={connected}
            account={sourceAccount}
            calendar={sourceCalendar}
            calendars={sourceCalendars.data}
            writableOnly={false}
            onAccount={(value) => { setSourceAccount(value); setSourceCalendar("") }}
            onCalendar={setSourceCalendar}
          />
          <EndpointFields
            legend="Destination calendar"
            idPrefix="replace-destination"
            accounts={connected}
            account={destinationAccount}
            calendar={destinationCalendar}
            calendars={destinationCalendars.data}
            writableOnly
            onAccount={(value) => { setDestinationAccount(value); setDestinationCalendar("") }}
            onCalendar={setDestinationCalendar}
          />
          <ProjectionChoice
            name="replace-projections"
            value={handling}
            onChange={setHandling}
            mappingCount={detail.mapping_count}
            destinationName={destinationName}
            deleteAvailable={destinationConnected}
          />
          {sameEndpoint && <p className="field-error" role="alert">Choose a different destination calendar.</p>}
          {replace.error && <div className="inline-error" role="alert">{replace.error.message}</div>}
          <div className="form-actions">
            <Button type="submit" variant="destructive" disabled={unchanged || sameEndpoint || !sourceCalendar || !destinationCalendar || replace.isPending}>
              {replace.isPending ? "Replacing…" : "Replace rule"}
            </Button>
          </div>
        </form>
      )}
    </section>
  )
}

function EndpointFields({
  legend,
  idPrefix,
  accounts,
  account,
  calendar,
  calendars,
  writableOnly,
  onAccount,
  onCalendar,
}: {
  legend: string
  idPrefix: string
  accounts: ConnectedAccount[]
  account: string
  calendar: string
  calendars: DiscoveredCalendar[] | undefined
  writableOnly: boolean
  onAccount: (value: string) => void
  onCalendar: (value: string) => void
}) {
  const options = (calendars ?? []).filter(
    (item) => !writableOnly || ["writer", "owner"].includes(item.access_role),
  )
  return (
    <fieldset className="endpoint-fields">
      <legend>{legend}</legend>
      <div className="field-stack">
        <Label htmlFor={`${idPrefix}-account`}>Google identity</Label>
        <NativeSelect id={`${idPrefix}-account`} value={account} onChange={(event) => onAccount(event.target.value)}>
          {accounts.map((item) => <option key={item.id} value={item.id}>{item.display_name} ({item.email})</option>)}
        </NativeSelect>
      </div>
      <div className="field-stack">
        <Label htmlFor={`${idPrefix}-calendar`}>{writableOnly ? "Writable calendar" : "Calendar"}</Label>
        <NativeSelect id={`${idPrefix}-calendar`} value={calendar} onChange={(event) => onCalendar(event.target.value)}>
          <option value="" disabled>Choose a calendar</option>
          {options.map((item) => <option key={item.id} value={item.id}>{item.summary}</option>)}
        </NativeSelect>
      </div>
    </fieldset>
  )
}

function RuleRemoval({
  detail,
  destinationName,
  destinationConnected,
  onRemoved,
}: {
  detail: RuleDetail
  destinationName: string
  destinationConnected: boolean
  onRemoved: () => void
}) {
  const invalidate = useRuleInvalidation(detail.id)
  const [handling, setHandling] = useState<ProjectionHandling>("delete")
  const [confirming, setConfirming] = useState(false)
  const effective: ProjectionHandling = destinationConnected ? handling : "detach"
  const remove = useMutation({
    mutationFn: () => api.removeRule(detail.id, effective),
    onSuccess: async () => {
      await invalidate()
      onRemoved()
    },
  })
  const removing = detail.state === "disabled"

  return (
    <section className="rule-section rule-removal" aria-labelledby="removal-title">
      <div className="section-heading">
        <div>
          <h2 id="removal-title">{removing ? "Removal incomplete" : "Remove rule"}</h2>
          <p>
            {removing
              ? `Removal stopped with ${plural(detail.mapping_count, "projection")} left. Retry to finish; the rule does not synchronize meanwhile.`
              : "Rule Removal is permanent. Choose what happens to the events this rule manages."}
          </p>
        </div>
      </div>
      <ProjectionChoice
        name="removal-projections"
        value={effective}
        onChange={(value) => { setHandling(value); setConfirming(false) }}
        mappingCount={detail.mapping_count}
        destinationName={destinationName}
        deleteAvailable={destinationConnected}
      />
      {!confirming ? (
        <div className="form-actions">
          <Button variant="outline" onClick={() => setConfirming(true)} aria-expanded={false} aria-controls="removal-confirmation">
            <Trash2 aria-hidden="true" /> {removing ? "Retry removal" : "Remove rule"}
          </Button>
        </div>
      ) : (
        <div className="disconnect-confirmation delete-confirmation" id="removal-confirmation" role="group" aria-labelledby="removal-confirm-title">
          <div>
            <h4 id="removal-confirm-title">Remove this rule permanently?</h4>
            <p>{removalConsequence(effective, detail.mapping_count, destinationName)}</p>
          </div>
          <div className="confirmation-actions">
            <Button variant="outline" onClick={() => setConfirming(false)} disabled={remove.isPending}>Keep rule</Button>
            <Button variant="destructive" onClick={() => remove.mutate()} disabled={remove.isPending}>
              <Trash2 aria-hidden="true" />
              {remove.isPending ? "Removing…" : removalConfirmLabel(effective, detail.mapping_count)}
            </Button>
          </div>
        </div>
      )}
      {remove.error && <div className="inline-error" role="alert">{remove.error.message}</div>}
    </section>
  )
}
```

(The implementer must check that `Badge` accepts `variant="neutral" | "healthy" | "attention"`, which `dashboard.tsx` already uses, and that `Button` supports `variant="destructive"` and `asChild`, which Settings already uses. If `react-hooks/exhaustive-deps` flags the focus effect, depend on `rule.data`.)

`web/src/index.css`. Add these after the `.form-actions` block and reuse the existing tokens:

```css
.back-link {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  gap: 0.375rem;
  color: var(--muted-foreground);
  font-size: 0.875rem;
  font-weight: 600;
  text-decoration: none;
}

.back-link:hover {
  color: var(--foreground);
}

.back-link:focus-visible {
  border-radius: var(--radius-sm, 6px);
  outline: 2px solid var(--ring);
  outline-offset: 2px;
}

.back-link svg {
  width: 1rem;
  height: 1rem;
}

.rule-details h1:focus {
  outline: none;
}

.rule-details-direction {
  margin-top: 1rem;
}

.rule-section {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding-top: 1.5rem;
  border-top: 1px solid var(--border);
}

.rule-section h2 {
  font-size: 1rem;
  font-weight: 700;
}

.rule-facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem 2rem;
}

.rule-facts dt {
  color: var(--muted-foreground);
  font-size: 0.85rem;
  font-weight: 600;
}

.rule-facts dd {
  margin-top: 0.25rem;
  line-height: 1.5;
}

.rule-fact-time {
  display: block;
  color: var(--muted-foreground);
  font-size: 0.85rem;
}

.rule-edit-form {
  display: flex;
  max-width: 44rem;
  flex-direction: column;
  gap: 1.25rem;
}

.endpoint-fields,
.projection-choice {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  border: 0;
  padding: 0;
}

.endpoint-fields legend,
.projection-choice legend {
  margin-bottom: 0.5rem;
  font-size: 0.85rem;
  font-weight: 600;
}

.radio-row {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.5rem 0;
  cursor: pointer;
}

.radio-row input {
  width: 1rem;
  height: 1rem;
  margin-top: 0.2rem;
  accent-color: var(--primary);
}

.radio-row input:disabled + span {
  opacity: 0.7;
}

.radio-row span {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.radio-row small,
.consequence-text {
  color: var(--muted-foreground);
  line-height: 1.5;
}

.consequence-panel {
  padding: 1rem 1.25rem;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--muted);
}

.consequence-panel h3 {
  margin-bottom: 0.5rem;
  font-size: 0.9rem;
  font-weight: 700;
}

.consequence-panel ul {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  padding-left: 1.1rem;
  list-style: disc;
  line-height: 1.5;
}
```

Inside the existing `@media (max-width: 800px)` block, add this:

```css
  .rule-facts {
    grid-template-columns: minmax(0, 1fr);
  }
```

(The implementer should check the token names `--muted-foreground`, `--border`, `--muted`, `--ring`, `--primary`, and `--foreground` against the top of `index.css`, and use whatever names exist.)

- [ ] **Step 4: Verify and build**

Run: `npm --prefix web run typecheck && npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`
Expected: PASS. The build regenerates `src/calendar_sync/interfaces/api/static/`.

Then run the app to check it manually. Start `.venv/bin/uvicorn calendar_sync.interfaces.api.app:create_app --factory` with a temporary `CALENDAR_SYNC_DATABASE_PATH`, insert a synthetic rule into SQLite, and open `/rules/<id>` at desktop and 390px widths. Tab through every control, confirm that focus moves to the heading, confirm the consequence panel appears before Save, and check the removal confirmation. Save screenshots to `.context/`.

- [ ] **Step 5: Commit**

```bash
git add web/src src/calendar_sync/interfaces/api/static
git commit -m "feat: add the Rule Details view with policy editing, replacement, and removal"
```

---

### Task 10: Documentation, ADR, changelog, final gates, and PR

**Files:**
- Modify: `CONTEXT.md`, `docs/domain-model.md`, `docs/sync-model.md`, `docs/deployment.md`, `CHANGELOG.md`, `README.md` (the supported-behavior list, if it enumerates rule actions)
- Create: `docs/adr/0010-rule-removal-and-calendar-replacement.md`

- [ ] **Step 1: Update `CONTEXT.md`** (in the Rule Lifecycle section)

Replace **Material Rule Change** with the following:

```markdown
**Material Rule Change**:
A change to a rule's transformation policy or event eligibility that invalidates its previous preview and requires a new one. Saving it stops synchronization immediately; after the rule is previewed and enabled again, the next run rewrites every mapped projection under the new policy. Calendars cannot change in place; that requires a Rule Replacement.
_Avoid_: Rule edit, configuration update
```

Replace **Rule Removal** with the following:

```markdown
**Rule Removal**:
Permanent removal of a rule after the administrator explicitly chooses to delete its mapped projections or keep them as detached ordinary events. Mapped projection deletion is the recommended default and requires an authorized destination account. A removal interrupted by a provider failure leaves the rule inert until it is retried.
_Avoid_: Disable rule, pause rule
```

Replace **Detached Event** with the following:

```markdown
**Detached Event**:
A former managed projection retained during rule removal after its mapping is removed. It keeps the removed rule's private origin metadata, so it is never updated again and never becomes a source for a reverse rule.
_Avoid_: Orphaned projection, preserved copy
```

Add a new term:

```markdown
**Rule Replacement**:
A change of a rule's source or destination calendar, performed as a Rule Removal followed by a new draft rule with the same transformation policy. The new relationship is validated before anything is removed.
_Avoid_: Calendar edit, rule move
```

- [ ] **Step 2: Update `docs/domain-model.md`**

In the aggregate paragraph, add: "Editing the transformation policy or all-day eligibility sets a persisted reprojection flag that the next successful Sync Run clears after rewriting every mapped projection." Replace the state machine block and the paragraph that follows it with the following:

```text
Draft -> DryRunValidated -> Enabled -> Paused
                |              |
                -> Degraded <--|
any state -> Disabled (Rule Removal incomplete) -> removed
```

```markdown
Only a successfully previewed configuration can become Enabled. A Material Rule Change returns
Enabled and Paused rules to Paused, Draft and DryRunValidated rules to Draft, and keeps Degraded
rules Degraded, so the rule must pass a new preview. Rule Removal first moves the rule to Disabled,
which cannot synchronize, preview, or enable; the rule is deleted once every mapping is deleted or
detached, and a failed removal can be retried in either mode.
```

Keep the existing disconnect and account-deletion paragraphs.

- [ ] **Step 3: Update `docs/sync-model.md`**. Add a section after "Initial and incremental synchronization":

```markdown
## Reprojection after a Material Rule Change

Incremental change feeds only report source events that changed, so a new transformation policy
would otherwise reach only future edits. When a rule's reprojection flag is set, its next Sync Run
ignores both cursors, then loads the authoritative source of every remaining Event Mapping,
including events that ended before the Initial Sync Window, and applies the normal decision.
A source that cannot be verified is recorded as a Conflict and its projection is left unchanged.
The run clears the flag with its cursors only if the rule was not changed again meanwhile.

## Rule Removal

Removal holds the same per-rule lock as synchronization. Deleting projections uses the normal
ownership checks and `sendUpdates=none`, committing each mapping as it is removed; keeping
projections as Detached Events removes mappings without provider writes. Managed events without a
mapping are never deleted.
```

- [ ] **Step 4: Update `docs/deployment.md`**. After the migration 2 paragraph:

```markdown
Migration 3 adds `sync_rules.reprojection_required` (default `0`) and the `rule_run_outcomes`
table, which stores only timestamps, counts, and failure categories for the Rule Details view.
Rolling back to the previous image works with the same database: it ignores the new column and
table and leaves the flag untouched. The previous image does not rewrite existing projections after
a policy change; upgrading again resumes the pending reprojection. Rules whose removal was
interrupted stay inert on the previous image.
```

- [ ] **Step 5: Create `docs/adr/0010-rule-removal-and-calendar-replacement.md`**

```markdown
# Remove rules explicitly and replace calendars instead of editing them

## Context

Administrators need to change or retire Directional Sync Rules. A rule's Event Mappings and
Managed Origin metadata bind every projection to one source and one destination. Moving a rule to
another calendar in place would leave mappings pointing at calendars the rule no longer manages, and
stripping ownership from retained events would let a reverse rule treat them as Native Events.

## Decision

- Transformation policy and all-day eligibility are editable as a Material Rule Change that
  stops synchronization, requires a new Rule Preview, and reprojects every mapping on the next run.
- Source and destination calendars are never edited in place. A Rule Replacement validates the new
  relationship, performs Rule Removal, and creates a new draft with the same policy.
- Rule Removal requires an explicit choice: delete mapped projections (recommended, requires an
  authorized destination) or keep them as Detached Events. Detached Events keep the removed rule's
  origin metadata and receive no provider write.
- Removal marks the rule Disabled first and commits per mapping, so a provider failure leaves a
  resumable, inert rule rather than a half-removed one.

## Alternatives considered

- In-place calendar edits would require re-homing or re-validating every mapping and invite
  ownership ambiguity.
- Stripping origin metadata from Detached Events makes them ordinary but lets `B -> A` rules copy
  them back as duplicates, and adds one provider write per event.
- Keeping an enabled rule running on its previous policy until re-enabled requires a second pending
  configuration per rule.

## Consequences

Replacement produces a new rule identity; its history starts fresh, while the removed rule's audit
entries remain. Detached Events can never be adopted by a later rule. Interrupted removals are
visible as "Removal incomplete" until retried.
```

- [ ] **Step 6: Update `CHANGELOG.md`** under `[Unreleased]`.

In `### Added`:

```markdown
- Rule Details at `/rules/{id}` showing calendars, projection policy, all-day eligibility, initial window, state, managed projection count, and the last synchronization and reconciliation outcomes.
- Transformation Policy and all-day eligibility editing as a Material Rule Change that pauses the rule, requires a new preview, and rewrites existing projections on the next run.
- Rule Removal with an explicit choice to delete mapped projections or keep them as Detached Events, and Rule Replacement for changing calendars.
```

In `### Changed`:

```markdown
- Migration 3 records rule reprojection state and run outcomes.
```

- [ ] **Step 7: Run every gate**

```bash
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80
npm --prefix web run typecheck && npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build
git status --short src/calendar_sync/interfaces/api/static
```

Expected: every command passes, and the static directory has no uncommitted changes after the build.

- [ ] **Step 8: Commit, push, and open the PR** (after PR #4 merges, rebase onto `origin/main` first: `git fetch origin && git rebase origin/main`, then rerun Step 7)

```bash
git add CONTEXT.md docs CHANGELOG.md README.md
git commit -m "docs: document rule details, material rule changes, and rule removal"
git push -u origin HEAD
gh pr create --base main --title "feat: add Rule Details, policy editing, and Rule Removal" --body-file .context/pr-body.md
```

Write `.context/pr-body.md` from `.github/PULL_REQUEST_TEMPLATE.md`. It needs a Summary, the Verification checklist ticked only for gates actually run, and Screenshots from `.context/`. End the body with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. If #4 has not merged yet, open the PR with `--base fix-account-avatars-emails` and say so in the Summary, or ask the user.
