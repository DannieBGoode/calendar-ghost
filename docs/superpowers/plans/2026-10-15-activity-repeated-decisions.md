# Activity without repeated decisions: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Outside the daily pass, stop recording an `ignore` decision that repeats the event's
previous Audit Entry when nothing tracked changed, and record on every entry what brought the event
into the run and how the source compared with its Source Observation.

**Architecture:** A pure Source Comparison and a pure `repeats_previous` policy live in the domain.
`record()` in `application/sync/sync_run.py` stays the one place that appends Sync Run entries: it
compares, asks the policy, and only then saves the observation and appends. The run's reason and
the phase that found the event are kept on `SyncRunContext` and copied onto each entry. Three
nullable columns store them; Activity reads them and the Web UI explains them.

**Tech Stack:** Python 3.12, SQLite, FastAPI, pytest; React + TypeScript, Vitest, pnpm.

**Spec:** `docs/superpowers/specs/2026-10-15-activity-repeated-decisions-design.md`. Read it
before your task. The plan argues from it; if they disagree, the spec wins and you report the
mismatch.

## Global Constraints

- Read `AGENTS.md` first. It is the canonical instruction source.
- Domain imports nothing from application or infrastructure. `lint-imports` enforces it.
- Never add `noqa` for `C901`, `PLR0912`, `PLR0913`, `PLR0915`; split code instead. Ruff `max-args = 7`.
- Never add an `eslint-disable`. React Doctor must report no warnings.
- No em dashes anywhere (`tests/test_no_em_dashes.py`). Use the terms in `CONTEXT.md`; never "event copy".
- Stored enum values are a compatibility surface: new values only, never renamed.
- Event content never reaches logs. The new columns hold codes only.
- After changing an API response model: `.venv/bin/python scripts/export_openapi.py` then `(cd web && pnpm run api:types)` in the same commit.
- Quality checks (run the relevant subset per task, all of them in the last task):
  ```sh
  .venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/lint-imports && .venv/bin/pytest -q
  cd web && pnpm run api:check && pnpm run typecheck && pnpm run lint && pnpm run doctor && pnpm run knip && pnpm run test && pnpm run build
  ```
- Commit messages: imperative sentence in the repository's style, ending with
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- If an existing test breaks, decide whether the spec intends the new behavior. If it does,
  update the test and say so in your report. If it does not, fix the code.

## Review Focus

1. **Legacy audit rows** with an `action` or `reason` that the current enums do not know: `latest_for` must not raise; it returns `None`, so the decision is recorded. Test in Task 2.
2. **Entries recorded before migration 0031** have `NULL` provenance: the API returns `null` and the UI shows neither new line. Tests in Task 5.
3. **A tracked change after suppressed revisions**: revision 2 (untracked) is not recorded, revision 3 renames the event; the Source Change compares with the observation from revision 1. Test in Task 3.
4. **Same instant, different UTC offset** in the recorded time counts as the same time. Test in Task 1.
5. **One event decided twice in one run** (`test_a_revision_decided_twice_in_one_run_records_its_change_once`, `test_a_revision_both_feeds_report_in_one_run_records_its_change_once` in `tests/application/test_source_changes.py`) still record their change once. Kept green in Task 3.

---

### Task 1: Domain: Source Comparison, recorded decisions, and the repeat policy

**Files:**
- Modify: `src/calendar_sync/domain/changes.py`
- Modify: `src/calendar_sync/domain/audit.py`
- Test: `tests/domain/test_source_comparison.py` (create)
- Test: `tests/domain/test_repeated_decisions.py` (create)

**Interfaces:**
- Produces (in `domain/changes.py`):
  ```python
  class ComparisonKind(StrEnum):
      CHANGED = "changed"
      UNTRACKED = "untracked"
      SAME_REVISION = "same_revision"
      CANCELLED = "cancelled"
      NO_BASELINE = "no_baseline"

  @dataclass(frozen=True, slots=True)
  class SourceComparison:
      kind: ComparisonKind
      change: SourceChange | None = None
      observation: SourceObservation | None = None   # what to save if the decision is recorded
      completes_baseline: bool = False

      @classmethod
      def of(cls, previous: SourceObservation | None, event: CalendarEvent) -> SourceComparison: ...

  def same_time(first: EventTime | None, second: EventTime | None) -> bool: ...
  ```
- Produces (in `domain/audit.py`):
  ```python
  class RunReason(StrEnum):
      CHANGES = "changes"; FIRST_RUN = "first_run"; DAILY_PASS = "daily_pass"
      RECONCILE_NOW = "reconcile_now"; REPROJECTION = "reprojection"; RELISTED = "relisted"

  class FoundBy(StrEnum):
      SOURCE_FEED = "source_feed"; DESTINATION_FEED = "destination_feed"
      REPROJECTION = "reprojection"; PENDING_REPLAY = "pending_replay"
      RECONCILIATION = "reconciliation"

  # AuditEntry gains, after `change`:
  run_reason: RunReason | None = None
  found_by: FoundBy | None = None
  source_comparison: ComparisonKind | None = None

  @dataclass(frozen=True, slots=True)
  class RecordedDecision:
      action: AuditAction
      reason: SyncReason | None
      destination_event_id: str | None
      event: RecordedEvent | None
      @classmethod
      def of(cls, entry: AuditEntry) -> RecordedDecision: ...

  def repeats_previous(
      previous: RecordedDecision | None, entry: AuditEntry, comparison: SourceComparison
  ) -> bool: ...
  ```

- [ ] **Step 1: Write the failing comparison tests** in `tests/domain/test_source_comparison.py`.
  Use `tests.helpers.event` and `dataclasses.replace` as `tests/application/test_source_changes.py` does.

