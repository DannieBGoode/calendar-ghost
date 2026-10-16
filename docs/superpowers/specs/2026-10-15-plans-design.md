# Plans: design

Terms are in `CONTEXT.md`. [ADR 0028](../../adr/0028-plans-apart-from-commercial-mode.md) settles
Plans in principle, and the [multi-user design](2026-10-09-multi-user-design.md) makes them phase 3.
This design adds Default Plan and Allowance to the glossary, and refines Plan and Plan Hold. ADR
0038 (Plans) and ADR 0039 (Plan Hold) will record it. A panel of three independent designs, three
judges, and several rounds of adversarial review against the code at `4efda9b6` shaped it.

## Goal

The Hosted Service can offer a free Plan and larger Plans, set by an administrator now and by
billing later, with no change to the model. A household administrator can keep one User from
using up shared resources. A self-hosted installation keeps every feature: Plans are off by
default, and with Plans off nothing in this design limits or changes anything.

## Settled decisions

1. **The Hosted Service drives Plans.** On the Hosted Service, Instant Sync may be only for
   high-paying Plans, and a free Plan may sync every 5 to 10 minutes. A self-hosted installation
   has every feature and no limits unless its own administrator turns Plans on.
2. **Plans now, billing later.** This work builds the seams billing needs: one assignment port
   that administrators and billing share, a stable key per Plan, and an assignment record with its
   source, actor, and time. It has no billing code. Billing (Commercial Mode) gets its own spec.
3. **What the rule limit counts.** Enabled rules, and rules stopped only by Lapsed Authorization.
   Drafts, previewed rules, paused rules, and Plan Holds do not count. The check runs at Start.
   Pausing a rule frees its place, and a held rule then resumes on its own.
4. **Only Rule Replacement keeps a place.** Changing a rule's calendars never meets the limit. A
   rule stopped by a provider error, or paused by a Material Rule Change, does not keep its place.
   If the User has held rules, a held rule may take the freed place, and the restart may be
   refused. A held rule has no place, so replacing it keeps none.
5. **Default Plan.** The administrator marks one Plan as the default. A User with no Plan of
   their own has it. Plans cannot turn on until a default exists. Billing falls back to it.
6. **Installation Administrators are never limited.** Under Only Me the only User administers, so
   Plans have no effect there, and the Web UI hides them.
7. **Sync intervals.** A fixed server list: Instant, 5, 10, 15, 30, and 60 minutes. Instant means
   Instant Sync plus a 5-minute poll. The Plan decides the interval. The User keeps only the
   existing Instant Sync on or off preference.
8. **A slower interval applies at once.** Losing Instant Sync, or a longer interval, needs no
   grace: nothing stops.
9. **Manual-run limit.** Only while Plans are on, never for administrators: one fixed limit per
   User, shared by Sync now, Reconcile now, and Rule Preview, kept in memory.
10. **Plan Hold emails.** One email when a grace starts, and one when the scheduled pass holds
    rules. The existing per-User email setting governs both, renamed from "Incident emails" to
    "Email notifications". No email on release, and none for holds the User asks for.
11. **Architecture.** Plans live in `identity`. `sync` reads an `Allowances` port it declares. A
    Plan Hold is a Degraded Rule with stop code 2 in the existing
    `sync_rules.awaiting_reauthorization` column. No new rule state, verdict, or problem kind.
12. **Delivery.** Four slices: (1) Plans core with Instant or 5 minutes; (2) intervals of 10 to 60
    minutes; (3) the manual-run limit; (4) Plan Hold. Plan Hold ships before billing, because a
    payment that ends lowers limits.

## The design in brief

| Concern | Design |
|---|---|
| The one decision | `allowance_for(...)` in `domain/plans.py` returns an `Allowance`: what one User may use now. Its basis is `plans_off`, `administrator`, or `plan`. It drives every limit, the sync cadence, the manual-run limit, and "Your plan". |
| Port | `Allowances.of(user)` and `of_users(users)`, declared in `application/sync/ports.py`, implemented by `SqlitePlans` |
| Storage | One `plans` table, and columns on `installation_settings`, `users`, and `sync_rules`. Migration 33 (slice 1) and 34 (slice 4). No new owned table. |
| Start | Write, count, and refuse with `plan_limit_reached` when the count is over the limit |
| Rule Replacement | The new draft is created, holding the old rule's place, in the transaction that begins the old rule's removal |
| Plan Hold | A Degraded Rule with stop code 2. Every reader of enabled rules already skips it. |
| Grace | One 7-day grace per User, started by the scheduled pass when the User is over their rule limit. The pass holds rules only after the grace ends, and never swaps rules. |
| Monitors | No new verdict or problem kind. Additive `counts.held` and `rules[].stop_cause`. |
| Scheduler | Each rule is due once per window of its interval, at its own stable phase. Instant and 5-minute rules are due at every pass, so Plans off changes nothing. |
| Faults | A fault in reading Plans never stops syncing, signing in, or reading rules, and never holds a rule. A limit check that cannot read the Plan fails like any database error. |

## 1. Domain

### 1.1 `domain/plans.py` (slice 1)

It imports only `domain/cadence.py`. `domain/access.py` imports `PlanKey` from it.

- `PlanKey`: lower-case letters, digits, and hyphens, at most 32 characters. Chosen at creation,
  never renamed. Billing will map prices to it.
- `SyncInterval` (`StrEnum`): `instant`, `5_minutes`, `10_minutes`, `15_minutes`, `30_minutes`,
  `60_minutes`. Its `cadence` maps `instant` to today's `DEFAULT_CADENCE` (Instant Sync plus a
  5-minute poll), and N minutes to `SyncCadence(instant=False, poll_every=N minutes)`.
- `OFFERED_INTERVALS`: what an administrator may choose. Slice 1 offers `instant` and
  `5_minutes`; slice 2 offers all six. Every value is known from slice 1, so a rollback from slice
  2 can still read every Plan. Until slice 2, an interval that is not offered maps to a 5-minute
  poll, because the scheduler then lists every rule at every pass.
- `PlanLimits(rules, connected_accounts, integration_tokens, sync_interval)`. Each count is a
  number or `None` for unlimited. Rules and accounts allow 1 to 10000. Tokens allow 0 to 10000,
  so a Plan may offer none.
- `Plan(key, name, limits)`. The name is 1 to 60 printable characters and can change.
- `AssignmentSource` (`StrEnum`): `administrator`, `billing`. Only the phase-5 billing adapter
  writes `billing`.
- `Allowance(basis, plan, on_default, assigned)`. `limits` is the Plan's limits when the basis is
  `plan`, and no limits otherwise. `cadence` follows `limits.sync_interval`. `limits_manual_runs`
  is true only when the basis is `plan`. `assigned` is the User's own stored Plan, so an
  administrator can see a Plan that does not apply yet.

`allowance_for(plans_on, administers, own, default)` decides in this order:

