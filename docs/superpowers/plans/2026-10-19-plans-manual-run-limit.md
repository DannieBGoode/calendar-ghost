# Plans Manual-Run Limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While Plans are on, a User a Plan limits starts at most 12 manual runs (Sync now,
Reconcile now, and Preview together) in any 60 minutes, so pressing Sync now cannot beat a
slower Plan's interval; administrators and Plans off are never limited.

**Architecture:** `AdmitManualRun` in `application/sync/manual_runs.py` reads the User's
Allowance and, only when its basis is `plan`, asks a `RunThrottle` port to admit the run; a
refusal raises `ManualRunsThrottled` with the wait. One `MemoryRunThrottle` per process lives on
`Adapters`. Each of the three routes runs admission and the use case together in its worker
thread, after `available()`, so a 503 uses no budget.

**Tech Stack:** Python 3.12, FastAPI, pytest; the web only gains one message.

**Spec:** `docs/superpowers/specs/2026-10-15-plans-design.md`, section 8 (and lines 43, 59, 95,
250, 263, 339, 615-621, 669-673, 723-728, 796-801, 852-853). The code map behind every file:line
below is `.context/slice3/map.md` (not committed).

## Global Constraints

- No em dashes anywhere. CONTEXT.md terms; never call this refusal a Plan limit (spec 615-616).
- Ruff `max-args = 7`; `tests/test_architecture.py` counts init fields of application
  dataclasses; no class in `manual_runs.py` is a frozen dataclass error
  (`tests/application/test_error_tracebacks.py:59`).
- `lint-imports` unchanged: `sync` may not import `identity`, so `ManualRunsThrottled` subclasses
  `ApplicationError` (`application/shared/errors.py`), not `SignInThrottled`.
- Every problem code has an English `common.apiError.<code>` message, in the same commit
  (`tests/adapters/test_api_problems.py:353, 361`); numbers in a plural message pass `count`.
- After any change under `web/`, `cd web && pnpm run build` and commit the bundle in the same
  commit (never a SHA-only rebuild). No schema or OpenAPI change is expected.
- Plans off and administrators: nothing changes, and every existing test keeps its behavior.
- Synthetic fixtures only. Commits end with
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- The owner rejects large PRs: the smallest change that does the job; target under 600 lines.

## Decisions (settled here; the spec leaves them open)

1. **Admission in the thread.** `AdmitManualRun.execute(run: Callable[[SyncRuleId], T],
   rule_id: SyncRuleId) -> T` admits, then calls `run(rule_id)`. Each route changes one line to
   `await asyncio.to_thread(services.admit_manual_run.execute, use_case.execute, SyncRuleId(rule_id))`
   after its `available(...)` call.
2. **Port.** `RunThrottle.admit(user: UserId) -> float`: under one lock it drops entries older
   than the window, and either records the run and returns 0.0, or records nothing and returns the
   seconds until a run may start, at most the window (a clock set back never asks for more).
3. **Constants.** `MANUAL_RUNS = 12` and `MANUAL_RUN_WINDOW = timedelta(hours=1)` in
   `manual_runs.py`, documented with the spec's reason (12 an hour is one run every 5 minutes, the
   shortest interval). `MemoryRunThrottle(clock, *, limit=MANUAL_RUNS, window=MANUAL_RUN_WINDOW)`.
4. **Fail open.** Any exception from `allowances.of` is logged with its class and the User id
   only, and the run goes ahead without touching the throttle (spec 339).
5. **Refusal.** `ManualRunsThrottled(retry_after: float)` keeps `retry_after = max(1,
   math.ceil(retry_after))` seconds. The API answers 429 `manual_runs_throttled` with params
   `{"retry_after": seconds, "count": minutes}`, where `minutes = ceil(seconds / 60)`, and a
   `Retry-After: <seconds>` header that `problem_from` sets for any error with `retry_after`.
   The message is "You started many runs in a short time. Try again in {count} minutes."
   (`one`: "... in 1 minute."). This says minutes where the spec says seconds: waits are mostly
   tens of minutes.
6. **Every admitted request counts**, including one that then answers 404, 409, or 424; only a 503
   (checked before admission) is free. A refused request is not recorded. Automatic previews (the
   preview page loading) count like any other.
