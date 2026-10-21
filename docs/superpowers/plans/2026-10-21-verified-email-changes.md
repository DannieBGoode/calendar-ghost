# Verified Email Changes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a signed-in User verify a new email without losing their current sign-in access.

**Architecture:** Pure domain decisions govern proof usability and email-change mode. Narrow
identity ports use SQLite only for new records. The existing identity mail worker delivers proofs
and old-address notices; SMTP and password verification stay outside write transactions.

**Tech Stack:** Python 3.12, SQLite, FastAPI, React, TypeScript, existing identity SMTP and pnpm 12.

**Spec:** `docs/superpowers/specs/2026-10-20-open-registration-design.md`, email-change scope;
ADR 0040 and ADR 0030. Status: implementation, documentation, local gates, scans, and reviews are complete. PR [#131](https://github.com/DannieBGoode/calendar-ghost/pull/131) is open with CI running; CI verification and any review follow-up remain open.

## Global Constraints

- Verification links last 24 hours. Use 32 cryptographically random bytes and persist only hashes.
- Signed-in email-change requests: 5 per User per rolling hour, plus 60-second target-email cooldown.
- Invalid checks: 20 per client network per 15 minutes. Password submissions: 10 per network per 15 minutes.
- Network keys: IPv4 address or IPv6 /64; at most 10,000 live keys; never evict an active allowance.
- Streamed bodies: 8,192 bytes; normalized email: 254 characters; token: 128 ASCII characters; current password: 1,024 characters.
- Security changes and administrator tests share the bounded lane of 10; reset retains its separate lane of 50.
- New email-change proof and admission locks wait at most 100 ms; existing User, Session, and credential writers retain their five-second wait. Cleanup batches are at most 500; target removal within 24 hours.
- No new registration/provider tables, in-memory identity records, Plan Hold edits, complexity suppressions, or WIDE_DATACLASSES entries.
- Keep import-linter contracts unchanged and constructors within seven fields. New code uses identity-named modules.
- Do not grow `bootstrap/container.py`, `interfaces/api/schemas.py`, `persistence/sqlite.py`, or `application/sync/ports.py`.
- Every frontend module has a live caller; text uses `t()`, values use `i18n.format`, and no em dashes appear.
- Build and commit substantive static assets with every web change. Generate API files through the existing commands.

## Review Focus

- SMTP disappears while a proof is pending: confirmation still works; direct change requires explicit cancellation.
- A sign-in already checked the old address: atomic session creation must refuse it after the address changes.
- A newer request arrives during SMTP preparation: the older request cannot replace or invalidate the newer proof.
- The browser switches User or opens a newer fragment: old query and mutation results cannot alter the new view.
- The mail queue drops a notice or proof: credential commits stand, the UI never promises delivery, retry remains possible.

## Decisions for owner review

1. Use a separate email-change admission scope with the limits above. It cannot spend reset allowances.
   Reuse the front-gate implementation and network resolution, not reset request counters or its HMAC key.
2. Do not check address ownership when requesting. A proposed address reserves nothing. Check uniqueness
   only at confirmation; use neutral `email_change_unavailable` text, never another User's identity.
3. Show a pending request immediately. Store no token until worker preparation, close to sending.
   Pending requests expire after 24 hours; preparation sets the issued proof's deadline to 24 hours
   from issuance. Status reads the current deadline. Cancellation/replacement invalidates queued work by ID.
4. Treat either SMTP host or sender being present as SMTP present. Partial or unsafe configuration
   blocks ordinary direct changes. Both absent permits direct change; readiness-test success is unnecessary.
5. Keep the confirming browser's existing live session, end every other session atomically, and keep
   Integration Tokens. Old-address notice delivery is best effort after commit and never rolls back email.
6. Require the expected email and credential revision at session creation, with no optional bypass.
   Load sign-in facts together so both old-address and change-away/back races lose atomically.
7. Keep the proof in component memory while sign-in is needed on `/email-change`. Do not put it in
   query strings, browser storage, or a return URL. A refresh may require reopening the mail link.

## Code map and requirement coverage

Paths below are relative to `src/calendar_sync/` unless they start with `tests/`, `web/`, or `docs/`.

| Requirement | Current code and gap | Task |
| --- | --- | --- |
| Domain proof and revision decisions | `domain/access.py`; current CAS lives in `persistence/credentials.py` | 1 |
| Request, replacement, cancel, confirm | `SetOwnEmail` is direct; no pending records | 1, 2 |
| Atomic invalidation and ownership | `credentials.py`, `registration.py`, `users.py`; email currently keeps all sessions | 2 |
| Request throttles and retention | Reset admission/front gate exists; email-change scope does not | 2, 3 |
| Proof and old-address mail | Test/reset lanes and verified SMTP exist | 3 |
| Configuration and upgrade exception | `identity_setup`; existing PUT permits restricted upgraded first User | 1, 4 |
| API privacy and bounds | `IdentityBoundary` currently covers reset only | 4 |
| Pending and confirmation UI | `settings-own-account.tsx`, AuthFrame, CurrentPasswordField, useLinkToken | 5 |
| Documentation, gates, security, independent review | Existing repository workflows and PR template | 6 |

Read-only maps: `.context/email-backend-map.md`, `.context/email-mail-map.md`; API/UI findings are in this session.
The delivery revision is its own commit (`5a3fdc69`). No migration number is reserved.

### Task 1: Pure identity decisions and narrow interfaces

**Files:** Create `domain/email_changes.py`, `application/identity/email_changes.py`,
`application/identity/email_change_admission.py`, `tests/domain/test_email_changes.py`.
Reuse `application/identity/credentials.py` and `identity_email.py`; do not introduce sign-up abstractions.

**Interfaces:** Domain `EmailChangeMode` values `direct`, `verified`, `unavailable`;
`email_change_mode(smtp_present: bool, configured: bool, initial_email: bool) -> EmailChangeMode`.
`CredentialRevision(value: int)` exposes `next() -> CredentialRevision` and refuses negative values.
`EmailChangeProof(user_id, revision, token_hash, expires_at, used_at=None, revoked_at=None)` hides
hash in repr; `usable_by(user_id: UserId, revision: CredentialRevision, active: bool, at: datetime) -> bool`.
Hash generation remains at the security adapter boundary; the domain validates a 64-character
lowercase SHA-256 digest and never accepts a raw token as the stored proof hash.
`PendingEmailChange(id: str, email: str, expires_at: datetime)` hides email in repr.
`EmailChangeCompletion(previous_email: str)` hides its field in repr.
Define `EmailChangeProofs` beside use cases: `pending(user_id) -> PendingEmailChange | None`,
`request(expected: CredentialSnapshot, email: str, session: str) -> PendingEmailChange`,
`cancel(user_id: UserId, request_id: str) -> None`, `check(user_id: UserId, token: str) -> bool`,
`confirm(expected: CredentialSnapshot, token: str, session: str) -> EmailChangeCompletion | None`.
New errors are `EmailChangeThrottled(retry_after: int)`, `EmailChangeStorageUnavailable`,
`EmailChangeUnavailable` (neutral address collision), and `EmailChangeConfigurationRequired`
(carrying IdentityEmailReason); register stable codes in Task 4. Concrete annotations use existing `UserId`, `CredentialSnapshot`, and the new pending/completion types.
Store methods own their clock reads under the write lock; use cases never pass pre-lock expiry decisions.

- [x] Write `test_email_change_mode_decision_table`: all configuration combinations; upgraded first active administrator with no email is direct; an ordinary User gets no exception; unsafe SMTP never falls back.
- [x] Write `test_email_proof_usability_decision_table`: exact expiry refuses; used/revoked/wrong owner/stale revision/disabled refuse; valid owner succeeds.
- [x] Write `test_credential_revision_is_monotonic`: zero allowed, negative refused, next increments, away/back cannot restore an earlier revision.
- [x] Run `.venv/bin/pytest tests/domain/test_email_changes.py`; observe failure, implement the values/decisions, then expect pass.
- [x] Review/fix with a fresh reviewer, commit owned files and inspect `git diff --shortstat origin/main...HEAD`.

### Task 2: SQLite proofs, admission, and atomic credential changes

**Files:** Create `infrastructure/persistence/email_changes.py`, `email_change_admission.py`,
`tests/adapters/test_email_change_store.py`, `test_email_change_admission.py`.
Modify `persistence/credentials.py`, `registration.py`, `users.py`, `migrations.py`,
`application/identity/ports.py`, `sign_in.py`, `administration.py`, `infrastructure/security.py`;
`tests/contracts/persistence.py`, `tests/identity_fakes.py`, and relevant session/reset/schema tests.

**Interfaces:** `SqliteEmailChangeProofs(database_path, ids, clock)` implements Task 1 and
`prepare(request_id: str) -> PreparedEmailChange | None`,
`purge(before: datetime, limit: int) -> int`. Preparation rechecks the request, User and revision,
generates a token only for an unprepared current request and stores only its hash. It returns recipient/token in repr-hidden fields.
`EmailChangeAdmission.admit_request(network: str) -> None`,
`check_token(network: str, check: Callable[[], bool]) -> bool`,
`admit_completion(network: str) -> None`, `purge(before: datetime, limit: int) -> int`.
Durable User/email issuance admission and proof replacement share `request`'s transaction;
network/invalid/completion admission uses its own purpose-separated counters.
Add `SignInCredentials(user: User, credential: CredentialSnapshot)` and
`UserDirectory.sign_in_credentials(email: str | None) -> SignInCredentials | None`: one coherent
read of User, hash and revision, including the upgraded first User. Add email to CredentialSnapshot.
Change `Sessions.start(user_id: UserId, password_hash: str, email: str | None, revision: int) -> Session | None`
and `start_session(sessions, user_id, password_hash, email, revision)`; update every caller.
SignIn uses the coherent read; setup and Invitation acceptance pass revision zero for their new User.

- [x] Fetch origin, inspect migration/ADR registries, then allocate the next free `<number>_email_changes.sql`. Latest main currently ends at 36. ADR 0040 covers this decision; no new ADR is needed.
- [x] Write fresh/upgrade/idempotence/rollback tests. Add owned `email_change_proofs` and `email_change_attempts`, plus anonymous `email_change_network_attempts` under the approved isolation ruling; proofs have `id`, `user_id`, proposed email, credential revision, nullable token hash, created/expiry/use/revocation times; owned counters hold time, boundary, non-null `user_id`, and HMAC target digests; anonymous network counters hold HMAC network digests and times. Owned rows reference Users with cascade; request IDs are always scoped by User. Add indexes for owner, hash, expiry and allowance windows.
- [x] Write `test_email_change_lifecycle`: request keeps current email; preparation issues a 24-hour hash-only proof; check never consumes; replacement/cancel prevents prepare and confirm; cancelling a stale request ID leaves its replacement intact; status excludes expired, revoked and stale-revision requests.
- [x] Write `test_confirmation_checks_ownership_and_live_session_atomically`: another User, expired/deleted session, wrong password snapshot, disabled/deleted owner, used/revoked/cross-purpose proof all change nothing; success retains only the confirming session and revokes resets/sibling changes.
- [x] Write `test_email_change_uniqueness_race_is_neutral`: two Users request the same address; one confirmation wins, the other leaves its credentials/sessions intact and reveals no person. Requesting a taken address has the same response and no ownership lookup.
- [x] Write `test_email_change_reset_password_and_disable_races`: both commit orders for reset and confirmation; ordinary password change cancels proofs; email away/back and disable/re-enable never revive them; failure after proof/session mutation rolls back every change.
- [x] Write `test_email_change_expiry_is_read_after_lock_wait`: exact deadline after password verification or lock wait refuses without writes. Keep password verification and SMTP outside transactions.
- [x] Write shared session contract tests: old email/revision cannot start a session after change with the same hash, including away/back; current facts can; nullable email works only before initial add-email. Add `test_email_change_during_sign_in_refuses_old_address` and `test_email_change_aba_refuses_stale_sign_in` with paused password verification.
- [x] Write limits tests: sixth User request/hour refused, 60-second target cooldown across Users, hour boundary, concurrency and restart persistence; cancellation/success never refunds. Check 20 invalid and 10 completion attempts, independent from reset/sign-in, IPv6 /64, capacity 10,000, and rejected front-gate floods causing no SQLite writes.
- [x] Observe focused failures, implement the adapters with `connections.transaction(timeout=0.1)` and `BEGIN IMMEDIATE`. Use domain revision/proof decisions against rows loaded under lock. At confirmation recheck active state, revision, digest, expiry, uniqueness and kept session before mutation; then increment revision and invalidate atomically.
- [x] Extend existing credential/password/reset writers to revoke pending email changes in the same transaction. Direct change refuses a live pending request until explicit cancel. Add no records to `memory.py`; update existing User/session fake behavior and shared contracts, without adding new identity proof records there.
- [x] Test HMAC purpose separation, hash-only storage, User cascade, bounded purge after traffic/restart, cleanup faults preserving an already admitted operation, 100 ms lock failure, and no removal of live allowances/proofs. Retain no completed email-change history beyond cleanup.
- [x] Run `.venv/bin/pytest tests/domain/test_email_changes.py tests/adapters/test_email_change_store.py tests/adapters/test_email_change_admission.py tests/adapters/test_password_reset_store.py tests/adapters/test_users_store.py tests/adapters/test_admin_sessions.py tests/adapters/test_user_isolation_schema.py tests/application/test_identity.py`; expect pass. Review/fix, commit, inspect size.

### Task 3: Application orchestration and security mail

**Files:** Complete `application/identity/email_changes.py`, `email_change_admission.py`;
create `bootstrap/identity_email_changes.py`, `infrastructure/identity_email_changes.py`,
`tests/application/test_email_changes.py`; modify `bootstrap/identity_email.py`,
`infrastructure/identity_mail_worker.py`, `identity_email.py` and their existing tests.

**Interfaces:** `EmailChangeServices` groups `show`, `direct`, `request`, `cancel`, `check`, `confirm`.
`EmailChangeStatus(mode: EmailChangeMode, reason: IdentityEmailReason | None, pending: PendingEmailChange | None)`;
`show.execute(user_id) -> EmailChangeStatus`;
`direct.execute(user_id, email, password: str | None) -> User` guards existing SetOwnEmail;
`request.execute(user_id, email, password, session, network) -> None`;
`cancel.execute(user_id, request_id) -> None`; `check.execute(user_id, token, network) -> bool`;
`confirm.execute(user_id, token, password, session, network) -> None`.
`EmailChangeMailRequest(request_id, fingerprint)` contains no password or token;
`EmailChangedNotice(recipient)` hides recipient. Queue methods `submit_change(request) -> bool`,
`submit_notice(notice) -> bool`; delivery `prepare(request) -> PreparedEmailChange | None`,
`send(prepared) -> None`. SMTP adds `send_email_change(recipient, token)` and `send_email_changed(recipient)`.

- [x] Write `test_request_requires_current_password_and_preserves_old_email`; confirm password once on request and again on completion. Wrong passwords never create/replace proofs. Count network request attempts before verification and durable User/email admission before issuing.
- [x] Write `test_direct_mode_never_bypasses_verification`: no SMTP permits direct; partial/invalid SMTP refuses actionably; restricted first User adds email without another password under every configuration; once stored the exception ends. A pending request blocks direct fallback after SMTP removal until explicit cancel.
- [x] Write `test_worker_rechecks_current_request_and_revision`: no send after replacement, cancel, disable, password/reset change or fingerprint mismatch; stale preparation cannot overwrite the replacement. Previously issued proof still completes without SMTP/readiness.
- [x] Write `test_security_lane_is_bounded_and_fair`: ten total waiting tests/changes/notices, reset retains fifty and receives alternating turns; one SMTP executor, no retries/outbox. Preparation is off the event loop. Stop/generation guards match existing reset delivery behavior.
- [x] Write `test_old_address_notice_is_after_commit_and_lossy`: exact previous recipient, notification preference/SMTP_RECIPIENT ignored, literal content-free template, no proof token; queue exception/saturation/SMTP failure cannot roll back success or create an error response.
- [x] Write `test_email_change_mail_is_private`: configured fragment origin `/email-change#<token>`, verified TLS, ten-second timeout, no request host influence, safe aggregate logs only; no address, token, password, body or provider exception marker in logs or repr.
- [x] Observe failures, implement use cases as load/verify/decide/save calls. Add a concrete delivery/cleanup bundle as the worker's sixth constructor dependency, not individual new arguments or a general job framework. Hourly and traffic-driven maintenance purges batches of 500 even when SMTP is unavailable.
- [x] Add `email_changes` to `IdentityEmailServices` as one grouped field. Build its SQLite adapters in `build_identity_email(settings, ids, clock)`, adding Clock at its existing callsite; extend `compose_identity_email` from five to seven parameters with PasswordHasher and CredentialChanges. Only replace the existing composition call in `container.py`; keep it no larger and add no identity logic there. Keep the dependency-call edits within the original container line count; other three growing files stay untouched.
- [x] Run `.venv/bin/pytest tests/application/test_email_changes.py tests/application/test_password_reset.py tests/adapters/test_identity_mail_worker.py tests/adapters/test_identity_email_transport.py tests/adapters/test_identity_email_store.py`; expect pass. Review/fix, commit, inspect size.

### Task 4: Guarded HTTP API and generated types

**Files:** Create `interfaces/api/identity_schemas.py`, `routes/email_changes.py`,
`tests/adapters/test_email_change_api.py`; modify `routes/account.py`, `app.py`, `problems.py`,
`identity_boundary.py`, authorization tests and `AGENTS.md`. Regenerate both web API files.

**Routes:** All new routes require `current_user`, accept no Integration Token authority, and use the
owning session. GET `/api/v1/account/email-change` returns `{mode, reason, pending}`; pending is
null or `{id,email,expires_at}`. POST at that path takes `{email,password}` and returns generic
202 `{accepted:true}`. DELETE at that path takes required query `request_id` and returns 204;
ID is scoped to the owner and stale/unknown cancellation is idempotent. POST `/check` takes
`{token}` and returns `{usable:bool}`. POST `/confirm` takes `{token,password}` and returns 204.
The existing PUT `/api/v1/account/email` keeps its response and upgrade access, but calls guarded
`email_changes.direct`. Confirmation refreshes session data through the existing session endpoint.

- [x] Write route tests for session/owner/restricted-session guards, no bearer bypass, current password twice, no direct PUT bypass, generic request/collision behavior, stale cancellation and configuration modes. Keep public-route lists unchanged in scope; document explicitly that verification needs a session.
- [x] Write streamed/false Content-Length boundary tests: 8,192/8,193 bytes; 254/255 normalized email; 128/129 ASCII/non-ASCII token; 1,024/1,025 current password. Refuse before lookup/hash and never echo rejected inputs in errors. Count completion before token lookup and password verification.
- [x] Write `test_email_change_private_headers_on_every_outcome`: no-store/no-referrer on page/API including 401,403,410,422,429,503; GET/check never consume. Map unavailable proof to 410, neutral address failure to 409, bad password to 403, throttles to 429 with Retry-After, storage/configuration failures to safe 503 codes.
- [x] Observe failures, implement identity-named schemas/router/protocols, extend IdentityBoundary to this API and `/email-change`, and add typed factory wiring. Keep `schemas.py` unchanged.
- [x] Run `.venv/bin/pytest tests/adapters/test_email_change_api.py tests/adapters/test_api_authorization.py tests/adapters/test_identity_api.py tests/adapters/test_password_reset_api.py`; expect pass.
- [x] Run `.venv/bin/python scripts/export_openapi.py`; inside web run `pnpm run api:types` and `pnpm run build`. Review/fix and commit generated files and substantive bundle with the route change; inspect size.

### Task 5: Pending email and session-aware confirmation UI

**Files:** Create `web/src/features/settings-own-email.tsx`, `email-change-page.tsx` and their tests;
modify `features/settings-own-account.tsx`, its tests, `App.tsx`, `lib/api.ts`, and
`i18n/locales/en/{settings,auth,common}.json`; extend app routing tests. Keep add-email behavior.

**Interfaces:** API methods `ownEmailChange()`, `requestEmailChange(email,password)`,
`cancelEmailChange(requestId)`, `checkEmailChange(token)`, `confirmEmailChange(token,password)`
use inferred generated types. `OwnEmailItem({email})` replaces extracted EmailItem.
`EmailChangePage` is live at `/email-change`, uses `useLinkToken` and a session-scoped check,
AuthFrame and CurrentPasswordField; do not add it to the token-only public admission mapping.

- [x] Write pending tests: current email stays visible, pending email/deadline/Cancel appear, replacement and cooldown are clear, no delivery promise, direct and invalid-config modes work, password changes invalidate status, long addresses wrap, stale cancel cannot clear a newer request. Refetch on focus and after mutations; scope queries by User and keep tokens out of query keys/devtools persistence.
- [x] Write confirmation tests: signed-out person signs in inline then checks proof, owning person enters current password, wrong User sees neutral unusable state with account-switch option, expired/replaced proof offers own-account retry. Preserve token only in memory through sign-in and explain reopen-link fallback after refresh.
- [x] Write late-response tests for fragment changes and User switches: no stale status/password/error/success crosses boundaries; remove the fragment only for the current completed token; disable automatic mutation retries and clear password after submission. Success refreshes session, explains other sessions ended, and links to Your account.
- [x] Observe failures, implement using DESIGN.md disclosures, focus restoration, field errors and polite announcements. Keep one primary action and visible focus during pending work; delete unused copy and keep every new module reachable.
- [x] Run each web command with real exits: `pnpm run test`, `typecheck`, `lint`, `knip`, `doctor`, `build`; expect pass. Review/fix, commit source/catalog/substantive bundle, inspect size.
- [x] Check port 8001 is free, start `.venv/bin/python scripts/dev_preview.py --scenario healthy`; capture before/after at 1440 and 390 px in light/dark with keyboard. Use a disposable synthetic harness for configured SMTP and captured mail, not real accounts. Save `.context/` screenshots; check focus, Enter, overflow, announcements, contrast and reduced motion. Run the owner's `/impeccable critique audit` UI review before delivery.

### Task 6: Documentation, security review and delivery

**Files:** Update `CONTEXT.md`, `README.md`, `docs/architecture.md`, `development.md`, `deployment.md`,
`self-hosting.md`, `data-ownership.md`, ADR 0040 status and this plan as behavior ships.

- [x] Document Email Change Link and pending behavior, old-address recovery access until completion, configuration failure/retry, lossy proof/notice delivery, cancellation before no-SMTP fallback, retained confirming session and Integration Tokens. No claims that later Open/OIDC/backup work has shipped.
- [x] Document migration backup/upgrade and matching database/image rollback, loss of writes since backup, retention and Master Key counter effects. No down migration, old binary on new schema, secrets, or `.env` commits.
- [x] Run every backend gate separately: `.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`, `.venv/bin/mypy`, `.venv/bin/lint-imports`, `.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80`.
- [x] Inside web run separately `pnpm audit --audit-level=high`, `pnpm run api:check`, `typecheck`, `lint`, `knip`, `doctor`, `test`, `build`. There is no package audit script. Site checks apply only if site changes. Never commit a SHA-only rebuild.
- [x] Run gitleaks 8.30.1 on history and branch: `gitleaks git .` and `gitleaks git . --log-opts=origin/main..HEAD`; run `docker compose build` or report its actual blocker. Inspect each exit code, never hide failures with tail. Full history and the final 14-commit branch scan were clean; Docker exited 127 because the CLI is unavailable, so CI owns image build verification.
- [x] Review account takeover, enumeration, hash/purpose/expiry/single-use, request/confirmation throttles, old-address notice, reset/password/sign-in/session races, cancellation and queue generations. Run whole-branch review and one test-first fix wave; retain implementer/reviewer/fix evidence in `.superpowers/sdd/`.
- [x] Obtain outside read-only Claude review of `git diff origin/main...HEAD`, excluding compiled static assets, `web/openapi.json`, `web/src/lib/api-schema.ts`. Fix every P1/P2 test-first and rerun affected and required gates; unavailable outside review remains unfinished.
- [x] Use the ship skill and `.github/PULL_REQUEST_TEMPLATE.md`, push/open [PR #131](https://github.com/DannieBGoode/calendar-ghost/pull/131) against main, attach before/after screenshots, and begin watching CI.
- [ ] Follow CI to completion and address any review comments test-first, then reply with fixing commits. Do not start the next PR before merge and owner approval of its plan.

## Plan self-review

Every email-change requirement maps to Tasks 1-6. Review Focus conditions have named assertions.
No future identity tables, dormant screens, Plan Hold work or architecture-contract changes are
planned. Task reports 1-5 record implementation and focused review. The issued-proof expiry
regression was fixed in `0e5064a9`; UI critique scored the baseline 33/40 and audit 18/20, with
two P2 findings fixed in `b7775b94`. The backend gate passed 4,569 tests at 97.16% coverage;
the frontend gate passed 1,516 tests and all eight checks. The final full-history and branch scans
were clean, and the UI scoped review was approved. Docker was unavailable locally (exit 127).
PR #131 holds delivery evidence; CI is running, so its results and any review follow-up remain open.
