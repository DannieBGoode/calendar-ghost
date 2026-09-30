# Source Change History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Write to the destination only when the projection changes, and record on each Audit
Entry which source fields changed with their values before and after.

**Architecture:** The decision service compares the derived projection with the destination and
ignores revision-only changes. A new domain module compares a Source Observation (the latest details
a rule saw) with the event now seen and produces a Source Change. The application observes events
when it records their decision; SQLite stores observations and change values sealed with a key
derived from the Installation Master Key, keeps values 90 days, and Activity unseals them on request.

**Tech Stack:** Python 3.12, FastAPI, SQLite, `cryptography` (AESGCM, HKDF), React + TypeScript +
Vite, pytest, vitest.

**Spec:** `docs/adr/0016-record-source-changes.md`

## Global Constraints

- Tracked fields, in display order: `title`, `time`, `description`, `location`, `guests`, `recurrence`, `conferencing`.
- RSVPs, reminders, colours, and any other field are not tracked or stored.
- Titles are plain text; every other stored value is sealed (AES-256-GCM, HKDF-SHA256 key, info `b"calendar-sync source history v1"`).
- No redaction of any value.
- Sealed change values are kept 90 days (`SOURCE_CHANGE_RETENTION = timedelta(days=90)`).
- Google writes keep `sendUpdates=none`; projections never carry guests or conferencing.
- No new `# noqa` complexity suppressions; `lint-imports` contracts unchanged.
- New SQLite migration is `0012_source_changes.sql`; update `_FORWARD_MIGRATIONS` and the version assertions in `tests/adapters/test_sqlite.py` and `tests/adapters/test_google_oauth_storage.py`.
- After any change under `web/`, rebuild and commit `src/calendar_sync/interfaces/api/static/`.

## Review Focus

- A guest list Google truncates (`attendeesOmitted: true`) must not read as guests removed.
- A retry after a failed series re-verification must re-verify again, not see the series as current.
- A cancelled then restored event compares with its last confirmed details, not with an empty event.
- Values sealed under another master key must show as unavailable, not fail the Activity request.
- An incremental run that sees the same revision twice (source feed then destination repair) records at most one Source Change.

---

### Task 1: Write only when the projection changes

**Files:**
- Modify: `src/calendar_sync/domain/services.py` (`_projection_decision`, `decide_occurrence`)
- Modify: `src/calendar_sync/application/synchronization.py` (`_synchronize_event`, `_decide_and_write`)
- Test: `tests/domain/test_model.py`, `tests/domain/test_occurrence_decisions.py`, `tests/application/test_execute_sync_rule.py`, `tests/application/test_recurring_sync.py`

**Interfaces:**
- Produces: `SyncDecision(IGNORE, PROJECTION_CURRENT, projection)` now carries the projection.

- [ ] **Step 1: Failing domain tests**
  - Busy-Only rule, mapped event, source revision changed, title changed, destination matches Busy projection → `IGNORE`, `PROJECTION_CURRENT`, `decision.projection` set.
  - Details rule, revision changed, content identical → `IGNORE`, `PROJECTION_CURRENT`.
  - Revision changed, projection equals `mapping.projection_fingerprint`, destination edited → `UPDATE`, `DESTINATION_DRIFT_REPAIRED`.
  - Details rule, title changed, destination edited too → `UPDATE`, `SOURCE_CHANGED`.
  - Occurrence with Occurrence Mapping, revision changed, destination occurrence content equal → `IGNORE`, `OCCURRENCE_CURRENT`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/domain -q` → new tests FAIL.
- [ ] **Step 3: Implement** in `_projection_decision`:

```python
expected = self._fingerprinter.fingerprint(projection)
actual = self._fingerprinter.fingerprint(self.as_projection(actual_destination))
if expected == actual:
    # A new revision alone is evidence to check, not a reason to write (ADR 0016).
    return SyncDecision(SyncAction.IGNORE, SyncReason.PROJECTION_CURRENT, projection)
