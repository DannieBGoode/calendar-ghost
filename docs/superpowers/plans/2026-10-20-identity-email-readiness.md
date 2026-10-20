# Identity email and test readiness implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Each task gets a fresh implementer, reviewer, and fix loop, then a whole-branch review and one fix wave. Record the run in `.superpowers/sdd/` and preserve `resumeFromRunId` if limited.

**Goal:** Let an Installation Administrator test secure identity email and see whether the current configuration passed, while Open remains unavailable.

**Architecture:** Identity and Access owns the use cases and narrow ports. Separate SMTP, SQLite, and bounded-worker adapters keep security messages outside notification preferences and scheduling. Bootstrap composes them; the API lifespan owns the worker.

**Tech Stack:** Python 3.12, FastAPI, SQLite, cryptography, React, TanStack Query, existing shadcn-style components, Node.js 22+, pnpm 12.

**Spec:** [Approved open-registration design](../specs/2026-10-20-open-registration-design.md), delivery slice 1 only. Status: approved for implementation on 2026-10-20 by the owner's "continue" instruction.

## Global constraints

- Only Me remains the default; keep exactly `only_me` and `invitation_only` in domain, database, API, and UI. No new public auth routes, proof tables, Plans/billing changes, or new dependencies.
- Use HTTPS root origins; permit HTTP only for localhost or literal loopback development. Reject user information, paths except `/`, query, fragment, invalid ports, and non-HTTP schemes.
- Remote identity SMTP requires certificate-verified STARTTLS with `ssl.create_default_context()` and a 10-second socket timeout. Cleartext is allowed only for localhost/literal loopback relay; never infer this by DNS.
- Test requests: 3 per administrator per rolling hour. One worker, one sending thread, capacity 10 waiting requests, no retry, no passwords in queued work, no persistent mail outbox.
- SQLite connections come only from `connections.py`; new identity writes use timeout `0.1` seconds. SMTP never runs under a database transaction or on the event loop.
- Security mail ignores Email notifications and SMTP_RECIPIENT. Keep existing notification transport/preferences/workers untouched, including `notifications.py` and `scheduling.py`.
- Keep Plan Hold implementation and dedicated files untouched. Shared bootstrap/app edits only wire identity email; preserve existing services and unrelated work. Keep this branch name.
- UI text uses `t()`, values use `i18n.format`, plural numbers use `count`. No em dashes or linter/doctor/knip exceptions. Rebuild and include the compiled bundle with each web commit.
- Every commit has a sentence-case user-facing summary and truthful `Co-Authored-By: Codex <noreply@openai.com>`. Check `git diff --shortstat origin/main...HEAD` after every commit.

## Review focus

- A slow SMTP send must not stall API requests, scheduling, shutdown, or a later application lifespan: Task 3 blocked-sender tests.
- Returning to setup during a send must leave readiness cleared after the old send finishes: Tasks 2 and 3 generation tests.
- An administrator changing or losing their email/role while queued must not send to a stale chosen address or establish readiness: Tasks 2 and 3 dispatch/completion checks.
- A test accepted by SMTP but not committed in SQLite must never appear successful: Tasks 2 and 3 storage-fault tests.
- UI must distinguish enqueue from SMTP acceptance, and a configuration change must remove old success: Task 4 polling/configuration tests.

## File map and settled recommendations

