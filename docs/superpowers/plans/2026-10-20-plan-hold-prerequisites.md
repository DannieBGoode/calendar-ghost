# Plan Hold Prerequisites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking. The owner has selected this method. Each task gets an implementer, an independent reviewer, and a fix loop, followed by a whole-branch review and one fix wave.

**Goal:** Keep an intervention failure from being lost after Lapsed Authorization stops a rule, and prevent cursor advancement from blocking lifecycle changes through reversed lock order.

**Architecture:** Change two existing application methods. Rule health reads the current rule under its write lock and clears its self-resume when intervention is needed. Cursor advancement takes that lock before its first database write and holds it through the cursor commit. Existing domain transitions and persistence ports suffice.

**Tech Stack:** Python 3.12, pytest, SQLite WAL, threading Events and RuleLocks.

**Spec:** `docs/superpowers/specs/2026-10-15-plans-design.md`, sections 1.2 (degrade row), 3.6 (lock order), and 12 (Slice 4 prerequisites). ADR 0027 governs recovery. ADRs 0024 and 0038 and the Plans UI catalog remain unchanged in this PR.

## Global Constraints

- The owner approved this plan on 2026-10-20. Execute PR 1 through review, gates, and PR creation.
- This is PR 1 of 3. PR 2 adds the hold engine; PR 3 adds the API, UI, emails, and remaining slice-4 docs. Plan those separately after the preceding PR lands.
- Preserve the current branch name. After `git fetch origin`, HEAD and `origin/main` both equal `47191d2b` at planning time. The tree was clean.
- Migration 34 and ADR 0039 are free on that fetched `origin/main`. PR 1 uses neither. Recheck before PR 2.
- With Plans off, no Plans behavior changes. These two fixes repair existing synchronization behavior regardless of Plans.
- No new rule state, stop code, domain field, persistence port, migration, API field, UI, or dependency.
- Use CONTEXT.md terms, synthetic fixtures, no secrets, and no em dashes.
- Keep locks short and provider calls outside SQLite write transactions. Preserve cursor-last persistence and the reprojection material-signature check.
- Keep a task/review ledger in `.superpowers/sdd/` during execution. If its workflow returns a usage limit and run id, resume with `resumeFromRunId`.
- Commits use sentence-case summaries of user behavior and end with a truthful `Co-Authored-By` trailer.
- Stage only this PR's files. Check `git diff --shortstat origin/main...HEAD` after each commit.

## Decisions and recommendations

1. **Reuse existing transitions.** For a current enabled rule, use `degrade()`; for a current lapse-stopped rule, use `require_preview()`. The latter already clears the self-resume and kept place while preserving DEGRADED. `on_account_disconnected` uses the same distinction. Do not expand `SyncRule.degrade` in this PR.
2. **Check both snapshots.** Broaden the early guard and the check of the freshly loaded rule to accept `synchronizes or stopped_by_lapsed_authorization`. Do not use `holdable` as a shortcut: future held rules are not holdable, but intervention must also stop their self-resume in PR 2.
3. **Preserve the outcome boundary.** Move cursor saves and retention inside the existing write-lock block. Keep the run-outcome record and its second commit after that block, as today. They never acquire the rule lock while holding SQLite's writer lock.
4. **Prove lock order now with a lifecycle write.** PlanHolds does not exist yet. A paused-state write under the same real rule lock proves the prerequisite a future settle needs. Use Events and a zero-timeout SQLite connection, with bounded cleanup; no sleeps or five-second timeout waits. Subclass RuleLocks with the same `for_writes(self, rule_id: SyncRuleId) -> Lock` signature, signal immediately before returning the real lock, and arm the signal only after main holds it. Construct ExecuteSyncRule directly with this instance; the existing `_use_case` helper creates its own locks.
5. **Document the repaired behavior only.** Add short explanations to the domain/sync references and the Unreleased fixes. Defer ADR 0039 and Plan Hold amendments to PR 2.

## Review Focus

1. A run started enabled, but the stored rule is lapse-stopped before its failure arrives: intervention clears self-resume (Task 1).
2. The snapshot supplied to health is itself lapse-stopped: the early guard must not lose intervention (Task 1).
3. A transient failure while authorization has lapsed must leave automatic recovery intact (Task 1).
4. A user pauses or removes a rule before a late failure arrives: health must preserve that lifecycle choice, or leave a missing rule absent (Task 1).
5. An empty completed batch races a lifecycle write: both operations finish, both cursors persist, and the lifecycle state survives (Task 2).

---

### Task 1: Intervention ends a lapse-only stop

**Files:**
- Modify: `src/calendar_sync/application/sync/health.py`, `RuleHealth._degrade`.
- Test: `tests/application/test_health.py`, reusing Records, Incidents, FixedClock, and memory_units.
- Modify: `docs/domain-model.md`, the Lapsed Authorization recovery paragraph, and `docs/troubleshooting.md`, under "A rule is degraded".

