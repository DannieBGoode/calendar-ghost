# Activity without repeated decisions: design

Terms are in `CONTEXT.md` (Audit Entry, Source Observation, Source Change, Sync Run, Event
Projection, Full Reconciliation). This design amends ADR 0013 and ADR 0017 through a new ADR 0037.

## Problem

On 2026-10-14 at 17:48 UTC, Google's change feed for one rule's Source Calendar returned 362
seminar events in one ordinary incremental run (`mode=incremental reason=changes`, no cursor
rejected). The runs five minutes before and after returned 0 or 1. Another rule whose Destination
Calendar is the same calendar saw 362 destination events at the same second, which points to a
change made in Google, not by Calendar Ghost. The run wrote nothing
(`created=0 updated=0 deleted=0 ignored=362`) and added about 277 Audit Entries:

| Reason | Entries |
|---|---|
| `occurrence_current` | 83 |
| `series_without_occurrences` | 47 |
| `declined` | 45 |
| `series_not_synchronized` | 43 |
| `projection_current` | 42 |
| `occurrence_already_cancelled` | 17 |

No entry showed a Source Change: no tracked field difference was detected, and cancelled events
have no Source Observation to compare with. A likely cause is a bulk change by the organizer to
fields Calendar Ghost does not track, such as responses, the organizer, or reminders. The data
cannot prove which.

Two things went wrong for the person reading Activity:

1. **Noise.** Each entry repeats the decision Activity already recorded for that event, with
   nothing new to explain. ADR 0013 records these skips "on incremental runs that saw the event
   change". The code reads "saw the event change" as "the provider reported it", not as "its
   tracked content changed".
2. **No reason given.** An entry does not say what brought the event into the run, or how the
   source compared with what the rule last saw.

## Goal

- Outside the daily pass, an `ignore` decision that repeats the event's previous entry, about an
  event with no detected tracked change, is counted but not recorded.
- Every entry recorded by a Sync Run says what brought its event into the run, and, when the run
  had a source event to compare, how it compared with the rule's Source Observation.
- Writes, blocks, a decision that differs from the event's previous entry, and a detected tracked
  change are still recorded.
- For the 2026-10-14 run, an event is not recorded again when its previous entry has the same
  decision and its comparison qualifies (Part 2). How many of the 277 entries that removes
  depends on each event's previous entry and observation, which have not been checked.

## Non-goals

- The daily pass keeps its behavior. ADR 0013 keeps its no-change checks as evidence that a run
  looked at an event, and `UNRECORDED_ON_DAILY_PASS` stays. `run.daily_pass` also covers
  reprojection and a rejected source cursor today; this does not change.
- `UNRECORDED_REASONS` stays as it is.
- No keyed digests of untracked fields. See "Rejected: field digests".
- No per-run history or summary row. See "Rejected: a run summary entry".

## Part 1: Source Comparison

Before a decision is recorded, the run compares the source event with the rule's Source
Observation of it. The result is a **Source Comparison**, a new domain value in
`domain/changes.py`:

| Kind | When |
|---|---|
| `changed` | A tracked field difference was detected. A Source Change exists. |
| `untracked` | The revision differs and no tracked field difference was detected. |
| `same_revision` | The revision equals the observation's. |
| `cancelled` | The event is cancelled, so `SourceObservation.of` returns `None`. Its last observation is kept, as now. |
| `no_baseline` | No observation exists, or it cannot be unsealed (for example, after the master key was replaced). |

For a newer revision (`changed` or `untracked`), the comparison also says whether it
**completes the baseline**: the new observation knows a value the stored one did not. That is when the stored `guests`, `conferencing`, or `response` is
`None` and the new one is not. No Source Change is reported for that (`_known_differ`, and the
`response` rule in `_differs`), but saving it lets later revisions be compared in full.

Today `_observe()` in `application/sync/sync_run.py` compares and saves in one step. This design
splits it:

1. `compare(run, event)` reads only. It loads the observation, builds the new one, applies
   `completed_by(previous)` before comparing (as now), and returns the comparison, the Source
   Change if any, and the observation to save. For `same_revision`, `cancelled`, and a
   managed projection, there is nothing to save, as now.
2. `observe(run, event, observation, at)` saves, and only for a decision that is recorded.

ADR 0017's rule that "observations are updated only by recorded decisions" therefore stays true.
An unrecorded decision leaves the stored observation as it was, so the next new revision is
compared with it again. A newer revision that completes the baseline is never treated as a
repeat (Part 2, condition 3), so it is recorded and saved. A `same_revision` comparison keeps
today's short circuit: nothing is compared or saved, and it never completes the baseline.

## Part 2: The repeated-decision rule

A new domain policy in `domain/audit.py`:

```python
def repeats_previous(
    previous: AuditEntry | None, entry: AuditEntry, comparison: SourceComparison
) -> bool:
```

It returns true only when **all** of these hold:

1. The decision is `ignore`. Creates, updates, deletes, and blocks are always recorded.
2. The comparison kind is `untracked` or `same_revision`, or it is `cancelled` and the previous
   entry's recorded event is cancelled too.
3. The comparison does not complete the baseline.
4. A previous entry exists for the same rule and `source_event_id`. "Previous" means the
   highest `id`, the order Activity already uses (ADR 0019). ADR 0019 always keeps an event's
   latest entry, so clearing old Activity does not remove it.
5. The previous entry has the same action, the same reason, and the same
   `destination_event_id`.
6. Both entries have a `RecordedEvent`, and the two are equal: same title, same time compared as
   instants (as `SourceChange` compares times), same `recurring`, same `cancelled`. This
   catches a restored event, a series turned into a single event, and an entry recorded before
   Source Observations existed. The latest entry can be a cancellation while the observation
   still describes the earlier live event, so this check is needed.

Two conditions are the caller's, not the policy's, because the policy cannot see them:

- **Not a daily pass.** `record()` applies the policy only when `run.daily_pass` is false.
- **Own identity.** `SynchronizeOccurrences._record()` (`occurrences.py`) records an
  occurrence under its series' identity when it has no `source_ref`. A previous entry under that
  identity may then be about the series or another occurrence. `record()` takes
  `own_identity: bool = True`, and `SynchronizeOccurrences._record()` passes
  `source_ref is not None`. `RetireLoneOccurrences._record()` (`lone_occurrences.py`) records
  under its mapping's own source and records only deletes and blocks, so it needs nothing.

If any condition fails, the entry is recorded as now. In particular:

- **The new rule never hides recovery from a block.** After a block, the previous action is
  `conflict`, so condition 5 fails and the next decision is recorded.
  `activity_queries.open_blocks` treats that later entry as the end of the block. The existing
  early returns for `UNRECORDED_REASONS` and the daily-pass reasons keep their current behavior.
- **A decision that changes for a reason outside the event is recorded.** Examples: a series
  loses its last live occurrence and becomes `series_without_occurrences`, or a rule change
  alters what is projected. The reason differs from the previous entry's reason.
- **Activity's comparisons with previous entries stay correct.** `_repeated_repairs` looks only
  at writes, which are always recorded. `_previous_names` reads the latest earlier titled entry,
  and condition 6 means a skipped entry would have recorded the same title and time.
- **The first `projection_current` after a create or update is recorded,** because the previous
  action differs. Later re-sends of the same unchanged event are not.

`record()` in `sync_run.py` stays the one place that decides whether an entry is appended:

1. Return if the reason is in `UNRECORDED_REASONS`, or it is a daily pass and the reason is in
   `UNRECORDED_ON_DAILY_PASS`, as now.
2. If an `observed` event is given, compare (Part 1). Without one, the comparison is empty
   (`NULL`).