| Facts | Allowance |
|---|---|
| Plans are off | `plans_off`, no limits |
| The User administers | `administrator`, no limits |
| The User has their own Plan | `plan`, that Plan |
| Otherwise | `plan`, the Default Plan, with `on_default` |
| Plans on and no Plan found | No limits, and the adapter logs a warning. It cannot happen (section 3), but a fault in Plans must never limit anything. |

Pure policies beside it: `require_plans_setting` (decision 5: no default, no Plans),
`require_removable` (not the default, nobody has it), `require_room` (raises
`PlanLimitReached(resource, limit)`), and `may_start(before, counting_after, limit)`, which is true
when there is no limit, when the rule keeps a place, or when the count after the Start is within
the limit.

`PlanLimitReached` is a `DomainError`, not a validation error, so no route turns it into 422 by
accident. Each route that can meet it catches it by name.

### 1.2 `User` and `SyncRule`

`User` gains `plan: PlanKey | None = None`: the User's own Plan, where `None` means the Default
Plan.

`SyncRule` gains two fields, neither in `material_signature`:

- `keeps_place` (slice 1): a Rule Replacement draft that holds the place of the rule it replaced,
  until it starts or is removed. It is valid only on a DRAFT or PREVIEWED rule.
- `held_by_plan` (slice 4): a Degraded Rule held by its User's Plan. It resumes without a preview
  once the rule limit allows it. It excludes `awaiting_reauthorization`, so a rule has at most one
  self-resuming stop cause.

Properties: `holdable` (enabled, or stopped only by Lapsed Authorization), `counts_toward_plan`
(`holdable or keeps_place`), `stopped_by_plan_hold`, and `stop_cause` (`lapsed_authorization`,
`plan_hold`, or none, as a `RuleStopCause` enum).

New transitions:

- `take_place_of(old)` (slice 1): on a DRAFT or PREVIEWED rule, sets `keeps_place` to
  `old.counts_toward_plan`.
- `give_up_place()` (slice 4): clears `keeps_place`.
- `hold()` (slice 4): requires `holdable`; the result is DEGRADED with `held_by_plan`. Holding a
  lapse-stopped rule replaces its lapse cause while the hold lasts.
- `release_hold(authorized)` (slice 4): ENABLED when both accounts are authorized, and otherwise
  lapse-stopped, which still counts and resumes later through ADR 0027.

Changes to existing transitions:

| Transition | `keeps_place` | `held_by_plan` |
|---|---|---|
| `mark_previewed` | kept | **a held rule stays held.** Preview is never limited, and never removes the self-resume. |
| `enable` | cleared: the rule now counts as enabled | not reachable |
| `pause` | not reachable | cleared: the rule needs a preview |
| `degrade` | cleared | **cleared, and so is `awaiting_reauthorization`: the rule becomes a plain Degraded Rule that needs a preview.** A run in flight when its rule was held, or when its account lapsed, can still report a failure that needs intervention, and that failure must win over any self-resume. `health._degrade` today acts only on a rule that synchronizes (`health.py:171-178`), so it drops such a failure for a lapse-stopped rule even now. It now acts on any rule that synchronizes or has a self-resuming stop. |
| `require_preview`, `begin_removal` | cleared | cleared |
| `on_account_disconnected` | cleared in every branch: disconnecting is deliberate | cleared through `require_preview` |
| `change_policy` | kept on a draft | cleared: a plain Degraded Rule that needs a preview (AGENTS.md invariant) |
| `resume_after_reauthorization` | not reachable | not reachable: a held rule never awaits reauthorization |

`on_account_disconnected` returns `self.degrade()` first for enabled and previewed rules
(`model.py:528-529`), so the clearing must happen in `degrade` and in each later branch.

What decision 4 means in practice, each pinned by a test: a rule a provider failure stops does
not count, and its recovery Start is checked; a rule a Material Rule Change pauses does not count;
previewing a lapse-stopped rule makes it PREVIEWED, which does not count; replacing a rule that
does not count keeps no place, and the replacement stays the newest rule.

### 1.3 `domain/plan_hold.py` (slice 4)

```python
GRACE = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class PlanGrace:
    holds_at: datetime  # when rules beyond the limit are held
    rule_limit: int  # the rule limit when the grace was last settled
    admissions: int  # the User's admission counter when the grace was last settled


@dataclass(frozen=True, slots=True)
class RuleStanding:
    rule_id: SyncRuleId
    place: RulePlace  # COUNTED (holdable), RESERVED (keeps_place), or HELD
    order: int  # creation_order; a replacement that keeps a place inherits it
    kept: bool  # the User's keep choice

    @property
    def rank(self) -> tuple[bool, int, str]:
        # Lower is better: kept first, then the oldest.
        return (not self.kept, self.order, self.rule_id.value)


def settle(
    standings: Sequence[RuleStanding],
    limit: int | None,
    grace: PlanGrace | None,
    admissions: int,
    now: datetime,
    *,
    active: bool,
) -> Settlement: ...
```

For one User: `L` is the rule limit (`None` is unlimited), `C` is the counted and reserved rules,
and `H` is the held rules. `settle` decides in five steps:

1. **A Disabled User.** Clear the grace. Nothing else.
2. **No limit** (Plans off, the User administers, or an unlimited Plan). Release every held rule,
   and clear the grace.
3. **Count.** `over = |C| - L`.
4. **Over the limit.**
   - No grace: start one, `holds_at = now + GRACE`, with the grace email.
   - A grace, and `L` is below its `rule_limit` (the limit went down again), or the User's
     admission counter is above its `admissions` (the User added a rule to the count since the
     last settle, which is only possible while within a limit, so the limit went up and down again
     between two passes): restart it with a new `holds_at`, with the grace email.
   - Otherwise keep `holds_at`.
   - Store `rule_limit = L` and `admissions` in every case.
   - Before `holds_at`: nothing else.
   - From `holds_at`: take the `over` worst-ranked rules of `C`. Hold each counted one, and make
     each reserved one give up its place. Send the "rules held" email. Keep the grace while the
     User is still over the limit, so the next pass finishes an interrupted settle with no new
     grace.
5. **Within the limit.** Release held rules into the free places, `L - |C|` of them, best rank
   first: kept rules, then the oldest. Clear the grace.

**Why the User cannot extend a grace.** A grace starts or restarts only when the User is over the
limit, and only a change of limit puts them there. Start is checked against the limit read inside
its own transaction; a lapse resume, a Rule Replacement, and a keep-choice swap do not change the
count; a release is checked; pause, removal, preview, a Material Rule Change, and disconnect never
raise it. So no act of the User grows the count above the limit. `users.plan_admissions` counts
every rule the User adds to the count, in the same transaction: a Start of a rule that did not
count before, and a release that a keep choice makes into a free place. A removal never lowers it,
so an admission stays visible even when the User removes another rule in the same interval.

**What a grace never does.** The pass holds only after a grace that started after the change of
limit that put the User over it. A rule the User starts is never held without a grace: a Start is
refused while the User is over the limit, and a Start or a keep-choice release made during a raise
that is gone by the next pass moves the admission counter, which restarts the grace.

## 2. Contexts and ports

