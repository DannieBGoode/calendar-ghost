# Plans Sync Intervals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Plan can sync every 10, 15, 30, or 60 minutes: the scheduler runs each rule once per
window of its User's interval, spread over the interval, while Plans off changes nothing.

**Architecture:** A pure `scheduled_run_due` in `domain/cadence.py` decides, per rule and pass,
from the rule's interval, a stable phase (SHA-256 of its id), the pass begin, the begin of the
pass that last listed it, and the facts that make a rule always due. `ScheduledRule` carries those
facts from both installation readers. `ScheduledPass.begin` reads every owner's cadence through
`cadences_of` (fail open), filters before `fairly_ordered`, and keeps its window marks in memory.

**Tech Stack:** Python 3.12, SQLite, pytest; React, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-15-plans-design.md`, section 7 (and 1.1, 12, 13.10).
The code map behind every file:line below is `.context/slice2/map.md` (not committed).

## Global Constraints

- No em dashes anywhere (`tests/test_no_em_dashes.py`). CONTEXT.md terms; never "tier".
- Ruff `max-args = 7`; `tests/test_architecture.py` counts init fields of application dataclasses.
  `ScheduledPass` has 5 today: add `cadence` as an init field and the marks as `init=False`.
- `lint-imports` unchanged; `infrastructure.scheduling` may not import `calendar_sync.domain`
  (pyproject.toml:161-167), so tie its 300 seconds to `SCHEDULED_EVERY` in `bootstrap/container.py`.
- `ruff format --check .` formats Python blocks in Markdown too; line length 100.
- Web: text through `t()`, numbers in plural messages as `count`; ESLint bounds; after any change
  under `web/`, `cd web && pnpm run build` and commit the bundle in the same commit (never a
  SHA-only rebuild); after a schema change, `scripts/export_openapi.py` then `pnpm run api:types`.
- Plans off, and administrators, keep `DEFAULT_CADENCE`: every rule is due at every pass, so every
  existing scheduler test keeps its expected behavior.
- No new clock reads in `ScheduledPass.begin` (`SteppingClock` in test_scheduling.py adds a minute
  per read). Use `begin`'s one `now`.
- Synthetic fixtures only. Commits end with
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- The owner rejects large PRs: no new abstraction beyond this plan, delete what a task makes unused.

## Decisions (settled here; the spec leaves them open)

1. **Phase and windows.** `phase = int.from_bytes(sha256(rule_id.encode()).digest()[:8], "big") %
   seconds`; `window(t) = (int(t.timestamp()) - phase) // seconds`, so windows are anchored at the
   Unix epoch and every offered interval divides a UTC day.
2. **Always due:** the interval is 5 minutes or less (`poll_every <= SCHEDULED_EVERY`); the rule
   never ran (no `sync` outcome); it is failing (its last `sync` outcome failed, or it has a
   `rule_failures` row, SQLite only); it was previewed after its last run; or
   `reprojection_required`.
3. **Marks.** `ScheduledPass` keeps `rule id -> begin of the pass that last listed it`, written at
   the end of `begin` for every listed rule, pruned to the rules `scheduled_rules` returned. A rule
   seen for the first time since start is seeded from its last run (`sync` outcome
   `completed_at`, any origin). Manual runs never move a mark.
4. **Full pass after a restart.** A rule whose full pass is due (`_full_pass_due`, unchanged) is
   also due once the pass begins at or after its phase past 00:00 UTC, so restarts plus Sync now
   cannot starve it, and hourly rules do not all run at the first pass after midnight.
5. **Fail open.** `begin` reads cadences with `cadences_of(self.cadence, owners)`; any fallback is
   `DEFAULT_CADENCE`, which is always due.
6. **All six intervals are offered**, so the "not offered" path is unreachable and goes:
   `require_offered`, `InvalidPlanReason.INTERVAL`, `ChangePlan`'s keep-a-stored-interval branch,
   the `invalid_plan` `reason: interval` answer, `common.apiError.invalid_plan_interval`, the web's
   `offeredWith`, and the editor hint "Longer intervals arrive in a later release.".
   `OFFERED_INTERVALS` stays as the API's `sync_intervals`, with `instant` first.