3. If this is not a daily pass, the decision is `ignore`, `own_identity` is true, and there is a
   comparison: look up the previous entry and apply `repeats_previous`. If it repeats, add one
   to `run.unrecorded` and return.
4. Save the observation when there is one to save, set the Source Change, the comparison, and
   the provenance (Part 3) on the entry, and append it.

`run.unrecorded` counts only decisions this rule did not record. It does not count the existing
`UNRECORDED_REASONS` or daily-pass skips.

The previous-entry lookup is a new `AuditRepository.latest_for(rule_id, source_event_id)`,
implemented in SQLite and in the in-memory repository. SQLite filters by `user_id`, as every
repository does. The existing index `audit_entries_source_event(rule_id, source_event_id, id)`
serves it, and a test checks the query plan. The lookup runs only for decisions that reach step
3: `ignore`, outside the daily pass, with their own identity and a comparison. Each is one
indexed read.

## Part 3: What brought the event into the run

Each entry recorded by a Sync Run carries two new values. They are separate because they answer
separate questions.

### `run_reason`: why the run read the calendars the way it did

`ChangeFeedCursors.begin()` sets it after both listings, once it knows which feeds were listed
in full. It is kept on `SyncRunContext`. The first value that applies wins:

| Order | Value | When |
|---|---|---|
| 1 | `reprojection` | `rule.reprojection_required`. Both feeds are listed in full without cursors. |
| 2 | `reconcile_now` | The run was started by Reconcile Now. |
| 3 | `daily_pass` | The scheduler asked for a full pass (`full=True`). |
| 4 | `first_run` | Neither a source cursor nor a destination cursor was saved. |
| 5 | `relisted` | An incremental run, but at least one feed was listed in full because its cursor was missing or the provider rejected it. |
| 6 | `changes` | An incremental run in which both feeds returned changes since their cursors. |

`relisted` does not say which feed or provider. The service log already names the feed
(`cursor rejected ... feed=...`), and the UI copy stays generic.

Reconcile Now needs the request origin. A new `RunOrigin` enum (`SCHEDULED`, `RECONCILE_NOW`)
is passed from `ReconcileNow._execute()` (`reconciliation.py:391`) to `ExecuteSyncRule.execute()`,
then to `_execute_measured()` and `_execute_serialized()`, and then to
`ChangeFeedCursors.begin()`. The default is `SCHEDULED`, so the scheduler, Sync Now, and every
other caller do not change.

The service log's first line (`log.begin`) runs before the listings and keeps its current
values. The `cursor rejected` lines still follow it.

### `found_by`: which work led to the decision

`SyncRunContext` gets a `found_by` value and one context manager, `run.finding(value)`, which
sets it and restores the earlier value in `finally`. The value names the work that started the
chain of decisions. Work nested inside it, such as a series repair or rebuild, an immediate
exception replay, or an occurrence re-verification, inherits the value:

| Value | Set around |
|---|---|
| `source_feed` | `_synchronize_sources` in `_execute_serialized`. |
| `destination_feed` | `_repair_destinations`. |
| `reprojection` | `_reproject_remaining`. |
| `pending_replay` | `ExceptionReplays.finish_pending`, which completes replays an earlier run left unfinished. |

`record()` copies `run.run_reason`, `run.found_by`, and the comparison onto the entry, so no
decision function gets a new parameter.

### Paths that append without `record()`

- `ExecuteSyncRule._record_unverifiable()` (`synchronization.py:465`) appends a block directly.
  It changes to call `record()`, which records every block and so changes nothing else.
- Full Reconciliation builds its block entries in `ReconcileSyncRule._execute_serialized()` and
  appends them in `ReconcileSyncRule._record()` (`reconciliation.py`). These entries get `found_by = reconciliation`, and `run_reason` and the
  comparison stay `NULL`. That applies whether Reconcile Now or a direct
  `ReconcileSyncRule.execute()` started it. The reconciliation is not a Sync Run, and its entries
  carry their own provenance.