| Where | What |
|---|---|
| `application/sync/ports.py` | `Allowances` (`of`, `of_users`). `SyncRuleRepository.inherit_place(rule, of)`. Slice 4: `standings()`, `keep(chosen)`, and a `PlanGraceRecord` on the User unit of work. |
| `application/sync/watch_ports.py` | `SyncCadencePolicy` gains `cadences(users)`. `PlanCadence(allowances)` implements it and replaces `EveryUserInstant` in `Adapters.sync_cadence`. |
| `application/sync/rules.py` | `EnableSyncRule` gains `allowances` and `owner`. `ReplaceSyncRuleCalendars` passes its new draft to the removal as `successor`. `GetSyncRuleDetails` answers `can_start`. |
| `application/sync/removal.py` | `RemoveSyncRule.execute(..., successor=None)` inserts the successor with the old rule's place (section 4) |
| `application/sync/plan_holds.py` (slice 4) | `PlanHolds.settle(notify)`, `ChooseKeptRules`, `SettleLocks`, the `PlanNotices` port |
| `application/sync/manual_runs.py` (slice 3) | `AdmitManualRun`, the `RunThrottle` port, `ManualRunsThrottled` |
| `application/identity/ports.py` | `PlanCatalog` (settings, list, get, add, change, remove) and `PlanAssignments.assign(user, plan, change)`, where `change` is `AssignmentChange(source, actor, at)`. Billing will depend on `PlanAssignments` only. |
| `application/identity/plans.py` | `ShowPlans`, `DefinePlan`, `ChangePlan`, `RemovePlan`, `SetPlansSetting`, `AssignPlan`. Each calls `require_administrator` first. |
| `application/identity/integration_tokens.py` | New `IssueIntegrationToken`, which also takes over the route's `installation:read` administrator check |
| `application/operations/own_plan.py` | `ShowOwnPlan`: a read model across sync and identity |
| `application/operations/scheduled_pass.py` | Slice 2: the due filter. Slice 4: the settle step and the notices it hands to the scheduler. |
| `infrastructure/persistence/plans.py` | `SqlitePlans` implements `Allowances`, `PlanCatalog`, and `PlanAssignments`. Each client depends only on the port it uses. |

`sync` declares `Allowances`, as it already declares `SyncCadencePolicy`, so it enforces limits
without importing `identity`. The lint-imports layers and the ADR 0032 contexts do not change. No
new module receives `InstallationUnitOfWork`: the hold step runs in `scheduled_pass.py`, which
already does. Classes already at the 7-field bound (`InstantSyncStatus`, `RuleHealth`,
`PreviewSyncRule`, `UpkeepWatches`) gain no field, so the manual-run gate sits in the routes. A
separate `plans` context can be split out later if billing grows large.

## 3. Persistence, migrations, and rollback

### 3.1 Migration 33 (slice 1)

```sql
CREATE TABLE plans (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    rule_limit INTEGER,              -- NULL: unlimited
    account_limit INTEGER,
    token_limit INTEGER,
    sync_interval TEXT NOT NULL,     -- no CHECK, so the list can grow without a table rebuild
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
ALTER TABLE installation_settings ADD COLUMN plans_enabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE installation_settings ADD COLUMN default_plan_key TEXT REFERENCES plans(key);
ALTER TABLE users ADD COLUMN plan_key TEXT REFERENCES plans(key);   -- NULL: the Default Plan
ALTER TABLE users ADD COLUMN plan_assigned_by TEXT;                 -- administrator | billing
ALTER TABLE users ADD COLUMN plan_assigner_id TEXT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE users ADD COLUMN plan_assigned_at TEXT;
ALTER TABLE sync_rules ADD COLUMN keeps_place INTEGER NOT NULL DEFAULT 0;
```

- Nothing is backfilled. Plans start off and limit nobody.
- The foreign keys keep NO ACTION, so the database refuses to delete a Plan that a User or the
  default names.
- `plans` joins `INSTALLATION_TABLES` in `test_user_isolation_schema.py`. The assignment is a
  column on `users`, which is an installation table, so no rule of the test changes.
- `SqliteRegistrationSettings.return_to_setup` also sets `plans_enabled = 0`. Definitions stay, and
  a new first User never inherits hidden limits.
- Phase 4 rebuilds `installation_settings` to allow Open registration, and must carry these columns.

### 3.2 Migration 34 (slice 4)

```sql
ALTER TABLE sync_rules ADD COLUMN plan_kept INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN plan_holds_at TEXT;      -- NULL: no grace
ALTER TABLE users ADD COLUMN plan_grace_limit INTEGER;
ALTER TABLE users ADD COLUMN plan_grace_admissions INTEGER;
ALTER TABLE users ADD COLUMN plan_admissions INTEGER NOT NULL DEFAULT 0;
```

`sync_rules.awaiting_reauthorization` gains the value 2. Only the User unit of work writes these
columns, on its own User's row, through `PlanGraceRecord`. `SqliteUserDirectory` never reads
them.

### 3.3 The rule adapter

- `_rule_values` writes `2` for a held rule, and `0` or `1` otherwise. `rule_from_row` reads 1 as
  awaiting reauthorization, and 2 on a degraded row as held. Any other value reads as a plain
  Degraded Rule that needs a preview, which fails safe.
- `keeps_place` is read only on draft and previewed rows, so a stale mark never breaks the domain
  invariant.
- `inherit_place(rule, of=old)` gives the replacement the old rule's `creation_order` (and, from
  slice 4, its `plan_kept`), in the transaction that moves the place, and only when the old rule
  counted. A replacement of a rule that did not count, a held rule included, keeps its own new
  order and no keep mark, so it is the newest rule. `creation_order` has no UNIQUE constraint,
  and the two rules never count at the same time.
- `standings()` (slice 4) lists the User's counted, reserved, and held rules in rank order.
- `keep(chosen)` sets the whole kept set in one statement. `_update` never writes `plan_kept`, so a
  late save of a rule cannot overwrite the choice.
- `list()` keeps its order, so the Rules page does not change.

### 3.4 `SqlitePlans`

- `of_users` reads in chunks of 500 Users, the bound the installation reads already use.
- An interval this release does not know reads as `instant` with a warning.
- **Limit checks fail closed.** Start, account save, and token issue read the allowance inside
  their own transaction (section 3.6). A read that raises fails the request, as any database error
  does. So a fault never admits a resource past the limit.
- **Everything else fails open.** A read that raises makes the scheduler list every rule, makes
  each Instant Sync and upkeep reader treat the User as instant, makes every display of a cadence
  fall back to `DEFAULT_CADENCE`, and lets manual runs through. `can_start` answers true, and the
  Start itself still checks. So a Plans fault never stops syncing, sign-in, or the rules API.
- **Settling** with a failed read settles nobody that pass, because "no limit" there would release
  every hold.
- Writes (`change_settings`, `add`, `change`, `remove`, `assign`) run under `BEGIN IMMEDIATE`, as
  `SqliteRegistrationSettings` does.
