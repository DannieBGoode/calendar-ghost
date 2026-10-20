# Self-service password reset implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Each task gets a fresh implementer and reviewer, with a fix loop. Keep the ledger in `.superpowers/sdd/`, preserve `resumeFromRunId`, then run a whole-branch review and one fix wave. Steps use checkboxes for tracking.

**Goal:** Let active Users request a private, single-use, one-hour Password Reset Link from sign-in.

**Architecture:** Admit public requests through bounded memory and durable narrow identity ports before queueing. The existing identity mail worker resolves the User and sends mail later. Both reset kinds finish through one atomic credential/proof/session transaction.

**Tech Stack:** Python 3.12, SQLite, FastAPI, React, TypeScript, pnpm 12, existing SMTP transport.

**Spec:** `docs/superpowers/specs/2026-10-20-open-registration-design.md`, PR 2; ADR 0040.

## Approval and review status

The owner authorized Claude review and continued execution on 2026-10-20, replacing the owner review gate. Execution is subagent-driven.
Fetched `origin/main` at `4da18b83` (#129). Created `DannieBGoode/self-service-password-reset`
from that commit. Three parallel read-only agents mapped reset persistence, mail/limits, and API/UI.
The design and PR 1 record still mark the second Claude review as pending. A read-only retry on
2026-10-20 failed before review: `Not logged in · Please run /login`. Evidence is in
`.context/reviews/open-registration-second-claude.txt`. No findings were produced or accepted.
The authentication diagnosis was incorrect: `--bare` skips saved OAuth credentials. A corrected
`--safe-mode` read-only review completed and is recorded in
`.context/reviews/open-registration-pr2-claude-review.txt`. Its P1/P2 findings have the explicit
fixes below. Review the final implementation separately before the PR.
Claude's scoped re-review in `.context/reviews/open-registration-pr2-claude-rereview.txt`
confirms all P1/P2 findings addressed and the design/plan ready to implement.

## Delivery record

PR 2 is implemented on an unmerged branch. Reports and TDD evidence live in
`.superpowers/sdd/2026-10-20-self-service-password-reset/`:

- [x] Task 1 credential-bound proofs and atomic completion: `task-1-report.md`.
- [x] Task 2 bounded durable admission: `task-2-report.md`.
- [x] Task 3 deferred recovery mail and worker maintenance: `task-3-report.md`.
- [x] Task 4 bounded public API and headers: `task-4-report.md`.
- [x] Task 5 sign-in recovery UI and production assets: `task-5-report.md`.
  Controller live synthetic preview, keyboard checks, and screenshots passed.
- [x] Task 6 proxy source/tests and operational guidance: `task-6-report.md`.
- [x] Final backend/frontend gates and history/branch secret scans.
- [ ] Supported linux/amd64 and linux/arm64 image builds through imminent PR CI.
- [x] Authentication security review, independent whole-branch review, and outside Claude review.
- [x] Resolve verified findings test-first, rerun affected gates, obtain both scoped approvals.
- [ ] Open the PR with screenshots and watch CI.

Final whole-branch, security, and outside Claude reviews completed. The combined fix wave maps
issuer permission races to private 403 and makes only typed post-admission cleanup faults best
effort, with real SQLite RED/GREEN regressions. See `.context/reviews/pr2-final-fix-report.md`.
Fixed-head backend: 4,389 passed with 97.18% coverage; four static gates and final branch scan pass.
Independent and outside Claude scoped re-reviews approve with no open P1/P2. Full frontend/site
gates passed on unchanged source and dependencies. Supported image builds, PR and CI remain pending.

The controller owns these remaining release checks. Local Docker is unavailable; CI must build
linux/amd64 and linux/arm64. No PR 3 work starts before PR 2 merges and its own plan is approved.

## Global constraints

- Only Me remains the default; Open stays unavailable until PR 8. Plans remain independent.
- No Plan Hold files, registration/email-change tables, dormant screens, external identity service, or new dependencies.
- Identity email uses PR 1's configured predicate, HTTPS root origin or HTTP loopback, and verified remote STARTTLS.
- Self-service links last 1 hour; administrator-issued links retain 7 days. Reset never signs in or enables a User.
- Tokens use 32 random bytes, hashes in SQLite, fragments in URLs, bounded POST bodies, hidden repr fields.
- No event content, email, token, password, body, or provider exception in auth diagnostics.
- SMTP and password hashing stay outside SQLite transactions. Anonymous identity writes wait at most 100 ms.
- All Web UI text uses `t()`, values use `i18n.format`, plural parameters use `count`. No em dashes.
- Body maximum 8 KiB; normalized email 254 characters; token 128 ASCII characters; new password 12 to 1,024 characters.
- Sign-in and current-password confirmations accept up to 1,024 characters so every reset password remains usable. Setup, Invitation, and ordinary new-password creation bounds stay unchanged. Rebuild substantive web bundles with source.

## Review Focus

1. Proof expires while hashing or waiting for a lock: check the clock after acquiring the final write lock.
2. Reset races with own-password change or a new sign-in: stale writes lose, old sessions end, a later valid session survives.
3. Email changes away and back, or disable/re-enable: an old reset must never revive.
4. Queue/worker failure and unknown addresses: identical HTTP outcomes and no request-path account lookup.
5. Forwarded-header spoofing, rotating IPv6, restart, and front-gate capacity: limits keep their meaning.

## Settled implementation calls

- Extend `password_reset_links`; do not create a second proof store or a purpose column. Persisted expiry already distinguishes lifetimes. `created_by` is already nullable and remains NULL for self-service.
- Add monotonic `users.credential_revision` and bind links to it. Increment on email/password changes and disable. Role and notification changes do not invalidate proofs.
- Revoke outstanding legacy reset links during upgrade because they lack a trustworthy revision binding. Document administrator reissue. Keep existing sessions and passwords through upgrade.
- Keep administrator replacement behavior: issuing an administrator link revokes earlier resets. Public resend preserves delivered links. Successful completion invalidates both kinds.
- Reuse public `GET /api/v1/setup` for a configuration-only `password_reset_available` flag. Successful SMTP test readiness is not required for recovery.
- Use `POST /api/v1/password-resets/request`, generic 202 `{ "accepted": true }`. Client copy: "If this address can receive a reset link, we will send one."
- No pending email-change records exist yet. PR 3 must join their cancellation to these atomic credential writes; PR 2 adds no placeholder table or hook.
- Existing own-password and direct-email writes must reject stale credential confirmation when a reset lands during their request. Include only the credential mutation needed for this race.
- Offline recovery command is PR 4. In PR 2 document administrator-issued fallback and the existing stopped-service backup recovery path, clearly stating the command is not shipped.
- The identity origin rule governs emailed link issuance, not administrator hand-delivered link completion. Valid proofs may finish after SMTP/origin settings change; administrator resets still work on HTTP LAN installations.
- Without a Master Key, reset token/completion network limits use the bounded memory gate only. Public email recovery remains unavailable. Whenever a Master Key exists, token/completion limits persist even if identity email is unavailable.
- Keep approved global/network caps. Document that two networks can exhaust the global allowance; administrator links remain the fallback. Do not add a /48 policy.
- Existing/Invitation Only emails remain eligible as approved, including direct changes before PR 3. Document wrong-email mailbox takeover risk without retroactive verification.
- Malformed email returns account-independent 422.

## Code map and requirement coverage

| Requirement | Existing boundary | Task |
| --- | --- | --- |
| Issuance, expiry, sibling/session races | `application/identity/administration.py`, `persistence/registration.py`, `persistence/users.py`, `identity_fakes.py` | 1 |
| Narrow public ports, durable limits, network grouping | new reset modules; existing `infrastructure/throttle.py` keeps sign-in and Invitation links, reset leaves it | 2 |
| Deferred lookup, reserved reset lane, secure mail | `identity_mail_worker.py`, `infrastructure/identity_email.py`, `bootstrap/identity_email.py` | 3 |
| Generic public request, bounded completion, authorization | `routes/users.py`, `routes/setup.py`, `schemas.py`, `app.py` | 4 |
| Live sign-in entry, request/retry/completion | `web/src/app.tsx`, `auth-screen.tsx`, `password-reset-page.tsx`, `lib/api.ts` | 5 |
| Proxy trust, retention, upgrades, outside/security review | Docker/Compose, docs and existing gates | 6 |

Paths below are relative to `src/calendar_sync/` unless they start with `tests/`, `web/`, or `docs/`.

### Task 1: Bind reset proofs and finish credentials atomically

**Files:** Modify `application/identity/ports.py`, `administration.py`, `sign_in.py`;
`infrastructure/persistence/registration.py`, `users.py`, `migrations.py`; `bootstrap/container.py`;
`tests/identity_fakes.py`, `tests/contracts/persistence.py`, `tests/application/test_identity.py`,
`tests/adapters/test_users_store.py`, `test_admin_sessions.py`, `test_user_isolation_schema.py`.
Create `application/identity/password_reset.py`, `application/identity/credentials.py`,
`infrastructure/persistence/credentials.py`, `tests/adapters/test_password_reset_store.py`.
Add the next free migration named `<number>_self_service_reset.sql` after a fresh fetch/check.
Current registry ends at 35; do not reserve 36 or add a new ADR for an already settled decision.

**Interfaces:** Keep `PasswordResetLinks.issue(user_id, created_by, at) -> IssuedLink` and
`owner(token, at) -> UserId | None`. Change `reset(token: str, password_hash: str) -> UserId | None`
to own all invalidation and read injected `Clock` after `BEGIN IMMEDIATE`.
Add `SelfServicePasswordResets.issue_for_email(email: str) -> PreparedPasswordReset | None`;
the store uses its clock under lock. `PreparedPasswordReset` contains recipient and issued link,
both hidden from repr. Add `CredentialSnapshot(user_id, revision, password_hash)` with hash hidden;
`CredentialChanges.current(user_id) -> CredentialSnapshot | None`,
`change_password(expected: CredentialSnapshot, hashed: str, keep: str | None) -> bool`, and
`change_email(expected: CredentialSnapshot, email: str) -> bool`.

- [x] Write `test_reset_lifetimes_and_resend`, asserting 1 hour versus 7 days, public siblings usable, administrator replacement, completion consumes every sibling.
- [x] Write `test_administrator_cannot_issue_for_disabled_user`, asserting refusal before insertion and after an issuance race; Task 4 maps the typed error to stable 409. Keep owner/check and completion state/revision checks identical.
- [x] Write `test_reset_refuses_disabled_deleted_changed_and_replayed_proofs`, including email away/back and disable/re-enable, cross-User and Invitation tokens; no unintended mutation.
- [x] Write `test_reset_tokens_are_hashed_and_secret_values_never_logged`, inspect persisted proofs/counters and captured logs, and assert only hashes/digests persist and no token/password/address/exception marker leaks.
- [x] Write `test_reset_checks_expiry_after_hash_and_lock_wait` with a controllable clock; exact expiry refuses without changing password, links, or sessions.
- [x] Write `test_reset_and_sign_in_serialize_sessions`: old-credential session start loses; a session started with the new credential after commit remains live.
- [x] Write `test_stale_own_password_and_email_changes_lose_to_reset`; pause confirmation/hashing, commit reset, resume stale write, assert reset credential and email remain authoritative.
- [x] Add shared fake/SQLite contract cases in `tests/contracts/persistence.py` for atomic failure, sibling consumption, current-state binding, isolation, and session deletion.
- [x] Run focused tests and observe failures. Implement `users.credential_revision INTEGER NOT NULL DEFAULT 0` and nullable link revision, revoke legacy NULL-bound links, issuance, atomic completion and credential compare-and-set. Under the same lock check active User/revision/expiry, update password/revision, invalidate all resets, delete `user_sessions`; never call `sessions.end_all` after reset commit.
- [x] Wire current own-password/direct-email use cases to guarded credential changes, checking active state/revision/hash under lock and preserving initial add-email and own-password keep-session behavior. A kept session must still belong to that active User. Increment revision on disable through the existing guarded store.
- [x] Test fresh install, upgrade from 35, restart/idempotence, migration rollback on fault, legacy proof revocation, User cascade and unchanged owned data/settings. Read-only checks and GET never consume a proof.
- [x] Run `.venv/bin/pytest tests/application/test_identity.py tests/application/test_administration.py tests/adapters/test_password_reset_store.py tests/adapters/test_users_store.py tests/adapters/test_admin_sessions.py tests/adapters/test_user_isolation_schema.py`; expect pass. Review/fix, commit owned files, check `git diff --shortstat origin/main...HEAD`.

### Task 2: Admit requests through bounded and durable limits

**Files:** Create `application/identity/reset_admission.py`, `infrastructure/identity_front_gate.py`,
`infrastructure/persistence/reset_admission.py`, `tests/application/test_reset_admission.py`,
`tests/adapters/test_reset_admission.py`, `test_identity_front_gate.py`.
Modify Task 1 migration before it ships, `infrastructure/security.py`, and isolation schema tests.

**Interfaces:** `ResetAdmission.admit(email: str, network: str) -> bool`: true admits, false silently suppresses email/pair limits; typed network/global throttle and storage-unavailable errors.
`ResetAdmission.check_token(network: str, check: Callable[[], bool]) -> bool` counts invalid attempts;
`ResetAdmission.admit_completion(network: str) -> None` precedes lookup/hash.
`IdentityFrontGate.admit(network: str, boundary: str) -> None`; boundaries are request, invalid-token, completion.
`ResetAdmission.purge(before: datetime, limit: int) -> int`; `client_network(value: str) -> str`.

- [x] Write rolling-window tests for email 5/hour and 60-second cooldown, pair 2/hour, network 20/15 minutes, global 100/hour reserved for reset, invalid tokens 20/network/15 minutes, completions 10/network/15 minutes including valid tokens.
- [x] Write `test_two_networks_can_exhaust_global_reset_budget`, asserting account-independent 429 and unchanged administrator recovery. Write `test_administrator_reset_without_master_key_uses_memory_limits`, asserting valid completion and invalid-token throttling without durable HMAC storage.
- [x] Write `test_limits_survive_restart_and_concurrent_admission`, asserting the exact cap with simultaneous SQLite callers, no refund after proof success or dropped queue work.
- [x] Write `test_front_gate_denied_flood_never_writes`, `test_front_gate_capacity_refuses_without_eviction`, `test_front_gate_concurrent_capacity`, `test_ipv6_64_grouping`; cap shared live network inventory at 10,000, expire keys, keep independent boundary counters. Missing/malformed clients share one conservative unknown key.
- [x] Write lock/fault tests: 100 ms busy timeout, generic failure, no partial increments. Email/pair suppression never emits Retry-After; network/global limits are independent of User existence.
- [x] Observe failures, then implement a short `BEGIN IMMEDIATE` transaction that checks every rolling allowance and records only admitted requests. Persist `reset_request_attempts` with timestamp and HMAC email/network/pair digests, never plaintext keys or account outcomes; completion/invalid entries carry only their boundary/network digest.
- [x] Derive a distinct HMAC key from Master Key with purpose/category framing. No per-request random salt or config fingerprint that resets counters on SMTP changes. A Master Key rotation requires the documented maintenance procedure.
- [x] Add bounded purge on identity traffic and hourly worker maintenance, batches of 500; remove expired/consumed proof records and counters within 24 hours of identity traffic, without scheduler dependence. Never remove a live allowance.
- [x] Run `.venv/bin/pytest tests/application/test_reset_admission.py tests/adapters/test_reset_admission.py tests/adapters/test_identity_front_gate.py tests/adapters/test_user_isolation_schema.py`; expect pass. Review/fix, commit and inspect diff size.

### Task 3: Deliver from a separate reset lane

**Files:** Extend `application/identity/password_reset.py`, `infrastructure/identity_mail_worker.py`,
`infrastructure/identity_email.py`, `bootstrap/identity_email.py`, `bootstrap/container.py`.
Create `tests/application/test_password_reset.py`; extend worker/transport tests and synthetic fakes.

**Interfaces:** `RequestPasswordReset.execute(email: str, client: str) -> None` normalizes, admits and queues only.
`ResetEmailRequest(email, fingerprint)` hides email in repr; `ResetEmailQueue.submit_reset(request) -> bool`.
`DeliverPasswordReset.prepare(request) -> PreparedPasswordReset | None`, `send(prepared) -> None`;
`IdentityResetSender.send_reset(recipient: str, token: str) -> None` uses the configured origin.
Reset preparation and purge run off the event loop and use a 0.1-second storage lock timeout.

- [x] Write `test_request_never_looks_up_user_or_sends_mail`, using fail-on-call lookup/sender; prove queue work is equal for active, administrator, disabled and unknown addresses.
- [x] Write `test_reset_worker_rechecks_eligibility`: active current-address User only, no send for disabled/deleted/stale configuration. Issue close to send, with transaction closed before SMTP.
- [x] Write `test_reset_preparation_lock_does_not_block_event_loop`: busy preparation fails in about 100 ms, sends nothing, unrelated loop work progresses, purge also stays off the loop.
- [x] Write `test_reset_and_test_lanes_have_separate_capacity_and_fair_turns`: reset holds 50 waiting items, existing test lane 10; alternate nonempty lanes, one SMTP executor, no later sign-up lane.
- [x] Write `test_overflow_stopped_worker_and_smtp_failure_are_lossy`: no HTTP outcome change, no retry/outbox, no passwords queued, no new old-generation delivery authorization or readiness update after stop; already-authorized SMTP may finish, and short in-flight preparation may leave an unused hash-only proof for normal expiry/cleanup, safe aggregate diagnostics only.
- [x] Write `test_reset_transport_uses_current_recipient_and_configured_fragment_origin`: ignore notification preference/SMTP_RECIPIENT; verified TLS, ten-second timeout, literal security template, no event content, no caller-supplied origin.
- [x] Observe failures, implement delivery/composition and bounded cleanup, rerun `.venv/bin/pytest tests/application/test_password_reset.py tests/adapters/test_identity_mail_worker.py tests/adapters/test_identity_email_transport.py tests/adapters/test_identity_email_store.py`; expect pass. Review/fix, commit and inspect diff size.

### Task 4: Expose bounded, private HTTP recovery

**Files:** Create `interfaces/api/routes/password_reset.py`, `interfaces/api/identity_boundary.py`,
`tests/adapters/test_password_reset_api.py`. Modify `routes/setup.py`, `routes/users.py`, `schemas.py`,
`problems.py`, `app.py`, composition/dependency protocols, `AGENTS.md`, authorization tests;
regenerate `web/openapi.json` and `web/src/lib/api-schema.ts`.

**Interfaces:** Public POST `/api/v1/password-resets/request` takes `{email: str}` and returns
202 `{accepted: true}`. Existing POST `/api/v1/password-resets/check` returns existing usable shape;
POST `/api/v1/password-resets` remains 204 on completion, 410 on unusable proof.
Setup adds `password_reset_available: bool = false`, from `IdentityEmailSetup.fingerprint` only.
Reset-specific schemas leave Invitation schemas unchanged. No signed-in session is created.

- [x] Write equal-response/timing-structure tests across active/disabled/unknown/admin emails, queue full/stopped, no account lookup or SMTP in request; email suppression remains 202 without Retry-After.
- [x] Write availability tests under every shipped policy, valid/invalid/missing configuration, readiness absent, and SMTP removal after issuance. With SMTP plus HTTP LAN origin, administrator links still check/complete and availability is false. Do not apply the origin predicate to completion.
- [x] Write streamed-body tests for absent/false Content-Length and chunks: 8,192 bytes accepted, 8,193 refused before parse/storage/hash. Test email 254/255, token 128/129/non-ASCII, password 12/1,024/1,025 before DB/hash. Never log rejected bodies.
- [x] Write completion-gate tests before hashing, usable and unusable proofs, and equal safe storage errors. Keep password-bearing and invalid-token budgets distinct from sign-in.
- [x] Replace `LinkAttempts` on both reset use cases with `ResetAdmission`/front gate; Invitations keep `LinkAttempts`. Resolve `client_network()` from `request.client.host`. Test sign-in/reset independence, IPv6 /64 token budgets, the 11th valid-token completion refused before hashing, and disabled-target issuance returning stable 409 with no link row.
- [x] Write no-store/no-referrer tests covering reset pages, API success, validation, 429, 503 and unusable responses. Ordinary page GET and token check cause no credential/proof mutation.
- [x] Observe failures, implement the narrow ASGI stream/header boundary and routes; only account-independent gates return 429 with Retry-After or generic 503. No public queue depth or worker status.
- [x] Extend public-route authorization list and verify bearer Integration Token alone grants no reset authority. Run `.venv/bin/pytest tests/adapters/test_password_reset_api.py tests/adapters/test_api_authorization.py tests/adapters/test_users_api.py tests/adapters/test_identity_api.py`; expect pass.
- [x] Run `.venv/bin/python scripts/export_openapi.py`, then `pnpm run api:types` and `pnpm run build` inside web. Review/fix and commit route/schema/generated files and substantive bundle together; inspect diff size.

### Task 5: Make recovery reachable from sign-in

**Files:** Create `web/src/features/forgot-password-page.tsx` and its test; modify `web/src/app.tsx`,
`features/auth-screen.tsx` and test, `features/password-reset-page.tsx` and test,
`components/new-password-fields.tsx`, `lib/api.ts`, `i18n/locales/en/auth.json`, `common.json`.
Update `lib/use-link-check.ts` only if needed for safe check cleanup; keep existing fragment race tests.

**Interfaces:** `api.requestPasswordReset(email: string)` uses generated route/body types.
`AuthScreen.passwordResetAvailable?: boolean`; `ForgotPasswordPage` is routed at `/forgot-password`
before the session gate, without adding it to the token-only `PublicPage`/CHECKS mapping.
`NewPasswordFields.maxLength?: number` is 1,024 only for reset callers.

- [x] Write tests for login-only entry when configured, email-only request/exact body, generic sent state, retry through same form, translated 429/503 with input preserved, direct unavailable page, safe sign-in escape.
- [x] Write tests for neutral completion copy for both link kinds, expired-link recovery when available, 1,024/1,025 password bounds, fragment removal and new-fragment races, no automatic sign-in, no local/session storage of proof tokens.
- [x] Observe failures, implement with AuthFrame and existing primitives under DESIGN.md. Keep one primary action, no account-status copy or promise of delivery. Unavailable recovery still explains administrator-issued fallback.
- [x] Run `pnpm run test`, `typecheck`, `lint`, `doctor`, `knip`, and `build` in web, checking each exit code. Review/fix and commit source/catalog/substantive bundle together; inspect diff size.
- [x] Check port 8001 is free; capture before screens with `scripts/dev_preview.py --scenario healthy`. Use a `.context/` synthetic adapter harness for configured recovery and captured synthetic mail, with no real SMTP/environment. Capture after states for sign-in/request/sent/usable/expired at 1440 and 390 px, light/dark, keyboard alone. Save screenshots in `.context/`; verify focus, labels, announcements, Enter, overflow and safe retry.

### Task 6: Proxy deployment, docs, security and release verification

**Files:** Modify `Dockerfile`, `docker-compose.yml`, `.env.example`, `interfaces/api/app.py`,
`README.md`, `CONTEXT.md`, `docs/architecture.md`, `development.md`, `deployment.md`,
`self-hosting.md`, `data-ownership.md`, ADR 0040 shipped-status notes and this plan's delivery record.
Create `tests/adapters/test_identity_proxy_limits.py`; amend deployment/config tests as needed.

- [x] Write tests using Uvicorn `ProxyHeadersMiddleware` around the app: untrusted XFF ignored, exact trusted proxy resolves two separate clients, same IPv6 /64 shares allowance, another /64 has its own. Forged Host/forwarded headers never set mail origin.
- [x] Observe failures, set deliberate proxy headers in CLI and `run()`, empty default trust, Compose `FORWARDED_ALLOW_IPS: "${FORWARDED_ALLOW_IPS:-}"`. Document direct use with empty trust and reverse proxy with exact IP/network allowlist, never `*`; overwrite forwarded headers at proxy, prevent direct bypass, preserve Authorization and secure cookies.
- [x] Correct deployment's claim that all proxy clients necessarily share a limit. Test empty trust against installed Uvicorn 0.54.0 (project range `>=0.34,<1`) and explain Docker NAT may expose only one gateway address. Document HTTPS emailed links, both lifetimes, generic responses, retry/loss, targeted/global-cap fallback, existing-email trust risk, retention and no telemetry. Keep later slices marked unshipped.
- [x] Document stopped-service backup before migration and matching database/image restore for rollback, lost post-backup writes, legacy reset reissue, Master Key rotation effects on counters. No manual down migration or old binary against upgraded schema.
- [x] Run each backend gate separately: `.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`, `.venv/bin/mypy`, `.venv/bin/lint-imports`, `.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80`. Check real exits, including Markdown Python formatting.
- [x] Run each frontend gate separately: `pnpm audit --audit-level=high`, `pnpm run api:check`, `typecheck`, `lint`, `knip`, `doctor`, `test`, `build`. There is no package `audit` script; use the actual pnpm audit command. Never commit a SHA-only rebuild.
- [ ] Run gitleaks 8.30.1 on history (`gitleaks git .`) and branch (`gitleaks git . --log-opts=origin/main..HEAD`), then `docker compose build`; report any blocker explicitly.
- [x] Run auth security review covering response/timing enumeration, deferred lookup, hashed single-use tokens, exact expiry, revision/ABA, ownership, throttle bypass/restart, session races, logging, headers, proxy spoofing and queue loss. Run whole-branch independent review and one test-first fix wave, with ledger evidence.
- [x] Obtain read-only Claude review of `git diff origin/main...HEAD` excluding `src/calendar_sync/interfaces/api/static`, `web/openapi.json`, `web/src/lib/api-schema.ts`. Fix every P1/P2 test-first; rerun affected and final required gates. A missing outside review remains a blocker, never reported as approval.
- [ ] Use the ship skill and `.github/PULL_REQUEST_TEMPLATE.md`, stage only owned files, include before/after screenshots, push/open against main and watch CI. Follow each verified review comment with a test-first fix and a reply naming its commit. Do not start PR 3 before this merges and its own plan is approved.

## Plan self-review

All PR 2 requirements map to Tasks 1-6. Review Focus cases have named tests. Interfaces use the
same shared reset completion and configured predicate. No future tables/screens or Plan Hold
changes are planned. Security review, outside review, local gates and live UI evidence are complete,
with accepted implementation adjustments recorded above and in the ledger. Task 6 image-build and PR/CI delivery
items remain open; secret scans already pass. The owner authorized continued execution.
