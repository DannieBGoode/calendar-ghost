# Context Module Splits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split four growing files by context and responsibility with no behavior change.

**Architecture:** Move existing definitions intact and change callers to import their owners.
Keep the application context order and all import-linter contracts unchanged. Keep the root
composition and the single User unit of work where existing architectural tests require them.

**Tech Stack:** Python 3.12, protocols, dataclasses, SQLite, Pydantic, FastAPI; existing pnpm 12 gates.

**Spec:** `docs/superpowers/specs/2026-10-20-open-registration-design.md`, delivery slice 2;
ADR 0032 and ADR 0040. The owner's attached brief adds the pure-move and review requirements.
Status: approved for implementation through the owner's delegated Claude review on 2026-10-21.
The first outside review found one P1 and three P2 issues. Those findings are addressed below;
Claude's second read-only review approved the revised plan with no remaining P1 or P2 findings.

## Global Constraints

- No behavior change: same routes, OpenAPI bytes, SQL, logs, errors, and compiled web bundle.
- Tests remain unchanged except import paths. No compatibility re-export shims or unused modules.
- Preserve names, signatures, field order, defaults, decorators, comments, and function bodies.
- Change only imports and necessary module headers around moved definitions; do not reformat bodies.
- Keep `pyproject.toml` import contracts and `WIDE_DATACLASSES` unchanged. No complexity suppressions.
  Add no constructor with more than seven fields; move existing dataclasses intact.
- No migration, provider change, Plan Hold activation, or work on the next delivery slice.
- One green commit per file split. Update current documentation paths in that same commit.
  Add this plan in the first split commit. In ADR 0040 and the open-registration spec, annotate
  only the paths changed by that commit; do not describe later tasks as already completed.
- Commit summaries use sentence case and end with `with no behavior change`; use truthful
  `Co-Authored-By` trailers. Stage only owned paths and inspect unrelated changes before staging.
- Follow-up improvements go into a note, not the implementation.

## Baseline and review focus

Fetched `origin/main` on 2026-10-21: `a3f9d00b14462c0b1cac4e12651bef62f959d56c`.
PR #131 is merged. `gh pr list --state open` returned no PRs, including Plan Hold PR 3.
Branch: `refactor/context-module-splits`, created directly from that remote commit.
Repeat the open-PR check before implementation; if a Plan Hold PR is open, ask whether to wait.

| File under `src/calendar_sync/` | Before lines | Before bytes | After |
| --- | ---: | ---: | --- |
| `bootstrap/container.py` | 1,057 | 42,287 | Measure root and every extracted module |
| `interfaces/api/schemas.py` | 1,149 | 38,303 | Measure every replacement module |
| `infrastructure/persistence/sqlite.py` | 1,185 | 49,144 | Measure every replacement module |
| `application/sync/ports.py` | 752 | 27,313 | Measure retained file and extracted modules |

Record final lines and bytes, including package initializers, after each split. Do not present
estimates as measured results. Imports can increase total size even when each module shrinks.

Review these five risks with the existing checks and direct comparisons, without changing assertions:

1. Provider reads and writes keep their distinct protocols and inheritance (Task 1, provider contracts).
2. Cross-User writes, commit failures, and rollback retain ownership and atomicity
   (Task 2, persistence contracts and isolation tests).
3. Model moves keep schema names, defaults, validators, and serialized fields
   (Task 3, enum tests and byte-identical OpenAPI export).
4. Missing Master Key, unsafe public address, and disabled Plan Hold engine keep existing behavior
   (Task 4, composition and Instant Sync tests).
5. All services keep the same shared locks, clock, stores, and construction order
   (Task 4, composition tests and direct body comparison).

Paths in task tables are relative to `src/calendar_sync/`. Each row lists all definitions assigned
to that module. Imported dependencies are not re-export APIs; callers import definitions directly.

### Task 1: Synchronization ports by responsibility

**Files:** Retain `application/sync/ports.py`; create the six sibling modules below.
Modify every affected import in `src/`, `tests/`, and `scripts/` (89 current importing files).
Update `AGENTS.md`, `docs/architecture.md`, ADR 0032, and ADR 0038's current port locations.
Amend the statements that all shared context ports live in `ports.py`, and ADR 0032's
condition that splitting waits for a new unit of work: sync uses focused `*_ports.py` siblings
while retaining its single unit of work. ADR 0040 already authorizes this pure-move split.