- `plans()` returns each Plan with `people` (everyone who has it, which `plan_in_use` uses) and
  `limited_people` (active Users who do not administer, whom it limits now).

### 3.5 The in-memory store and contracts

The in-memory store gains the same fields: rule order, keep marks, and the grace. A `MemoryPlans`
fake in `tests/identity_fakes.py` implements the three Plans ports. `tests/contracts/persistence.py`
covers the new rule fields, stop codes 0 to 2, `inherit_place`, `keep`, `standings`, the grace
record, and that held rules never appear in `scheduled_rules` or `pending_instant_runs` and never
want watch coverage. `instant_sync_owners` keeps listing a User whose only rules are held while
their watches exist, so upkeep retires those watches. `tests/users.py` gains a `limited_user()`
helper, because `add_user` defaults to an administrator, who is never limited.

### 3.6 Race safety

The User unit of work uses DEFERRED transactions, so the first write takes SQLite's writer lock
and later reads see the latest commits. "Write, count, then roll back on failure" is therefore
serialized against every other writer, as `CreateSyncRule` already relies on.

Plan writes (`SqlitePlans`) run under `BEGIN IMMEDIATE`. The database runs in WAL mode, so a read
on `SqlitePlans`' own connection, made after a transaction has taken the writer lock, sees every
committed Plan change, and no Plan change can commit until that transaction ends. Each check below
reads the allowance at that point, so its decision and the limit it used cannot drift apart.

| Check | Mechanism |
|---|---|
| Start | Save `enable()`, then read the allowance, count, and raise `PlanLimitReached` before the commit when `may_start` fails. Two Starts cannot both take the last place, and a lowering cannot slip in between. From slice 4, a Start of a rule that did not count also adds one to `users.plan_admissions` in the same transaction. |
| Place move | Section 4: the replacement draft is inserted, and the old rule's removal begins, in one transaction |
| Settle | **One transaction per User.** Take the User's `SettleLocks` lock, then the write locks of the User's counted, reserved, and held rules in id order, then open a unit of work that takes the writer lock first. Inside it, read the allowance, the grace, the standings, and the authorization of every account the rules use; decide with `settle`; write every hold, give-up, release, and the grace; commit. A settle changes only rules whose write locks it holds. A rule that appears or starts meanwhile (a new Rule Replacement draft, or a Start) is outside the locked set: the decision counts it, but it stays as it is until the next pass, so no rule is ever changed without its lock. A release derives ENABLED or lapse-stopped from the account records read in that transaction, so a lapse that commits first is seen, and one that commits after sees the released rule as enabled and stops it. |
| Keep choice | `ChooseKeptRules` uses the same single transaction, under the same locks. Each release it makes into a free place adds one to `users.plan_admissions`. |
| Connected Account | Inside the existing `BEGIN IMMEDIATE` of `SqliteUserConnectedAccounts.save`, and only when no row has the same provider and email. Reauthorization never reaches the count. |
| Integration Token | `issue(..., within=limit)` runs under `BEGIN IMMEDIATE`, reads the limit, counts unrevoked tokens, then inserts |

In-process locks must be taken before SQLite's writer lock. One path breaks this today:
`ChangeFeedCursors.advance` writes both cursors, which takes the writer lock, and only then takes
the rule write lock (`change_feeds.py:111-118`). A lifecycle change or a settle that holds that rule
lock then waits for the writer lock until SQLite's 5-second busy timeout fails it. `advance` takes
the rule write lock before its first write, and keeps its writes and commit inside it. A threaded
regression test pins the order.

A settle holds rule write locks only for its short transaction, with no provider call. A run in
flight holds the rule's run lock, not its write lock, so a hold does not wait for it: the run's own
stop check, made under the write lock before each provider write, sees the hold and stops. If that
run then reports a failure that needs intervention, the hold ends (section 1.2).

### 3.7 Upgrade and rollback

This text goes into the SQL headers, `docs/deployment.md`, and the CHANGELOG.

- **Migration 33.** Rolling back works with the same database. Earlier releases ignore the table
  and the columns, and limit nobody. After upgrading again, Plans are as the administrator left
  them.
- **Migration 34.** Rolling back works with the same database. An earlier release reads a held
  rule as stopped by Lapsed Authorization, so its monitor reads `stopped`. It resumes that rule
  when an account is reauthorized or its access check passes, and it can preview and start it.
  Each save it makes writes 0 or 1, so no hold outlives a change it made. On a release with Plans
  but without Plan Hold (slices 1 to 3), a held rule also reads as lapse-stopped and counts.
- **Slices 2 and 3** add no migration. Rolling them back restores polling every five minutes and
  unlimited manual runs.

## 4. Limits and enforcement

| Resource | What counts | Checked at | Refusal | When the limit is lowered |
|---|---|---|---|---|
| Rules | Enabled rules, lapse-stopped rules, and replacement drafts that keep a place | Start, and hold release. Creating and previewing are never limited. | 409 `plan_limit_reached` | A 7-day grace, then Plan Hold (section 5). Until slice 4, new Starts are refused and nothing stops. |
| Connected Accounts | Every account of the User, Disconnected Accounts included | Saving a new provider and email after OAuth | The OAuth outcome `account_limit_reached` | Existing accounts stay, and so does their Reauthorization. New accounts are refused. |
| Integration Tokens | Unrevoked tokens | `IssueIntegrationToken` | 409 `plan_limit_reached` | Existing tokens keep working (ADR 0024: silent expiry breaks monitors). New ones are refused. |
| Sync interval | Not a count | The scheduler and Instant Sync | none | At once (decision 8) |

**Rules.** A rule that keeps a place always starts, because its Start does not change the count.
A lapse resume needs no check, because a lapse-stopped rule already counts. `GetSyncRuleDetails`
answers `can_start`, `rule_limit`, and `held_rules`, so the Web UI disables Start with the same
message a refused Start shows, and computes nothing itself.

**Rule Replacement.** Today `ReplaceSyncRuleCalendars` creates the new draft, then removes the old
rule (`rules.py:279-289`). The draft is visible while the removal waits for the old rule's run,
and if the removal then fails, the draft is deleted without its locks, even after a client started
it. This design creates the draft later instead:

- `RemoveSyncRule.execute` gains `successor: SyncRule | None`. After it waits for the old rule's
  run lock, it inserts the successor in the same transaction that saves `begin_removal()`, with the
  checks `CreateSyncRule` makes today (no duplicate relationship, both accounts exist), plus
  `take_place_of(old)`, and `inherit_place` when the old rule counted. The old rule is read under
  its write lock in that transaction. The checks move into a helper that takes the open unit of
  work, which `CreateSyncRule` also calls: calling `CreateSyncRule.execute` there would open a
  second transaction.
- If any check fails, the transaction rolls back: the old rule stays as it was, and no draft
  exists. The uniqueness constraint still refuses a concurrent duplicate before anything
  destructive happens.
- After the commit, the draft holds the old rule's place, and the old rule no longer counts. No
  moment counts both, no client can see the draft before its place moves, and no cleanup path
  deletes a draft.
