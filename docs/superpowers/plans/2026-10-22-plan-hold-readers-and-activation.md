# Plan Hold Readers and Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development after owner review. The owner selected this method. Give each task a fresh implementer, an independent reviewer, and a fix loop. Finish with whole-branch review and one fix wave. Steps use checkbox syntax for tracking.

**Goal:** Let people see their Plan grace and held rules, choose which rules sync, and safely activate Plan Hold.

**Architecture:** Reuse the shipped User-scoped settlement and keep-choice use cases. Extend Operations read models and their HTTP/MCP adapters, then add focused React features. Production settlement stays unwired through PR 3a and activates only with the complete UI and recovery controls in PR 3b.

**Tech Stack:** Python 3.12, SQLite, FastAPI, pytest, React, TypeScript, TanStack Query, Vitest, Node.js 22+, pnpm 12.

**Spec:** `docs/superpowers/specs/2026-10-15-plans-design.md`, sections 5, 6, 10, 11, 12 and 13; `docs/superpowers/specs/2026-10-17-plans-ui-catalog-design.md`; ADRs 0039, 0027, 0024 and 0038; `CONTEXT.md`; `DESIGN.md`.

## Global constraints and baseline

- The owner requested Claude review and authorized implementation once review consensus is reached. No application code changed during mapping.
- Fetched `origin/main` on 2026-10-22: `8f836f2e301862be7e18dcc16ec6f464e5b6b377` (#134). Open-PR check returned none. Clean starting tree; created `DannieBGoode/plan-hold-pr3-plan` from that ref without renaming the placeholder branch.
- Latest migration is 39, latest ADR is 0041. This work needs neither a migration nor a new ADR. Recheck fetched main before using a number if scope changes.
- Keep existing stop code 2, seven-day grace, kept/oldest/id rank, no scheduled swaps, 100 settlement attempts per pass and Allowance chunks of 500. Reuse the engine; do not rewrite it.
- Preserve short transactions, shared SettleLocks, rule-before-writer lock order, fresh transactional Allowances, authorization-aware release and no provider/SMTP calls inside SQLite write transactions.
- No new rule state, verdict, problem kind, token scope, feature flag, dependency, context or import-contract exception. No complexity suppression, constructor above seven fields or WIDE_DATACLASSES addition.
- Use exact glossary terms, synthetic fixtures, existing components/tokens, `t()` catalogs, `count` for plural numbers and `i18n.format` for local dates/numbers. No em dashes.
- Rebuild and commit static assets with every web change. Generate OpenAPI and TypeScript types after route/schema changes. Stage only this task's files; never commit a SHA-only bundle rebuild.
- Record execution/review evidence in locally excluded `.superpowers/sdd/`; never commit the ledger. Resume a workflow with `resumeFromRunId` when its runner supplies one.

## Decisions for owner review

1. **Ship two PRs.** 3a contains HTTP/read contracts and tests, still with `plan_holds=None`. 3b contains all UI, email explanations, operational docs and activation together. Merge 3a before opening 3b from freshly fetched main. Stop for the delivery handoff between them; no activation in 3a.
2. **Keep saves return 204.** Request is `{ "rule_ids": ["..."] }`; duplicates have set meaning and `[]` clears marks. The UI then refreshes all affected reads. A successful write must not be reported as failed because a subsequent response read failed.
3. **Use explicit problems.** Busy is 409 `plan_settlement_busy`, with an explicit retry action and no automatic mutation retry. Too many is 409 `too_many_kept_rules`, params `limit` and `count` equal to the finite limit. Unknown, foreign, malformed and ineligible identifiers are 404 `rule_not_found`, without echoing identifiers. Wrong JSON shapes remain 422.
4. **Add read fields, keep existing meanings.** Own Plan gains held count, persisted grace with predicted actual holds/reserved-place losses, and ranked eligible choices. Rule/status payloads gain nullable `stop_cause`. Status raw incident/block totals stay unchanged; Dashboard totals exclude held-rule-owned records.
5. **Keep the chooser inline.** Use existing rule names from the signed-in rule list. Keep checked choices on transient failure. Permit an unchanged save, because saving again can swap a kept held rule after a competing Start. On stale eligibility, refresh and ask the person to review choices before another save.
6. **Complete the held-capacity refusal.** Add the spec's `rules_with_held` problem reason without adding a LimitedResource enum value. Keep `rules` as the resource; carry the held count as optional error/read information. Explain the capacity and link to Your plan.
7. **Activate through existing composition.** No environment switch or backfill. Updating to 3b lets the next successful scheduled settlement start graces for existing excess. The UI is the durable fallback for lost mail.

## Read-only map and spec coverage

Three parallel read-only agents mapped backend, frontend and documentation. The map reflects the per-context split in #132.

| Spec | Shipped seam and remaining work | Tasks |
| --- | --- | --- |
| 5.1, 5.2 | Domain policy, migration 34, PlanHolds, scheduled step and private mail already shipped; preserve tests | 6 |
| 5.3 | `application/sync/plan_holds.py::ChooseKeptRules.execute(chosen: Collection[SyncRuleId]) -> None`; UserServices already composes it; HTTP/form missing | 1, 4 |
| 5.4 | Lifecycle/authorization policy shipped; presentation still infers recovery from degraded | 2, 3, 5 |
| 6.1 | `application/operations/status.py`, status payload, shared Operator Overview, MCP assume degraded means Stopped | 2, 5 |
| 6.2 | Mail and preference rename shipped; explanations still promise incident-only notices | 6 |
| 10.1 | Own Plan has four fields; no grace/choices/held causes; keep route and two problems absent | 1, 3 |
| 10.2 | Your plan card, shared rule commands, preview footer and overview require held-aware behavior | 4, 5 |
| 11, 12 | ADRs and guides state production is inactive; composition test pins the gate | 2, 6 |
| 13 | Retain rollback, lost mail, grace resets, retry/save races and capacity-loss warnings | 3 to 6 |

## Review focus

- Held rules with old incidents/blocks must remain quiet without hiding a lapsed account's own problem: Task 2.
- Reserved-only excess must not promise that rules will be held: Tasks 3 and 4.
- Another tab, a removed rule or busy writer must never turn a complete choice into a partial save: Tasks 1 and 4.
- A held rule with lapsed accounts must offer keep choice, while account recovery stays available in Settings: Task 5.
- A failed Plans read or missed email must not invent an Allowance, erase choices or hide recovery: Tasks 3, 4 and 6.

## PR 3a: contracts and readers, production inactive

### Task 1: Expose the whole-set keep choice

**Files:** Create `src/calendar_sync/interfaces/api/routes/plan_choices.py`; modify `interfaces/api/app.py`, `interfaces/api/schemas/sync.py`, `interfaces/api/problems.py` under the same source root. Tests: `tests/adapters/test_plans_api.py`, `test_api_authorization.py`, `test_api_problems.py` (create if absent).

**Interfaces:** `KeptRulesRequest(rule_ids: list[str])`; `keep_rules(payload: KeptRulesRequest, services: OwnPlanChoiceServices) -> None` on `PUT /api/v1/account/plan/kept-rules`, status 204. A narrow services protocol exposes the existing `choose_kept_rules: ChooseKeptRules`; obtain it through session-scoped `user_services`. Register the router using the app's existing flat registration. Do not impose a schema maximum based on a mutable Plan limit.

- [x] Add `test_keep_rules_requires_the_owning_session` and `test_keep_rules_refuses_integration_tokens`: anonymous 401, Integration Token cannot authorize, ordinary owning session succeeds; another User's records never change.
- [x] Add `test_keep_rules_saves_the_whole_set_and_swaps_immediately`: complete marks replaced, duplicates collapse, empty set clears, free-place release and counted swap match engine; no mail, Incident or Audit Entry.
- [x] Add `test_keep_rules_unknown_foreign_and_ineligible_ids_are_not_found`, including malformed/empty IDs: identical 404 code, no identifier disclosure, no changes. Add wrong-shape 422 cases.
- [x] Add `test_keep_rules_too_many_returns_limit_and_plural_count` and `test_keep_rules_busy_saves_nothing_and_can_be_retried`: exact status/codes/params, unchanged marks and rules on refusal, explicit retry later succeeds. Reuse real-lock tests in `test_choose_kept_rules.py` and `test_plan_races.py` rather than duplicate their engine coverage.
- [x] Run these tests red, add the adapter and problem mappings, run them green and the existing choice/race tests. Export OpenAPI and regenerate API types in this route-changing commit; update typed fixtures/build assets if required. Review, fix and commit.

### Task 2: Make shared status, Dashboard and MCP hold-aware

**Files:** Modify `src/calendar_sync/application/operations/status.py`, `src/calendar_sync/interfaces/api/status_payload.py`, `schemas/operations.py`, `schemas/shared.py`, and `src/calendar_sync/interfaces/mcp/server.py`. Tests: `tests/application/test_status.py`, `tests/adapters/test_status_api.py`, `test_status_payload.py`, `test_mcp.py`, `test_operator_overview_reads.py`, `test_schema_enums.py`.

**Interfaces:** Keep `assess_installation(...) -> InstallationStatus` unchanged. Add `RuleCounts.held: int`, `StatusCountsResponse.held: int`, `StatusRuleResponse.stop_cause: RuleStopCauseValue | None`, `DashboardResponse.held_rules: int`. Define `RuleStopCauseValue = Literal["lapsed_authorization", "plan_hold"]`. `Dashboard.of()` uses status counts for held without inflating enabled_rules. Refactor focused private helpers if needed; do not grow complexity or constructor parameters.

**Count integrity:** Add `OperationsOverview.held_open_incidents: int = 0` as its seventh field. Populate the exact count across all open rule-owned incidents with held-owner rule joins in SQLite's own and bulk readers, and the in-memory installation reader. Dashboard open_incidents is raw total minus this exact count, never the length of the capped incident page. Extend `application/operations/ports.py`, the current `SqliteOperationsQueries` adapter, `persistence/activity_queries.py::operations_of`, `memory_installation.py`, and `tests/contracts/persistence.py` with SQLite/memory parity assertions. Keep raw totals and Activity unchanged.

**Assessment page:** Add `OperationsQueries.assessment_incidents() -> Sequence[IncidentSummary]` in `application/operations/activity.py` and `StatusRecords.assessment_incidents: tuple[IncidentSummary, ...]` in `application/operations/ports.py`; update `operator_overview.py`, SQLite activity queries and memory installation records. Read at most 100 open incidents after excluding owned held-rule incidents, newest first, retaining account-owned records. The bulk reader derives this page from its existing all-facts read with no per-User query. Own and bulk status assess this page but serialize the unchanged raw incident page. Add SQLite/memory contracts and `test_held_incident_page_does_not_hide_older_active_or_account_problem`: 101 newest held incidents must not hide an older active problem, alter raw counts/list, or cross Users. This closes a correctness gap found during Task 2 execution.

- [x] Add `test_held_rule_has_no_stopped_or_reauthorization_problem` and `test_held_rule_covers_its_incidents_and_blocks_without_hiding_activity`: held rules have no problem even with old rule incidents/blocks; source records remain; other running rules' problems remain visible.
- [x] Add `test_lapsed_account_with_only_held_rules_still_needs_attention`: skip held rules before lapse-derived rule recovery, but retain the account-owned Incident/problem. Other stopped rules may still cover their account normally.
- [x] Add `test_held_rules_need_a_working_scheduler`, `test_running_and_held_rules_can_be_healthy`, `test_only_held_rules_are_paused_after_a_successful_run`, and a no-prior-run setup case. Assert unchanged verdict vocabulary, no grace problem, held excluded from running/stopped, existing stalled timing unchanged.
- [x] Add `test_dashboard_filters_held_incidents_but_status_keeps_raw_counts`: filter Dashboard counts and block links using nonheld records; keep status counts.open_incidents, counts.blocked_events and incidents as raw records. A shared block problem counts only nonheld blocks.
- [x] Add `test_dashboard_held_incident_count_is_exact_beyond_page_limit`: more than 100 open incidents, held and nonheld, produce exact raw and Dashboard totals in own and bulk Operator Overview reads. Never subtract only held incidents from the bounded page.
- [x] Add `test_status_and_mcp_expose_identical_hold_counts_and_causes` and `test_operator_overview_matches_held_own_status`: exact additive fields, private neutral calendar labels, unchanged MCP tools/scopes. Mirror stop-cause enum in schema-enum tests.
- [x] Run red, implement scoped filtering for assessment and Dashboard without mutating the raw overview, then run all named test modules green. MCP instructions explain `stop_cause: plan_hold`, automatic release and Your plan; no new tool.
- [x] Update ADR 0024's reader contract and CHANGELOG for 3a, explicitly leaving activation pending. Keep the production inactivity test passing. Export OpenAPI and regenerate API types in this schema-changing commit; update typed fixtures/build assets if required. Review, fix and commit.

### Task 3: Supply the grace/choice read contract and held-capacity refusal

**Files:** Modify `src/calendar_sync/application/operations/own_plan.py`; create `own_plan_holds.py` beside it; modify `application/sync/rules.py`, `domain/plans.py`, `interfaces/api/plan_payload.py`, `routes/rules.py`, `schemas/sync.py`, `schemas/operations.py`, `schemas/shared.py`, and `problems.py` under `src/calendar_sync/`. Modify `web/src/lib/api.ts`, `lib/plans.ts`, `i18n/locales/en/common.json`. Tests: `tests/application/test_own_plan.py`, `test_plan_limits.py`, `tests/adapters/test_plans_api.py`, `test_schema_enums.py`, existing rule API tests; `web/src/lib/plans.test.ts` and API error tests.

**Interfaces:** OwnPlan gains `held_rules: int`, `grace: OwnPlanGrace | None`, `rules: tuple[RuleStanding, ...]`, keeping exactly seven constructor fields. Define `OwnPlanGrace(holds_at: datetime, rule_limit: int, held: int, reserved: int)` and `grace_view(grace: PlanGrace | None, standings: Sequence[RuleStanding], limit: int | None, admissions: int) -> OwnPlanGrace | None` in the focused sibling. Use the current Allowance limit and engine rank to predict COUNTED holds versus RESERVED losses. Return None without a stored grace, without a finite limit, within limit, or when a further lowering/increased admissions requires a new grace. Otherwise retain stored holds_at and report current rule_limit. Read grace, standings and admissions in one User unit of work; GET creates or changes nothing.

**Wire format:** Add `held_rules: int`, `grace: {holds_at: ISO datetime, rule_limit: int, held: int, reserved: int} | null`, `rules: [{rule_id: str, place: "counted" | "reserved" | "held", kept: bool}]` to OwnPlanResponse. Choices keep repository rank order. Add nullable stop_cause to RuleResponse, inherited by list/detail; use both existing rule serializers. Mirror RulePlace literals in enum tests.

**Refusal interface:** Extend `PlanLimitReached(resource: LimitedResource, limit: int, held_rules: int = 0)` and `SyncRuleDetails.held_rules: int = 0`. Read counted/held counts once per rules snapshot. When a RULES refusal has held_rules > 0, `_plan_params` returns reason `rules_with_held`, otherwise preserves its existing reason; include limit/count. `GetSyncRuleDetails` and RuleDetailResponse expose held_rules for the same preflight message. Failed preflight Allowance reads still return allowed/no-limit hints; Start itself fails closed. Add typed `api.chooseKeptRules(ruleIds: string[]): Promise<void>` through the existing route/method-selected call.

- [x] Add `test_own_plan_exposes_grace_held_rules_and_keep_choices`: owned ranked eligible choices only, exact deadline/counts, no marks/grace/admissions/rules changed by GET. Add reserved-only and mixed-loss cases, empty choices, held-only, unlimited/admin and a stored expired grace.
- [x] Add `test_reserved_place_loss_is_not_a_predicted_hold` and `test_own_plan_failure_never_invents_an_allowance`: failed Allowance read fails GET; ordinary rule/detail cadence reads retain their existing fail-open policy.
- [x] Add `test_grace_view_uses_current_allowance_without_mutation`: Pause brings count within limit and hides grace; raise still over recalculates losses with the same deadline; unlimited/off/admin hides grace; further lowering/admission hides the obsolete deadline until settlement records the new one. Expired eligible grace remains readable for next-check wording.
- [x] Add `test_start_refusal_explains_held_rules`: blocked Start rolls back and reports rules_with_held only with held rules; ordinary refusal and successful reserved Start stay unchanged. Pin matching preflight/UI copy and the link to Your plan, with count-based plurals.
- [x] Run red, implement, then run named backend/frontend modules green. Generate `.venv/bin/python scripts/export_openapi.py` and `(cd web && pnpm run api:types)`; commit both generated files and build static assets with the web changes.
- [ ] Review, fix and commit. Run 3a's complete gates and outside review below. Confirm `test_production_composition_does_not_activate_plan_holds` still passes, then deliver 3a as an explicitly inactive PR. Do not claim Plans enforcement is active.

## PR 3b: visible controls and activation together

### Task 4: Show the grace and inline keep form in Your plan

**Files:** Modify `web/src/features/settings-own-plan.tsx`, `lib/use-own-plan.ts`, `lib/plans.ts`; create `features/settings-kept-rules.tsx`, `lib/use-kept-rules.ts`; modify `i18n/locales/en/settings.json` and `common.json`. Tests: `features/settings-own-plan.test.tsx`, new `features/settings-kept-rules.test.tsx`, `lib/use-own-plan.test.tsx`.

**Interfaces:** `KeptRulesForm({plan}: {plan: OwnPlan})`; `useKeptRules()` owns the typed mutation and refresh. Join OwnPlan.rules to existing signed-in rule summaries for labels; never infer eligibility from UI state. Show a recoverable load error if names cannot be read; never save a partial list. Save sends the complete selected set, including unchanged choices. Refresh own-plan, rules, affected rule details, dashboard and existing person/status query keys after success.

- [ ] Add `test_grace_uses_local_time_and_separate_reserved_losses`: visible grace line uses grace.held as count, rule_limit as limit and i18n.format date/time; reserved-only losses use a grace deadline sentence, not “rules will be held”; list reserved losses separately. Keep usage meters based on rules_counted and held count separate.
- [ ] Add `test_expired_grace_says_next_scheduled_check`: a past holds_at says “At the next scheduled check, {count} rules will be held” rather than promising a past future date; reserved losses remain separate. No active grace means no deadline warning.
- [ ] Add `test_keep_form_saves_whole_set_and_allows_unchanged_resave`: counted/reserved/held labels, saved checkmarks, finite maximum, deselection possible at maximum, empty choice valid, unchanged save enabled. Use one visible “Choose which rules sync” step opening the inline form, then Save/Cancel; no modal.
- [ ] Add `test_keep_form_preserves_edits_on_busy_and_recovers_stale_choices`: busy message with explicit retry, no automatic retry, edits/focus retained; 404 refreshes candidates and requires review; too-many refreshes capacity and shows coded text. Success acknowledges save, refetches authoritative state and can report refresh failure separately.
- [ ] Add `test_keep_form_has_keyboard_labels_and_anchor_focus`: native labelled checkboxes, labelled maximum/count, pending state, inline alert/live result, no focus loss on save, #your-plan arrival focus, pseudo-locale without raw keys/placeholders. Existing read-error retry and fail-open hints remain.
- [ ] Add `test_own_plan_remains_reachable_until_pending_holds_release`: held_rules > 0 keeps the section visible even with Plans off or administrator exemption. Render “These rules resume at the next scheduled check” without requiring an applied Plan card; confirmed unlimited/off/admin rules have no keep-choice next-step link. A stale link can still reach the pending-release section. Unknown/failed Plan reads retain an actionable link to the section's Retry. With no holds/grace, retain existing off/Only Me visibility.
- [ ] Run red, implement with existing checkbox/card/button tokens, run the named Vitest modules green, build and include static assets. Review, fix and commit without activating settlement.

### Task 5: Correct held-rule actions across every screen

**Files:** Modify `web/src/components/rule-commands.tsx`, `features/rules.tsx`, `rule-details.tsx`, `rule-policy-editor.tsx`, `rule-preview-footer.tsx`, `overview-sections.tsx`, `overview.tsx`, `user-overview.tsx`, `lib/overview-health.ts`, `lib/use-own-plan.ts`, `lib/rule-change.ts`, relevant `i18n/locales/en/{rules,rule-details,rule-preview,overview,people,settings}.json`. Split focused helpers/components where lint requires; features compose components, never the reverse.

**Interfaces:** Shared badge/action/menu inputs gain `stopCause: RuleSummary["stop_cause"]`; third-person display uses an explicit flag or its existing owner context. Check plan_hold before degraded/account inference. `usePlanWarning() -> boolean` becomes over_rule_limit OR held_rules > 0 on a successful read. Use actual cache keys and existing YourPlanLink navigation, preserving modified clicks.

- [ ] Extend rules/detail tests: neutral “Held by your plan”, “Resumes by itself when your plan has room”, one “Choose which rules sync” next step; no “Preview to restart”, Start, Sync now or Reconcile now. Pause and ordinary Preview remain in More actions. Held plus lapsed account keeps the same held step; the account remains actionable in Settings. Add Plans-off, unlimited and administrator cases: omit the keep step when a read confirms no finite limit, retaining pending-release text; a failed read still links to Your plan Retry.
- [ ] Extend `features/rule-preview.test.tsx`: held preview retains results, explains hold in Start's place and links to Your plan. Give hold precedence over changed-since-preview and capacity-refusal branches. Preview itself never releases the hold.
- [ ] Extend `features/overview.test.tsx`, `lib/overview-health.test.ts`, `lib/overview-onboarding.test.ts`: all-held paused hero mentions holds with keep step; enabled + held keeps server verdict; checklist uses enabled_rules + held_rules. Update `features/person-page.test.tsx` for “Held by their plan” with degraded plus null problem; preserve neutral labels/privacy.
- [ ] Extend `lib/use-own-plan.test.tsx` and policy/Pause/Disconnect feature tests: show “Your plan may not let this rule start again.” with held_rules > 0 even within limit; failed reads hide hints and leave actions usable. Update `lib/rule-recovery.test.ts` to assert held behavior rather than pin the obsolete degraded expression.
- [ ] Add `test_policy_edit_ends_automatic_plan_release`: held-specific edit consequence explains that the hold ends and preview plus limit-checked Start are required. Ordinary stopped and paused consequences remain correct.
- [ ] Update rule labels and menu count inference to stop_cause; do not treat held rules as Active Rules. Run affected Vitest modules red/green, build and include assets. Review, fix and commit with production still inactive.

### Task 6: Explain notices, verify the full UI, then activate production

**Files:** Modify `web/src/features/settings-own-account.tsx`, `i18n/locales/en/{settings,people}.json`, their tests and Plan editor tests; create `scripts/dev_preview_plan_holds.py` with synthetic seeding and integrate in `scripts/dev_preview.py`, `tests/test_dev_preview.py`; modify `src/calendar_sync/bootstrap/container.py`, `tests/adapters/test_composition.py`. Docs: `CONTEXT.md`, `AGENTS.md`, `CHANGELOG.md`, `docs/{self-hosting,troubleshooting,deployment,data-ownership,architecture,domain-model,sync-model,development}.md`, ADRs 0039, 0038, 0027, 0024; update the Plans spec delivery record and UI catalog's obsolete lowering copy. Correct `ChangePlan`, change_plan route and OwnPlan.over_rule_limit docstrings.

**Interfaces:** Replace compose's `plan_holds=None` with `ScheduledPlanHolds(adapters.allowances, lambda owner: user_services(owner).plan_holds, adapters.clock)`. Reuse its import and existing per-process locks/services. No engine-policy change. Add preview-only `--plan-holds grace|held|mixed|reserved` fixtures layered on `--scenario healthy`; ordinary Robin is limited, administrator remains exempt. No scheduler, SMTP, credentials, environment reads or provider writes in preview.

- [ ] Extend settings tests for Email notifications covering incidents and Plan grace/hold notices; Activity retains incidents, Your plan and held-rule views retain Plan state. Preserve legacy help URL/anchor. Identity/security mail remains independent of this preference. Remove the PR3 placeholder comment.
- [ ] Replace activated rule-limit copy in `settings.ownPlan.note.rules`, `people.usage.note.rules`, and `people.plans.editor.lowered.rules`/`people.plans.editor.loweredLater.rules`: excess keeps syncing during its seven-day grace, then is held until room returns. Keep account/token copy unchanged. Assert Your plan's over-limit usage row and Plan editor on/off lowering warnings mention the grace and hold. Correct ADR 0038's inactive-lowering bullet, troubleshooting's rule-limit/assignment claims, and self-hosting's Plans explanation in the same activation change.
- [ ] Add preview tests for each synthetic fixture and unchanged healthy default. Check port 8001 is free, then run `.venv/bin/python scripts/dev_preview.py --scenario healthy` with each fixture. Capture before/after at 1440 and 390 px, light/Twilight dark; also inspect Midnight, pseudo-locale and 200% text. Use keyboard through keep form, preview and recovery links. Store screenshots under `.context/` for PR attachment.
- [ ] Replace the inert composition test with `test_production_composition_starts_grace_holds_and_releases`: real composed pass starts exact seven-day grace, expiry holds only excess, keeps mappings/projections, hands off private notices and releases within Allowance before listing. Assert Plans off/admin exemption and authorization-aware release. Use synthetic/fake provider and mail only.
- [ ] Run the new composition test red before wiring, then green after wiring. Existing scheduler ordering, busy rotation, mail independence and privacy tests must stay green. Activation and all UI prerequisites ship in this same PR; do not merge a partial activation commit separately.
- [ ] Finish docs: grace/keep/swap/release, preview-preserves-hold, capacity-loss warnings, lost/coalesced mail, visible fallback, and monitor guidance to read stop_cause or needs_attention rather than state. Announce degraded-without-Stopped and unchanged raw status totals. Replace production-dormancy claims, preserve historical rollback-to-inert-build guidance and pre-migration-34 risks. Read README and licensing/instant-sync text for contradictions; change only stale claims. Keep accounts/tokens unaffected by lowering.
- [ ] Review activated docs against runtime and accepted spec risks. Run wording/architecture/isolation tests, relevant site rendered-doc checks including the legacy anchor, frontend tests and build; include static assets. Review, fix and commit.

## Final review and delivery for each PR, after owner approval

- [ ] Use the task implementer/reviewer fix loops, then independent whole-branch review against both specs, and one test-first fix wave. Keep ledger/results locally in `.superpowers/sdd/`.
- [ ] Run separately and record real exit codes: `.venv/bin/ruff format --check .`; `.venv/bin/ruff check .`; `.venv/bin/mypy`; `.venv/bin/lint-imports`; `.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80`.
- [ ] In web run each: `pnpm audit --audit-level=high`; `pnpm run api:check`; `pnpm run typecheck`; `pnpm run lint`; `pnpm run knip`; `pnpm run doctor`; `pnpm run test`; `pnpm run build`. There is no `pnpm run audit` script; use pnpm's audit command. No piped tail that hides failures.
- [ ] Since operational docs render in site, run site `pnpm run check`, `pnpm test`, `pnpm run build`, `pnpm run audit:dist`, `pnpm run e2e` for 3b and any 3a rendered-doc changes. Run `gitleaks git .` with 8.30.1 over full history and branch commits, and `docker compose build`, or state the exact blocker; verify supported-architecture image CI.
- [ ] Obtain a read-only Claude review of `git diff origin/main...HEAD`, excluding static assets, web/openapi.json and web/src/lib/api-schema.ts. Fix every verified P1/P2 test-first and rerun affected gates. Report unavailability rather than claim an outside review.
- [ ] After every commit check `git diff --shortstat origin/main...HEAD`; also measure excluding generated files. If source diff passes about 4,000 lines, stop and propose a further split, retaining the activation/UI gate. Use sentence-case summaries, truthful Co-Authored-By trailers and explicit staging.
- [ ] Follow the ship skill for push/PR creation after implementation. Use `.github/PULL_REQUEST_TEMPLATE.md`, base main, screenshots for 3b and explicit activation status for both. Keep that PR's branch checked out. Watch CI; verify comments, fix valid findings test-first, push and reply on each thread with the fixing commit.
- [ ] Report every gate that could not run. Do not build hosted backup/restore or billing. Begin Task 1 after Claude review consensus, as the owner authorized.

## Claude plan review, 2026-10-22

Initial read-only review requested revisions for activated lowering copy, stale grace predictions and hidden Your plan links. These are corrected, along with exact Dashboard counts above the incident page limit, held policy-edit consequences and generated files in each schema commit. Scoped re-review exited 0: “Ready to implement. No P1 or P2 is left.” Two P3 notes were incorporated: the no-link cases also belong in Task 5, and the chooser uses one action label. Full local reports are in `.context/plan-review/claude-plan-review.txt` and `claude-plan-rereview.txt`. The owner authorized implementation on review consensus.