**Interfaces:** Every existing protocol method, dataclass field, and enum member stays identical.
`UnitOfWorkFactory.__call__(self) -> UnitOfWork` and `UnitOfWork` keep their current module.
All extracted modules remain in Synchronization, below Identity and Operations.

| Module under `application/sync/` | Definitions |
| --- | --- |
| `ports.py` | `UnitOfWork`, `UnitOfWorkFactory` |
| `provider_ports.py` | `ProviderChangeSet`, `CreatedProjection`, `CalendarReader`, `ProjectionDeleter`, `ProjectionWriter`, `OccurrenceWriter`, `CalendarProvider` |
| `account_ports.py` | `CalendarNameRepository`, `ConnectedAccountRecords`, `AccountAuthorizations`, `ConnectedAccountRepository`, `CalendarAccess`, `DiscoveredCalendar`, `AccountAccess`, `AuthorizedAccount`, `AccountAuthorization`, `AccountCalendars` |
| `record_ports.py` | `SyncRuleRepository`, `EventMappingRepository`, `OccurrenceMappingRepository`, `ExceptionReplayRepository`, `SyncCursorRepository`, `AuditRepository`, `SourceObservationRepository`, `RuleRunOutcomeRepository`, `RulePreviewSummary`, `RulePreviewRepository`, `ProviderCallRepository` |
| `health_ports.py` | `IncidentRepository`, `IncidentNotifications`, `RuleHealthRecords`, `RemovalIncidents`, `RecoveryIncidents`, `FullPassRecords` |
| `plan_ports.py` | `PlanGraceRecord`, `Allowances` |
| `run_ports.py` | `ScheduledRule`, `RunIdGenerator`, `ProviderCallCounts`, `ProviderCallTally`, `ProviderCallStats` |

- [ ] Snapshot definitions and SQL/string constants as non-Python data under `.context/` for comparison,
  so Ruff does not discover duplicate source snapshots. Confirm local snapshots stay gitignored.
  Record hashes of `web/openapi.json`, `web/src/lib/api-schema.ts`, and the compiled static tree.
- [ ] Move definitions intact; update imports to the table. `ports.py` imports repository protocols
  for its actual annotations. Record ports may depend on run ports; run ports never import records
  or `ports.py`. Keep existing `watch_ports.py` definitions in place; redirect its type-only
  `Allowances` import to `plan_ports.py`. Record its stale cycle comment as a follow-up.
- [ ] Compare moved AST definitions and exact definition text with the baseline, ignoring only
  import relocation. Run provider and persistence contracts, architecture tests, and the full
  backend gate below. Existing allowed and blocked paths must pass unchanged.
- [ ] Fresh reviewer checks pure moves and dependency direction. Fix findings, rerun affected gates,
  measure sizes, inspect `git diff -M` and `git diff --color-moved`, then commit only this split.

### Task 2: SQLite adapters in their owning context

**Files:** Replace `infrastructure/persistence/sqlite.py` with the package below; both
`sqlite/__init__.py` and `sqlite/sync/__init__.py` are empty. Existing identity and operations
adapters already have separate modules. Do not move them or create empty context placeholders.
Update `docs/architecture.md` and ADR 0032's persistence locations. Annotate only the SQLite
paths in ADR 0040 and the open-registration spec in this commit.

**Interfaces:** Keep `SqliteUnitOfWork`, `SqliteUnitOfWorkFactory`, every repository, and each row
decoder's existing signature. All repositories still share the one connection supplied by the UOW.

| Module under `infrastructure/persistence/sqlite/` | Definitions |
| --- | --- |
| `sync/accounts.py` | `SqliteConnectedAccountRecords`, `SqliteCalendarNameRepository` |
| `sync/rules.py` | `SqliteSyncRuleRepository`, `_rule_refusals`, `_rule_values`, `rule_from_row`, `SqliteRulePreviewRepository`, `preview_from_row` |
| `sync/mappings.py` | `SqliteEventMappingRepository`, `SqliteExceptionReplayRepository`, `SqliteOccurrenceMappingRepository`, `_serialize_start`, `_parse_start`, `_ref`, `_occurrence_from_row`, `_mapping_from_row` |
| `sync/records.py` | `SqliteSyncCursorRepository`, `SqliteAuditRepository`, `_recorded_event`, `SqliteRuleRunOutcomeRepository`, `_caused`, `outcome_from_row`, `SqliteProviderCallRepository` |
| `shared.py` | `optional_time`, `_require_own` |
| `unit_of_work.py` | `SqliteUnitOfWork`, `SqliteUnitOfWorkFactory`, `_UserUnitsOfWork` |