- New application module `src/calendar_sync/application/identity/identity_email.py`: values, narrow ports, safe errors, readiness/request/delivery services. Split to sibling `identity_email_ports.py` only if complexity/length needs it; do not modify shared UOWs.
- New adapters: `infrastructure/identity_email.py` (configuration/origin/fingerprint/SMTP), `infrastructure/identity_mail_worker.py` (queue/executor/lifecycle), `infrastructure/persistence/identity_email.py` (readiness and admitted test counts).
- New route `interfaces/api/routes/identity_email.py`; schemas stay in `interfaces/api/schemas.py`; wiring stays in `bootstrap/container.py` and `interfaces/api/app.py`.
- New web component `web/src/features/settings-identity-email.tsx`, hook `web/src/lib/use-identity-email.ts`, and focused component test; mount in `features/settings.tsx` beside Who can join.
- Test files are named in the tasks. Existing contracts in `tests/contracts/persistence.py` stay unchanged because neither UOW nor its persistence ports changes. New focused fake/SQLite contracts cover the new identity port.
- Identity readiness requires a valid Installation Master Key, even if no calendar is connected. Do not create a temporary signing key. Missing key gives an actionable configuration reason; this PR changes no email-change or reset behavior.
- Readiness proves the transport/origin configuration, not an administrator's continuing identity. Later email/role changes need not revoke a historical successful configuration test. Recheck eligibility/recipient for each new send and before recording its result; do not add per-User revision columns.
- A persisted installation generation prevents return-to-setup races. The current configuration fingerprint includes all effective SMTP fields and the normalized origin, excluding recipient/preferences/webhook. A→B→A may reuse a prior matching success unless setup reset intervened; do not promise historical configuration revocation.
- Keep pending/failure status per administrator in bounded process memory. Readiness/time is durable and installation-wide. Later transient failures do not erase an earlier valid success; show the latest attempt separately.
- Admission consumes the hourly allowance before enqueue. Queue rejection, SMTP failure, or shutdown does not refund it. Repeated pending requests are rejected before admission; race losers may still consume an attempt.

### Task 1: Secure identity configuration and SMTP transport

**Files:** create `src/calendar_sync/infrastructure/identity_email.py`, `bootstrap/identity_email.py`, `tests/adapters/test_identity_email_transport.py`, `tests/identity_smtp_server.py`; modify `infrastructure/security.py`; create the application values/ports in `application/identity/identity_email.py`.

**Interfaces:**
- `IdentityEmailSetup(fingerprint: str | None, reason: IdentityEmailReason | None)` is nonsecret; reason values: `smtp_missing`, `smtp_security`, `origin_missing`, `origin_invalid`, `origin_insecure`, `master_key_missing`.
- `identity_origin(value: str) -> str | None`; frozen `IdentitySmtp(host, port, sender, username, password, use_starttls, origin)` hides secrets in repr.
- `identity_setup(settings: Settings) -> IdentityEmailSetup` lives in new `bootstrap/identity_email.py`, never in application/infrastructure importing Settings.
- In `infrastructure/security.py`, `identity_email_fingerprint(master_key: str, values: tuple[str, int, str, str, str, bool, str]) -> str`; values are effective host/port/sender/username/password/STARTTLS/origin in that order.
- `IdentityTestSender.send_test(recipient: str) -> None` is the application port; `IdentitySmtp` implements it and raises only safe `IdentityEmailDeliveryFailed` for delivery failure.

- [ ] Write `test_identity_origin_requires_a_safe_root` with valid HTTPS/default ports/trailing slash, loopback IPv4/IPv6/localhost HTTP, HTTP LAN refusal, userinfo, malformed port, path/query/fragment, whitespace/control characters, and deceptive localhost suffix cases. Expect normalized safe origin or None.
- [ ] Write `test_identity_configuration_requires_key_smtp_and_origin`: missing SMTP, remote cleartext, HTTP LAN, and missing key each give the exact reason and no fingerprint; valid settings give a digest. Invalid nonempty Master Key keeps existing bootstrap validation failure, never a usable state.
- [ ] Write `test_identity_fingerprint_tracks_effective_configuration`: every tuple field and Master Key change invalidates; sender preference/SMTP_RECIPIENT do not; equivalent normalized origins match; digest has no credential text.
- [ ] Write `test_identity_smtp_verifies_tls` parameterized for trusted CA, unknown CA, hostname mismatch, and STARTTLS refusal, using a local synthetic SMTP server and ephemeral cryptography-generated CA/server certificates. Success sends exactly one literal test message; failures send none. No real SMTP/account or committed private key.
- [ ] Add `test_cleartext_identity_mail_requires_loopback`, `test_test_mail_contains_only_literal_copy_and_configured_origin`, and `test_delivery_failure_exposes_no_provider_detail`. Assert timeout=10, no source/event data, no SMTP_RECIPIENT, no logging of recipient/password/body, and Email notifications off does not suppress this transport.
- [ ] Run `.venv/bin/pytest tests/adapters/test_identity_email_transport.py -q` and verify the intended failures before implementation.
- [ ] Implement purpose-separated HKDF-SHA256 (`b"calendar-sync identity email readiness v1"`), canonical versioned JSON tuple framing, and HMAC-SHA256. Keep the public fingerprint helper beside the existing master-key decoding in `security.py`; no infrastructure-private import across modules.
- [ ] Implement the dedicated verified transport, leaving existing notification helpers unchanged. Subject: `Calendar Ghost: test email`. Body: `Calendar Ghost can send identity email with the current settings.\n\nOpen Calendar Ghost: {origin}\n\nThis test does not change who can join.` No token or password.
- [ ] Run transport tests plus `tests/adapters/test_notifications.py`; confirm both pass. Commit only Task 1 files after reviewer/fix loop.