7. **Web scope.** Only the message: Sync and Reconcile already show "... did not complete." with
   the server's message, and Preview shows its failure panel with Refresh.
8. **Live provider checks** stop at once, with a clear line, when `GET /api/v1/account/plan`
   answers `basis == "plan"`, since one run of the checks needs more than 12 manual runs.

## Review Focus

1. **A failed Plans read never refuses a run** and records nothing (Task 1).
2. **A refused request is not recorded**, so a script hammering at the limit does not push its
   own wait further out (Task 2).
3. **A clock set back** never asks for a wait longer than the window (Task 2).
4. **A 503** (no master key or no provider) uses no budget (Task 3).
5. **Twelve threads racing for the last place** admit exactly the remaining count (Task 2).

---

### Task 1: Who is limited, and admission

**Files:**
- Modify: `src/calendar_sync/domain/plans.py:311-335` (`Allowance`)
- Create: `src/calendar_sync/application/sync/manual_runs.py`
- Test: `tests/domain/test_plans.py:126-160`, create `tests/application/test_manual_runs.py`

**Interfaces:**
- Produces: `Allowance.limits_manual_runs -> bool` (property; true only when `basis is PLAN and
  plan is not None`); `MANUAL_RUNS`, `MANUAL_RUN_WINDOW`; `class RunThrottle(Protocol): def
  admit(self, user: UserId) -> float`; `class ManualRunsThrottled(ApplicationError)` with
  `.retry_after: int`; `@dataclass(slots=True) class AdmitManualRun: allowances: Allowances;
  throttle: RunThrottle; owner: UserId` with `execute[T](self, run: Callable[[SyncRuleId], T],
  rule_id: SyncRuleId) -> T`.

