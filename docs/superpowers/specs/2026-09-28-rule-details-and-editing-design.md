# Rule Details, policy editing, and Rule Removal

Status: approved decisions D1–D4 (all recommended options), 2026-09-28. Based on PR #4
(`fix-account-avatars-emails`), which adds `ruleEndpointLabel`, `AccountAvatar`, and migration 2.

## Intent

The Installation Administrator can open one Directional Sync Rule, see everything it does, and
change it safely. Editing never writes to Google. Only Rule Preview (reads), synchronization, and
Rule Removal write, and every Google write keeps `sendUpdates=none`.

Success means:

- `/rules/{id}` is a bookmarkable details view reachable from every rule row.
- Changing the Transformation Policy or All-Day Sync Policy is a Material Rule Change. The rule
  cannot be enabled again until a new Rule Preview passes. After it is re-enabled, every mapped
  Managed Projection is rewritten under the new policy.
- Changing a calendar removes the rule and creates a new Draft rule. The administrator chooses
  whether its mapped projections are deleted (the recommended default) or kept as Detached Events.
- The effects on privacy and the destructive effects are stated before confirmation.

## Settled decisions

| # | Decision |
|---|----------|
| D1 | Saving a Material Rule Change stops synchronization immediately. There is one configuration per rule, and no pending copy. |
| D2 | Keeping projections as Detached Events issues no Google write. The events keep the private origin metadata of the removed rule, so reverse rules keep ignoring them. |
| D3 | The first run after a policy change reprojects every Event Mapping, including events outside the Initial Sync Window. |
| D4 | This work builds on PR #4. The migration is number 3. The PR targets `main` after #4 merges. |

## Domain (`domain/model.py`)

### State after a Material Rule Change

`SyncRule` gains the field `reprojection_required: bool = False`, and the method
`change_policy(transformation) -> SyncRule`:

| Current state | Result |
|---|---|
| Draft, DryRunValidated | Draft |
| Enabled, Paused | Paused |
| Degraded | Degraded (recovery is still required, and one preview validates both) |
| Disabled (removal incomplete) | `InvalidStateTransition` |

- A transformation that equals the current one is not material. The method returns the rule
  unchanged, so the state is not reset.
- Any material change sets `reprojection_required = True`.
- `busy_title` is preserved. The source, destination, and initial lookback are not editable. A
  calendar change goes through Rule Replacement, described below.
- `complete_reprojection()` clears the flag.

The existing states already block enabling after a change: `enable()` accepts only
DryRunValidated, and only `mark_dry_run_validated()` produces that state. The existing
`material_signature` guard in `PreviewSyncRule` rejects a preview that races an edit.

### Rule Removal

`ProjectionHandling` is a StrEnum with the members `DELETE` (recommended) and `DETACH`.

`SyncRule.begin_removal()` moves the rule from any state to **Disabled**, which the UI calls
"Removal incomplete". Disabled is already defined and inert: it cannot sync, preview, or enable.
From now on it means that Rule Removal started but has not finished. A Disabled rule accepts only
another removal, in either mode.

## Application

### Shared rule lock

`RuleLocks` (`application/locking.py`) extracts the per-rule `Lock` map from `ExecuteSyncRule`.
It is injected into `ExecuteSyncRule` and `RemoveSyncRule`, so a removal can never race a Sync Run.

### `ChangeSyncRulePolicy` (`application/rules.py`)

The use case loads the rule, calls `change_policy`, saves it, and appends an audit entry: action
`policy_changed`, with the new policy values in `detail` and no event content. It returns the rule.
It does not take the rule lock, because the reprojection clear-guard below handles a concurrent run.

### Reprojection in `ExecuteSyncRule`

When `rule.reprojection_required` is true:

1. The run is forced to be full: both cursors are treated as `None`, so events that are now
   eligible, such as newly included all-day events, are created.
2. After the source and destination batches, every mapping whose source was not already handled
   in this run is swept. `provider.get_event(mapping.source)` is called:
   - If the source is found, the existing `_synchronize_event` path runs. That is an Update for a
     policy change, a Delete for an all-day event that is now excluded, or a Delete for a cancelled
     source.
   - If the source is not found (`None`), the mapping is recorded as a blocked Conflict audit entry
     and the mapping is kept. An unverifiable source never authorizes deletion.
3. In the transaction that advances the cursors, the rule is re-read. The flag is cleared only if
   its `material_signature` still equals the signature read at the start. If the rule was edited
   during the run, the flag survives and the next run sweeps again.

### Run outcomes

A new port, `RuleRunOutcomeRepository`, is exposed as `uow.run_outcomes`. It has two methods:
`record(outcome)` and `latest(rule_id) -> (sync | None, reconciliation | None)`.
`RuleRunOutcome` stores only the following:

- `rule_id`, `kind` (`sync` | `reconciliation`), `completed_at`, `succeeded`, and `full`
- the counts `created`, `updated`, `deleted`, and `conflicts`
- `checked_mappings` and `drift`
- `failure_kind` (a `ProviderFailureKind` value), with no provider message text