### Task 2: Persist test readiness and atomic allowance

**Files:** create `src/calendar_sync/infrastructure/persistence/0035_identity_email.sql`, `infrastructure/persistence/identity_email.py`, `tests/adapters/test_identity_email_store.py`, `tests/identity_email_fakes.py`; modify `persistence/migrations.py`, `persistence/registration.py`, `tests/adapters/test_user_isolation_schema.py`, and extend the application module.

**Number allocation:** freshly fetched origin/main ends at migration 0034/ADR 0039. Recheck immediately before creating the migration; if occupied, rename this planned migration and tests to the next free number. ADR 0040 is already the approved phase decision; do not allocate another ADR for this slice.

**Schema and interfaces:**
- `identity_email_readiness`: singleton INTEGER PRIMARY KEY CHECK(singleton=1), fingerprint TEXT nullable, tested_at TEXT nullable, generation INTEGER NOT NULL DEFAULT 0 CHECK(generation>=0); fingerprint/time are both present or both null. Seed one empty row. This is an installation setting, add only this table to INSTALLATION_TABLES with its reason.
- `identity_email_test_attempts`: id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, admitted_at TEXT NOT NULL; index(user_id, admitted_at). No recipient, password, config, job outcome, or message body.
- `EmailTest(id: str, actor: UserId, generation: int, fingerprint: str)` and `PreparedEmailTest(test: EmailTest, recipient: str)`; recipient is repr-hidden and memory-only.
- Narrow `IdentityEmailTests`: `tested_at(fingerprint: str) -> datetime | None`, `admit(actor: UserId, fingerprint: str, at: datetime) -> EmailTest`, `record_success(test: EmailTest, recipient: str, at: datetime) -> bool`, `purge(before: datetime, limit: int) -> None`.
- `SqliteIdentityEmailTests(database: Path, ids: IdGenerator)` implements these. `admit` atomically checks active administrator/current non-null email, counts admitted_at > now-1h including future timestamps, refuses attempt four with `IdentityEmailTestThrottled(retry_after: int)`, inserts, and captures current generation.
- `record_success` requires matching existing attempt/actor, active administrator, current email equal to recipient, and unchanged generation; success writes fingerprint/time. No actor eligibility revision or User schema change.
- `return_to_setup(at)` clears fingerprint/time and increments generation in its existing transaction. A refused setup reset changes neither readiness nor generation. Do not delete attempt counts there.

