# Plan Hold Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. The owner selected this method. Give each task an implementer, an independent reviewer, and a fix loop, then review the whole branch and run one fix wave. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and test the Plan Hold engine, grace, recovery, and private notices, ready for PR 3 to activate with its visible hold information.

**Architecture:** A pure domain settlement decides holds, releases, reserved-place loss, and grace changes. User-scoped use cases apply those decisions in short locked transactions. An optional scheduled step selects up to 100 Users in turns before listing rules, with SMTP independent of pass completion. Production composition leaves that step unwired until PR 3 provides visible notices and correct recovery actions.

**Tech Stack:** Python 3.12, SQLite WAL, pytest, threading Events, React, TypeScript, pnpm 12.

**Spec:** `docs/superpowers/specs/2026-10-15-plans-design.md`, sections 1.2, 1.3, 2, 3.2 to 3.7, 4, 5, 6.2, 11, 12, and 13. ADRs 0024, 0027, 0028, 0038 and CONTEXT.md govern existing behavior.

## Global constraints and baseline

- The owner approved continuing with this revised plan on 2026-10-20. Execute the tasks through review, gates, and PR creation.
- Fetched `origin/main` on 2026-10-20: `9519fd3fa67a3a16b0cd3c1fabd86a15c1c0db77`. The tree was clean. Created `plan-hold-engine` from it without renaming the placeholder branch.
- Checked that tree: migration 34 and ADR 0039 are free. Recheck before using them if main moves.
- Before implementation, fetched again and fast-forwarded to `9facec24fd7f760259da1b435e5c4c2578eb1869` (landing-page change only). Migration 34 and ADR 0039 remain free; focused domain/health baseline tests pass.
- PR 1 (#125) is present: intervention ends lapse-only recovery, and cursor advancement takes the rule write lock before writing. Extend those paths; do not repeat their fixes.
- With Plans off or for Installation Administrators, no new restriction applies. Existing holds release on the next successful pass. Disabled Users clear grace but retain holds.
- `GRACE = timedelta(days=7)`; settle at most 100 Users per pass; read Allowances in existing chunks of 500 Users.
- No new rule state, verdict, problem kind, owned table, dependency, provider branch, billing code, or installation-wide writer.
- Use CONTEXT.md terms, synthetic fixtures, no secrets, and no em dashes. Keep provider calls outside database write transactions.
- PR 3 owns keep-rules HTTP routes/form, held-rule visuals, status, Dashboard, MCP, production activation, and their remaining documentation. PR 2 cannot start a grace, hold a rule, or send a Plan notice through production composition.
- Keep execution evidence in `.superpowers/sdd/`, excluded through this worktree's local Git excludes and never committed. Resume a limited workflow with `resumeFromRunId` when it provides one.
- Use sentence-case commit summaries and a truthful Co-Authored-By trailer. Stage only this work. Check `git diff --shortstat origin/main...HEAD` after each commit.

## Decisions for owner review

1. **Include both emails and the setting rename in PR 2.** Reuse the existing per-User preference and SMTP gates. No email on release or keep-choice holds. Do not add an outbox.
2. **Gate activation in composition.** A person can build any commit on main, so a promise to release later is insufficient. PR 2 explicitly passes `plan_holds=None` to ScheduledPass. PR 3 wires the engine only in the change that supplies visible grace/hold information, the keep form, and correct recovery actions. No new feature flag. Test this production composition boundary.
3. **No interim email copy.** Build the spec's choice instruction and public-address link now. The production composition gate prevents sending until the linked form exists. Correct the spec's reserved-draft count wording as described below; drafts giving up a place are not held rules.
4. **Acquire the writer through the grace record.** `PlanGraceRecord.acquire()` makes a no-op UPDATE of its own User row as the first transaction statement. No global change to DEFERRED units of work and no new transaction framework.
5. **Count all rules, change only locked rules.** Initial standings choose lock IDs. Fresh standings decide settlement. A newly started rule or replacement draft outside that set counts but stays unchanged until the next pass. Preserve expired grace until remaining excess is settled. Notice `held` counts only actual holds, never reserved-place loss; suppress the held notice when that count is zero.
6. **Keep choice is an application use case now.** Validate all chosen IDs against fresh eligible standings, reject unknown/foreign/ineligible IDs with `RuleNotFound`, and reject more than a finite limit with `TooManyKeptRules(limit)`. Save all or none. No HTTP work until PR 3.
7. **Correct rollback wording.** Older domain readers interpret code 2 as a lapse and Start counts it; old installation `plan_use` SQL and unfinished-lapse selection use exact code 1. A code-2-only User can stay stopped until account restoration or preview and Start. Every old save replaces 2 with 0 or 1. On re-upgrade, code 1 may resume without a new limit check, then receive a fresh grace if over the limit.
8. **Keep delivery independent of passes.** Use one scheduler-owned mail thread and a background task that no pass awaits. Retain at most one sending batch of 100 and one latest pending notice per User. Do not drain a second batch while sending; newer notices replace stale pending notices for that User. Cancel mail work with the scheduler, discard unsent in-memory notices, and let an already-running bounded SMTP call finish without another send. Never block the event loop on executor shutdown.
9. **Never wait on provider work in the settle step.** Acquire rule write locks nonblocking in ID order. On contention, release already-acquired locks, raise `PlanSettlementBusy`, and rotate to another User. Keep choice uses the same helper and error; PR 3 maps its retry response. SQLite retains its existing five-second writer timeout.

## Read-only map and spec coverage

Three parallel agents mapped domain/application, persistence/races, and scheduling/notices. Their results were checked against the spec. No code changed.

| Spec requirement | Existing seam | Work |
| --- | --- | --- |
| 1.2 transitions and health | `domain/model.py`, `application/sync/health.py` | Task 1 |
| 1.3 pure policy | No Plan Hold policy yet | Task 1 |
| 3.2, 3.3, 3.5 storage/contracts | `persistence/sqlite.py`, `memory.py`; existing `rule_order` | Task 2 |
| 3.6, 4 admissions and races | `EnableSyncRule.execute`, atomic `_place_successor` already shipped | Tasks 2, 3 |
| 5.2 installation read and fair selection | `ScheduledPass.begin`, installation units | Task 4 |
| 5.3 keep choice | No use case yet | Task 3; route/form PR 3 |
| 5.1, 5.4 execution/watch exclusion | Enabled-only SQL/domain predicates already skip holds | Tasks 2, 3 contracts |
| 6.2 two notices and setting | `OwnerNotifier`, `SmtpServer`, own-account preference | Tasks 4, 5; sends activate in PR 3 |
| 3.7, 11 rollback, ADRs, invariant | Existing forward migrations and documentation | Task 5 |
| 6.1, 10 visual/status work | Existing readers assume degraded means Stopped | PR 3, release dependency |
| 12, 13 regressions and accepted limits | Existing race tests and persistence contracts | All tasks; final gates |

### Task 1: Domain settlement and safe transitions

**Files:** Modify `src/calendar_sync/domain/model.py`, `src/calendar_sync/application/sync/health.py`, `tests/domain/test_rule_places.py`, `tests/application/test_health.py`; create `src/calendar_sync/domain/plan_hold.py` and `tests/domain/test_plan_hold.py`.

**Interfaces:**
- Add `held_by_plan: bool = False`, `RuleStopCause(StrEnum)` values `lapsed_authorization`, `plan_hold`, and `SyncRule.stop_cause -> RuleStopCause | None`, `stopped_by_plan_hold -> bool`.
- Add `hold() -> Self`, `release_hold(authorized: bool) -> Self`, `give_up_place() -> Self`. Hold requires holdable; release requires held. Both flags cannot coexist; a hold requires DEGRADED. Neither field enters `material_signature`.
- Define `RulePlace(StrEnum)` values `counted`, `reserved`, `held`; `PlanGrace(holds_at: datetime, rule_limit: int, admissions: int)`; `RuleStanding(rule_id: SyncRuleId, place: RulePlace, order: int, kept: bool)` and `rank -> tuple[bool, int, str]`.
- Define `PlanNoticeKind` values `grace_started`, `rules_held`; count-only `PlanNotice(kind: PlanNoticeKind, count: int, limit: int, held: int, holds_at: datetime, reserved: int = 0)`. No rule/account/event identifiers. Grace notice `held` counts counted losers only, and `reserved` counts reserved losers. A held notice uses only committed holds and has `reserved=0`.
- Define `Settlement(hold: tuple[SyncRuleId, ...], give_up: tuple[SyncRuleId, ...], release: tuple[SyncRuleId, ...], grace: PlanGrace | None, notice: PlanNotice | None)`.
- Implement `settle(standings: Sequence[RuleStanding], limit: int | None, grace: PlanGrace | None, admissions: int, now: datetime, *, active: bool) -> Settlement` in the exact five-step spec order.

- [ ] Add `test_settle_decision_table`: disabled, unlimited, first excess, further lowering, increased admissions, raised limit still over, inclusive expiry, no expiry action before deadline, counted versus reserved losers, kept/oldest/ID ranking, best-first release, within-limit grace clearing, and no automatic swap. Assert exact IDs, grace values, and notice values for every row. Reserved-only expiry produces give-ups and no held notice; mixed expiry reports only actual holds.
- [ ] Add `test_a_raise_and_lowering_with_an_admission_restarts_grace`: admission survives another rule's removal, and expiry resets to `now + GRACE`. Add `test_expired_grace_survives_until_excess_is_gone`.
- [ ] Expand `test_rule_places.py` transition tables: held preview stays held; hold replaces lapse; authorized release enables; unauthorized release becomes lapse-stopped and counts; pause, require-preview, removal, policy change, disconnect, and intervention clear hold. Reject invalid flags/states; a held rule cannot Start or synchronize.
- [ ] Extend both `_degrade` guards for held rules. Preserve current enabled handling and use `require_preview()` for either self-resuming stop. Test `test_intervention_ends_a_hold` and `test_intervention_after_hold_release_ends_lapse_recovery`, including actual restoration of authorized accounts and zero resumed rules. Transient/account-scoped failures preserve their existing semantics.
- [ ] Run the new tests and record expected failures, implement, then run `.venv/bin/pytest tests/domain/test_plan_hold.py tests/domain/test_rule_places.py tests/application/test_health.py tests/application/test_lapsed_authorization.py -q`. Review, fix, commit.

### Task 2: Migration, scoped records, and admissions

**Files:** Create `src/calendar_sync/infrastructure/persistence/0034_plan_holds.sql` and `src/calendar_sync/infrastructure/persistence/plan_grace.py`; modify `migrations.py`, `sqlite.py`, `memory.py` in that directory, `src/calendar_sync/application/sync/ports.py`, `src/calendar_sync/application/sync/rules.py`, `tests/contracts/persistence.py`, `tests/adapters/test_plans_schema.py`, and `tests/application/test_plan_limits.py`.

**Interfaces:**
- `SyncRuleRepository.standings() -> Sequence[RuleStanding]`, ranked by `(not kept, creation_order, id)`; `keep(chosen: Collection[SyncRuleId]) -> None` replaces the whole kept set with one scoped UPDATE. Preserve `list()` ordering.
- `PlanGraceRecord.acquire() -> None`, `get() -> PlanGrace | None`, `save(grace: PlanGrace | None) -> None`, `admissions() -> int`, `admit(count: int = 1) -> None`; add `UnitOfWork.plan_grace: PlanGraceRecord`.
- SQLite acquire: `UPDATE users SET plan_admissions = plan_admissions WHERE id = ?`, before any reads in a settle transaction. Missing User raises `MissingReference`. Memory acquire checks its owner exists; its new state fields participate in existing commit/discard behavior.
- Migration 34 adds exactly `sync_rules.plan_kept INTEGER NOT NULL DEFAULT 0`, `users.plan_holds_at TEXT`, `plan_grace_limit INTEGER`, `plan_grace_admissions INTEGER`, `plan_admissions INTEGER NOT NULL DEFAULT 0`. No backfill or table rebuild. Register version 34.

- [ ] Add `test_migration_34_preserves_rules_and_has_zero_default_admissions`: upgrade 33 twice; assert exact defaults, unchanged states/data, one migration row, clean foreign keys. Add code 0/1/2 and unknown-code read/write cases. Code 2 is held only on DEGRADED; unexpected codes fail safe without a self-resume.
- [ ] Update `_rule_values` to encode holds as 2, lapse as 1, otherwise 0; read lapse only from exact 1. Read stale reserved marks only in DRAFT/PREVIEWED. Ordinary rule saves never write `plan_kept`.
- [ ] Extend `inherit_place(rule, of)` to copy order and kept mark. The existing removal call invokes it only for a predecessor that counted. Test held/non-counting replacements retain new order and no mark.
- [ ] Add contract cases `test_standings_rank_and_keep_survives_late_rule_save`, `test_replacement_inherits_order_and_keep_only_with_a_place`, `test_plan_grace_and_admissions_commit_or_discard`, and `test_plan_records_are_user_scoped`. Exercise both memory and SQLite, whole-set clearing, rollback, and foreign IDs.
- [ ] In accepted Start, call `admit()` only if the previous rule did not count, before commit. Test `test_fresh_start_records_one_admission`, `test_reserved_start_records_no_admission`, and `test_refused_start_rolls_back_admissions`, including allowance-read failure. Lapse resume, scheduled release, and replacement transfer never increment.
- [ ] Record failures first, implement, run `.venv/bin/pytest tests/adapters/test_plans_schema.py tests/adapters/test_persistence_contract.py tests/application/test_plan_limits.py -q`. Review, fix, commit.

### Task 3: Transactional settlement and keep choice

**Files:** Create `src/calendar_sync/application/sync/plan_holds.py`, `tests/application/test_plan_holds.py`, `tests/application/test_choose_kept_rules.py`; modify `tests/adapters/test_plan_races.py` and `tests/application/test_rule_state_serialization.py`.

**Interfaces:**
- `SettleLocks.for_user(owner: UserId) -> Lock`, with a guarded lock map, one shared instance per process.
- `PlanHolds(unit_of_work: UnitOfWorkFactory, owner: UserId, allowances: Allowances, locks: RuleLocks, settle_locks: SettleLocks, clock: Clock)`; `settle(notify: bool = True) -> PlanNotice | None`.
- `ChooseKeptRules(holds: PlanHolds).execute(chosen: Collection[SyncRuleId]) -> None`; `TooManyKeptRules(limit: int)` and `PlanSettlementBusy` are application errors in the same module. Share the locked-transaction helper, not nested calls to `settle` while holding a non-reentrant lock.
- `PlanNotices.plan_changed(notice: PlanNotice) -> None` is a port declared here; OwnerNotifier implements it in Task 4.

- [ ] Add application tests for atomic holds/give-up/releases/grace, authorization-aware release, disabled User, unlimited/admin/Plans off, no swaps during scheduled settle, no Incident or Audit Entry, and notices returned only after successful commit. `notify=False` changes no policy, only suppresses the notice.
- [ ] Implement lock order: User settle lock; read/close discovery unit; try discovered counted/reserved/held rules' write locks nonblocking in ID order; open fresh unit; acquire writer first; read Allowance, active state, grace/admissions, all standings, and authorization; decide; apply only locked IDs; save grace; commit. Contention releases acquired locks and raises PlanSettlementBusy before opening the writer. Never take run locks or call providers. Re-read actual remaining count before clearing expired grace. Build held notice counts from committed `hold()` calls only; no held notice for give-ups alone. Add `test_busy_rule_skips_user_without_delaying_listing` and `test_keep_choice_contention_changes_nothing`.
- [ ] Add keep tests: validate full chosen set before writes; reject excess, foreign, absent, and non-standing IDs atomically; persist choice during grace; release best kept held rules into free places; swap kept held with worst not-kept COUNTED rules, never a reserved rule; no swaps for disabled Users; no hold or limit with Plans off/admin. Free-place releases increment admissions, swaps do not; no email. Leave newly discovered unlocked candidates unchanged, as settlement does.
- [ ] Add real-thread SQLite tests: `test_lowering_before_settle_is_seen_and_after_writer_waits`, `test_lapse_before_and_after_release_is_preserved`, `test_start_racing_release_cannot_exceed_limit`, `test_new_start_during_discovery_stays_unchanged`, `test_replacement_during_settle_waits_for_next_pass`, `test_admission_survives_removal_and_restarts_grace`, `test_keep_release_during_temporary_raise_restarts_grace`, and `test_settle_failure_rolls_back_every_change`.
- [ ] Add `test_cursor_advance_and_settle_finish_without_busy_timeout`, `test_in_flight_run_stops_before_its_next_write_after_hold`, and the hold -> release-as-lapse -> permanent-failure -> authorized-restoration regression. Assert no forbidden destination write and no automatic recovery after intervention. Use Events, captured thread failures, bounded joins/finally cleanup, and real locks; no sleep-based race tests.
- [ ] Record red tests, implement, run the two new application modules plus `test_plan_races.py`, `test_rule_state_serialization.py`, `test_execute_sync_rule.py`, and `test_locking.py`. Review, fix, commit.

### Task 4: Fair scheduled settlement and private email notices

**Files:** Create `src/calendar_sync/application/operations/scheduled_plan_holds.py`; modify `src/calendar_sync/application/operations/ports.py`, `scheduled_pass.py` beside it, `src/calendar_sync/infrastructure/persistence/installation.py`, `memory_installation.py`, `src/calendar_sync/infrastructure/scheduling.py`, `notifications.py` beside it, `src/calendar_sync/bootstrap/container.py`, `tests/adapters/test_composition.py`, `tests/application/test_scheduled_pass.py`, `tests/adapters/test_scheduling.py`, `tests/adapters/test_notifications.py`, `tests/contracts/persistence.py`, and `tests/application/test_instant_sync_upkeep.py`.

**Interfaces:**
- `UserPlanStanding(owner: UserId, active: bool, standings: tuple[RuleStanding, ...], grace: PlanGrace | None, admissions: int)` in operations ports; `InstallationUnitOfWork.plan_standings() -> Sequence[UserPlanStanding]` reads from Users in one SELECT, including Users with only grace and Disabled Users.
- Add cohesive `ScheduledPlanHolds` in new `application/operations/scheduled_plan_holds.py`, consuming Allowances, `holds_for: Callable[[UserId], PlanHolds]`, and Clock. `settle(standings: Sequence[UserPlanStanding]) -> tuple[tuple[UserId, PlanNotice], ...]`; holds its rotation cursor, not InstallationUnitOfWork.
- `ScheduledPass` gains one optional `plan_holds: ScheduledPlanHolds | None`; `plan_notices_due() -> tuple[tuple[UserId, PlanNotice], ...]` drains once. Store pending mail in an init=False field to respect constructor limits. No new field on RuleHealth, InstantSyncStatus, or PreviewSyncRule.
- Add `plan_notices: PlanNotices | None = None` to ScheduledServices and `ScheduledPass.send_plan_notice(owner: UserId, notice: PlanNotice) -> None`, with isolated delivery failures. Add typed `plan_notices` to UserServices and pass it through `_scheduled_services`, from `Adapters.plan_notices: Callable[[UserId], PlanNotices | None]`. No cast from the Incident port.
- `SmtpServer.send_plan(recipient: str, notice: PlanNotice, link: str | None) -> None`; preserve incident `send` and factor only their shared private SMTP delivery. Share one SettleLocks through composed User services. Production `compose` explicitly keeps `plan_holds=None`; direct test composition supplies the optional step.

- [ ] Add ordering test `test_plan_settlement_follows_lapses_and_precedes_listing`, same-pass release/run, grace-only and held-only Users, more than 100 candidates, unchanged Users costing no slot, busy/failed User rotation, and a raised allowance-batch read changing nobody. SqlitePlans already returns every requested key, including its fallback for deleted Users; do not add an impossible missing-key test. A later per-User failure rolls back that User, logs identifiers/error class only, and permits others.
- [ ] Prefilter with pure settle and fresh batch Allowances. Unchanged means no hold/give-up/release IDs and a grace equal to the stored grace. A raise while still over changes the stored grace limit even when its expiry stays the same. Rotate sorted User IDs after the last attempted User, including failed attempts; cap attempts at 100. Read Allowance again inside every selected transaction. After lapse repairs settle before rule listing. Close installation read scopes before User mutations where needed so listings see committed releases.
- [ ] Implement independent mail worker lifecycle from decision 8, with latest pending notices keyed by User, one batch in flight, and no await of delivery from run_once. Drain newly listed notices into pending state after listing. Test `test_slow_plan_email_holds_up_no_rule`, `test_next_pass_lists_while_smtp_is_blocked`, latest-pending replacement, no duplicate drain, SMTP failure isolation, cancellation/no subsequent sends, no rule capacity lost, and no work on the event loop/default executor.
- [ ] Test exact subject `Calendar Ghost: your plan`, spec count/deadline body and choice instruction, UTC date/time, optional public-address link `/settings/account#your-plan`, all existing email gates, and no installation recipient/webhook delivery. When reserved losers exist, append "{reserved} replacement drafts will also give up their reserved places and will need a Start within your plan's limit." Omit the held-count sentence when its count is zero; test reserved-only and mixed grace cases. Dedicated privacy sentinels include calendar/account names, IDs, email markers other than the recipient header, rule IDs, and event content; none reaches body or logs. Log delivery failures without exception text that could expose SMTP credentials or recipients.
- [ ] Add `test_production_composition_does_not_activate_plan_holds`: a real composed pass with Plans on, excess rules, and expired grace leaves rules/grace unchanged and sends no Plan notice. In explicit test composition, the same data holds rules and queues notices. PR 3 must change the production test when it supplies the visible state and wires the step.
- [ ] Extend contracts: held rules absent from scheduled/instant work and wanted watch sources, exact-code-1 lapse recovery only; held-only owners still listed while watches exist. Test upkeep retires those watches. Existing `limited_user` already exists; reuse it.
- [ ] Record red tests, implement, run the changed scheduling/notification/upkeep tests and persistence contract runners. Review, fix, commit.

### Task 5: Preference wording, ADRs, and operational truth

**Files:** Modify `web/src/i18n/locales/en/settings.json`, `web/src/features/settings-own-account.tsx`, its `.test.tsx`, `web/src/features/settings-instant-sync.tsx`, `web/src/lib/brand.ts`, `README.md`, `CONTEXT.md`, `AGENTS.md`, `docs/adr/0027-lapsed-authorization-and-automatic-recovery.md`, `docs/adr/0024-integration-tokens-installation-status-and-mcp.md`, `docs/adr/0038-plans-allowances-and-limits.md`, `docs/domain-model.md`, `docs/sync-model.md`, `docs/architecture.md`, `docs/data-ownership.md`, `docs/deployment.md`, `docs/troubleshooting.md`, `docs/self-hosting.md`, `docs/instant-sync.md`, `CHANGELOG.md`, `site/e2e/landing.spec.ts`, and the Plans spec's rollback/delivery/email notes; create `docs/adr/0039-plan-hold.md`. Include the resulting `src/calendar_sync/interfaces/api/static/` assets.

- [ ] Rename every user-visible preference reference from Incident emails to Email notifications, covering notices, unavailable hints, save acknowledgments, README and guides. Keep `notify_by_email` and the current API route. Rename the help constant to `EMAIL_NOTIFICATIONS_HELP_URL` and update its consumers; retain its old troubleshooting anchor with an explicit anchor. Add a site browser assertion that `/docs/troubleshooting#incident-emails-are-unavailable-or-never-arrive` still reaches that section. Update settings/Instant Sync comments and the setting control id. No new API schema or generated API types.
- [ ] Keep PR 2 preference text true while activation is gated: "When one of your rules needs attention, Calendar Ghost can also email you. Activity always lists every incident." Its title/label can become Email notifications now. In unavailable hints, say that incidents remain in Activity, not that every notification does. PR 3 adds Plan notice scope and its visible fallback when it activates enforcement. Do not move the requested preference rename out of PR 2.
- [ ] Update settings tests to assert the shared preference controls both notice kinds. Build in the same commit; never commit a SHA-only rebuild.
- [ ] Write ADR 0039: stop code 2, grace/admissions, keep rank/swaps, held preview, locks, nonblocking busy skips, bounded fair settlement, private notices and coalescing, rollback discrepancy, and accepted limits from spec section 13. State that the engine exists but production activation, status, and visuals await PR 3. Amend ADR 0027's automatic-resume exception and ADR 0024's decision that held rules require a working scheduler; label runtime status support as PR 3.
- [ ] Update AGENTS resume invariant with the Plan Hold exception. Update CONTEXT's Plan Hold/Degraded Rule and Incident Notification definitions, architecture, state machine, and settle/lock explanations. Correct stale claims that all non-limit reads release safely on failure: failed settlement reads change nobody.
- [ ] Put migration-34 upgrade/rollback analysis in the SQL header, deployment guide, and CHANGELOG: additive columns, older code reads 2 as lapse, old saves erase 2, Start still counts it, and older raw display counts may omit it. Exact-code-1 unfinished-lapse discovery can leave code-2-only Users stopped; recover with account restoration or preview and Start. Re-upgrade may automatically resume code 1, with a new grace if then over the limit. State that production enforcement stays inactive in PR 2 and only PR 3 will produce holds normally. Keep current claims that lowering stops nothing until activation, clearly separated from the new engine's design. Document restart loss of pending email and replacement of stale pending notices.
- [ ] Correct the spec's mail analogy: checks share rule slots, mail does not share slots or pass completion. Amend its reserved-draft email counts and record the PR 3 composition gate.
- [ ] Run settings tests, `.venv/bin/pytest tests/test_ubiquitous_language.py tests/test_architecture.py tests/adapters/test_user_isolation_schema.py -q`, frontend build, `cd site && pnpm run build && pnpm run audit:dist && pnpm run e2e` for rendered-anchor coverage, and `git diff --check`. Review, fix, commit.

### Final review and delivery after owner approval

- [ ] Fresh whole-branch review against the spec, especially locked-set changes, grace restarts, authorization release, preference gates, notices, and release boundary. One fix wave, test-first for findings; record task/reviewer results in `.superpowers/sdd/`.
- [ ] Run each backend gate separately and record real exit codes: `.venv/bin/ruff format --check .`; `.venv/bin/ruff check .`; `.venv/bin/mypy`; `.venv/bin/lint-imports`; `.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80`.
- [ ] In `web/`, run each separately: `pnpm audit --audit-level=high`; `pnpm run api:check`; `pnpm run typecheck`; `pnpm run lint`; `pnpm run knip`; `pnpm run doctor`; `pnpm run test`; `pnpm run build`. Run `gitleaks git .` with CI's 8.30.1 and `docker compose build`, or report why unavailable. Check supported-architecture image CI.
- [ ] Obtain a read-only Claude review of `git diff origin/main...HEAD`, excluding `src/calendar_sync/interfaces/api/static`, `web/openapi.json`, and `web/src/lib/api-schema.ts`. Fix every valid P1/P2 test-first and rerun affected gates. If Claude is unavailable, report it without claiming cross-model review.
- [ ] Push and open the PR against `main` using `.github/PULL_REQUEST_TEMPLATE.md`. Make the inactive production composition and PR 3 activation dependency explicit. Keep `plan-hold-engine` checked out so Conductor shows the PR. Watch CI, verify comments, fix valid findings test-first, push, and reply to each review thread with its fixing commit.
- [ ] Do not start PR 3 in this branch. Report all checks that could not run and all remaining release dependencies.

## Claude plan review (2026-10-20)

Read-only Claude CLI review completed with exit 0. Full report: `.context/plan-review/claude-review.txt` (local, not committed). Claude rejected the original plan pending its two P1 and six P2 corrections. The changes below address those findings; Claude has not re-reviewed this revision. The owner subsequently approved continuing with the revised plan.

- **P1-1, P1-2 accepted:** a future release promise does not protect people building main. Gate production settlement through the existing optional composition seam until PR 3, test that boundary, and remove interim email copy.
- **P2-1 accepted:** define the typed delivery path, background mail task, pending coalescing, and cancellation. Test a second pass while SMTP remains blocked.
- **P2-2 accepted:** distinguish counted holds from reserved-place loss in both grace and held email counts. No held email for give-ups alone.
- **P2-3 accepted:** use nonblocking rule-lock acquisition and fair retry rather than wait on a provider write before listing everybody else's rules.
- **P2-4 accepted:** document exact-code-1 discovery, manual rollback recovery, and re-upgrade recovery/grace behavior.
- **P2-5 accepted with scope retained:** expand rename references and rendered-anchor coverage. Keep the owner's requested rename in PR 2, with current incident-only explanatory text until PR 3 activates Plan notices.
- **P2-6 accepted:** test raised allowance reads; remove the missing-key scenario the current adapter cannot produce.
- **Lower-priority accepted:** define unchanged settlements by exact grace equality, keep the workflow ledger uncommitted, and correct the spec's checks/mail analogy. Keep both standings readers consistent through contracts. No new rule-place property or arbitrary line-count gate is needed for this change.