- An interrupted removal keeps the draft and its place, as `ReplacementInterrupted` does today.

**Connected Accounts.** Disconnected Accounts count, because reconnecting one is Reauthorization,
which is never refused. Otherwise a User could disconnect one account, connect another, and then
reauthorize the first. The check can only run after the provider's consent, because only then is
the address known. The Web UI disables Connect at the limit, and Reauthorize stays enabled. When
an account's address changes at the limit (a renamed Microsoft or Google Workspace account), the
documented recovery keeps every rule: get one free account place, connect the new address, use
Replace calendars on each rule, then disconnect and delete the old account. Deleting the old account
first would delete its rules. When every place is in use by accounts with rules, the free place
comes from an administrator, who raises the limit or assigns a larger Plan for the recovery.

**Integration Tokens.** `installation:read` tokens are for administrators only, who are never
limited, so health monitoring is never blocked.

## 5. Plan Hold (slice 4)

### 5.1 Representation

A held rule is DEGRADED with code 2 in `sync_rules.awaiting_reauthorization`. The domain keeps two
booleans, and only the adapter knows the code. ADR 0027 foresaw this: "the Degraded Rule gains a
recorded stop cause".

- Every reader of enabled rules already skips it: the scheduler, Instant Sync dispatch and
  watches, the watch inbox, Sync now, and Reconcile now.
- `users_with_unfinished_lapses` selects code 1 only, so a held rule is never taken for a lapse.
- Release 31 reads 2 as true and writes 0 or 1 on every save, and the column has no CHECK. So no
  stale hold survives a rollback, and no rule ever skips a recovery preview it needs.

### 5.2 Settling

The scheduled pass settles right after it finishes interrupted lapses, and before it lists rules,
so a released rule can run in the same pass.

- `InstallationUnitOfWork.plan_standings()` reads, in one statement that starts from `users`,
  every User with a counted, reserved, or held rule, or with a grace.
- The pure `settle` runs over that light read. Only Users whose settlement would change something
  are settled, at most 100 per pass, in turns, so a User whose settle keeps failing never blocks
  the others.
- `PlanHolds.settle` settles one User in one short transaction (section 3.6): it reads, decides
  with `settle`, and writes everything at once. A failure rolls the whole settle back, and the
  next pass tries again.
- A failed allowance read settles nobody that pass. A Plans fault never holds a rule.
- `settle` hands each email to the pass instead of sending it. The scheduler sends them on a
  thread of its own after the pass lists its rules, as it does for `checks_due()`. A slow SMTP
  server never delays syncing.

### 5.3 Keep choice

- `PUT /api/v1/account/plan/kept-rules` saves which rules should keep syncing: at most `L` of the
  User's counted, reserved, and held rules. A save sets the whole kept set.
- The save applies at once, in `ChooseKeptRules`, in one transaction (section 3.6). While a place
  is free, the best kept held rule is released into it. Then, while a kept held rule and a
  not-kept counted rule both exist, a swap holds the worst-ranked not-kept rule and releases the
  best kept held rule. The count does not change.
- No email for these holds: the User asked for them.
- During a grace, the choice decides which rules the pass will hold.
- **The pass never swaps.** A kept rule can stay held while a not-kept rule runs, for example when
  the User starts a rule just before the pass releases a held one. Saving the choice again swaps
  them.

### 5.4 Interactions

| Event | Effect |
|---|---|
| A held rule's account lapses | No change: a lapse stops only enabled rules. On release, an unauthorized account makes the rule lapse-stopped, which counts. |
| A run in flight when the rule is held | Its next stop check stops it before any provider write. If it then reports a failure that needs intervention, the hold (or a lapse that replaced it on release) ends, and the rule becomes a plain Degraded Rule that needs a preview. |
| Reauthorization | Resumes code-1 rules only. Held rules stay held. |
| Pause a counted rule | Frees its place. The next pass releases the best held rule into it. |
| Pause a held rule | Becomes PAUSED and needs a preview. It frees nothing. |
| Preview a held rule | Allowed. The rule stays held. The footer explains the hold in place of Start. |
| Material Rule Change on a held rule | A plain Degraded Rule that needs a preview, and does not count |
| Sync now or Reconcile now on a held rule | `rule_not_executable`, as for a paused rule. The Web UI hides both. |
| Remove a counted rule | Frees its place for a held rule at the next pass |
| Disconnect an account | The hold ends, and the rule needs a preview |
| Disabled User | The grace clears. Holds stay. Once enabled again, an excess gets a new 7 days. |
| Plans turned off, or the administrator role granted | No limit: the next pass releases every hold and clears the grace |
| Plans turned on, a default change, a Plan edit, an assignment, or the role removed | The next pass starts a grace for each User over their limit |
| Plan deleted | Refused while it is the default or anyone has it |
| Billing ends a payment (later) | `assign(user, None, billing)` puts the User back on the Default Plan, and the usual settle applies |

## 6. Status, monitors, and emails

### 6.1 Installation Status (slice 4)

- A held rule gets no Stopped problem, and no false "needs reauthorization".
- The hold covers the held rule's own open incidents and blocks, as its Stopped problem covered
  them before. They never make `needs_attention` true. They stay listed in Activity, and close
  after the rule is released and runs.
- A lapsed account whose only rules are held keeps its own problem: the User can fix it now.
- Held rules count toward `stalled`, because they need the scheduler to resume.
- No new problem kind and no new verdict. When every rule that ran is held, the verdict is
  `paused`. Otherwise the running rules decide it. A grace is no status problem: nothing is stopped
  yet.
- `RuleCounts` gains `held`. `running` and `stopped` exclude held rules.
- The Web UI's Dashboard gains `held_rules`, and its open-incident and block counts leave out held
  rules'. `/api/v1/status` keeps the meaning of `counts.open_incidents` and
  `counts.blocked_events`, and gains `counts.held` and `rules[].stop_cause`.
- **A behaviour change to announce.** Today every visible `degraded` rule has a Stopped problem.
  After slice 4, a `degraded` rule can come with no problem and a `paused` or `healthy` verdict.
  The CHANGELOG and `docs/self-hosting.md` say: read `stop_cause` or `needs_attention`, not `state`.
- MCP gains no tool. Its instructions gain one line about `stop_cause: plan_hold`.

A hold is not an Incident (nothing failed) and writes no Audit Entry (a lapse, a pause, and a
resume write none either).

### 6.2 Emails (slice 4)

- `OwnerNotifier` sends them, with the same gates as incident email: an email address, the setting
  on, an active User, and SMTP configured. Subject: "Calendar Ghost: your plan". English only, like
  incident email.
- **Grace started:** "{count} of your rules count toward your plan, which allows {limit}. After
  {date} at {time} UTC, {held} of them will be held until your plan has room. You can choose which
  rules keep syncing under Settings, Your account, Your plan." Users have no stored time zone, so
  the email names UTC. The Web UI shows the same time in local time.
- **Rules held:** "{held} of your rules are now held by your plan. They keep their events and
  resume by themselves when your plan has room."