**Interfaces:** Preserve `_degrade(self, rule: SyncRule) -> None` and public `record_failure(self, rule: SyncRule, failure: ProviderFailure, *, attempted_at: datetime | None = None) -> None`. Consume `SyncRule.require_preview() -> Self`, `degrade(*, awaiting_reauthorization: bool = False) -> Self`, and `RuleLocks.for_writes(rule_id)` without changing them.

- [x] **Step 1: Add failing regressions.** Exercise `record_failure`, not only its private helper.
  - `test_intervention_clears_a_lapse_stop_before_reauthorization`: parameterize the existing INTERVENTION kinds and enabled versus lapse-stopped input snapshots. Use `account_id=None` for AUTHENTICATION and AUTHORIZATION to exercise the rule-failure path; account-scoped authorization failures retain their existing lapse behavior. Persist a lapse-stopped current rule. Assert DEGRADED, `awaiting_reauthorization is False`, `counts_toward_plan is False`, and one provider Incident with the failure's category and one notification. Seed the Connected Account as CONNECTED and its lapse time earlier than `accepted_at`; ensure every account the rule uses is authorized after restoration. Restore through LapsedAuthorizations, assert the account lapse cleared, `restored(...) == 0`, and the rule stays DEGRADED. This must not pass merely because the account remains unauthorized.
  - `test_transient_failure_preserves_a_lapse_stop`: RATE_LIMIT and TEMPORARY retain `awaiting_reauthorization`, including after reaching the Incident threshold. Seed real restoration preconditions as above; assert the account lapse clears, `restored(...) == 1`, and the rule returns to ENABLED. Keep existing incident-threshold assertions.
  - `test_account_scoped_authorization_failure_preserves_a_lapse_stop`: parameterize AUTHENTICATION and AUTHORIZATION with the Connected Account id; assert the rule stays lapse-stopped and the account Incident path is used. These failures return before `_degrade` and must not become ordinary Degraded Rules.
  - `test_late_intervention_preserves_a_rule_that_no_longer_self_resumes`: an enabled run snapshot with current DRAFT, PREVIEWED, PAUSED, plain DEGRADED, REMOVING, or missing. Assert the stored rule remains exactly as it was, or absent. Preserve current Incident reporting behavior.
- [x] **Step 2: Run** `.venv/bin/pytest tests/application/test_health.py -q`. Verify the new intervention regression fails because the stop flag remains true, not from fixture setup.
- [x] **Step 3: Implement** decisions 1 and 2. Re-read under `for_writes` and the User unit of work; save and commit only an eligible current rule. Preserve failure recording, lapse handling, and notification boundaries.
- [x] **Step 4: Update** the domain and troubleshooting references to say that a later failure requiring intervention also clears lapse-only recovery.
- [x] **Step 5: Run** `.venv/bin/pytest tests/application/test_health.py tests/application/test_lapsed_authorization.py tests/domain/test_health.py tests/domain/test_model.py -q`. Expected exit 0. Existing enabled-failure and stale-authorization tests must still pass.
- [x] **Step 6: Review, fix, and commit** only this task's files. Suggested summary: `Keep rules stopped for review when a later failure needs intervention`.

### Task 2: Cursor advancement takes the rule lock first

**Files:**
- Modify: `src/calendar_sync/application/sync/change_feeds.py`, `ChangeFeedCursors.advance`.
- Test: `tests/application/test_execute_sync_rule.py`.
- Modify: `docs/sync-model.md`, lock-order and partial-failure paragraphs.
- Modify: `CHANGELOG.md`, Unreleased fixes for both prerequisites.

**Interfaces:** Preserve `advance(self, run: SyncRunContext, feeds: ChangeFeeds) -> None`. Its only caller remains ExecuteSyncRule in `application/sync/synchronization.py`. No persistence implementation or contract changes.

- [x] **Step 1: Add** `test_cursor_advance_waits_for_the_rule_write_lock_before_writing` using real SQLite and a worker thread:
  - Seed an enabled rule and empty source/destination feeds with distinct next cursors. Empty feeds prevent earlier event writes from masking the order.
  - Share one RuleLocks subclass instance with ExecuteSyncRule, constructed directly. Its type-compatible `for_writes` override calls `super()`, signals an Event when armed, and returns the real `Lock`; do not return a proxy context manager.
  - Main thread obtains and holds that real lock before arming the Event, starts ExecuteSyncRule in the worker, then waits for the acquisition-attempt Event. Seed no pending reprojection or replays so the first attempt is in `advance`.
  - While still holding the lock, main opens a connection through `open_connection(database, timeout=0)`, updates this User's rule to PAUSED, and commits. The old code must fail immediately with SQLite busy because cursor advancement already owns the database writer lock.
  - Release the rule lock and join the worker with bounded waits, including in `finally`. Capture and assert worker exceptions in the main thread.
  - Assert the lifecycle write succeeded, the worker finished without error, the rule remains PAUSED, both next cursors persisted, and the successful Sync Run outcome exists. A run that has completed its empty batches keeps today's cursor completion behavior.