- [ ] Write `test_identity_test_port_contract` against focused memory and SQLite fakes: no initial success; successful current fingerprint returns time; another fingerprint returns None; ordinary/disabled/missing/email-less actors cannot admit or record success.
- [ ] Write `test_test_allowance_is_atomic_and_persists_restart`: three concurrent requests succeed, fourth fails, another administrator retains their own allowance, reopening the adapter preserves limits, and exactly one hour after the oldest admission frees its slot.
- [ ] Write `test_attempts_are_not_refunded_by_failed_delivery_or_setup_reset` and `test_clock_rollback_does_not_refund_future_attempts`.
- [ ] Write `test_setup_reset_rejects_inflight_success`, `test_refused_setup_reset_preserves_readiness`, and `test_record_success_rechecks_recipient_role_state_and_attempt`. Use blocked-send/transaction interleavings; stale generation, deletion, changed email, demotion, and disable all refuse success.
- [ ] Write `test_identity_store_fails_closed_on_lock_and_storage_fault` using a held SQLite writer and timeout=0.1; no attempt/readiness mutation on refusal. Test read faults are not displayed as usable/untested success.
- [ ] Write `test_identity_email_migration_fresh_upgrade_and_restart`, `test_identity_email_migration_rolls_back_on_fault`, `test_identity_email_schema_constraints_and_user_cascade`, and `test_identity_attempt_purge_is_bounded`: assert clean install/v34 upgrade/idempotency, atomic rollback, FK/paired-field constraints, cascade/no secret or recipient columns, and purge at most the requested limit before cutoff. Use existing migration helpers, no hand-edited migration ledger.
- [ ] Run new store tests plus `tests/adapters/test_users_store.py` and `test_user_isolation_schema.py` to observe failures; implement the narrow adapter/migration and setup-reset hook; rerun to pass. Commit after reviewer/fix loop.

### Task 3: Live use cases, bounded worker, API, and lifecycle

**Files:** extend `application/identity/identity_email.py`; create `infrastructure/identity_mail_worker.py`, `interfaces/api/routes/identity_email.py`, `tests/application/test_identity_email.py`, `tests/adapters/test_identity_mail_worker.py`, `tests/adapters/test_identity_email_api.py`; modify `bootstrap/container.py`, `interfaces/api/app.py`, `schemas.py`, `problems.py`, and `tests/adapters/test_api_authorization.py`.

**Interfaces and HTTP:**
- `ShowIdentityEmail.execute(actor: UserId) -> IdentityEmailStatus`; `RequestIdentityEmailTest.execute(actor: UserId) -> None`. Both recheck active administrator through UserDirectory. New errors: `IdentityEmailNotConfigured`, `IdentityEmailTestThrottled`, `IdentityEmailQueueBusy`, `IdentityEmailStorageUnavailable`; map to safe 503/429 problems, Retry-After only for throttling.
- `IdentityEmailQueue.submit(test: EmailTest) -> bool`, `state(actor: UserId) -> EmailTestState`; state values `idle`, `queued`, `sending`, `accepted`, `failed`. Queue refuses duplicate pending actors/full capacity; request counts before submit, never promises SMTP success.
- `DeliverIdentityEmailTest.prepare(test: EmailTest) -> PreparedEmailTest | None`, `.send(prepared: PreparedEmailTest) -> None`, `.complete(prepared: PreparedEmailTest) -> bool`. Prepare checks current config fingerprint, actor role/state/email; send only invokes transport; complete uses atomic record_success and Clock.
- `IdentityMailWorker.run_forever() -> None` owns one single-thread executor for its lifetime. SMTP-only send runs there; completion persistence runs only after the awaited send while the worker is live. No thread may commit readiness after cancellation. Queue/status maps are bounded by 10 pending + 1 active; finished statuses expire after 15 minutes, capped at 100, without evicting pending work.
- On startup/periodic idle work (at most once per hour), purge up to 500 expired attempts per transaction until caught up, without a scheduler dependency. Stop admits no further work, clears pending items/status, cancels/awaits its loop, and does not wait for an SMTP thread already finishing. Do not start a new sender while an old send is still running on that worker instance.
- Add a cohesive identity-email adapter/service group in bootstrap rather than a list of new application constructor arguments. Adapters expose ports; Container exposes the composed service and optional identity_mail_worker; app lifespan starts/stops it independently of scheduling.
- `GET /api/v1/identity-email`, administrator session only, no-store: `{configured: bool, unavailable_reason: Reason | null, tested_at: datetime | null, test_state: State}`. Omit origin, recipient, fingerprint, credentials, and provider text.
- `POST /api/v1/identity-email/test`, administrator only, no recipient/body model, returns 202 with no body when queued; 503 unconfigured/busy/storage; 429 with Retry-After when limited. No API field can choose a recipient. Never add either endpoint to the public or Integration Token allowlist.