- Rule removal (`removal.py`) and rule edits (`rules.py`) are not Sync Run decisions. Their
  entries leave all three values `NULL`.
- The series rebuild's delete (`synchronization.py:426`) and lone-occurrence retirement pass no
  `observed` event. Their comparison stays `NULL`. Both record only writes and blocks.

## Storage, API, and UI

- **Migration `0032_audit_entry_provenance.sql`** adds three nullable `TEXT` columns to
  `audit_entries`: `run_reason`, `found_by`, and `source_comparison`. Earlier entries keep
  `NULL`. The values are codes, like `reason`, and contain no event content, so ADR 0014's limits
  are unchanged. Register the migration as the others are. `docs/deployment.md` notes the new
  migration, and that rolling back to an earlier release ignores the columns.
- **Domain and persistence:** `AuditEntry` gains `run_reason`, `found_by`, and
  `source_comparison`. SQLite `append` writes them, Activity's queries
  (`activity_queries.py`) select them, and `ActivityEntry` carries them. The in-memory audit
  repository stores them too.
- **Web API:** `_entry_response()` returns them as optional enums. Export the OpenAPI document
  and regenerate `web/src/lib/api-schema.ts`.
- **Web UI:** Activity rows keep their current per-reason trigger ("Changed in {source}",
  "Missing from {destination}"). The entry's details gain the lines below. The copy is a draft:
  final copy goes in `web/src/i18n/locales/en/activity.json` and follows `DESIGN.md`. Rebuild the
  compiled UI.

"Why it was checked":

| `run_reason` / `found_by` | Line |
|---|---|
| `changes` / `source_feed` | "{source} reported a change to this event or its series." |
| `changes` / `destination_feed` | "{destination} reported a change to the event Calendar Ghost wrote there." |
| any / `pending_replay` | "A change to its series that an earlier run left unfinished was completed." |
| `daily_pass` | "Daily check of every event." |
| `first_run` | "First sync of this rule." |
| `reconcile_now` | "Reconcile Now." |
| `reprojection` | "The rule's settings changed." |
| `relisted` | "A calendar's saved sync position was missing or rejected, so it was read in full." |
| `NULL` / `reconciliation` | "Full Reconciliation compared the two calendars." |

The comparison line, shown only when it adds something to the existing Source Change section:

| Kind | Line |
|---|---|
| `untracked` | "{source} has a different version than the one Calendar Ghost last recorded. No change was detected in what it tracks." |
| `same_revision` | "Same version of the event as the one Calendar Ghost last recorded." |
| `cancelled` | Nothing new. The row already says the event is cancelled. |
| `no_baseline` | "No earlier version to compare with." |
| `changed` | Nothing new. The Source Change section already lists the fields. |

An entry with `NULL` values shows neither line.

## Log

`SyncRunLog.finished` adds `unrecorded=N` after `ignored=`. The 2026-10-14 run would read
`ignored=362 unrecorded=N`, so the log still shows the burst.

## Rejected: field digests

Storing a keyed digest (HMAC) of each untracked field, such as the organizer, responses,
reminders, and color, plus one digest of the rest of the payload, would name which untracked field
changed without keeping its value. It is not part of this design:

- **It explains entries that are no longer shown.** A digest-only difference must not create an
  entry, or the 2026-10-14 run would record its 277 entries again, each saying "responses
  changed". Under Part 2 those entries are not recorded, so the digests would explain almost
  nothing a person sees.
- **The "rest of the payload" digest is not stable.** Leaving out volatile fields such as
  `etag`, `updated`, `sequence`, and `htmlLink` still leaves differences from missing fields,
  defaults, key order, and adapter versions. Graph reads selected fields only. A mismatch proves
  that the input differed, not that the organizer did something.
- **It weakens ADR 0017's privacy position.** ADR 0017 considered keyed digests and rejected
  them. Responses have four possible values, so with the installation key they can be guessed,
  and equal digests show when a value went back to an earlier one. Digests would also need their
  own key derivation, canonical form, version, retention, and key-reset behavior.