```python
"""How a source event compares with the rule's Source Observation of it."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta, timezone

from calendar_sync.domain.changes import (
    ComparisonKind,
    SourceComparison,
    SourceField,
    SourceObservation,
    same_time,
)
from calendar_sync.domain.model import EventStatus, TimedInterval
from tests.helpers import NOW, event

GUESTS = ("ana@example.com",)


def _observed(**changes: object) -> SourceObservation:
    observation = SourceObservation.of(replace(event(), guests=GUESTS, **changes))  # type: ignore[arg-type]
    assert observation is not None
    return observation


def test_no_observation_is_no_baseline_and_saves_the_event() -> None:
    comparison = SourceComparison.of(None, replace(event(), guests=GUESTS))
    assert comparison.kind is ComparisonKind.NO_BASELINE
    assert comparison.change is None
    assert comparison.observation is not None


def test_the_same_revision_saves_nothing() -> None:
    comparison = SourceComparison.of(_observed(), replace(event(), guests=GUESTS))
    assert comparison.kind is ComparisonKind.SAME_REVISION
    assert comparison.observation is None
    assert not comparison.completes_baseline


def test_a_new_revision_with_the_same_tracked_fields_is_untracked() -> None:
    comparison = SourceComparison.of(_observed(), replace(event(), guests=GUESTS, revision="r2"))
    assert comparison.kind is ComparisonKind.UNTRACKED
    assert comparison.change is None
    assert comparison.observation is not None
    assert comparison.observation.revision == "r2"
    assert not comparison.completes_baseline


def test_a_new_revision_with_a_new_title_is_changed() -> None:
    comparison = SourceComparison.of(
        _observed(), replace(event(), guests=GUESTS, revision="r2", title="Renamed")
    )
    assert comparison.kind is ComparisonKind.CHANGED
    assert comparison.change is not None
    assert comparison.change.fields == (SourceField.TITLE,)


def test_learning_a_complete_guest_list_completes_the_baseline() -> None:
    previous = _observed(guests=None)
    comparison = SourceComparison.of(previous, replace(event(), guests=GUESTS, revision="r2"))
    assert comparison.kind is ComparisonKind.UNTRACKED
    assert comparison.completes_baseline


def test_a_partial_guest_list_keeps_the_known_one() -> None:
    comparison = SourceComparison.of(_observed(), replace(event(), guests=None, revision="r2"))
    assert comparison.observation is not None
    assert comparison.observation.guests == GUESTS
    assert not comparison.completes_baseline


def test_a_cancelled_event_is_cancelled_and_saves_nothing() -> None:
    cancelled = replace(event(), status=EventStatus.CANCELLED, time=None, revision="r2")
    comparison = SourceComparison.of(_observed(), cancelled)
    assert comparison.kind is ComparisonKind.CANCELLED
    assert comparison.observation is None


def test_times_are_the_same_when_they_name_the_same_instants() -> None:
    utc = TimedInterval(NOW, NOW + timedelta(hours=1))
    shifted = timezone(timedelta(hours=2))
    local = TimedInterval(NOW.astimezone(shifted), (NOW + timedelta(hours=1)).astimezone(shifted))
    assert same_time(utc, local)
    assert same_time(None, None)
    assert not same_time(utc, None)
    assert not same_time(utc, TimedInterval(NOW, NOW + timedelta(hours=2)))
```

  If `tests.helpers.event()` has no guests or a fixed revision different from what these tests
  assume, read `tests/helpers.py` and adjust the arguments, not the assertions.

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/pytest tests/domain/test_source_comparison.py -q`
Expected: FAIL with `ImportError` for `ComparisonKind`.

- [ ] **Step 3: Implement in `domain/changes.py`**, below `SourceChange`:

```python
class ComparisonKind(StrEnum):
    """How a source event compared with the rule's Source Observation of it; stored values are a
    compatibility surface."""

    CHANGED = "changed"
    UNTRACKED = "untracked"
    SAME_REVISION = "same_revision"
    CANCELLED = "cancelled"
    NO_BASELINE = "no_baseline"


@dataclass(frozen=True, slots=True)
class SourceComparison:
    """A source event compared with what the rule last observed, before anything is saved."""

    kind: ComparisonKind
    change: SourceChange | None = None
    observation: SourceObservation | None = None
    """The observation to save if the decision is recorded; None when there is nothing to save."""
    completes_baseline: bool = False
    """The new observation knows a guest list, conferencing, or response the stored one did not."""

    @classmethod
    def of(cls, previous: SourceObservation | None, event: CalendarEvent) -> SourceComparison:
        current = SourceObservation.of(event)
        if current is None:
            # A cancellation keeps the last observation, so a restored event compares with it.
            if event.status is EventStatus.CANCELLED:
                return cls(ComparisonKind.CANCELLED)
            return cls(ComparisonKind.NO_BASELINE)
        if previous is None:
            return cls(ComparisonKind.NO_BASELINE, observation=current)
        if previous.revision == current.revision:
            return cls(ComparisonKind.SAME_REVISION)
        current = current.completed_by(previous)
        change = SourceChange.between(previous, current)
        return cls(
            ComparisonKind.CHANGED if change else ComparisonKind.UNTRACKED,
            change,
            current,
            completes_baseline=_learns(previous, current),
        )


def _learns(previous: SourceObservation, current: SourceObservation) -> bool:
    return (
        (previous.guests is None and current.guests is not None)
        or (previous.conferencing is None and current.conferencing is not None)
        or (previous.response is None and current.response is not None)
    )


def same_time(first: EventTime | None, second: EventTime | None) -> bool:
    """Whether two recorded times name the same instants or days."""
    if first is None or second is None:
        return first is second
    return _instants(first) == _instants(second)