source_changed = (
    mapping.source_revision != source_event.revision
    and expected != mapping.projection_fingerprint
)
reason = SyncReason.SOURCE_CHANGED if source_changed else SyncReason.DESTINATION_DRIFT_REPAIRED
return SyncDecision(SyncAction.UPDATE, reason, projection)
```

  and in `decide_occurrence` replace `if expected == actual and (occurrence_mapping is None or source_unchanged):` with `if expected == actual:`.
- [ ] **Step 4: Failing application tests**
  - Busy-Only mapped event whose source title changes: provider records no `update_projection` call; the mapping's `source_revision` equals the new revision; the audit entry is `ignore`/`projection_current`.
  - Busy-Only series whose master title changes, with one recorded Occurrence Mapping: the occurrence is re-verified (`get_occurrence` called for it) and the Series Mapping's revision advances.
  - Same series where `get_occurrence` raises on the first run: the Series Mapping keeps the old revision; a second run re-verifies and then advances it.
- [ ] **Step 5: Implement** in `_decide_and_write`: return a third value `source_moved = mapping is not None and mapping.source_revision != source_event.revision` (mapping read before the decision). For `IGNORE`/`PROJECTION_CURRENT` with `source_moved`, save the mapping with the new revision and `fingerprint(decision.projection)`. For a recurring source with `source_moved` and recorded occurrences (`uow.occurrences.for_series(mapping.id)`), save UPDATE/IGNORE mappings with the **previous** revision; `_synchronize_event` reverifies when `action in {CREATE, UPDATE}` or `source_moved` or reprojection, then saves the mapping with `source_event.revision` and commits.
- [ ] **Step 6: Run** `.venv/bin/pytest -q` → all pass (fix any test that asserted the old redundant write, stating why in its name).
- [ ] **Step 7: Commit** `fix: write projections only when their content changes`

### Task 2: Source Observations and Source Changes in the domain

**Files:**
- Create: `src/calendar_sync/domain/changes.py`
- Modify: `src/calendar_sync/domain/model.py` (`CalendarEvent.guests`, `CalendarEvent.conferencing`)
- Test: `tests/domain/test_source_changes.py`

**Interfaces:**
- Produces:

```python
class SourceField(StrEnum): TITLE, TIME, DESCRIPTION, LOCATION, GUESTS, RECURRENCE, CONFERENCING
@dataclass(frozen=True, slots=True)
class SourceObservation:
    revision: str
    title: str
    time: EventTime
    description: str = ""
    location: str = ""
    recurrence: tuple[str, ...] = ()
    guests: tuple[str, ...] | None = None   # None: Google did not list every guest
    conferencing: tuple[str, ...] | None = None
    @classmethod
    def of(cls, event: CalendarEvent) -> SourceObservation | None  # None when cancelled or managed
@dataclass(frozen=True, slots=True)
class SourceChange:
    before: SourceObservation
    after: SourceObservation
    fields: tuple[SourceField, ...]
    @classmethod
    def between(cls, before: SourceObservation, after: SourceObservation) -> SourceChange | None
```

- [ ] **Step 1: Failing tests:** each field alone is detected; unchanged content with a new revision → `None`; guests `None` on either side are not compared; guest order does not matter (normalised on construction: sorted, deduplicated, lower-cased); cancelled or managed events observe as `None`; `fields` follow `SourceField` order.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/domain/test_source_changes.py -q` → FAIL (import error).
- [ ] **Step 3: Implement** `changes.py`; add `guests`/`conferencing` (default `None`) to `CalendarEvent`. `EventProjector` stays unchanged, so projections never carry them.
- [ ] **Step 4: Run** tests → PASS.
- [ ] **Step 5: Commit** `feat: describe source changes between observations`

### Task 3: Translate guests and conferencing from Google

**Files:**
- Modify: `src/calendar_sync/infrastructure/google/translation.py`, `src/calendar_sync/infrastructure/google/provider.py` (`OCCURRENCE_EXCEPTION_FIELDS`)
- Test: `tests/adapters/test_google_translation.py`

- [ ] **Step 1: Failing tests:** attendees → sorted lower-cased emails, `responseStatus` ignored; no `attendees` key → `()`; `attendeesOmitted: true` → `None`; `conferenceData.entryPoints[].uri` plus `hangoutLink` → sorted unique URIs; none → `()`; cancelled payload → both `None`; projection payloads never include `attendees` or `conferenceData`.
- [ ] **Step 2: Implement** `_guests(payload)` and `_conferencing(payload)`; append `attendees(email),attendeesOmitted,conferenceData(entryPoints(uri)),hangoutLink` to `OCCURRENCE_EXCEPTION_FIELDS` so every translated payload has them.
- [ ] **Step 3: Run** `.venv/bin/pytest tests/adapters/test_google_translation.py tests/adapters/test_google_provider.py -q` → PASS.
- [ ] **Step 4: Commit** `feat: read guests and conferencing links from Google events`

### Task 4: Seal history values with a purpose-derived key

**Files:**
- Modify: `src/calendar_sync/infrastructure/security.py`
- Test: `tests/adapters/test_history_cipher.py`