- Each email links to `/settings/account#your-plan` only when the installation has a public
  address, as incident email does.
- The emails count rules and never name them. A dedicated test checks that no calendar, account,
  rule id, or event marker appears.
- "Incident emails" becomes "Email notifications" in every string of the setting, in CONTEXT
  (Incident Notification), `docs/data-ownership.md`, `docs/deployment.md`, and
  `docs/troubleshooting.md`. The troubleshooting section's old anchor stays alive, because earlier
  releases link to it.

## 7. Sync intervals in the scheduler (slice 2)

Today `SyncScheduler` runs a pass, sleeps 300 seconds, and runs every enabled rule at every pass.
`poll_every` exists but only the rules API reads it.

- **Due once per window.** `scheduled_run_due` lists a rule when its interval is 5 minutes or
  less, when it never ran, or when the pass begins in a new window of its interval. Each rule's
  windows start at its own stable phase (a SHA-256 of its id, modulo the interval), so 3,000 rules
  on an hourly Plan spread over the passes of the hour instead of all running at one pass and
  delaying the faster Plans.
- **Always due, at the next pass:**
  - a failing rule, from its last outcome or a `rule_failures` row. Sync now and Reconcile now
    never clear `rule_failures`, so a manual success does not stop the retries, and Provider
    Incidents keep today's timing;
  - a rule previewed since its last run, so "The first sync runs within five minutes" stays true;
  - a rule with a pending reprojection after a Material Rule Change.
- **Windows are measured from pass begins.** `ScheduledPass` keeps, in memory, the begin time of
  the pass that last listed each rule. A manual run does not move it, so Sync now can never keep a
  rule from being listed. After a restart, a rule is due from its last run once, and also whenever
  its daily full pass is due, so manual runs and restarts together cannot starve the full pass.
- **The daily full pass is spread too.** `_full_pass_due` keeps deciding whether a listed rule's
  run is its full pass, as today. A rule takes its full pass at its first listing after 00:00 UTC,
  at its own phase, so at most one interval late, and the full passes of hourly rules spread over
  the first hour of the day instead of all landing on one pass.
- **Fail open.** A failed allowance read lists every rule, as with Plans off. Each batch cadence
  read in Instant Sync dispatch, watch upkeep, and the installation hints falls back per User, and
  a User whose read still fails counts as instant, so a transient error never drops their Instant
  Sync requests or retires their watches. `InstantSyncStatus` falls back to `DEFAULT_CADENCE`, so a
  Plans fault never breaks sign-in or the rules API.
- **Overdue and stall do not change.** A rule that is not due is not failing, so its last success
  is at most about one interval old, far under the 24-hour overdue bound. A test pins this.
- **Losing Instant Sync** needs no new code. Dispatch drops the User's pending requests, upkeep
  retires their watches, and availability reads `not_in_plan`, whose copy already exists. The
  User's own preference is kept.
- **Copy.** "Every five minutes" becomes the User's own interval in the Overview, CONTEXT
  (Scheduled Sync, Sync Cadence, and the Instant Sync wording row), `docs/sync-model.md`,
  `docs/instant-sync.md`, `docs/self-hosting.md`, `README.md`, and ADR 0036. The landing page adds
  "by default". `docs/troubleshooting.md`'s "within five minutes" stays true for failing rules.
- **An accepted edge.** A run already in flight can record its success after a Pause, a Preview,
  and a Start. The first run after that Start then waits up to one interval. Nothing is lost.

## 8. Manual-run limit (slice 3)

- **12 manual runs per User in any 60 minutes**, shared by Sync now, Reconcile now, and Preview,
  only while the User's Allowance has the basis `plan`.
- **Why 12 per hour.** Sync now is an incremental poll. A higher limit would let a script poll
  faster than the User's Plan allows: 20 runs per 15 minutes is 80 polls an hour on a 60-minute
  Plan. 12 per hour is one run every 5 minutes, the shortest interval. It still lets a User set up
  5 rules, preview each twice, and run Sync now a few times.
- **Where.** Each of the three routes admits the run inside its worker thread, after
  `available()`, right before the use case. A 503 answer uses no budget.
- **Refusal.** 429 `manual_runs_throttled`, with a `Retry-After` header: "You started many runs
  in a short time. Try again in {count} seconds." It never calls this a Plan limit.
- **In memory, and atomic.** `RunThrottle.admit(user)` drops old entries, checks the count, and
  records the run under one lock, so concurrent requests cannot all pass the check.
  (`MemorySignInThrottle` checks and records under separate locks, `throttle.py:35-47`, which is
  fine for sign-in but not here.) A restart forgets the counts, which only gives runs back.
- **Live provider checks** run as an administrator, or with Plans off, and wait once on a 429.

## 9. Plan administration

| Use case | Effect and refusals |
|---|---|
| `ShowPlans` | Every Plan with `people` and `limited_people`, the setting, the default, and the offered intervals |
| `DefinePlan` | 409 `plan_key_taken`; 422 `invalid_plan` with the reason |
| `ChangePlan` | The key never changes. New limits apply at once to new resources. The form warns how many people the Plan limits, and that rules beyond a lower limit keep syncing for 7 days, then are held (before slice 4: that no new rule can start). |
| `RemovePlan` | 409 `plan_is_default`, or 409 `plan_in_use` with `people`. The administrator moves those Users first, which is also safe for billing. |
| `SetPlansSetting` | 409 `plans_need_default` when turning Plans on without a default. Turning them off is always allowed and keeps everything. |
| `AssignPlan` | `PlanAssignments.assign(user, plan, AssignmentChange(administrator, actor, now))`. `None` returns the User to the default. Allowed while Plans are off, so an administrator can prepare. |

- **Billing seam.** Billing will call the same port with `AssignmentChange(billing, None, at)`,
  and assign `None` when a payment ends. `plan_assigned_by` lets the billing spec decide whether
  billing may overwrite an assignment an administrator made.
- **Provenance.** The current assignment records its source, actor, and time. A history waits for
  the deferred record of administrator actions. Each change writes a log line with ids only.