```

- [ ] **Step 4: Run the comparison tests**

Run: `.venv/bin/pytest tests/domain/test_source_comparison.py -q`
Expected: PASS.

- [ ] **Step 5: Write the failing policy tests** in `tests/domain/test_repeated_decisions.py`:

```python
"""An ignore decision that repeats the event's previous entry, with nothing new, is not recorded."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from calendar_sync.domain.audit import (
    AuditAction,
    AuditEntry,
    AuditOutcome,
    RecordedDecision,
    RecordedEvent,
    repeats_previous,
)
from calendar_sync.domain.changes import ComparisonKind, SourceComparison
from calendar_sync.domain.model import SyncReason, TimedInterval
from tests.helpers import NOW, rule

TIME = TimedInterval(NOW, NOW + timedelta(hours=1))
SEMINAR = RecordedEvent(title="Seminar", time=TIME, recurring=True)
UNTRACKED = SourceComparison(ComparisonKind.UNTRACKED)


def _entry(**changes: object) -> AuditEntry:
    entry = AuditEntry(
        occurred_at=NOW,
        rule_id=rule().id,
        action=AuditAction.IGNORE,
        outcome=AuditOutcome.SKIPPED,
        source_event_id="seminar",
        destination_event_id=None,
        reason=SyncReason.SERIES_WITHOUT_OCCURRENCES,
        event=SEMINAR,
    )
    return replace(entry, **changes)  # type: ignore[arg-type]


PREVIOUS = RecordedDecision.of(_entry())


def test_an_unchanged_repeat_of_the_previous_skip_is_a_repeat() -> None:
    assert repeats_previous(PREVIOUS, _entry(), UNTRACKED)
    assert repeats_previous(PREVIOUS, _entry(), SourceComparison(ComparisonKind.SAME_REVISION))


def test_the_same_instant_in_another_offset_is_a_repeat() -> None:
    shifted = TimedInterval(TIME.starts_at.astimezone(), TIME.ends_at.astimezone())
    entry = _entry(event=replace(SEMINAR, time=shifted))
    assert repeats_previous(PREVIOUS, entry, UNTRACKED)


def test_a_cancelled_repeat_of_a_cancelled_previous_entry_is_a_repeat() -> None:
    cancelled = replace(SEMINAR, cancelled=True)
    previous = RecordedDecision.of(_entry(event=cancelled))
    assert repeats_previous(previous, _entry(event=cancelled), SourceComparison(ComparisonKind.CANCELLED))


@pytest.mark.parametrize(
    ("previous", "entry", "comparison"),
    [
        pytest.param(None, _entry(), UNTRACKED, id="no previous entry"),
        pytest.param(PREVIOUS, _entry(action=AuditAction.CONFLICT, outcome=AuditOutcome.BLOCKED), UNTRACKED, id="not an ignore"),
        pytest.param(PREVIOUS, _entry(), SourceComparison(ComparisonKind.CHANGED), id="tracked change"),
        pytest.param(PREVIOUS, _entry(), SourceComparison(ComparisonKind.NO_BASELINE), id="no baseline"),
        pytest.param(PREVIOUS, _entry(event=replace(SEMINAR, cancelled=True)), SourceComparison(ComparisonKind.CANCELLED), id="cancelled after live"),
        pytest.param(PREVIOUS, _entry(), SourceComparison(ComparisonKind.UNTRACKED, completes_baseline=True), id="completes the baseline"),
        pytest.param(RecordedDecision.of(_entry(action=AuditAction.CONFLICT)), _entry(), UNTRACKED, id="previous was a block"),
        pytest.param(RecordedDecision.of(_entry(reason=SyncReason.PROJECTION_CURRENT)), _entry(), UNTRACKED, id="different reason"),
        pytest.param(RecordedDecision.of(_entry(destination_event_id="other")), _entry(), UNTRACKED, id="different destination"),
        pytest.param(RecordedDecision.of(_entry(event=None)), _entry(), UNTRACKED, id="previous has no event"),
        pytest.param(PREVIOUS, _entry(event=None), UNTRACKED, id="entry has no event"),
        pytest.param(PREVIOUS, _entry(event=replace(SEMINAR, title="Renamed")), UNTRACKED, id="different title"),
        pytest.param(PREVIOUS, _entry(event=replace(SEMINAR, time=TimedInterval(NOW, NOW + timedelta(hours=2)))), UNTRACKED, id="different time"),
        pytest.param(PREVIOUS, _entry(event=replace(SEMINAR, recurring=False)), UNTRACKED, id="no longer recurring"),
        pytest.param(RecordedDecision.of(_entry(event=replace(SEMINAR, cancelled=True))), _entry(), UNTRACKED, id="restored"),
    ],
)
def test_anything_new_is_recorded(
    previous: RecordedDecision | None, entry: AuditEntry, comparison: SourceComparison
) -> None:
    assert not repeats_previous(previous, entry, comparison)
```

  Format the long `pytest.param` lines with `ruff format`; keep them readable.

- [ ] **Step 6: Run them to see them fail**

Run: `.venv/bin/pytest tests/domain/test_repeated_decisions.py -q`
Expected: FAIL with `ImportError` for `RecordedDecision`.

- [ ] **Step 7: Implement in `domain/audit.py`.** Add `RunReason` and `FoundBy` after
  `AuditOutcome`, the three fields at the end of `AuditEntry` (each with a one-line docstring
  in the existing style), then:

```python
@dataclass(frozen=True, slots=True)
class RecordedDecision:
    """What an earlier Audit Entry decided about its source event, as a later one compares it."""

    action: AuditAction
    reason: SyncReason | None
    destination_event_id: str | None
    event: RecordedEvent | None

    @classmethod
    def of(cls, entry: AuditEntry) -> RecordedDecision:
        return cls(entry.action, entry.reason, entry.destination_event_id, entry.event)


def repeats_previous(
    previous: RecordedDecision | None, entry: AuditEntry, comparison: SourceComparison
) -> bool:
    """Whether a skip says nothing the event's previous entry did not (ADR 0036).

    The caller applies it only outside the daily pass and only to an entry recorded under the
    event's own identity.
    """
    if previous is None or entry.action is not AuditAction.IGNORE:
        return False
    if not _nothing_new(comparison, previous):
        return False
    return (
        previous.action is entry.action
        and previous.reason == entry.reason
        and previous.destination_event_id == entry.destination_event_id
        and _same_event(previous.event, entry.event)
    )


def _nothing_new(comparison: SourceComparison, previous: RecordedDecision) -> bool:
    if comparison.completes_baseline:
        return False
    if comparison.kind is ComparisonKind.CANCELLED:
        return previous.event is not None and previous.event.cancelled
    return comparison.kind in {ComparisonKind.UNTRACKED, ComparisonKind.SAME_REVISION}


def _same_event(first: RecordedEvent | None, second: RecordedEvent | None) -> bool:
    return (
        first is not None
        and second is not None
        and first.title == second.title
        and same_time(first.time, second.time)
        and first.recurring == second.recurring
        and first.cancelled == second.cancelled
    )
```

  Import `ComparisonKind`, `SourceComparison`, `same_time` from `domain.changes` (it already
  imports `SourceChange` from there).

- [ ] **Step 8: Run the domain tests and the full domain suite**

Run: `.venv/bin/pytest tests/domain -q && .venv/bin/mypy && .venv/bin/ruff check src tests`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/calendar_sync/domain/changes.py src/calendar_sync/domain/audit.py tests/domain/test_source_comparison.py tests/domain/test_repeated_decisions.py
git commit -m "Compare a source event with its observation, and tell a repeated skip from news"
```

---

### Task 2: Persistence: provenance columns and the previous-entry lookup

**Files:**
- Create: `src/calendar_sync/infrastructure/persistence/0031_audit_entry_provenance.sql`
- Modify: `src/calendar_sync/infrastructure/persistence/migrations.py` (register `(31, "0031_audit_entry_provenance.sql")`)
- Modify: `src/calendar_sync/application/sync/ports.py` (`AuditRepository`)
- Modify: `src/calendar_sync/infrastructure/persistence/sqlite.py` (`SqliteAuditRepository`)
- Modify: `src/calendar_sync/infrastructure/persistence/memory.py` (`InMemoryAuditRepository`)
- Test: `tests/contracts/persistence.py`, `tests/adapters/test_sqlite.py` (or the module that already tests `SqliteAuditRepository`; find it with `grep -rn "SqliteAuditRepository\|audit.append" tests/adapters`)

**Interfaces:**
- Consumes: `RecordedDecision`, `RunReason`, `FoundBy`, `ComparisonKind`, the new `AuditEntry` fields (Task 1).
- Produces on `AuditRepository`:
  ```python
  def latest_for(self, rule_id: SyncRuleId, source_event_id: str) -> RecordedDecision | None:
      """The decision of the latest entry (highest id) for this rule and source event."""
  ```

- [ ] **Step 1: Write the failing contract tests** in `PersistenceContract` (`tests/contracts/persistence.py`), next to the other audit tests (search for `uow.audit.append`). Follow that file's harness and `_commit_as` patterns:

```python
    def test_the_latest_entry_for_an_event_is_its_previous_decision(
        self, harness: PersistenceHarness
    ) -> None:
        first = _skip("seminar", SyncReason.SERIES_NOT_SYNCHRONIZED)
        latest = _skip("seminar", SyncReason.SERIES_WITHOUT_OCCURRENCES)
        other_event = _skip("other", SyncReason.DECLINED)
        harness.commit(lambda uow: [uow.audit.append(e) for e in (first, latest, other_event)])

        with harness.unit_of_work() as uow:
            assert uow.audit.latest_for(RULE.id, "seminar") == RecordedDecision.of(latest)
            assert uow.audit.latest_for(RULE.id, "missing") is None
            assert uow.audit.latest_for(OTHER_RULE.id, "seminar") is None
```

  with a module helper:

```python
def _skip(source_event_id: str, reason: SyncReason) -> AuditEntry:
    return AuditEntry(
        occurred_at=NOW,
        rule_id=RULE.id,
        action=AuditAction.IGNORE,
        outcome=AuditOutcome.SKIPPED,
        source_event_id=source_event_id,
        reason=reason,
        event=RecordedEvent(
            title="Seminar", time=TimedInterval(NOW, NOW + timedelta(hours=1)), recurring=True
        ),
        run_reason=RunReason.CHANGES,
        found_by=FoundBy.SOURCE_FEED,
        source_comparison=ComparisonKind.UNTRACKED,
    )
```

  Use the harness's real helper names (`harness.commit`, `OTHER_RULE`, etc.). If they differ,
  adapt to what the file provides; if no second rule exists, save one as other tests do. Also
  add an all-day variant (`AllDayRange`) so date round-tripping is covered.

- [ ] **Step 2: Write the failing SQLite-only tests** beside the existing SQLite audit tests:

```python
def test_the_previous_decision_lookup_uses_the_event_index(tmp_path: Path) -> None:
    connection = ...  # open a migrated database the way neighbouring tests do
    plan = connection.execute(
        "EXPLAIN QUERY PLAN " + SqliteAuditRepository.LATEST_FOR_SQL, ("rule", "event", "user")
    ).fetchall()
    assert any("audit_entries_source_event" in str(row) for row in plan)


def test_an_unknown_stored_reason_reads_as_no_previous_decision(tmp_path: Path) -> None:
    # Insert a row with reason 'retired_reason' and action 'ignore' directly with SQL,
    # then latest_for returns None instead of raising.


def test_another_users_entry_is_never_the_previous_decision(tmp_path: Path) -> None:
    # Append an entry as user A, then latest_for as user B with the same rule id and event id
    # returns None. Use the user fixtures in tests/users.py.


def test_provenance_round_trips_through_the_columns(tmp_path: Path) -> None:
    # Append an entry with run_reason, found_by, source_comparison set; read the row with SQL
    # and assert the three stored codes.
```

  Fill in the elided setup from the neighbouring tests in the same file. Each test must fail
  before Step 4.

- [ ] **Step 3: Run them to see them fail**

Run: `.venv/bin/pytest tests/adapters/test_persistence_contract.py tests/adapters/test_sqlite.py -q -k "previous_decision or latest_entry or provenance"`
Expected: FAIL (`latest_for` missing).

- [ ] **Step 4: Implement.**

  Migration `0031_audit_entry_provenance.sql`:

```sql
-- What brought each event into the run, and how it compared with its Source Observation
-- (ADR 0036). Codes only, never event content; earlier entries keep NULL.
ALTER TABLE audit_entries ADD COLUMN run_reason TEXT;
ALTER TABLE audit_entries ADD COLUMN found_by TEXT;
ALTER TABLE audit_entries ADD COLUMN source_comparison TEXT;
```

  Port (`ports.py`, `AuditRepository`):

```python
    def latest_for(self, rule_id: SyncRuleId, source_event_id: str) -> RecordedDecision | None:
        """The decision of the latest entry, by id, for this rule and source event."""
        ...
```

  SQLite: add the three columns to the `INSERT` in `append` (`entry.run_reason`,
  `entry.found_by`, `entry.source_comparison`), and:

```python
    LATEST_FOR_SQL = """
        SELECT action, reason, destination_event_id, event_title, event_starts, event_ends,
               event_all_day, event_recurring, event_cancelled
        FROM audit_entries INDEXED BY audit_entries_source_event
        WHERE rule_id = ? AND source_event_id = ? AND user_id = ?
        ORDER BY id DESC LIMIT 1
    """

    def latest_for(self, rule_id: SyncRuleId, source_event_id: str) -> RecordedDecision | None:
        row = self._connection.execute(
            self.LATEST_FOR_SQL, (rule_id.value, source_event_id, self._user)
        ).fetchone()
        if row is None:
            return None
        try:
            action = AuditAction(row["action"])
            reason = SyncReason(row["reason"]) if row["reason"] is not None else None
        except ValueError:
            # A value this release no longer knows proves nothing, so the decision is recorded.
            return None
        return RecordedDecision(action, reason, row["destination_event_id"], _recorded_event(row))
```

  `_recorded_event(row)` returns `None` when `event_title` is `NULL`; otherwise a
  `RecordedEvent` whose `time` is `None` when `event_starts` is `NULL`, an `AllDayRange` of
  `date.fromisoformat(...)` when `event_all_day`, else a `TimedInterval` of
  `datetime.fromisoformat(...)`. Check how `append` writes these columns (lines ~598-635) and
  mirror it exactly. If `INDEXED BY` fails because the index name differs after migration 21,
  use the name in `0021_users.sql` (`audit_entries_source_event`).

  Memory (`InMemoryAuditRepository`):

```python
    def latest_for(self, rule_id: SyncRuleId, source_event_id: str) -> RecordedDecision | None:
        for entry in reversed(self._state.audit):
            if entry.rule_id == rule_id and entry.source_event_id == source_event_id:
                return RecordedDecision.of(entry)
        return None
```

  Any other class implementing `AuditRepository` (search `def forget_change_values`) gets the
  same method.

- [ ] **Step 5: Run the persistence suites**

Run: `.venv/bin/pytest tests/adapters tests/contracts -q && .venv/bin/mypy`
Expected: PASS, including `tests/adapters/test_user_isolation_schema.py` and the migration tests.

- [ ] **Step 6: Commit**

```bash
git add src/calendar_sync/infrastructure/persistence src/calendar_sync/application/sync/ports.py tests
git commit -m "Store where each Audit Entry came from, and look up an event's previous decision"
```

---

### Task 3: Application: compare before observing, and leave out repeated skips

**Files:**
- Modify: `src/calendar_sync/application/sync/sync_run.py` (`SyncRunContext`, `record`, `_observe`, `SyncRunLog.finished`)
- Modify: `src/calendar_sync/application/sync/occurrences.py` (`SynchronizeOccurrences._record`)
- Test: `tests/application/test_repeated_decisions.py` (create)
- Test: existing `tests/application/test_source_changes.py` stays green

**Interfaces:**
- Consumes: `SourceComparison`, `repeats_previous`, `RecordedDecision`, `AuditRepository.latest_for` (Tasks 1-2).
- Produces:
  - `SyncRunContext.unrecorded: int = 0`
  - `record(run, entry, observed=None, *, own_identity: bool = True) -> None`
  - `SyncRunLog.finished(counts, unrecorded: int)` printing `unrecorded=N` right after the decision counts.

- [ ] **Step 1: Write the failing application tests** in `tests/application/test_repeated_decisions.py`. Reuse the helpers from `tests/application/test_source_changes.py` (`FakeCalendars`, `enabled_rule_factory`, `sync_use_case`, `event`, `rule`):

```python
"""Outside the daily pass, a skip that repeats the event's previous entry is not recorded."""