**Interfaces:**
- Produces: `HistoryCipher(encoded_master_key: str)` with `seal(plaintext: str, context: str) -> bytes` and `open(sealed: bytes, context: str) -> str | None` (None when the key, context, or version does not match).

- [ ] **Step 1: Failing tests:** round trip; different context → `None`; different master key → `None`; ciphertext does not contain the plaintext; `CredentialCipher` cannot decrypt a sealed value (keys differ).
- [ ] **Step 2: Implement** with `HKDF(SHA256(), 32, salt=None, info=b"calendar-sync source history v1")`, a version byte `b"\x01"`, 12-byte random nonce, AAD `version + context`. Extract `_master_key_bytes(encoded)` shared with `CredentialCipher`.
- [ ] **Step 3: Run** tests → PASS. **Commit** `feat: seal source history with a derived key`

### Task 5: Observe events when their decision is recorded

**Files:**
- Modify: `src/calendar_sync/application/ports.py` (`SourceObservationRepository`, `UnitOfWork.observations`, `AuditEntry.change`, `AuditRepository.forget_change_values`)
- Modify: `src/calendar_sync/application/sync_run.py` (`record(run, entry, observed=None)`, `observe`)
- Modify: `src/calendar_sync/application/synchronization.py`, `src/calendar_sync/application/occurrences.py` (pass `observed=`; retention in `_advance_cursors`)
- Modify: `src/calendar_sync/infrastructure/persistence/memory.py`
- Test: `tests/application/test_source_changes.py`

**Interfaces:**

```python
class SourceObservationRepository(Protocol):
    def get(self, rule_id: SyncRuleId, source: EventRef) -> SourceObservation | None: ...
    def save(self, rule_id: SyncRuleId, source: EventRef, observation: SourceObservation, at: datetime) -> None: ...
    def forget_stale(self, rule_id: SyncRuleId, source: CalendarEndpoint, ended_before: datetime) -> None: ...
class AuditRepository(Protocol):
    def append(self, entry: AuditEntry) -> None: ...
    def forget_change_values(self, rule_id: SyncRuleId, before: datetime) -> None: ...
SOURCE_CHANGE_RETENTION = timedelta(days=90)
```

- [ ] **Step 1: Failing tests (in-memory):** first run records no change; Details description change records `fields == (DESCRIPTION,)` with before/after on the update entry; Busy-Only title change records `(TITLE,)` on a `projection_current` entry and no provider write; guest response only → no change; the same revision seen twice in one run → one change; cancelled then restored with new location → change against the last confirmed observation; unrecorded reasons (`before_sync_window`) do not update the observation; a full-listing run calls `forget_change_values(rule, NOW - 90 days)` and `forget_stale`.
- [ ] **Step 2: Implement** `record()`:

```python
def record(run: SyncRunContext, entry: AuditEntry, observed: CalendarEvent | None = None) -> None:
    reason = entry.reason
    if reason in UNRECORDED_REASONS or (run.daily_pass and reason in UNRECORDED_ON_DAILY_PASS):
        return
    if observed is not None:
        entry = replace(entry, change=observe(run, observed, entry.occurred_at))
    run.uow.audit.append(entry)
```

  `observe` loads the previous observation, returns `None` when the event observes as `None` or the revision is unchanged, saves the new observation, and returns `SourceChange.between(previous, current)` when there was a previous one.
- [ ] **Step 3: Run** `.venv/bin/pytest -q` → PASS. **Commit** `feat: record source changes on audit entries`

### Task 6: Persist observations and change values in SQLite

**Files:**
- Create: `src/calendar_sync/infrastructure/persistence/0012_source_changes.sql`, `src/calendar_sync/infrastructure/persistence/source_changes.py`
- Modify: `src/calendar_sync/infrastructure/persistence/sqlite.py`, `src/calendar_sync/bootstrap/container.py`
- Test: `tests/adapters/test_source_change_persistence.py`, `tests/adapters/test_sqlite.py`, `tests/adapters/test_google_oauth_storage.py`

Migration:

```sql
CREATE TABLE IF NOT EXISTS source_observations (
    rule_id TEXT NOT NULL REFERENCES sync_rules(id) ON DELETE CASCADE,
    source_account_id TEXT NOT NULL,
    source_calendar_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    title TEXT NOT NULL,
    recurring INTEGER NOT NULL,
    ends TEXT NOT NULL,
    sealed BLOB NOT NULL,
    PRIMARY KEY (rule_id, source_account_id, source_calendar_id, source_event_id)
);
ALTER TABLE audit_entries ADD COLUMN change_fields TEXT;
ALTER TABLE audit_entries ADD COLUMN change_title_before TEXT;
ALTER TABLE audit_entries ADD COLUMN change_sealed BLOB;
CREATE INDEX IF NOT EXISTS audit_entries_change_values
ON audit_entries(rule_id, occurred_at) WHERE change_sealed IS NOT NULL;
```