7. **Copy for 60 minutes** reads "every hour" on Rule Details and the Overview, as the Plans
   screens already do.
8. **No rollback text.** No release has Plans without this slice (both sit in Unreleased), so
   section 3.7's slice-2 rollback sentence has nothing to describe.

## Review Focus

1. **Irregular pass begins.** Passes begin 300 s plus the pass length apart: a rule is listed once
   per window even when two passes fall in one window or a long pass skips one (Task 1, Task 3).
2. **A Plan change mid-window.** A rule moved from 60 minutes to Instant is listed at the next pass;
   one moved from Instant to 60 minutes is listed again only in its next window (Task 3).
3. **Time zones.** A pass `begins` given in a non-UTC zone decides the same windows and the same
   UTC day for the full pass (Task 1).
4. **Spread.** 3,000 rules on one 60-minute Plan: no 5-minute pass lists more than 400 of them
   (mean 250) (Task 1).
5. **Overdue still holds.** A failing rule on a 60-minute Plan whose last success is 25 hours old is
   listed at every pass, so the 24-hour overdue check still sees it (Task 3).

---

### Task 1: The due rule and each interval's own minutes

**Files:**
- Modify: `src/calendar_sync/domain/cadence.py` (module doc :1-5, `SCHEDULED_EVERY` doc :15)
- Modify: `src/calendar_sync/domain/plans.py:92-116` (delete `_POLLED` and its comment)
- Test: `tests/domain/test_cadence.py`, `tests/domain/test_plans.py:52, 141-151, 281-287`,
  `tests/application/test_plan_cadence.py:21-32` (the `SCHEDULED_ONLY` slice-1 docstrings)

**Interfaces:**
- Produces: `scheduled_run_due(poll_every: timedelta, rule_id: str, begins: datetime, listed:
  datetime | None, *, always_due: bool, full_pass_due: bool) -> bool` in `domain/cadence.py`.
  `listed` is the begin of the pass that last listed the rule (or the seeded last run).
- Produces: `SyncInterval.cadence` returns `SyncCadence(instant=False, poll_every=timedelta(
  minutes=N))` for N in 5, 10, 15, 30, 60, and `DEFAULT_CADENCE` for `INSTANT`.

- [ ] **Step 1: Write the failing tests** in `tests/domain/test_cadence.py`:
  - `test_a_five_minute_or_instant_rule_is_due_at_every_pass`: 5 minutes, listed one minute ago,
    `always_due=False` -> True.
  - `test_a_rule_always_due_is_due_whatever_its_window`: 60 minutes, listed one minute ago,
    `always_due=True` -> True.
  - `test_a_slow_rule_is_listed_once_per_window_of_its_interval`: for 10, 15, 30, 60 minutes, step
    `begins` from `NOW` every minute for 6 hours, updating `listed` when due: every listing is
    exactly one interval after the one before (after the first), and listings per interval == 1.
  - `test_irregular_pass_begins_list_a_rule_once_per_window`: begins 5 min 40 s apart, and one gap
    of 70 minutes: never two listings in one window, and the first pass after the gap lists it.
  - `test_windows_follow_the_instant_not_its_time_zone`: the same instants given in UTC and in
    `ZoneInfo("Pacific/Honolulu")` give the same answers.
  - `test_three_thousand_hourly_rules_spread_over_the_hour`: ids `rule-0`..`rule-2999`, each
    listed at `NOW - SCHEDULED_EVERY`, passes every 5 minutes for one hour from `NOW`: each is
    listed once, no pass lists more than 400.
  - `test_a_full_pass_due_waits_for_the_rules_phase_after_midnight`: 60 minutes, `listed` 1 minute
    before `begins`, `full_pass_due=True`: as `begins` steps one minute from 00:01 to 01:00 UTC,
    it is not due at any step before its phase and is due at the first step at or after it; across
    3,000 ids those first-due minutes are spread (no single minute holds more than 100).
  In `tests/domain/test_plans.py`, replace
  `test_every_other_interval_polls_every_five_minutes_without_instant_sync` with
  `test_each_interval_polls_every_its_own_minutes_without_instant_sync` (5, 10, 15, 30, 60).