- [ ] Move definitions intact. Put `_require_own` in shared so rules and records need no sibling
  dependency for their ownership check. Keep connection creation, order of repository construction,
  commit validation, rollback, close, SQL text, parameter order, and refusal classification intact.
- [ ] Change UOW imports in bootstrap, `scripts/dev_preview.py`, `tests/users.py`, and adapter tests
  `test_persistence_contract.py`, `test_watch_inbox.py`, `test_account_limit.py`, `test_plans_schema.py`,
  `test_api.py`, and `test_plan_races.py`. Change repository
  imports in scheduling and SQLite tests. Change `installation.py` to import each row decoder
  from its owner and `optional_time` from shared. Preserve monkeypatch targets as the same classes.
- [ ] Compare every definition, class SQL constant, and SQL literal byte for byte with the baseline.
  Run `tests/adapters/test_persistence_contract.py`, `test_sqlite.py`, `test_sqlite_connections.py`,
  `test_user_isolation_schema.py`, and the full backend gate. Do not extend persistence contracts:
  the port and UOW behavior and signatures are unchanged.
- [ ] Fresh reviewer checks ownership and transaction equivalence. Fix, verify, measure, inspect
  moves, and commit only this split and its path documentation.

### Task 3: HTTP schemas by context

**Files:** Replace `interfaces/api/schemas.py` with `schemas/{shared,sync,identity,operations}.py`
and an empty `schemas/__init__.py`. Update `AGENTS.md`'s schema generation instructions.
Keep `interfaces/api/identity_schemas.py` in place.

**Interfaces:** Keep all existing class and alias names, inheritance, field definitions, validation,
and model configuration. No route, request, response, generated type, or bundle changes.

| Module under `interfaces/api/schemas/` | Definitions |
| --- | --- |
| `shared.py` | `ApiResponse`, `RecordedTimeResponse`, `FieldChangeResponse`, `IncidentMessageResponse`, `IncidentResponse`, `ProjectionChoice`, `TentativeChoice`, `UnansweredChoice`, `PrivacyPolicy`, `StatusVerdictValue`, `ProblemKindValue`, `CauseValue`, `IncidentCategoryValue`, `IncidentStepValue`, `HintKindValue`, `InstantSyncAvailabilityValue`, `EffectiveCadenceValue`, `SyncIntervalValue`, `AllowanceBasisValue`, `LimitedResourceValue`, `RunReasonValue`, `FoundByValue`, `SourceComparisonValue`, `WorkKind`, `TokenScope`, `_STATUS_READ`; retain the existing imports of `IncidentResolutionValue` and `IncidentState` |
| `sync.py` | `CalendarEndpointPayload`, `NamedCalendarEndpointResponse`, `CreateRuleRequest`, `RuleResponse`, `RunOutcomeResponse`, `PreviewSummaryResponse`, `SyncResultResponse`, `DriftResponse`, `ReconciliationConflictResponse`, `ReconcileResultResponse`, `PreviewProjectionResponse`, `PreviewItemResponse`, `RulePreviewResponse`, `RuleWorkResponse`, `RuleSummaryResponse`, `RuleDetailResponse`, `UpdateRulePolicyRequest`, `ReplaceRuleRequest`, `RemovalResponse`, `RuleReplacementResponse`, `ProviderConfigurationResponse`, `ProviderResponse`, `ConnectedAccountResponse`, `AccountAccessResponse`, `DiscoveredCalendarResponse` |
| `identity.py` | `SetupStatusResponse`, `SetupRequest`, `SignInRequest`, `SignedInUserResponse`, `SessionResponse`, `SetEmailRequest`, `ChangePasswordRequest`, `IntegrationTokenResponse`, `IssuedIntegrationTokenResponse`, `IssueIntegrationTokenRequest`, `RegistrationResponse`, `RegistrationRequest`, `IssuedLinkResponse`, `PendingInvitationResponse`, `LinkRequest`, `LinkStatusResponse`, `AcceptInvitationRequest`, `RequestPasswordResetRequest`, `PasswordResetAcceptedResponse`, `PasswordResetLinkRequest`, `ResetPasswordRequest`, `UserResponse`, `PlanNameResponse`, `AppliedPlanResponse`, `PlanLimitsResponse`, `PlanLimitsRequest`, `DefinePlanRequest`, `ChangePlanRequest`, `PlansSettingRequest`, `RoleRequest`, `UserStateRequest`, `DeleteOwnAccountRequest`, `UserDeletionResponse`, `OwnAccountDeletionResponse`, `NotificationPreferenceRequest`, `InstantSyncPreferenceRequest`, `IdentityEmailResponse`, `UseCountResponse`, `PlanUseCountsResponse`, `PlanResponse`, `PlansResponse` |
| `operations.py` | `ProblemResponse`, `DashboardResponse`, `RecordedEventResponse`, `AuditEntryResponse`, `SourceChangeResponse`, `EventSnapshotResponse`, `ActivityEventResponse`, `DatabaseUsageResponse`, `LogUsageResponse`, `StorageResponse`, `ClearableActivityResponse`, `ClearActivityRequest`, `ClearedActivityResponse`, `RecentChangeResponse`, `SchedulerResponse`, `StatusCountsResponse`, `StatusCalendarResponse`, `StatusRuleResponse`, `StatusIncidentResponse`, `StatusResponse`, `ProviderCallsResponse`, `ResourceUseResponse`, `OverLimitResponse`, `LimitUseResponse`, `PersonPlanUseResponse`, `PersonPlanOverviewResponse`, `OwnPlanResponse`, `PlanAssignmentsRequest`, `PlanMoveResponse`, `PlanAssignmentsResponse`, `PersonResponse`, `UserOverviewResponse`, `UserPageResponse`, `PeopleQuery`, `InstallationIncidentResponse`, `InstallationHintResponse`, `InstallationHealthResponse` |