- [ ] Write `test_only_active_administrators_can_test_email`, `test_unconfigured_email_never_admits`, `test_test_queue_capacity_and_duplicate_actor`, `test_dispatch_rechecks_actor_and_configuration`, `test_test_mail_ignores_notification_preference`, and `test_transient_failure_preserves_previous_success`; assert each named behavior and safe errors without provider detail.
- [ ] Write worker tests: `test_enqueue_is_not_success`, `test_slow_mail_does_not_block_api_or_other_tasks`, `test_shutdown_during_send_never_records_late_success`, `test_restart_drops_pending_without_refunding_allowance`, `test_setup_reset_during_send_stays_unready`, `test_send_success_with_failed_storage_stays_unready`, `test_status_capacity_expiry_and_hourly_purge`. Use fake clocks and barriers, no real time sleeps.
- [ ] Write `test_identity_email_routes_require_administrator_session`, `test_queued_test_is_not_ready`, `test_test_recipient_cannot_be_overridden`, `test_current_config_only_and_no_store`, `test_identity_email_api_failures_are_safe`, and `test_open_remains_unavailable`; assert 401 anonymous, 403 ordinary/disabled, token refusal, 202 before delivery, readiness only after commit, current actor address, no redirect via JSON, changed config hides success, no-store, stable errors, exactly two policies, and open refusal.
- [ ] Run these tests and the authorization inventory to observe failures. Implement composition/lifecycle and add both tuples to ADMINISTRATOR_ROUTES; keep PUBLIC_API_ROUTES unchanged. Extend the app's flat router inventory and typed service protocols.
- [ ] Run application/worker/API tests plus authorization, identity, users API, and dev-preview tests; verify pass, review, fix, and commit. Export OpenAPI and generate API types now with the new route/schema commit; run the web build and include only substantive bundle changes, never a SHA-only rebuild.

### Task 4: Administration UI, generated API, docs, and whole-branch gates

**Files:** create `web/src/features/settings-identity-email.tsx`, `web/src/lib/use-identity-email.ts`, `web/src/features/settings-identity-email.test.tsx`; modify `features/settings.tsx`, `features/settings-administration.test.tsx`, `lib/api.ts`, `i18n/locales/en/settings.json`, `i18n/locales/en/common.json`; use the Task 3 generated `web/openapi.json` / `web/src/lib/api-schema.ts`, and regenerate compiled static assets. Regenerate API artifacts again only if the schema changes. Update `docs/deployment.md`, `docs/self-hosting.md`, `docs/architecture.md`, `CONTEXT.md`, and README only for this slice's actual email test behavior. Do not describe Open/reset/email-change as shipped.

**Interfaces and copy:**
- `api.identityEmail()` calls GET path above; `api.testIdentityEmail()` calls POST path above; infer all types from generated schema. `useIdentityEmail()` owns query key `["identity-email"]` and the mutation. Poll every 1 second only while queued/sending, stop polling on idle/accepted/failed/unmount; invalidate immediately after 202.
- `IdentityEmailSection()` has a live import in AdministrationTab, adjacent to Who can join. Use existing section/button/skeleton/error styles. No email input and no new policy option.
- Catalog prefix `settings.identityEmail.*`; use literal maps for reason/state keys. Heading `Identity email`; action `Send test email`; pending `Sending test email…`; accepted `The mail server accepted the test email. Check your inbox.` Failure `The test email could not be sent. Check the email settings and try again.`
- Give distinct actionable hints for missing SMTP, invalid remote TLS, missing/invalid/insecure origin, and missing Master Key. A prior durable tested_at is shown separately from latest actor attempt failure; format it through i18n.format. No inbox-delivery claim.