- [ ] **Step 1: Write the failing tests.** In `test_plans.py`, extend the decision table:
  `limits_manual_runs` is true only for a `plan` basis with a Plan. In `test_manual_runs.py`, with
  a recording fake throttle and a fake `run`:
  - `test_plans_off_and_administrators_run_without_the_throttle`
  - `test_a_limited_user_runs_while_the_throttle_admits` (the run's result is returned)
  - `test_a_refused_run_raises_with_the_wait_and_never_runs` (`retry_after` 89.2 becomes 90)
  - `test_a_failed_plans_read_runs_without_the_throttle_and_logs_only_the_class` (`BrokenAllowances`, `caplog`)
- [ ] **Step 2: Run** `.venv/bin/pytest tests/domain/test_plans.py tests/application/test_manual_runs.py -q` -> FAIL.
- [ ] **Step 3: Implement** decisions 3 to 5 (the error message names seconds, as `SignInThrottled` does).
- [ ] **Step 4: Run** them plus `tests/test_architecture.py tests/application/test_error_tracebacks.py`, `ruff`, `mypy`, `lint-imports` -> PASS.
- [ ] **Step 5: Commit** "Decide who a manual run counts against, with no behavior change".

### Task 2: The in-memory throttle

**Files:**
- Modify: `src/calendar_sync/infrastructure/throttle.py` (module docstring; add `MemoryRunThrottle`)
- Test: create `tests/adapters/test_run_throttle.py`

**Interfaces:**
- Consumes: Task 1 `RunThrottle`, `MANUAL_RUNS`, `MANUAL_RUN_WINDOW`.
- Produces: `MemoryRunThrottle(clock: Clock, *, limit: int = MANUAL_RUNS, window: timedelta =
  MANUAL_RUN_WINDOW)` implementing `admit`.

- [ ] **Step 1: Write the failing tests** with a settable clock:
  - `test_twelve_runs_are_admitted_and_the_thirteenth_waits_for_the_oldest_to_leave_the_window`
    (runs one minute apart; the 13th returns the seconds until the first is an hour old)
  - `test_each_user_has_their_own_count`
  - `test_a_refused_run_is_not_recorded` (hammer 100 times at the limit; the wait does not grow)
  - `test_the_window_slides` (after the oldest leaves, one more is admitted)
  - `test_a_clock_set_back_never_asks_for_more_than_the_window`
  - `test_threads_racing_for_the_last_places_admit_exactly_the_limit` (24 threads, a barrier,
    11 already recorded: exactly 1 more admitted)
- [ ] **Step 2: Run** `.venv/bin/pytest tests/adapters/test_run_throttle.py -q` -> FAIL.
- [ ] **Step 3: Implement** decision 2 with one `Lock`, a `deque` per User, and Users with no
  recent run forgotten, as `MemorySignInThrottle._recent` does.
- [ ] **Step 4: Run** the test and the gates -> PASS.
- [ ] **Step 5: Commit** "Count manual runs per User in memory, with no behavior change".

### Task 3: The routes answer 429

**Files:**
- Modify: `src/calendar_sync/bootstrap/container.py` (`Adapters` field `run_throttle:
  RunThrottle`, built at :449 beside `sign_in_throttle`; `UserServices.admit_manual_run`,
  composed in `_compose_user` as `AdmitManualRun(adapters.allowances, adapters.run_throttle,
  user_id)`)
- Modify: `src/calendar_sync/interfaces/api/routes/rules.py:87-113` (the `RuleServices` Protocol),
  `:166-260` (the three routes: admission in `to_thread`, `except ManualRunsThrottled` -> 429)
- Modify: `src/calendar_sync/interfaces/api/problems.py` (`_CODES`, `_params`, and `problem_from`
  setting `Retry-After` for an error with `retry_after`)
- Modify: `web/src/i18n/locales/en/common.json` (`manual_runs_throttled`, `{one, other}`, between
  `link_unusable` and `mcp_not_running`); `web/src/i18n/api-errors.test.ts`; rebuild the bundle
- Test: `tests/adapters/test_api_problems.py:153-246` (one row), create
  `tests/adapters/test_manual_run_limit_api.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.

- [ ] **Step 1: Write the failing tests** in `test_manual_run_limit_api.py`, with a member a Plan
  limits (`limited_user`, `session_for`, `plans_on`, as `tests/adapters/test_rule_limit_api.py:27-43`
  does), `master_key` set so the routes are available, and a missing rule id (404, no provider call):
  - `test_twelve_manual_runs_are_shared_by_sync_reconcile_and_preview_and_the_thirteenth_waits`:
    4 of each answer 404; the 13th answers 429 `manual_runs_throttled` with params
    `retry_after` and `count` (minutes) and a `Retry-After` header equal to `retry_after`.
  - `test_an_administrator_and_plans_off_are_never_limited` (20 runs each, no 429).
  - `test_an_unavailable_run_uses_no_budget`: two clients over one `Adapters` (sharing the
    throttle); one answers 503 twenty times, the other still has 12.
  Add the `test_problem_from_maps_exceptions` row and an `api-errors.test.ts` case ("Try again in
  2 minutes." and "in 1 minute.").
- [ ] **Step 2: Run** them -> FAIL.
- [ ] **Step 3: Implement** decisions 1, 5, and 6.
- [ ] **Step 4: Run** the full backend suite, the gates, and `cd web && pnpm run test && pnpm run lint && pnpm run knip` -> PASS. Build the bundle.
- [ ] **Step 5: Commit** "Refuse a 13th manual run in an hour for people a Plan limits, and say when to try again" (with the bundle).

### Task 4: Docs and the live checks

**Files:**
- `docs/adr/0038-plans-allowances-and-limits.md`: a "Slice 3" section (decisions 1 to 6, why the
  floor is the shortest interval, accepted edges: counts reset on restart, every admitted request
  counts, automatic previews count); the code in the codes list; the fail-open bullet (:126-136)
  names manual runs.
- `docs/adr/0028-plans-apart-from-commercial-mode.md`: amend decision 9 (:29-30) and drop
  "The fixed rate limit for manual runs also comes in a later release." (:73-75).
- `CONTEXT.md` Allowance (:65-72): it also decides whether manual runs are limited.
- `CHANGELOG.md` Unreleased Plans bullets (:22-30, codes :37-39).
- `docs/self-hosting.md:300-306`: one sentence on the limit.
- `scripts/live_provider_checks.py` `connect()` (:832-865) and `docs/development.md:168-170`:
  decision 8.

- [ ] **Step 1: Edit** the files above.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_no_em_dashes.py tests/test_ubiquitous_language.py -q`, `ruff format --check .`, `ruff check .`, `mypy` -> PASS.
- [ ] **Step 3: Commit** "Describe the manual-run limit in the docs, and stop the live checks for a limited User".