- [x] **Step 2: Run** `.venv/bin/pytest tests/application/test_execute_sync_rule.py -k cursor_advance_waits -q`. Verify the expected old-code SQLite busy failure and successful thread cleanup.
- [x] **Step 3: Move** the existing write-lock boundary above the first cursor save. Both saves, full-listing retention writes, conditional reprojection completion, and their commit stay inside it. Preserve outcome recording and its second commit outside it.
- [x] **Step 4: Run** `.venv/bin/pytest tests/application/test_execute_sync_rule.py tests/application/test_locking.py -q`. Expected exit 0. In particular retain `test_complete_create_use_case_persists_mapping_cursor_and_audit`, `test_provider_failure_does_not_advance_cursor_or_write_audit`, `test_edit_during_a_run_keeps_reprojection_pending`, `test_run_stops_before_writing_when_the_rule_changes_mid_run`, and `test_concurrent_requests_for_the_same_rule_are_serialized`.
- [x] **Step 5: Document** rule-lock-before-database-write order and both fixes. Resolve the current `docs/sync-model.md` statement that a paused run never advances cursors: it stops at its next provider write after Pause or a Material Rule Change, while a run that already applied every batch change can commit its cursors. Preserve the reprojection material-signature guard. This is a clarification of existing behavior, not a new cursor policy. Announce no Plan Hold behavior, schema, or monitor change.
- [x] **Step 6: Review, fix, and commit** only this task's files. Suggested summary: `Let cursor advancement and rule changes finish without a lock timeout`.

### Final review and delivery

- [x] Review the whole branch with a fresh reviewer; run one fix wave with regression tests for findings. Record decisions and evidence in the ledger.
- [x] Run each backend gate separately and record its real exit code: `.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`, `.venv/bin/mypy`, `.venv/bin/lint-imports`, `.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80`.
- [x] In `web/`, run each separately: `pnpm audit --audit-level=high`, `pnpm run api:check`, `pnpm run typecheck`, `pnpm run lint`, `pnpm run knip`, `pnpm run doctor`, `pnpm run test`, `pnpm run build`. Do not stage a SHA-only bundle rebuild.
- [ ] Run `gitleaks git .` with CI's 8.30.1 version. Run `docker compose build` or verify the supported-architecture image CI job. Report any gate that cannot run.
- [x] Obtain the requested outside gstack `/codex` review via `codex exec`, using `git diff origin/main...HEAD` excluding compiled static assets, `web/openapi.json`, and `web/src/lib/api-schema.ts`. Discover/read that skill before use; if missing, report the missing workflow. Fix each P1 and P2 test-first and rerun affected gates.
- [ ] Check diff scope, use `.github/PULL_REQUEST_TEMPLATE.md`, push this branch, and open PR 1 against `main`. Watch CI to completion. Verify review comments, fix valid findings test-first, push, and reply on each thread with its fixing commit.
- [ ] Do not start PR 2 until PR 1 has landed; fetch `origin/main` again before planning its hold engine and recheck migration/ADR numbers.

## Claude review (2026-10-20)

Claude reviewed the plan against the spec and repository through the local CLI with read-only tools. Verdict: sound design, no blockers after corrections. The full report is in `.context/plan-review/claude-review.txt` (local, not committed).

- Accepted: type-compatible real-lock signaling, explicit cursor-documentation correction, and restoration preconditions with exact resumed counts.
- Accepted: account-scoped authorization coverage to protect the separate lapse path.
- Deferred optional simplification: removing the early snapshot guard. Preserve the narrow two-guard correction for this PR and keep its regression; no extra refactor is needed.
- The owner approved implementation after the Claude corrections on 2026-10-20.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
| --- | --- | --- | --- | --- | --- |
| Task reviews | Approved subagent workflow | Spec and task quality | 2 | CLEAR | No findings |
| Whole-branch review | Approved subagent workflow | Cross-task correctness and tests | 1 | CLEAR | No findings |
| Claude review | Ship adversarial pass | Recovery and lock-order failures | 1 | CLEAR | No actionable findings; tests reviewed in summary mode |
| Codex review | `codex exec` | Independent filtered branch review | 1 | PASS | Zero P1 and P2 findings |

**CODEX:** Current-state recovery and cursor lock order are correct; regression assertions inspected.

**CROSS-MODEL:** Claude, the task reviewers, the whole-branch reviewer, and Codex found no actionable defect.

**VERDICT:** Code reviews and local backend/frontend gates cleared. Backend: 3,735 tests, 97.10% coverage. Frontend: 1,469 tests. Secret scan and supported image CI results are recorded in the execution ledger and PR.

NO UNRESOLVED DECISIONS