from __future__ import annotations

from dataclasses import replace

from calendar_sync.domain.audit import AuditAction
from calendar_sync.domain.changes import SourceField
from calendar_sync.domain.model import CalendarEvent, SyncReason
from calendar_sync.infrastructure.persistence.memory import InMemoryUserUnitOfWorkFactory
from tests.fake_calendar import FakeCalendars, enabled_rule_factory, sync_use_case
from tests.helpers import event, rule

GUESTS = ("ana@example.com",)


def _synced() -> tuple[FakeCalendars, InMemoryUserUnitOfWorkFactory]:
    calendars = FakeCalendars()
    calendars.put(replace(event(), guests=GUESTS, conferencing=()))
    factory = enabled_rule_factory()
    sync_use_case(factory, calendars).execute(rule().id)
    return calendars, factory


def _send(calendars: FakeCalendars, factory: InMemoryUserUnitOfWorkFactory, *events: CalendarEvent) -> int:
    recorded = len(factory.state.audit)
    calendars.report(*(calendars.put(item) for item in events))
    sync_use_case(factory, calendars).execute(rule().id)
    return recorded


def _revision(name: str, **changes: object) -> CalendarEvent:
    return replace(event(), guests=GUESTS, conferencing=(), revision=name, **changes)  # type: ignore[arg-type]