`ExecuteSyncRule` records a success when its cursors advance. On `ProviderFailure` or any other
exception, it records a failure in a fresh unit of work and re-raises. `ReconcileSyncRule` records
its report. A rejection because the rule is not executable is not recorded as a run.

### `GetSyncRuleDetails`

This query use case returns `SyncRuleDetails`: the rule, the count from
`uow.mappings.count_for_rule`, and the latest sync and reconciliation outcomes.

### `RemoveSyncRule`

The use case runs under the rule lock:

1. It loads the rule and fails if it is missing. For `DELETE`, it first requires a provider (503
   when the master key is absent). It also requires the destination Connected Account to be
   connected, checked through a new port `AccountAuthorizations.is_connected(account_id)` that is
   implemented by `SqliteConnectedAccountStore`. If the account is disconnected, the use case
   raises `RemovalRequiresAuthorization`.
2. It calls `begin_removal()`, saves, and commits, so the scheduler skips the rule from then on.
3. For each mapping:
   - `DELETE`: the ownership-checked `provider.delete_projection` is called with a stable Operation
     Key over rule, mapping, and `remove`. Provider not-found counts as done. Then the mapping is
     deleted, an audit entry `remove_projection` is appended, and the change is committed. It
     commits one mapping at a time so no write lock is held across network calls.
   - `DETACH`: the mapping is deleted and an audit entry `detach_projection` is appended, with no
     provider call. These are committed in one short transaction.
4. The rule is removed with `uow.rules.remove(rule_id)`. This deletes the row, and its cursors,
   failures, and outcomes cascade. The same transaction resolves the rule's open incidents. Audit
   entries are kept, and a final `rule_removed` entry records the handling and counts.

A `ProviderFailure` in step 3 stops the removal. The rule stays Disabled with its remaining
mappings, and the error reports how many were processed. Retrying continues from where it stopped,
and may switch to `DETACH`. Managed events without a mapping are never deleted, as the ownership
invariant requires. It returns `RemovalResult(deleted, detached)`.

### `ReplaceSyncRuleCalendars`

The input is the rule id, the new source and destination, and a `ProjectionHandling`.

1. It validates before anything destructive:
   - The rule exists.
   - The new endpoints form a valid `SyncRule`.
   - They differ from the current pair. If they are the same, it raises
     `NotACalendarChange`, which tells the administrator to edit the policy instead.
   - `relationship_exists` is false for the new pair, otherwise it raises
     `DuplicateDirectionalRelationship`.
2. It runs `RemoveSyncRule`.
3. It runs `CreateSyncRule` with a new id, the same transformation and initial lookback, and the
   state Draft.
4. It returns the new rule and the `RemovalResult`.

A duplicate created by a race between steps 1 and 3 fails step 3 with a 409 after the removal has
happened. That is acceptable for a single administrator and is documented.

## Persistence (migration 3: `0003_rule_editing.sql`)

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

- The migration is forward-only through PR #4's `_FORWARD_MIGRATIONS` runner. It commits
  atomically with its version row.
- The in-memory adapter gains the same repositories.
- **Rollback.** The previous image ignores the new column and table. Its explicit column lists in
  `INSERT` and `UPDATE` leave the column at its default. A reprojection that is pending when you roll
  back is not performed by the old image. To apply it, re-save the policy after upgrading again.
  Rules in the Disabled state (removal incomplete) remain inert on the old image.

## HTTP (`interfaces/api`), all behind `require_admin`

| Route | Behavior |
|---|---|
| `GET /api/v1/rules/{id}` | `RuleDetailResponse` extends `RuleResponse` with `initial_lookback_days`, `reprojection_required`, `mapping_count`, `last_sync`, and `last_reconciliation`. Returns 404 for a missing rule. |
| `PATCH /api/v1/rules/{id}` | Body `{privacy_policy, sync_all_day_events}`. Returns `RuleResponse`. Returns 404 for a missing rule, 409 for a Disabled rule, and 422 for an unknown policy. |
| `DELETE /api/v1/rules/{id}?projections=delete\|detach` | The query value is required, with no server default, so the choice stays explicit. Returns `{deleted, detached}`. Returns 404 for a missing rule, 409 when authorization is required, 424 on a provider failure (with the processed count), and 503 when delete is requested without a provider. |
| `POST /api/v1/rules/{id}/replace` | Body `{source, destination, projections}`. Returns 201 with the new `RuleResponse` and the removal counts. Returns 409 for a duplicate relationship, 422 when the calendars are unchanged or invalid, and the same errors as removal otherwise. |

`RuleResponse` also gains `reprojection_required`, so the list can show that a preview is needed.

## Web UI

### Routing (`lib/navigation.ts`)

- `AppLocation = { view: AppView; ruleId: string | null }`.
- `/rules/{id}` parses to the `rules` view with a `ruleId`. The id is URL-decoded, and only a single
  path segment is accepted.
- `appPathForRule(id)` builds the path. `isKnownAppPath` accepts the rule path.
- `App.tsx` passes `ruleId`. `Dashboard` renders `RuleDetailsView` when it is set, and a "Back to
  rules" link returns to the list.