- [ ] Move definitions in their existing relative declaration order. Sync and identity import
  shared; operations imports identity and shared. Import `_STATUS_READ` into identity so the
  token scopes default-factory lambda resolves exactly as before.
  `IncidentResponse` and `IncidentMessageResponse` live in shared so its two imported incident
  aliases remain used and the unchanged enum-test bodies can inspect the single shared namespace.
  All callers import these models from shared directly. Operations imports `IncidentMessageResponse`
  from shared for `ProblemResponse`; there is no alias re-export or unused import.
  `RecordedTimeResponse` and `FieldChangeResponse` also live in shared, in source order, so Ruff
  can trace their local `ApiResponse(BaseModel)` inheritance without flagging the unchanged
  Pydantic list defaults (RUF012). Operations and the Activity route import them from shared
  at runtime. Claude approved this placement correction during implementation.
  Plan catalog models `PlanResponse`, `PlansResponse`, `PlanUseCountsResponse`, and `UseCountResponse`
  belong to identity, alongside their existing `PlanListing` and `PlansOverview` use-case outputs.
- [ ] Update imports in API routes `account`, `accounts`, `activity`, `compatibility`, `identity_email`,
  `incidents`, `integrations`, `password_reset`, `plans`, `rules`, `session`, `setup`, `storage`,
  and `users`, plus `plan_payload.py` and `status_payload.py`. In `test_schema_enums.py`, change
  only the module import to `from calendar_sync.interfaces.api.schemas import shared as schemas`.
- [ ] Compare definitions, then run schema enum tests, `tests/test_openapi_contract.py`, API
  authorization tests, and the backend gate. Export OpenAPI and require identical baseline bytes
  and `git diff --exit-code -- web/openapi.json`. Do not regenerate changed frontend types to
  conceal a difference. The difference must be fixed in the move.
- [ ] Fresh reviewer checks wire equivalence. Fix, verify, measure, inspect moves, and commit.

### Task 4: Composition by context with a small root

**Files:** Retain `bootstrap/container.py`; create `bootstrap/{shared,sync,identity,operations}.py`.
Keep existing `bootstrap/identity_email.py` and `identity_email_changes.py` in place.
Update `docs/architecture.md` and ADR 0022's current provider composition paths.

**Interfaces:** Keep service fields and factory signatures intact. The sole production interface
import stays `interfaces.api.app -> bootstrap.container`, as the existing contract requires.

| Module under `bootstrap/` | Definitions |
| --- | --- |
| `container.py` | Retain `Container`, `Adapters`, `build_container`, `service_container`, `build_adapters`, `compose`, `_failure_causes` |
| `shared.py` | `UserServices`, `public_address`, `instant_sync_address`, `_mail_server` |
| `sync.py` | `calendar_providers`, `_compose_user`, `_watch_upkeep`, `_account_watches`, `_no_account_watches`, `_no_provider` |
| `identity.py` | `IdentityServices`, `AdministrationServices`, `_identity`, `_administration`, `_owned_rules`, `_no_watches` |
| `operations.py` | `PlanServices`, `_plan_services`, `_InstantSync`, `_instant_sync`, `_notice_readers`, `_instant_sync_signals`, `_scheduled_services`, `_installation_notifier` |