- [ ] Write `test_identity_email_states_and_polling` with absent/invalid config, idle, queued/sending, SMTP accepted, failure, changed configuration, GET fault/retry, mutation failure, and unmount. Assert button disabled while unusable/pending; 202 never renders acceptance; current success time disappears on mismatch.
- [ ] Extend integrated administration tests: non-admin mounts neither component nor query, exactly two registration choices remain, current actor cannot choose a recipient, status announcements work, raw keys/placeholders never render. Add safe default GET mock to existing test server.
- [ ] Run the focused Vitest tests to observe failures. Use Task 3 generated API types. Implement typed methods, hook, component, catalogs, and mount; rerun focused tests to pass.
- [ ] Document verified identity SMTP versus unchanged incident email, HTTPS/loopback origin rules, Master Key prerequisite, successful SMTP acceptance versus inbox delivery, configuration-bound test status, 3/hour cap and lossy bounded worker. Name Identity Email Readiness in CONTEXT.md. Document additive migration, stopped-service backup before upgrade, conservative restore of matching pre-upgrade backup/image for rollback; a later upgrade begins with no restored readiness.
- [ ] Rebuild via `pnpm run build` in web and stage source/generated schema/bundle together. Never commit a bundle whose only change is build SHA. Run reviewer/fix loop before commit.
- [ ] Check port 8001 is free, run `.venv/bin/python scripts/dev_preview.py --scenario healthy --port 8001`; use preview@preview.test / previewpreview. Never load real SMTP into preview. Verify absent state at 1440 and 390 px, light/dark, keyboard. For pending/accepted/failure visuals, use a temporary fake adapter in .context with synthetic SMTP and no external mail; do not change preview's safe defaults. Save screenshots in .context.
- [ ] Run all backend gates separately, inspecting each real exit: `.venv/bin/ruff format --check .`; `.venv/bin/ruff check .`; `.venv/bin/mypy`; `.venv/bin/lint-imports`; `.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80`.
- [ ] Run separately inside web: `pnpm audit --audit-level=high`; `pnpm run api:check`; `pnpm run typecheck`; `pnpm run lint`; `pnpm run doctor`; `pnpm run knip`; `pnpm run test`; `pnpm run build`. No site change, so site gates are out of scope.
- [ ] Run `gitleaks git .` with 8.30.1 and `docker compose build`; record blockers, never silently skip. Run auth/email security review and final branch review/fix wave. Full gates follow any fixes that affect them.
- [ ] Obtain read-only Claude review, excluding compiled static/OpenAPI generated files from `git diff origin/main...HEAD`; fix P1/P2 test-first. If quota still blocks it, report the blocker and do not claim outside approval or open the PR as reviewed.
- [ ] Follow the ship skill and `.github/PULL_REQUEST_TEMPLATE.md`, stage only owned files, commit/push/open the small PR against main and watch CI. Verify Conductor remains on this PR branch. Investigate/fix/reply to each review thread with its fixing commit.

## Coverage and handoff

PR 1 covers secure test transport, trusted-origin validation, persisted matching readiness, explicit test admission, worker lifecycle, admin API/UI, and return-to-setup invalidation. Registration, reset/email-change proofs, public abuse limits, backup tools, and Open activation remain in PRs 2-8, as the approved spec orders. Code-map/coverage notes are in `.context/reviews/open-registration-pr1-coverage.md`.

Plan self-review: all five Review Focus cases have named tests; port/value names match across tasks; no bodies are copied; no future-use tables or screens; task-level tests and commits are explicit. The revised whole design's second Claude review is still quota-blocked; this plan does not claim it passed.

The owner approved execution on 2026-10-20. Execution method is already chosen: subagent-driven, with independent implementer/reviewer loops and the ledger. Do not ask the owner to choose a method again.