### Rule list

Each row's direction becomes a link to its details page. It is a real `<a>`, so it is keyboard- and
middle-click friendly. The row also shows "Preview required" when `reprojection_required` is true
and the state requires a preview.

### `features/rule-details.tsx`

The page is split out because `dashboard.tsx` is already over 1,000 lines. It has these sections,
separated by dividers and without nested cards:

1. **Header.** The direction uses `AccountAvatar` and `ruleEndpointLabel`, showing the calendar name
   and account email. It has a state badge (text and icon) and the same next action as the row:
   Preview, Enable, Sync now, or Reauthorize.
2. **What this rule does.** A `<dl>` with these entries:
   - Event information: "Busy only" or "Title, description, and location".
   - All-day events: "Included" or "Excluded".
   - Initial window: "Events ending in the last N days or later".
   - Managed projections: `mapping_count`.
3. **Recent runs.** Shows the last synchronization and the last reconciliation. Each gives a
   relative and absolute time, whether it succeeded, and its counts, or "Not run yet". A failure
   is described in plain language mapped from `failure_kind`.
4. **Change policy.** A toggled inline form with the same controls as the rule builder. Before
   saving, a consequence summary is shown:
   - Whether the rule will pause, or return to Draft, and that it needs a new preview.
   - What happens to the N existing projections in the destination calendar, for example that they
     will show titles, descriptions, and locations, will become "Busy", or that all-day
     projections will be deleted.
   - Save is disabled until something changes.
5. **Change calendars.** An inline form with source and destination selectors, the same as the
   builder, and a projection-handling radio group. It states: "This removes the current rule and
   creates a new draft with the same policy."
6. **Remove rule.** A radio group offering "Delete N projections from <destination> (recommended)"
   and "Keep them as ordinary events that are no longer updated". Delete is disabled and explained
   when the destination account is disconnected. Removal needs a second confirmation step that
   uses the existing `disconnect-confirmation` pattern, and a destructive button names the effect,
   for example "Remove rule and delete 37 projections". A Disabled rule shows "Removal incomplete"
   with the retry options.

The pure copy and consequence logic lives in `lib/rule-change.ts`, with Vitest tests. Errors use
`role="alert"` and results use `role="status"`. Every control has a label. The layout stacks at the
existing mobile breakpoint.

## Tests (allowed and blocked paths)

- **Domain**
  - The `change_policy` state table.
  - A policy that is not a change leaves the state unchanged.
  - A Disabled rule is blocked.
  - The flag is set, and cleared by `complete_reprojection`.
  - `begin_removal` from every state.
  - Enabling after an edit fails. Enabling after a preview succeeds.
- **Application**
  - An edit on an Enabled rule stops `ExecuteSyncRule`, which raises `RuleNotExecutable`.
  - A reprojection run updates a mapping outside the lookback window and clears the flag.
  - An edit during a run keeps the flag.
  - A source that cannot be verified during the sweep does not delete, and is recorded as a
    Conflict.
  - Removal in `DELETE` mode deletes through the provider with ownership checks and removes the
    rule.
  - Removal in `DETACH` mode makes zero provider calls.
  - Removal is blocked when the destination is disconnected, with no state change.
  - A partial failure leaves the rule Disabled with its remaining mappings, and a retry completes.
  - A mismatch in ownership metadata stops the removal.
  - Replacement with a duplicate relationship makes zero deletions.
  - Replacement with unchanged calendars is rejected.
  - A successful replacement creates a Draft with the same policy.
  - Success and failure outcomes are recorded.
- **SQLite**
  - Migration 3 on a database at version 2 that already has rules: the default is 0 and the
    migration is idempotent on restart.
  - The outcome repository.
  - `remove` cascades and resolves incidents while keeping audit entries.
- **API**
  - Each new route returns 401 without a session.
  - 404, 409, and 422 paths.
  - `DELETE` without `projections` returns 422.
  - Detail counts and outcomes.
- **Web**
  - The navigation parse and build round trip for `/rules/{id}`, including rejected paths.
  - The consequence copy in `rule-change.ts`.

## Documentation

- **`CONTEXT.md`**: Material Rule Change, noting that a calendar change is not in place (it is a
  Rule Replacement); Rule Removal, covering the incomplete state, retry, and destination
  authorization; Detached Event, which keeps origin metadata and is never a source; and a new term,
  **Rule Replacement**.
- **`docs/domain-model.md`**: the state machine, now showing Disabled as removal incomplete, and the
  reprojection flag.
- **`docs/sync-model.md`**: a reprojection section.
- **`docs/deployment.md`**: migration 3 upgrade and rollback.
- **`CHANGELOG.md`**
- **ADR 0010, "Rule Removal and calendar replacement"**: removal as the only way to change
  calendars, Detached Events keeping their metadata, and removal being resumable through Disabled.

## Out of scope

- Editing the initial lookback or the busy title.
- Bulk removal.
- Deleting unmapped managed events.
- Undoing a removal.
- Recurring-event support.