The root will retain roughly 400 lines plus imports: unchanged structural tests reserve rule-lock
construction and installation UOW references for this file. Keep `compose` with `Container` to
avoid a runtime cycle between the root and a sibling importing `Container` to build it. Moving
`Container` too would require changing the import-linter exception. Keep the mixed-context `_compose_user`
function intact; this PR moves its composition responsibility without redesigning service bundles.

- [ ] Move definitions intact. Siblings import the root's `Adapters` only under `TYPE_CHECKING`,
  using existing postponed annotations. Preserve construction order, shared instances, lambdas,
  nullable branches, scheduler closure timing, logging setup, and `plan_holds=None`.
- [ ] Update `calendar_providers` imports in live provider checks and troubleshooting anchor tests;
  `UserServices` in dev preview and `tests/adapters/test_api.py`; address helpers in notifications and Instant Sync tests; and
  `_scheduled_services` in composition tests. Keep root-name callers unchanged, without shims.
- [ ] Compare bodies. Run composition, notifications, Instant Sync loops, architecture, isolation,
  provider neutrality, troubleshooting anchors, and OpenAPI tests, then the backend gate.
- [ ] Fresh reviewer checks object sharing, optional configuration, and deferred callbacks. Fix,
  verify, measure, inspect moves, and commit this split with its documentation.

## Checks and delivery after all four commits

Execute commands separately and record real exit codes in `.context/`. Never pipe through `tail`.
The full backend gate required for each commit is:

```sh
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/lint-imports
.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80
.venv/bin/python scripts/export_openapi.py
git diff --exit-code -- web/openapi.json
```

- [ ] Use an implementer and a fresh behavior reviewer per task, then a final whole-branch review.
  Keep the run/task/review/fix ledger in `.superpowers/sdd/`; resume limited workflows with
  `resumeFromRunId` rather than skipping their reviews.
- [ ] Compare baseline and final test bodies after removing import nodes recursively, including
  imports inside test functions; they must match. Path-parametrized architecture checks may collect
  more cases because the split creates more files; their test bodies still remain identical.
  Compare all moved definitions and literals, verify no re-export shims remain, and check the
  dependency contracts, SQL migrations, generated types, and bundle hashes against the baseline.
  Audit each moved definition's global bindings against the baseline using the move map to
  normalize module paths: names must still refer to the same intended definitions or constants.
  Include default-factory globals and resolved Pydantic fields, since matching bodies alone cannot
  prove that a relocated name still resolves correctly. Do not require literal object identity
  between separate baseline and final processes, or runtime resolution of type-only imports.
  Inspect `git diff -M origin/main...HEAD`; use `--color-moved` to review splits where Git's
  one-source/one-target rename detection cannot show every extraction.
- [ ] Run in `web/`: `pnpm audit --audit-level=high`, `pnpm run api:check`, `pnpm run typecheck`,
  `pnpm run lint`, `pnpm run doctor`, `pnpm run knip`, `pnpm run test`, `pnpm run build`.
  Set `CALENDAR_GHOST_SOURCE_URL=https://github.com/DannieBGoode/calendar-ghost/tree/0e5064a99538ea3aa244e2379b05775e77d1c608`
  for the build, matching the source URL embedded in the baseline bundle, so output stays identical;
  investigate any changed assets and stage none from unrelated processes.
- [ ] Verify `gitleaks version` is 8.30.1, then run `gitleaks git .`, including the branch commits.
  Complete container validation through `docker compose build` or supported-architecture CI.
- [ ] Get an outside read-only Claude review of the branch, excluding generated assets, asking
  specifically for behavior changes. Fix every verified P1/P2 and rerun affected gates. A behavior
  defect found in untouched code goes into a follow-up note rather than this pure-move PR.
- [ ] Fill `.github/PULL_REQUEST_TEMPLATE.md`, include measured before/after sizes, move evidence,
  gate results, review outcome, and any blocker. Push, open against `main`, remain on the PR branch,
  and watch CI. Verify review comments, fix valid findings, push, and reply with fixing commits.
- [ ] Do not start Open sign-up until this PR merges and its own plan is approved.