def test_an_event_sent_again_with_nothing_tracked_changed_is_not_recorded_twice() -> None:
    calendars, factory = _synced()
    _send(calendars, factory, _revision("r2"))  # first "already current" after the create: recorded
    assert factory.state.audit[-1].reason == SyncReason.PROJECTION_CURRENT

    recorded = _send(calendars, factory, _revision("r3"))

    assert factory.state.audit[recorded:] == []
    observation = factory.state.observations[(rule().id, event().reference)][0]
    assert observation.revision == "r2"


def test_a_tracked_change_after_a_left_out_revision_compares_with_the_last_recorded_one() -> None:
    calendars, factory = _synced()
    _send(calendars, factory, _revision("r2"))
    _send(calendars, factory, _revision("r3"))

    recorded = _send(calendars, factory, _revision("r4", title="Renamed"))

    [entry] = factory.state.audit[recorded:]
    assert entry.change is not None
    assert entry.change.fields == (SourceField.TITLE,)
    assert entry.change.before.revision == "r2"
```

  Add these tests to the same file, written in the same style (set up the state the existing
  tests in `tests/application/test_recurring_sync.py`, `test_lone_occurrences.py`, and
  `test_reconcile_sync_rule.py` use for series, occurrences, and blocks):

  - `test_a_complete_guest_list_after_a_partial_one_is_recorded_and_saved`: first observation with `guests=None`, then a revision with `GUESTS` and nothing else changed: one entry recorded, and the stored observation now has `GUESTS`.
  - `test_a_skipped_series_sent_again_unchanged_is_not_recorded`: a series whose every occurrence is cancelled records `series_without_occurrences` once; a new revision with the same tracked fields records nothing.
  - `test_a_series_that_loses_its_last_occurrence_is_recorded`: previous entry `projection_current`, then every occurrence cancelled: `series_without_occurrences` recorded.
  - `test_an_occurrence_without_its_own_source_is_recorded_every_time`: an occurrence decided under its series' identity (no `source_ref`) is recorded on each run.
  - `test_a_blocked_event_decided_again_without_a_change_is_recorded_and_unblocks`: a block, then the same event decided `ignore` with an untracked revision: recorded, and `open_blocks` (see `tests/adapters/test_activity_queries.py` for how to call it, or assert the latest entry is no longer a block in memory) no longer lists it.
  - `test_a_cancelled_series_sent_again_is_not_recorded_and_a_restored_one_is`: cancelled twice: second not recorded; restored with identical content: recorded and compared with the kept observation.
  - `test_the_daily_pass_records_what_it_recorded_before`: run `execute(rule().id, full=True)` twice with nothing changed; both passes record their `projection_current` check, as today.
  - `test_the_run_log_counts_the_entries_it_left_out`: with `caplog` at INFO, the `run finished` line contains `unrecorded=1` for the run in the first test.

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/pytest tests/application/test_repeated_decisions.py -q`
Expected: the "not recorded" tests FAIL (entries are still appended); the others may pass already.

- [ ] **Step 3: Implement in `sync_run.py`.** Add `unrecorded: int = 0` to `SyncRunContext`
  with the docstring `"""Decisions this run counted but left out of Activity as repeats (ADR 0036)."""`.
  Replace `record` and `_observe` with:

```python
def record(
    run: SyncRunContext,
    entry: AuditEntry,
    observed: CalendarEvent | None = None,
    *,
    own_identity: bool = True,
) -> None:
    """Append an Audit Entry unless its decision is one Activity deliberately leaves out.

    An entry about `observed` also records how it compared with the rule's Source Observation.
    Outside the daily pass, a skip that repeats the event's previous entry with nothing new is
    counted but not recorded (ADR 0036). Only recorded decisions observe, so no change is
    absorbed by a decision Activity never shows. `own_identity` is false when the entry is filed
    under another event's identifier, so its previous entry may be about something else.
    """
    reason = entry.reason
    if reason in UNRECORDED_REASONS or (run.daily_pass and reason in UNRECORDED_ON_DAILY_PASS):
        return
    comparison = _compare(run, observed) if observed is not None else None
    if comparison is not None and own_identity and _repeats(run, entry, comparison):
        run.unrecorded += 1
        return
    if comparison is not None:
        assert observed is not None
        if comparison.observation is not None:
            run.uow.observations.save(
                run.rule.id, observed.reference, comparison.observation, entry.occurred_at
            )
        entry = replace(entry, change=comparison.change, source_comparison=comparison.kind)
    run.uow.audit.append(entry)


def _compare(run: SyncRunContext, event: CalendarEvent) -> SourceComparison:
    return SourceComparison.of(run.uow.observations.get(run.rule.id, event.reference), event)


def _repeats(run: SyncRunContext, entry: AuditEntry, comparison: SourceComparison) -> bool:
    if run.daily_pass or entry.action is not AuditAction.IGNORE or entry.source_event_id is None:
        return False
    previous = run.uow.audit.latest_for(run.rule.id, entry.source_event_id)
    return repeats_previous(previous, entry, comparison)
```

  `SourceObservation`, `SourceChange` imports that become unused are removed. Task 4 adds
  provenance to the same `replace`; do not add it here.

  `SyncRunLog.finished` gains `unrecorded: int` and prints it after `_decisions(counts)`:
  `"run finished %s in %s %s unrecorded=%d %s"`. Update its caller in `synchronization.py`
  (`log.finished(run.counts, run.unrecorded)`).

- [ ] **Step 4: Pass `own_identity` from occurrences.** In `SynchronizeOccurrences._record`
  (`occurrences.py`), add `own_identity=source_ref is not None` to the `record(...)` call.

- [ ] **Step 5: Run the application suite**

Run: `.venv/bin/pytest tests/application -q`
Expected: the new tests PASS. If an existing test fails because an incremental run no longer
records an unchanged repeat, check it against the spec (Part 2) and update its expectation; list
every such test in your report.

- [ ] **Step 6: Full Python checks**

Run: `.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/lint-imports && .venv/bin/pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/calendar_sync/application/sync tests/application
git commit -m "Leave a skip out of Activity when it repeats the event's previous entry with nothing new"
```

---

### Task 4: Application: what brought the event into the run

**Files:**
- Modify: `src/calendar_sync/domain/runs.py` (add `RunOrigin`)
- Modify: `src/calendar_sync/application/sync/sync_run.py` (`SyncRunContext.run_reason`, `found_by`, `finding`; `record` copies them)
- Modify: `src/calendar_sync/application/sync/change_feeds.py` (`begin` takes `origin`, sets `run_reason`)
- Modify: `src/calendar_sync/application/sync/synchronization.py` (`execute`, `_execute_measured`, `_execute_serialized`, `_record_unverifiable`)
- Modify: `src/calendar_sync/application/sync/reconciliation.py` (`ReconcileNow._execute` passes the origin; Full Reconciliation entries get `found_by`)
- Test: `tests/application/test_run_provenance.py` (create)