- **Operator Overview.** The person page shows a Plan fact ("Family", "Free (default)", "No plan
  limits administrators") and a "Change plan" action, whenever at least one Plan exists. This
  keeps ADR 0030's promise, and CONTEXT's Operator Overview entry gains the Plan.
- **Invitations** carry no Plan. Invited Users start on the default.
- A malformed Plan key in a path names no Plan, so it answers 404 `plan_not_found`.

## 10. API and Web UI

### 10.1 Routes

| Method and path | Guard | Slice |
|---|---|---|
| `GET /api/v1/plans` | administrator | 1 |
| `PUT /api/v1/plan-settings` | administrator | 1 |
| `POST /api/v1/plans`, `PUT` and `DELETE /api/v1/plans/{plan_key}` | administrator | 1 |
| `PUT /api/v1/users/{user_id}/plan` (in `routes/users.py`, through `_named_user`) | administrator | 1 |
| `GET /api/v1/account/plan` | current user | 1 (hold fields in 4) |
| `PUT /api/v1/account/plan/kept-rules` | current user | 4 |

- `enable_rule` and `issue_integration_token` catch `PlanLimitReached` as 409, never 500.
  `issue_integration_token` also catches `AdministratorRequired` as 403, because the
  `installation:read` check moves into the use case.
- New codes, each with an English `common.apiError.*` message, and with `count` beside every
  number so the translator picks the plural form: `plan_limit_reached` (reason `rules`,
  `rules_with_held`, or `integration_tokens`), `plans_need_default`, `plan_not_found`,
  `plan_key_taken`, `plan_in_use`, `plan_is_default`, `invalid_plan`, `too_many_kept_rules`, and
  `manual_runs_throttled`.
- The OAuth outcome `account_limit_reached` carries `limit` through the settings arrival params.
  Its notice links to Your plan in place of "Try again". A new test checks that the server's OAuth
  outcomes equal the Web UI's union.
- New schema literals mirror their enums in `test_schema_enums.py`: `SyncInterval`,
  `AllowanceBasis`, `RuleStopCause`, and `RulePlace`.
- `test_api_authorization.py` gains the six administrator routes, and its malformed-user body
  gains `"plan": null`.

### 10.2 Web UI

The UI follows DESIGN.md: no modals, inline disclosure, one visible next step, and the Quiet
Indicator rule.

- **Settings, Administration, Plans** (between Registration and Storage, hidden under Only Me): a
  checkbox row "Limit people with plans", disabled until a default exists; a select for the
  default; one row per Plan with an inline edit form, where each limit is a number or "Unlimited"
  and the interval is a select of the offered values; Remove with an inline confirmation; and an
  inline "Add a plan" form that warns the key cannot change.
- **People:** the Plan fact and "Change plan" on the person page.
- **Settings, Your account, Your plan** (`#your-plan`): for example "Family: 3 of 5 rules counted,
  2 of 3 calendar accounts, 1 of 2 tokens, syncs about every 15 minutes". An administrator reads
  "You administer this installation, so no plan limits you." Hidden while Plans are off and under
  Only Me. Slice 4 adds the grace line ("On {date}, {n} rules will be held: your plan lets {limit}
  sync."), with the step "Choose which keep syncing" and an inline checkbox list.
- **Limits:** Start is disabled when `can_start` is false, with the refusal message and a link to
  Your plan. The preview footer shows the coded message, not "Try again in a moment". "Create sync
  rule" stays enabled. Connect is disabled at the account limit, and Reauthorize stays enabled.
  Issuing a token is disabled at the token limit. When the User has held rules or is over the limit,
  a note before a privacy edit, a Pause, or a Disconnect says "Your plan may not let this rule start
  again."
- **Held rule** (slice 4): a neutral badge "Held by your plan", the note "Resumes by itself when
  your plan has room", and one next step, "Choose which rules sync". Never "Preview to restart".
  Sync now and Reconcile now are hidden. Every place that turns `degraded` into "Stopped" (the
  Overview list, the Rules list, the rule page, and the Operator Overview person page, which reads
  "Held by their plan") checks `stop_cause` first.
- **Overview:** the paused hero mentions held rules. The setup checklist counts enabled and held
  rules.
- Copy lives in the existing catalogs. New files keep the ESLint bounds. Each web change rebuilds
  the static bundle.

## 11. Documentation and ADRs

- **New ADR 0038, Plans** (slice 1, with addenda in slices 2 and 3): Plans in `identity` with
  `Allowances` in `sync`; the Allowance order and fail-open; the Default Plan; administrators
  never limited; what each limit counts; only Rule Replacement keeps a place, moved atomically;
  enforcement and race safety; lowering keeps accounts and tokens; the changed-address recovery;
  the interval list; the assignment port and its source; return to setup turns Plans off. Slice 2
  adds the due rule and its phases. Slice 3 adds the manual-run limit and why its floor is the
  shortest interval.
- **New ADR 0039, Plan Hold** (slice 4): stop code 2 and its rollback analysis; the per-User grace;
  the keep choice and swaps; that a preview keeps a hold; the settle step; status without a new
  verdict; the two emails; and the accepted limits of section 13.
- **Amendments:** ADR 0028 (decisions 1, 5, 7, and 9; the manual-run limit replaces "a fixed rate
  limit for every User"); ADR 0027 (the Plan Hold exception to "every other stop needs a recovery
  preview"); ADR 0036 (Scheduled Sync every five minutes "while Plans are off"; `PlanCadence`
  replaces `EveryUserInstant`); ADR 0030 (the Operator Overview shows the Plan; no effect under Only
  Me; return to setup turns Plans off); ADR 0024 (`stalled` covers held rules); ADR 0023 (a note
  pointing to 0028 and 0038).
- **CONTEXT.md:** refine Plan and Plan Hold; add Default Plan and Allowance (avoid "entitlement");
  update Sync Cadence, Scheduled Sync, Sync Now, Reconcile Now, Rule Preview, Operator Overview,
  Degraded Rule, Lapsed Authorization, Installation Status, Incident Notification, and the
  Interface Wording rows. Always write "held by ... plan", so it never reads like a Disabled User's
  held rules.
- **AGENTS.md:** the resume invariant adds "and a rule held by its User's Plan resumes on its own
  once the Plan's rule limit allows it (ADR 0039)". The Plans paragraph adds that administrators
  are never limited.
- **Contradictions to fix:** README and `docs/licensing.md` replace "charges for operating, not for
  features" with: the Hosted Service runs this same code with Plans on; its Plans may differ in how
  many rules and calendar accounts you have and how soon your calendars sync, including Instant
  Sync; they never limit how a rule protects your privacy or the tools to see and recover from a
  problem; a self-hosted installation has every feature and no limits unless its own administrator
  turns Plans on. `docs/instant-sync.md` keeps its "Not in your plan" heading (a test pins it).
  `docs/architecture.md` drops the stale `OperatorOverview.own`.
- **Other docs:** data-ownership (what Plans store, what administrators see, what the emails
  contain), self-hosting (Plans, the monitor table), troubleshooting (a held rule; the account
  limit and the changed-address recovery), domain-model (the state machine), sync-model,
  deployment, the multi-user spec's slice order, and the CHANGELOG.
- **`tests/test_ubiquitous_language.py`** adds the terms `CONTEXT.md` avoids for Plan and Plan
  Hold, except `quota` and `subscription`, which `Cause.QUOTA_EXCEEDED` and Graph subscriptions use
  for other things.

## 12. Delivery

Every slice depends only on slice 1, and each can ship alone.

### Slice 1: Plans core (migration 33)

Domain `plans.py`; `User.plan`; `SyncRule.keeps_place`; `Allowances`, `SqlitePlans`, and
`PlanCadence` with `instant` and `5_minutes` offered; the identity Plan use cases;
`IssueIntegrationToken`; `ShowOwnPlan`; the Operator Overview Plan; the Start check, the atomic
place move, the account limit with its OAuth outcome, and the token limit; routes, schemas, and
codes; the Administration, People, and Your plan UI with every limit hint; ADR 0038 and the slice-1
doc changes.

Releases: administrators define Plans, choose a default, turn Plans on, and assign Plans. New
Starts, accounts, and tokens respect limits. Instant Sync can be kept for some Plans. A lowered rule
limit refuses new Starts and stops nothing, and the release notes say so.

Tests: domain tables for `allowance_for`, validation, `counts_toward_plan` over every state, and
every transition's `keeps_place`; the decision-4 consequences; Rule Replacement (no draft exists
before the old rule's removal begins; a failed check leaves the old rule as it was and creates no
draft; a duplicate relationship is refused before anything changes; the draft keeps the place from
the commit that begins the removal; an interrupted removal keeps it); the Plans store contract on
SQLite and memory; migration 32 to 33; real-thread races (two Starts for one place, a Start against
a Plan lowering, two account connects, two token issues); Reauthorization at the limit;
administrators exempt; limit checks failing closed and every other read failing open; the API
catalogues; and Vitest for each UI section.

### Slice 2: Sync intervals (no migration)

All six intervals; `scheduled_run_due` and the phases; the new `ScheduledRule` fields in the
scheduled and instant readers; the due filter in `ScheduledPass`; fail-open; the interval in the
Dashboard and Your plan; the "five minutes" copy; the ADR 0036 amendment and the ADR 0038 addendum.

Tests: a decision table for `scheduled_run_due`; a 60-minute rule skipped until due; a started,
failing, or reprojection rule listed at once; Sync now every minute never keeps a rule from its
listing or its daily full pass, even across restarts; 60-minute rules, and their daily full passes,
spread over an hour; a rule with a `rule_failures` row due after a successful Sync now; a rule that
is not due is never overdue; Plans off leaves every existing scheduler test unchanged.

### Slice 3: Manual-run limit (no migration)

`manual_runs.py`, `MemoryRunThrottle`, admission in the routes, the 429 code, the UI message, the
live-checks script, and the docs. Tests: the sliding window, per-User counts, no limit with Plans
off or for administrators, the 13th run refused with `Retry-After`, concurrent requests never
admitting more than 12, one budget for all three actions, and no budget used by a 503.

### Slice 4: Plan Hold (migration 34)

Two fixes to today's code, which can also ship first: `health._degrade` acts on a rule with a
self-resuming stop, and `ChangeFeedCursors.advance` takes the rule write lock before its first
write. Then `held_by_plan` and its transitions; `plan_hold.py`; stop code 2; `plan_kept`, the
admission counter, and the grace columns; `PlanHolds`, `ChooseKeptRules`, and the settle step;
status, Dashboard, and MCP changes; the emails and the setting's new name; the held-rule UI and the
keep form; ADR 0039, the ADR 0027 and 0024 amendments, the AGENTS.md invariant, and the slice-4
docs.

Tests: a decision table for `settle` with one row per step and branch (including a further lowering
during a grace, a raise during a grace, a raise and lowering back between two passes with rules
started in between, release order, and a Disabled User); every transition matrix, including "a
preview keeps a hold", "a lapse never touches a held rule", and "a failure that needs intervention
ends a hold or a lapse"; a run in flight across a hold, a release as lapse-stopped, and a permanent
failure, after which Reauthorization does not resume the rule; `advance` and a settle racing on one
rule finish without a busy timeout; a Start, a removal, and a lowering between two passes restart
the grace; a keep-choice release during a raise that is gone by the next pass restarts the grace;
a Rule Replacement during a settle leaves its new draft unchanged until the next pass; `PlanHolds`
on real SQLite with threads (a Plan lowering that commits during a settle, a
lapse that commits during a release, a Start racing a release, a rule started during a settle left
for the next pass, a run in flight that stops at its next write after a hold); `ChooseKeptRules`
swaps; rollback readings of codes 0, 1, and 2; status with a held rule that has an open incident or
blocks; a User whose only rules are held keeps their watches listed until upkeep retires them; the
email privacy test; and the Web UI never offering "Preview to restart" for a held rule.

## 13. Accepted limits and risks

These are known and accepted, to keep the design simple:

1. **A grace can be longer than 7 days.** A further lowering during a grace restarts it for every
   rule beyond the limit, not only the new ones. A raise that brings the User within the limit
   clears the grace, so a later lowering gives a fresh 7 days. A User can only get this through a
   change of limit: an administrator's choice, or a paid upgrade followed by a downgrade.
2. **Decision 4's strictness.** A User with held rules may find the restart of a failed or edited
   rule refused, after the pass gave its place to a held rule. The refusal says what happened, and
   a note warns before a privacy edit, a Pause, or a Disconnect.
3. **A kept rule can stay held** while a not-kept rule runs, after a Start that beat the pass's
   release. Saving the choice again swaps them.
4. **Naming debt.** `awaiting_reauthorization` stores a stop code with three values, until rollback
   past migration 34 is no longer supported. It can then be renamed `stop_cause`.
5. **Monitors that read `state`.** A held rule reads `degraded`. The CHANGELOG announces it.
6. **The account refusal comes after OAuth consent,** and leaves an unused grant at the provider.
   The disabled Connect button makes this rare. A renamed account at the limit, with every place in
   use, needs an administrator to make room for the recovery.
7. **Lost emails.** A restart between a settle and its send drops the email. Your plan and the
   held-rule views still show the grace and the holds.
8. **Mass changes.** A default change can start many graces at once: up to 100 settles and emails
   per pass, and watch retirements that share the 200-call upkeep budget.
9. **No global caps** on drafts or on manual runs running at the same time.
10. **In-memory state.** Manual-run counts and the scheduler's window marks reset on restart. That
    only gives runs back.
11. **Phase 4** must carry `plans_enabled` and `default_plan_key` through its rebuild of
    `installation_settings`.

## Alternatives considered

- **Plans as their own bounded context.** Rejected for now: it changes the lint-imports layers
  (ADR 0032), loosens the isolation test (ADR 0029), and adds ports for the same behaviour. It
  remains open if billing grows large.
- **A new `HELD` rule state.** Rejected: rolling back crashes on `SyncRuleState(row["state"])`, and
  every switch on state must learn it.
- **A held rule that stays ENABLED with a flag.** Rejected: one forgotten reader of enabled rules
  would silently run held rules.
- **A separate `held_by_plan` column.** Rejected: an earlier release never writes it, so a rule it
  stops for another reason could come back held and resume without its recovery preview.
- **Places kept by stopped and paused rules.** Rejected by decision 4. Paused rules would count,
  against decision 3, and could hold places the User cannot give back.
- **A hold date per rule.** It closes the gaps in section 13, item 1, but adds per-rule dates, a
  quiet-time clock, and date rules for every keep choice. The gap it closes needs an administrator
  or a paid upgrade, so the simpler per-User grace wins.
- **Swaps at the scheduled pass.** Rejected: a lasting keep choice would hold a rule the User had
  just started, with no grace.
- **A higher manual-run limit.** Rejected: it would let a script cancel a slower Plan's interval.