- [ ] **Step 2: Run them:** `.venv/bin/pytest tests/domain/test_cadence.py tests/domain/test_plans.py -q` -> FAIL (no `scheduled_run_due`; 10 minutes polls every 5).
- [ ] **Step 3: Implement** `scheduled_run_due`: due when `poll_every <= SCHEDULED_EVERY`, when
  `always_due` (decision 2's other facts, which Task 2 computes), when `listed` is None or in
  another window (decision 1; a later mark means the clock was set back), or by decision 4; `hashlib` only. The minutes per `SyncInterval` sit
  in a module-level mapping. Update the docstrings that say Scheduled Sync runs every rule every five
  minutes.
- [ ] **Step 4: Run** the domain tests and `tests/application/test_plan_cadence.py` -> PASS.
- [ ] **Step 5: Commit** "Give each Plan interval its own minutes, and decide when a slow rule is due".

### Task 2: What the scheduler knows about each rule

**Files:**
- Modify: `src/calendar_sync/application/sync/ports.py:470-478` (`ScheduledRule`)
- Modify: `src/calendar_sync/infrastructure/persistence/installation.py:87-108, 261-292`
- Modify: `src/calendar_sync/infrastructure/persistence/memory_installation.py:71-79, 351-364`
- Modify: `src/calendar_sync/application/operations/ports.py:131` (the `scheduled_rules` doc)
- Test: `tests/contracts/persistence.py` (new case; update the equality at :2285-2288),
  `tests/adapters/test_sqlite.py` (near :1467)

**Interfaces:**
- Produces: `ScheduledRule` gains `last_run_at: datetime | None = None`, `failing: bool = False`,
  `previewed_at: datetime | None = None`, and `@property always_due -> bool` (decision 2: never
  ran, failing, previewed after `last_run_at`, or `rule.reprojection_required`). Defaults keep
  every positional `ScheduledRule(owner, rule, last)` in src and tests working.

- [ ] **Step 1: Write the failing tests.** Contract (both stores):
  `test_scheduled_rules_say_when_each_last_ran_failed_and_was_previewed`: a rule that never ran
  (`always_due`), one whose last sync succeeded after its preview (`not always_due`, `last_run_at`
  == the outcome's `completed_at`), one whose last sync failed (`failing`), and one previewed after
  its last run (`always_due`). SQLite only:
  `test_a_rule_with_a_failure_row_stays_failing_after_a_successful_manual_run`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/adapters/test_persistence_contract.py tests/adapters/test_sqlite.py -q -k "scheduled_rules or failure_row"` -> FAIL.
- [ ] **Step 3: Implement.** SQLite: one shared SELECT list and row mapper for both readers, with
  `outcome.completed_at`, `outcome.succeeded`, `EXISTS` on `rule_failures` (by `rule_id` and
  `user_id`), and `rule_previews.completed_at`. Memory: the same from its outcomes and previews;
  `failing` is "last outcome failed" (the memory store has no `rule_failures`). Keep
  `PendingInstantRun.last_run_failed` as it is.
- [ ] **Step 4: Run** the tests above plus `tests/adapters/test_plans_schema.py` -> PASS.
- [ ] **Step 5: Commit** "Read when each rule last ran, failed, or was previewed for the scheduler, with no behavior change".

### Task 3: The scheduled pass lists only the rules that are due

**Files:**
- Modify: `src/calendar_sync/application/operations/scheduled_pass.py` (fields :71-78, `begin`
  :80-99, module and `begin` docstrings :1-6, :81-82)
- Modify: `src/calendar_sync/bootstrap/container.py:537-543`
- Modify: docstrings only: `src/calendar_sync/application/operations/ports.py:218-219`,
  `src/calendar_sync/infrastructure/scheduling.py:51, 110`
- Test: `tests/application/test_scheduled_pass.py`, `tests/application/test_status.py` (near
  :317-346), `tests/adapters/test_api.py` (near :3434, the wiring test)

**Interfaces:**
- Consumes: Task 1 `scheduled_run_due`; Task 2 `ScheduledRule.last_run_at`, `.always_due`;
  `cadences_of(policy, users)` and `EveryUserInstant` from `application/sync/watch_ports.py`.
- Produces: `ScheduledPass.cadence: SyncCadencePolicy = field(default_factory=EveryUserInstant)`;
  `ScheduledPass._listed: dict[SyncRuleId, datetime] = field(default_factory=dict, init=False)`.
  The container passes `cadence=adapters.sync_cadence` and
  `SyncScheduler(..., interval_seconds=int(SCHEDULED_EVERY.total_seconds()))`.

- [ ] **Step 1: Write the failing tests** in `tests/application/test_scheduled_pass.py`, with a
  fake policy giving one User 60 minutes and another `DEFAULT_CADENCE`:
  - `test_plans_off_lists_every_rule_at_every_pass` (no cadence given).
  - `test_an_hourly_rule_is_listed_once_per_window_and_an_instant_one_at_every_pass`.
  - `test_sync_now_every_minute_never_keeps_a_rule_from_being_listed`: `last_run_at` moves every
    minute; the rule is still listed in each new window.
  - `test_a_restart_lists_a_rule_from_its_last_run_once`: a new `ScheduledPass` seeds from
    `last_run_at`; due in the next window, not at once.
  - `test_a_restart_never_starves_the_daily_full_pass`: full pass due, last run 1 minute ago,
    restarted every pass: listed as a full pass once the pass is past its phase.
  - `test_a_plan_change_mid_window_takes_effect_at_the_next_due_pass` (both directions, Review 2).
  - `test_a_failing_hourly_rule_is_listed_at_every_pass` (Review 5).
  - `test_a_failed_cadence_read_lists_every_rule` (a policy that raises).
  - `test_marks_forget_rules_that_are_no_longer_enabled`.
  In `tests/application/test_status.py`: `test_a_failing_hourly_rule_is_still_reported_overdue`
  (its last success 25 hours old, listed at the last pass).
- [ ] **Step 2: Run** `.venv/bin/pytest tests/application/test_scheduled_pass.py tests/application/test_status.py -q` -> FAIL.
- [ ] **Step 3: Implement** decisions 3 and 5 in `begin`: read rules inside the installation unit
  as now, close it, read cadences once, filter with `scheduled_run_due`, then `fairly_ordered`;
  write marks and prune at the end. Wire the container. Fix the docstrings that say every enabled
  rule is listed at every pass.
- [ ] **Step 4: Run** the full suite `.venv/bin/pytest -q` and `ruff format --check .`, `ruff check .`, `mypy`, `lint-imports` -> PASS.
- [ ] **Step 5: Commit** "Run each rule once per window of its Plan's interval, spread over the interval".

### Task 4: Offer every interval

**Files:**
- Modify: `src/calendar_sync/domain/plans.py` (`OFFERED_INTERVALS` all six, `instant` first;
  delete `require_offered` :415-418 and `InvalidPlanReason.INTERVAL`)
- Modify: `src/calendar_sync/application/identity/plans.py:87-88, 109-111`
- Modify: `src/calendar_sync/interfaces/api/problems.py:223-226` (the `reason` param for
  `invalid_plan`; no schema `Literal` names it); regenerate `web/openapi.json` and
  `web/src/lib/api-schema.ts` if a description changes
- Modify: `web/src/features/plan-editor-fields.tsx:126-173` (the hint, its id in
  `aria-describedby`, the doc comment), `web/src/features/plan-panel.tsx:193-211` (`offeredWith`),
  `web/src/i18n/locales/en/people.json:654`, `web/src/i18n/locales/en/common.json:74`
- Test: `tests/domain/test_plans.py:290-305`, `tests/application/test_plans.py:140, 168-212`,
  `tests/adapters/test_plans_api.py:76, 454, 475, 602-626`,
  `web/src/features/plan-editor.test.tsx:274`, `web/src/features/people-plans.test.tsx:1534`

- [ ] **Step 1: Write the failing tests:** `test_every_interval_is_offered_instant_first` (domain
  and the `GET /api/v1/plans` answer `sync_intervals`); `test_a_plan_can_sync_every_hour` (API:
  `POST` with `60_minutes` answers 201 and the Plan reads it back); in the editor test, the group
  description is only "How soon changes reach the other calendars." and six cards show, Instant
  first. Delete the refusal tests for intervals not offered and the "kept beside the offered ones"
  web test.
- [ ] **Step 2: Run** them -> FAIL.
- [ ] **Step 3: Implement** decision 6. Regenerate the API files.
- [ ] **Step 4: Run** the backend suite and gates; `cd web && pnpm run typecheck && pnpm run lint && pnpm run knip && pnpm run doctor && pnpm run test && pnpm run api:check` -> PASS. Build the bundle.
- [ ] **Step 5: Commit** "Offer every sync interval, from Instant to every hour" (with the bundle).

### Task 5: Say each person's own interval

**Files:**
- Modify: `web/src/i18n/locales/en/overview.json:115`, `web/src/lib/overview-health.ts:128, 437`,
  `web/src/features/overview.tsx` (pass the own Plan's `poll_every_minutes`)
- Modify: `web/src/i18n/locales/en/rule-details.json:57-60`, `web/src/features/rule-details-facts.tsx:149-170`
- Test: `web/src/lib/overview-health.test.ts:42-47`, `web/src/features/rule-details.test.tsx:307`,
  `web/src/features/settings-own-plan.test.tsx:273`

**Interfaces:**
- Produces: `OverviewContext` gains `pollEveryMinutes?: number` (5 when Your plan has not loaded or
  failed). New keys: `overview.health.healthy.detail` as a plural message with `{count}` minutes,
  `overview.health.healthy.detailHourly`, `ruleDetails.cadence.everyHour`. 60 minutes uses the
  hourly key.

- [ ] **Step 1: Write the failing tests:** the healthy detail says "every 15 minutes" for a 15-minute
  Plan, "every hour" for 60, and "every 5 minutes" when Your plan failed; Rule Details says "Syncs
  every hour" for 60; Your plan shows "Every hour" for a 60-minute Plan.
- [ ] **Step 2: Run** them -> FAIL (Your plan's may already pass: keep it as a pin).
- [ ] **Step 3: Implement**; keep "The first sync runs within five minutes." (a previewed rule is due at the next pass).
- [ ] **Step 4: Run** the web gates -> PASS. Build the bundle.
- [ ] **Step 5: Commit** "Say on the Overview and a rule's page how often its own Plan syncs" (with the bundle).

### Task 6: Docs

**Files** (each line from `.context/slice2/map.md`, part E):
- `CONTEXT.md`: delete the interim sentence in Sync Cadence (:284-286); update the Instant Sync
  wording row (:516, "every N minutes" or "every hour") and the Plan wording row (:524, six speeds,
  no hint).
- `docs/sync-model.md:6-8, 44-47` (each rule's interval; the full pass at its phase after 00:00 UTC).
- `docs/instant-sync.md:4-5, 166-167, 303-306`; `docs/self-hosting.md:289, 333`; `README.md:101`.
- `docs/adr/0036-instant-sync-through-provider-notices.md:123-124`.
- `docs/adr/0038-plans-allowances-and-limits.md`: :25-26, the :92 row ("The scheduler and Instant
  Sync"), :147-152, and a section "Slice 2: each rule once per window of its interval" stating
  decisions 1 to 5 and the accepted edges (a run in flight after Pause, Preview, and Start; a rule
  resumed after a lapse may wait one interval; marks reset on restart).
- `docs/superpowers/specs/2026-10-17-plans-ui-catalog-design.md:175-179`.
- `CHANGELOG.md` Unreleased Plans bullets (:14, :23-24): every speed from Instant to every hour,
  each rule once per interval.
- `site/src/i18n/en.ts:149, 373`: "by default".

- [ ] **Step 1: Edit** the files above.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_no_em_dashes.py tests/test_instant_sync_docs.py tests/test_troubleshooting_anchors.py tests/test_ubiquitous_language.py -q` and `ruff format --check .` -> PASS.
- [ ] **Step 3: Commit** "Describe sync speeds from Instant to every hour in the docs".