**Interfaces:**
- Consumes: `RunReason`, `FoundBy` (Task 1), `record` (Task 3).
- Produces:
  ```python
  class RunOrigin(StrEnum):            # domain/runs.py
      SCHEDULED = "scheduled"
      RECONCILE_NOW = "reconcile_now"

  # SyncRunContext
  run_reason: RunReason | None = None
  found_by: FoundBy | None = None
  @contextmanager
  def finding(self, found_by: FoundBy) -> Iterator[None]: ...

  # ExecuteSyncRule
  def execute(self, rule_id, *, full=False, work=None, origin: RunOrigin = RunOrigin.SCHEDULED) -> SyncRunResult
  # ChangeFeedCursors
  def begin(self, uow, rule, *, full, origin, log, work) -> tuple[SyncRunContext, ChangeFeeds]

  def run_reason(*, reproject: bool, origin: RunOrigin, full: bool,
                 saved_source: bool, saved_destination: bool, feeds: ChangeFeeds) -> RunReason
  ```

- [ ] **Step 1: Write the failing tests** in `tests/application/test_run_provenance.py`:

```python
"""Each recorded entry says why its run read the calendars as it did, and which work found it."""

from __future__ import annotations

import pytest

from calendar_sync.application.sync.change_feeds import ChangeFeeds, run_reason
from calendar_sync.application.sync.ports import ProviderChangeSet
from calendar_sync.domain.audit import FoundBy, RunReason
from calendar_sync.domain.runs import RunOrigin

EMPTY = ProviderChangeSet((), "cursor", complete=False)


def _feeds(source_listed: bool = False, destination_listed: bool = False) -> ChangeFeeds:
    return ChangeFeeds(EMPTY, EMPTY, source_listed, destination_listed)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (dict(reproject=True, origin=RunOrigin.RECONCILE_NOW, full=True), RunReason.REPROJECTION),
        (dict(origin=RunOrigin.RECONCILE_NOW, full=True), RunReason.RECONCILE_NOW),
        (dict(full=True), RunReason.DAILY_PASS),
        (dict(saved_source=False, saved_destination=False, feeds=_feeds(True, True)), RunReason.FIRST_RUN),
        (dict(feeds=_feeds(source_listed=True)), RunReason.RELISTED),
        (dict(feeds=_feeds(destination_listed=True)), RunReason.RELISTED),
        (dict(saved_destination=False, feeds=_feeds(destination_listed=True)), RunReason.RELISTED),
        ({}, RunReason.CHANGES),
    ],
)
def test_the_first_reason_that_applies_names_the_run(kwargs: dict[str, object], expected: RunReason) -> None:
    arguments: dict[str, object] = dict(
        reproject=False, origin=RunOrigin.SCHEDULED, full=False,
        saved_source=True, saved_destination=True, feeds=_feeds(),
    )
    arguments.update(kwargs)
    assert run_reason(**arguments) is expected  # type: ignore[arg-type]
```

  Add end-to-end tests in the same file, using `FakeCalendars`, `enabled_rule_factory`,
  `sync_use_case` as in Task 3 and the Reconcile Now setup from
  `tests/application/test_reconcile_sync_rule.py`:

  - `test_a_source_change_is_found_by_the_source_feed`: an incremental run with a renamed source event: the entry has `run_reason=CHANGES`, `found_by=SOURCE_FEED`, `source_comparison=CHANGED`.
  - `test_an_edited_projection_is_found_by_the_destination_feed`: edit the projection in the destination (see `test_a_revision_both_feeds_report_in_one_run_records_its_change_once`): the repair entry has `found_by=DESTINATION_FEED`.
  - `test_a_daily_pass_entry_says_so`: `execute(rule().id, full=True)`: `run_reason=DAILY_PASS`.
  - `test_the_first_run_says_so`: the first run's create entry has `run_reason=FIRST_RUN`.
  - `test_a_rejected_source_cursor_relists`: make the fake reject the source cursor (find how `tests/fake_calendar.py` does it; search `complete=True`) and expect `RELISTED`.
  - `test_reconcile_now_names_its_pass_and_its_own_entries`: entries of the pass have `run_reason=RECONCILE_NOW`; a Full Reconciliation block entry has `found_by=RECONCILIATION` and `run_reason is None`.
  - `test_a_reprojection_entry_says_the_rule_changed`: a rule with `reprojection_required`: an entry decided in `_reproject_remaining` has `run_reason=REPROJECTION` and `found_by=REPROJECTION`.
  - `test_a_pending_replay_is_found_by_the_replay`: a pending exception replay left by an earlier run (see `tests/application/test_recurring_sync.py`, search `replays`): its occurrence entry has `found_by=PENDING_REPLAY`; an immediate replay during a source change keeps `SOURCE_FEED`.
  - `test_an_unverifiable_source_is_recorded_with_its_provenance`: the `SOURCE_UNVERIFIABLE` block (search tests for it) now carries `run_reason` and `found_by`.
  - `test_finding_restores_the_outer_work_when_it_raises`:

```python
def test_finding_restores_the_outer_work_when_it_raises() -> None:
    run = ...  # build a SyncRunContext the way tests/application tests that use it do, or use
    #            dataclasses.replace on one returned by ChangeFeedCursors.begin in a fake setup
    with run.finding(FoundBy.SOURCE_FEED):
        with pytest.raises(RuntimeError), run.finding(FoundBy.PENDING_REPLAY):
            raise RuntimeError
        assert run.found_by is FoundBy.SOURCE_FEED
    assert run.found_by is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/pytest tests/application/test_run_provenance.py -q`
Expected: FAIL with `ImportError` for `run_reason`.

- [ ] **Step 3: Implement.**

  `domain/runs.py`:

```python
class RunOrigin(StrEnum):
    """Who started a Sync Run, where it changes what the run means."""

    SCHEDULED = "scheduled"
    RECONCILE_NOW = "reconcile_now"
```

  `change_feeds.py`:

```python
def run_reason(
    *,
    reproject: bool,
    origin: RunOrigin,
    full: bool,
    saved_source: bool,
    saved_destination: bool,
    feeds: ChangeFeeds,
) -> RunReason:
    """Why the run read the calendars as it did: the first reason that applies (ADR 0036)."""
    if reproject:
        return RunReason.REPROJECTION
    if origin is RunOrigin.RECONCILE_NOW:
        return RunReason.RECONCILE_NOW
    if full:
        return RunReason.DAILY_PASS
    if not saved_source and not saved_destination:
        return RunReason.FIRST_RUN
    if feeds.source_listed or feeds.destination_listed:
        return RunReason.RELISTED
    return RunReason.CHANGES
```

  In `begin`, add the `origin: RunOrigin` keyword, keep the saved destination cursor in a
  variable before `full_run` clears it, and pass
  `run_reason=run_reason(reproject=reproject, origin=origin, full=full, saved_source=previous_cursor is not None, saved_destination=saved_destination is not None, feeds=feeds)`
  to `SyncRunContext`. `log.begin` keeps its current arguments. If `begin` grows past Ruff's
  complexity bounds, move the `SyncRunContext` construction into a helper.

  `sync_run.py`: add to `SyncRunContext`:

```python
    run_reason: RunReason | None = None
    """Why this run read the calendars as it did."""
    found_by: FoundBy | None = None
    """The work that led to the decisions being made now; nested work inherits it."""

    @contextmanager
    def finding(self, found_by: FoundBy) -> Iterator[None]:
        """Name the work that finds events until the block ends, then restore the earlier one."""
        outer = self.found_by
        self.found_by = found_by
        try:
            yield
        finally:
            self.found_by = outer
```

  and in `record`, set provenance on every appended entry (before the `comparison` branch):

```python
    entry = replace(entry, run_reason=run.run_reason, found_by=run.found_by)
```

  `synchronization.py`:
  - `execute(..., origin: RunOrigin = RunOrigin.SCHEDULED)`, passed through `_execute_measured`
    and `_execute_serialized` to `change_feeds.begin(..., origin=origin, ...)`.
  - In `_execute_serialized`:

```python
            with run.finding(FoundBy.SOURCE_FEED):
                self._synchronize_sources(run, feeds.source)
            with run.finding(FoundBy.DESTINATION_FEED):
                self._repair_destinations(run, feeds.destination)
            if run.reproject:
                with run.finding(FoundBy.REPROJECTION):
                    self._reproject_remaining(run)
            with run.finding(FoundBy.PENDING_REPLAY):
                self.exception_replays.finish_pending(run)
```

  - `_record_unverifiable` builds the same `AuditEntry` and calls `record(run, entry)` instead
    of `run.uow.audit.append(entry)`.

  `reconciliation.py`:
  - `ReconcileNow._execute` calls `self.synchronize.execute(rule_id, full=True, work=work, origin=RunOrigin.RECONCILE_NOW)`.
  - The `AuditEntry(...)` objects `ReconcileSyncRule._execute_serialized` builds get
    `found_by=FoundBy.RECONCILIATION`.

  Any protocol that declares `execute(rule_id, *, full=...)` for `ExecuteSyncRule` and is used
  by `ReconcileNow` gains the same `origin` keyword; the scheduler's protocol in
  `application/operations/scheduled_pass.py` does not need it.

- [ ] **Step 4: Run the application and architecture suites**

Run: `.venv/bin/pytest tests/application tests/test_architecture.py -q && .venv/bin/mypy && .venv/bin/lint-imports && .venv/bin/ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/calendar_sync tests/application
git commit -m "Record on each entry why its run read the calendars and which work found the event"
```

---

### Task 5: Activity shows why an event was checked

**Files:**
- Modify: `src/calendar_sync/application/operations/activity.py` (`ActivityEntry`)
- Modify: `src/calendar_sync/infrastructure/persistence/activity_queries.py` (select and hydrate the three columns)
- Modify: `src/calendar_sync/interfaces/api/schemas.py` (`AuditEntryResponse` + Literal aliases)
- Modify: `src/calendar_sync/interfaces/api/routes/activity.py` (`_entry_response`)
- Modify: `tests/adapters/test_schema_enums.py` (`MIRRORS`)
- Regenerate: `web/openapi.json`, `web/src/lib/api-schema.ts`
- Create: `web/src/lib/activity-provenance.ts`, `web/src/lib/activity-provenance.test.ts`
- Modify: `web/src/features/activity-entry-details.tsx`, `web/src/i18n/locales/en/activity.json` (and any other locale catalog the i18n check requires, see `web/src/i18n/`)
- Rebuild: `src/calendar_sync/interfaces/api/static/` (`cd web && pnpm run build`)
- Test: `tests/adapters/test_activity_queries.py`, `tests/adapters/test_audit_entries_api.py`, `web/src/features/activity.test.tsx`

**Interfaces:**
- Consumes: the three stored columns (Task 2), set by Tasks 3-4.
- Produces: `ActivityEntry.run_reason: str | None = None`, `found_by: str | None = None`,
  `source_comparison: str | None = None`; API fields of the same names typed with Literal aliases
  `RunReasonValue`, `FoundByValue`, `SourceComparisonValue` mirroring `RunReason`, `FoundBy`,
  `ComparisonKind`.
  ```ts
  // web/src/lib/activity-provenance.ts
  export function checkedBecauseKey(entry: AuditEntry): string | null
  export function comparisonKey(entry: AuditEntry): string | null
  ```

- [ ] **Step 1: Write the failing backend tests.**
  - `tests/adapters/test_activity_queries.py`: an appended entry with all three values reads back in `ActivityEntry`; an entry inserted without them reads back `None`.
  - `tests/adapters/test_audit_entries_api.py`: the Activity list response includes `run_reason`, `found_by`, `source_comparison`, and `null` for an entry without them.
  - `tests/adapters/test_schema_enums.py`: add the three aliases to `MIRRORS`.

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/pytest tests/adapters/test_activity_queries.py tests/adapters/test_audit_entries_api.py tests/adapters/test_schema_enums.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement the backend.** Add the fields to `ActivityEntry` (after
  `changed_fields`, each with a one-line docstring), select the columns in the queries that
  build entries (`_entries` and the single-entry query), add to `AuditEntryResponse`:

```python
RunReasonValue = Literal["changes", "first_run", "daily_pass", "reconcile_now", "reprojection", "relisted"]
FoundByValue = Literal["source_feed", "destination_feed", "reprojection", "pending_replay", "reconciliation"]
SourceComparisonValue = Literal["changed", "untracked", "same_revision", "cancelled", "no_baseline"]

    run_reason: RunReasonValue | None = None
    """Why the Sync Run read the calendars as it did (ADR 0036); None for earlier entries."""
    found_by: FoundByValue | None = None
    """Which work led to the decision (ADR 0036); None for earlier entries."""
    source_comparison: SourceComparisonValue | None = None
    """How the source event compared with the rule's Source Observation; None when not compared."""
```

  and pass them in `_entry_response`. Place the aliases where the file keeps its other
  `...Value` aliases.

- [ ] **Step 4: Regenerate the API types and run the backend tests**

Run: `.venv/bin/python scripts/export_openapi.py && (cd web && pnpm run api:types) && .venv/bin/pytest tests/adapters tests/test_openapi_contract.py -q`
Expected: PASS.

- [ ] **Step 5: Write the failing web tests** in `web/src/lib/activity-provenance.test.ts`
  (Vitest, matching `web/src/lib/activity.test.ts`):