- **The revision already says what the data supports.** `untracked` says that the provider sent
  a new version and no tracked change was detected. The data supports nothing stronger.

If a later need, such as acting on other people's responses, requires a new field, it becomes a
tracked field under ADR 0017's rules, with its value sealed.

## Rejected: a run summary entry

One Audit Entry that summarized the burst ("Google sent 362 events again...") would break the
meaning of an Audit Entry as one decision about one event. Activity's categories, counts, search,
block queries, and retention all depend on that meaning. `rule_run_outcomes` keeps only the
latest outcome per rule and run kind, so a summary there would disappear five minutes later. A
retained per-run record, shown as a run heading in Activity, would work, but it is a separate
feature. The `unrecorded=N` log field covers investigations for now.

## Documentation

- **ADR 0037**, "Record a decision only when it says something new". It amends ADR 0013 (the
  repeated-decision rule and provenance on entries) and ADR 0017 (compare before observing; a
  comparison that completes the baseline is recorded; digests rejected again, for the reasons
  above).
- **`docs/sync-model.md`**, Activity section: the rule, the comparison kinds, `run_reason`, and
  `found_by`.
- **`CONTEXT.md`**: add **Source Comparison**.
- **`CHANGELOG.md`** under Unreleased.

## Tests

Domain (`repeats_previous`):

- One test per failing condition: a non-`ignore` action; a `changed` or `no_baseline`
  comparison; `cancelled` with a live previous entry; a comparison that completes the baseline;
  no previous entry; a different action, reason, or destination; a missing `RecordedEvent` on
  either side; a different title, time, `recurring`, or `cancelled`.
- All conditions hold: a repeat.
- Times equal as instants but with different offsets: a repeat.

Application (in-memory adapters):

- The 2026-10-14 case: a series and an occurrence with earlier entries are sent again with a new
  revision and the same tracked fields. Nothing is recorded, `unrecorded` counts them, and the
  stored observation keeps its old revision.
- A tracked change (title) on an event sent again: recorded with its Source Change and `changed`.
- A stored observation without guests, then a revision with a complete guest list and nothing
  else changed: recorded, and the observation now has the guests.
- A blocked event sent again and now decided `ignore`: recorded, and `open_blocks` no longer
  lists it.
- A series that loses its last live occurrence after a `projection_current`: recorded as
  `series_without_occurrences`.
- An occurrence without its own `source_ref`: recorded on every new revision.
- A cancelled series sent again with a cancelled previous entry: not recorded. Restored with
  identical content: recorded (condition 6), compared with the kept observation.
- A daily pass records exactly what it records today, including `projection_current` checks.
- `run_reason` for every row of the precedence table, including Reconcile Now with a pending
  reprojection, a source-only rejection, and a destination-only rejection.
- `found_by` for each phase. An immediate exception replay inside the source phase inherits
  `source_feed`. A scope that raises restores the earlier value.
- `_record_unverifiable` entries carry provenance. Full Reconciliation entries carry
  `reconciliation`, with `run_reason` `NULL`.
- `SyncRunLog.finished` prints `unrecorded=`.

Adapters:

- `tests/contracts/persistence.py` covers `latest_for` for both repositories: the latest entry
  by insertion order, no entry, and separation by rule and by source event.
- Migration 0031 on a database that already has entries.
- `latest_for` uses `audit_entries_source_event` (query plan) and returns nothing for another
  User's entry with the same rule and event identifiers (a runtime test, beside the schema check
  in `tests/adapters/test_user_isolation_schema.py`).
- The Activity API returns the three values, and `NULL` for earlier entries.

Web:

- The details line for each `run_reason` and `found_by` pair, and for each comparison kind.
- Entries with `NULL` values show neither line.
- The i18n catalog check and `pnpm run doctor` pass.