- [ ] **Step 1: Failing tests:** observation round trip; the `sealed` column never contains a description or guest email in plain text; audit change round trip (fields JSON, previous title, sealed values); `forget_change_values` clears `change_sealed` older than the cutoff and keeps `change_fields`; `forget_stale` deletes ended single events and other calendars' observations and keeps series; deleting the rule deletes its observations; without a cipher, observations are not stored and entries keep only fields and title.
- [ ] **Step 2: Implement** `SqliteSourceObservationRepository` and `seal_change/open_change` helpers (sealed JSON: `{field: {"before": v, "after": v}}` for non-title fields; guests as `{"added": [...], "removed": [...]}`; times as `{"all_day", "starts", "ends"}`), wire `SqliteUnitOfWorkFactory(path, clock, history=None)` and pass `HistoryCipher(settings.master_key)` from `build_adapters`.
- [ ] **Step 3: Run** `.venv/bin/pytest tests/adapters -q` → PASS. **Commit** `feat: store source observations and sealed change values`

### Task 7: Activity and API expose changes

**Files:**
- Modify: `src/calendar_sync/application/activity.py` (`ActivityEntry.changed_fields`, `ActivityQueries.entry_change`, `RecordedChange`)
- Modify: `src/calendar_sync/infrastructure/persistence/activity_queries.py`
- Modify: `src/calendar_sync/interfaces/api/schemas.py`, `src/calendar_sync/interfaces/api/routes/activity.py`
- Test: `tests/adapters/test_activity_queries.py`, `tests/adapters/test_audit_entries_api.py`

**Interfaces:**
- `GET /api/v1/audit-entries` items add `changed_fields: list[str] | null`.
- `GET /api/v1/audit-entries/{id}/changes` → `{"fields": [...], "values_available": bool, "changes": [{"field", "before", "after", "before_time", "after_time", "added", "removed"}]}`; 404 when the entry has no Source Change; admin only.

- [ ] **Step 1: Failing tests:** list shows `changed_fields`; changes endpoint returns title before/after in plain text and unsealed description values; after expiry `values_available` is false and only the title change remains; values sealed under another key → `values_available` false; unauthenticated → 401.
- [ ] **Step 2: Implement.** **Step 3: Run** `.venv/bin/pytest -q` → PASS. **Commit** `feat: show source changes in the Activity API`

### Task 8: Activity UI says what changed

**Files:**
- Modify: `web/src/lib/api.ts`, `web/src/lib/activity.ts`, `web/src/features/activity.tsx`, `web/src/index.css`
- Test: `web/src/lib/activity.test.ts`
- Regenerate: `src/calendar_sync/interfaces/api/static/`

- [ ] **Step 1: Failing tests:** `whatHappened` for `source_changed` with `changed_fields: ["title", "description"]` → "Title and description changed in Work → updated in Family"; for `projection_current` with `["guests"]` → "Guests changed in Work → already up to date"; `["time"]` with `moved_from` keeps "Moved from …"; `describeEntry` explains an unchanged entry with changes as "The event changed in Work, but Family shows none of what changed, so nothing was written."
- [ ] **Step 2: Implement** labels (`title` Title, `time` Time, `description` Description, `location` Location, `guests` Guests, `recurrence` Repeat pattern, `conferencing` Video call links) and a `SourceChangeDetails` section in the entry panel that fetches `/changes` and lists each field with Before/After (guests as Added/Removed), preserving line breaks, and says "Earlier values are kept for 90 days." when unavailable.
- [ ] **Step 3: Run** `npm --prefix web run typecheck && npm --prefix web run lint && npm --prefix web run test && npm --prefix web run build`. **Commit** `feat: show what changed in Activity`

### Task 9: Documentation and full gates

**Files:** `AGENTS.md`, `CONTEXT.md`, `docs/sync-model.md`, `docs/deployment.md`, `docs/domain-model.md`, `docs/adr/0014-record-event-titles-on-audit-entries.md`, `CHANGELOG.md`, `README.md` (if it states the old invariant)

- [ ] Update the invariant, glossary (**Source Observation**, **Source Change**), audit evidence, backup and master-key consequences, retention; mark ADR 0014 as amended by ADR 0016; CHANGELOG entries.
- [ ] Run every backend and frontend gate from AGENTS.md; commit `docs: record source changes and projection-only writes`.