```ts
import { describe, expect, it } from "vitest"
import { checkedBecauseKey, comparisonKey } from "./activity-provenance"
import type { AuditEntry } from "./activity"  // use the type the neighbouring tests use

const entry = (fields: Partial<AuditEntry>): AuditEntry => ({ ...BASE, ...fields })  // BASE as neighbouring tests build entries

describe("checkedBecauseKey", () => {
  it.each([
    [{ run_reason: "changes", found_by: "source_feed" }, "activity.detail.why.sourceReported"],
    [{ run_reason: "changes", found_by: "destination_feed" }, "activity.detail.why.destinationReported"],
    [{ run_reason: "changes", found_by: "pending_replay" }, "activity.detail.why.pendingReplay"],
    [{ run_reason: "daily_pass", found_by: "source_feed" }, "activity.detail.why.dailyPass"],
    [{ run_reason: "first_run", found_by: "source_feed" }, "activity.detail.why.firstRun"],
    [{ run_reason: "reconcile_now", found_by: "source_feed" }, "activity.detail.why.reconcileNow"],
    [{ run_reason: "reprojection", found_by: "reprojection" }, "activity.detail.why.reprojection"],
    [{ run_reason: "relisted", found_by: "source_feed" }, "activity.detail.why.relisted"],
    [{ run_reason: null, found_by: "reconciliation" }, "activity.detail.why.reconciliation"],
    [{ run_reason: null, found_by: null }, null],
  ] as const)("%o -> %s", (fields, key) => {
    expect(checkedBecauseKey(entry(fields))).toBe(key)
  })
})

describe("comparisonKey", () => {
  it.each([
    ["untracked", "activity.detail.comparison.untracked"],
    ["same_revision", "activity.detail.comparison.sameRevision"],
    ["no_baseline", "activity.detail.comparison.noBaseline"],
    ["changed", null],
    ["cancelled", null],
    [null, null],
  ] as const)("%s -> %s", (kind, key) => {
    expect(comparisonKey(entry({ source_comparison: kind }))).toBe(key)
  })
})
```

  In `web/src/features/activity.test.tsx`, add: an entry with `run_reason: "changes"`,
  `found_by: "source_feed"`, `source_comparison: "untracked"` shows both lines in its details;
  an entry with all three `null` shows neither.

- [ ] **Step 6: Implement the web part.**

```ts
// web/src/lib/activity-provenance.ts
import type { AuditEntry } from "./activity"

const BY_RUN_REASON: Record<string, string> = {
  daily_pass: "activity.detail.why.dailyPass",
  first_run: "activity.detail.why.firstRun",
  reconcile_now: "activity.detail.why.reconcileNow",
  reprojection: "activity.detail.why.reprojection",
  relisted: "activity.detail.why.relisted",
}

/** The catalog key of the line that says why the run looked at this event, if it recorded one. */
export function checkedBecauseKey(entry: AuditEntry): string | null {
  if (entry.found_by === "reconciliation") return "activity.detail.why.reconciliation"
  if (entry.found_by === "pending_replay") return "activity.detail.why.pendingReplay"
  if (entry.run_reason === "changes") {
    if (entry.found_by === "source_feed") return "activity.detail.why.sourceReported"
    if (entry.found_by === "destination_feed") return "activity.detail.why.destinationReported"
    return null
  }
  return entry.run_reason ? (BY_RUN_REASON[entry.run_reason] ?? null) : null
}

const BY_COMPARISON: Record<string, string> = {
  untracked: "activity.detail.comparison.untracked",
  same_revision: "activity.detail.comparison.sameRevision",
  no_baseline: "activity.detail.comparison.noBaseline",
}

/** The catalog key of the comparison line, only when it adds to the Source Change section. */
export function comparisonKey(entry: AuditEntry): string | null {
  return entry.source_comparison ? (BY_COMPARISON[entry.source_comparison] ?? null) : null
}
```

  Use the generated API type for `AuditEntry` the way `web/src/lib/activity.ts` does, and type
  the keys with the catalog's key type if the i18n module exports one.

  Catalog (`activity.json`, under `detail`):

```json
"checkedBecause": "Why it was checked",
"why": {
  "sourceReported": "{source} reported a change to this event or its series.",
  "destinationReported": "{destination} reported a change to the event Calendar Ghost wrote there.",
  "pendingReplay": "A change to its series that an earlier run left unfinished was completed.",
  "dailyPass": "Daily check of every event.",
  "firstRun": "First sync of this rule.",
  "reconcileNow": "Reconcile Now.",
  "reprojection": "The rule's settings changed.",
  "relisted": "A calendar's saved sync position was missing or rejected, so it was read in full.",
  "reconciliation": "Full Reconciliation compared the two calendars."
},
"comparison": {
  "untracked": "{source} has a different version than the one Calendar Ghost last recorded. No change was detected in what it tracks.",
  "sameRevision": "Same version of the event as the one Calendar Ghost last recorded.",
  "noBaseline": "No earlier version to compare with."
}
```

  In `activity-entry-details.tsx`, inside `<dl className="activity-detail-facts">` after the
  rule row, render a `checkedBecause` row when `checkedBecauseKey(entry)` is not null, filling
  `{source}` and `{destination}` from `names` as the existing copy does. Render the comparison
  line as a `<p>` before `<SourceChangeDetails>`. Keep the component within ESLint's bounds;
  if it grows past them, move the two rows into a small component in a new file
  `web/src/features/activity-entry-provenance.tsx`.

- [ ] **Step 7: Run the web checks and rebuild the bundle**

Run: `cd web && pnpm run api:check && pnpm run typecheck && pnpm run lint && pnpm run doctor && pnpm run knip && pnpm run test && pnpm run build`
Expected: PASS; `src/calendar_sync/interfaces/api/static/` changes.

- [ ] **Step 8: Commit**

```bash
git add src/calendar_sync tests web
git commit -m "Show in Activity why an event was checked and how it compared with what the rule last saw"
```

---

### Task 6: Documentation

**Files:**
- Create: `docs/adr/0036-record-a-decision-only-when-it-says-something-new.md`
- Modify: `docs/adr/0013-record-decisions-worth-explaining.md`, `docs/adr/0017-record-source-changes.md` (an "Amended by ADR 0036" line at the top, as ADR 0013 does for 0019)
- Modify: `docs/sync-model.md` (Activity section), `CONTEXT.md` (Source Comparison), `docs/deployment.md` (migration 31 note), `CHANGELOG.md` (Unreleased)
- Test: `tests/test_ubiquitous_language.py`, `tests/test_no_em_dashes.py`, `tests/test_troubleshooting_anchors.py`

- [ ] **Step 1: Write ADR 0036** with the repository's ADR sections (Context, Decision,
  Alternatives considered, Consequences). Take the content from the spec: the 2026-10-14
  incident, Parts 1-3, "Rejected: field digests", "Rejected: a run summary entry". State in
  Decision that the daily pass is unchanged, that `unrecorded=N` is logged, and that earlier
  entries keep `NULL` provenance.

- [ ] **Step 2: Update the other documents.**
  - `sync-model.md`: near the paragraph about recorded decisions and Source Changes (around
    line 162-180), add the repeated-decision rule, the comparison kinds, `run_reason`, and
    `found_by`, each in one or two sentences, linking ADR 0036.
  - `CONTEXT.md`: add **Source Comparison** beside Source Observation and Source Change, in the
    glossary's format: how a source event compared with the rule's Source Observation of it:
    changed, untracked, same revision, cancelled, or no baseline.
  - `docs/deployment.md`: where migrations are listed or described, note migration 31 adds three
    nullable columns and that an earlier release ignores them.
  - `CHANGELOG.md` under Unreleased: one entry for the noise reduction and the "Why it was
    checked" line.

- [ ] **Step 3: Run the documentation tests and the full checks**

Run: `.venv/bin/pytest tests/test_ubiquitous_language.py tests/test_no_em_dashes.py tests/test_troubleshooting_anchors.py -q`, then every command in Global Constraints.
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add docs CONTEXT.md CHANGELOG.md
git commit -m "Document why Activity leaves out a repeated skip and says what brought an event in"
```
