# Provider Sign-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Each task gets an implementer, a separate reviewer, and a fix loop. Keep the run ledger in `.superpowers/sdd/`; resume interrupted runs with `resumeFromRunId`.

**Goal:** Let people sign in, join, and link a sign-in identity through an administrator-enabled provider, with separate calendar consent.

**Architecture:** Pure domain decisions govern linking, admission, and the last usable method. Identity use cases coordinate maintained OIDC adapters and narrow SQLite ports. Final authorization and fresh application sessions commit together, without provider calls or hashing under the write lock.

**Tech Stack:** Python 3.12, FastAPI, SQLite, Authlib 1.9.1, joserfc, Requests, React, generated OpenAPI types.

**Spec:** `docs/superpowers/specs/2026-10-20-open-registration-design.md`, especially Google and Microsoft sign-in decisions; ADRs 0023, 0028, 0029, 0030, and 0040.

## Global Constraints

- Plan review is required before product code. This plan does not authorize execution.
- Sign-in scopes are exactly `openid email profile`. Reuse installed client IDs/secrets; calendar consent remains separate.
- Provider identities use issuer plus `sub`, never email. No service, ORM, memory adapter extension, or import-contract changes.
- New Users have Role.USER and no own Plan. Plans off gives every feature; administrators are never limited.
- Keep constructors within seven fields, no complexity suppressions or WIDE_DATACLASSES additions.
- All Web UI copy uses `t()`; formatted values use `i18n.format`; no em dashes.
- Synthetic providers and temporary SQLite only. No credentials, codes, tokens, addresses, or provider errors in logs.
- After web changes build and commit the bundle with its source; regenerate both API artifacts after schema changes.
- Stage only owned changes. Report the source diff without generated files after each commit. After the explicit 4,668-line split proposal, the owner approved continuing this plan in one larger PR.

## Map and requirement coverage

- Fetched `origin/main` at `2e6e0cac` (#133); no open PRs on 2026-10-21, so no overlapping owner to notify. Work branch: `oidc-sign-in-plan`.
- `domain/{access,registration}.py` and `application/identity/{registration,sign_in,credentials}.py` already define policy, normalization, Default Plan admission, password proof, and revision guards. Tasks 1, 2, 4 reuse these.
- `persistence/{users,credentials,registration,registration_proofs}.py` own sessions, Invitations, resets, and verified joining. Password hashes are currently required. Tasks 2 and 4 add provider-only credentials and atomic provider admission.
- Calendar OAuth in `infrastructure/{google,microsoft}/oauth.py` decodes ID tokens only for display; its states require a User and lack nonce/anonymous-browser binding. Task 3 builds a separate validated flow.
- `bootstrap/config.py` holds OAuth clients/redirects and the tenant selector; provider descriptors keep provider-specific branching inside their packages. Tasks 3 and 5 preserve that boundary.
- `auth-screen`, `sign-up-page`, `invitation-page`, `settings-own-account`, and Administration are the UI entry points. Task 6 adds provider actions, method management, and enablement.
- Tasks 1/4 cover identity, verified auto-link/password fallback, all policies, Invitations, and Default Plan. Tasks 2/6 cover passwords and last-method protection. Tasks 3/5 cover protocol security and private responses. Task 7 covers delivery evidence.

## Recommendations for owner review

1. Use `Authlib>=1.9.1,<2` for code flow and `joserfc>=1.6.8,<2` for supported JOSE validation; declare `requests>=2.32.5,<3` for its transport. Authlib's deprecated `authlib.jose` is avoided. The Requests transport preserves the restriction on `httpx` imports. Verify dependency compatibility before implementation.
2. Derive new exact callbacks from validated `CALENDAR_SYNC_PUBLIC_URL`: `/api/v1/sign-in/google/callback` and `/api/v1/sign-in/microsoft/callback`. Require HTTPS except loopback, a Master Key, and the existing client credentials. Register these additional callbacks with each provider; keep calendar callback settings unchanged.
3. Represent no password with SQL NULL, not an unknown generated password. Rebuild `users` safely; preserve every field, index, trigger, and foreign key. Set password is allowed from a live owning session when no password exists. Existing password replacement still requires its current value.
4. Existing Invitations are bearer links without recipient emails. Bind the Invitation form's normalized email and token hash into the OIDC flow; require a verified provider email equal to that email. This proves bearer possession plus email ownership, not an administrator-selected recipient. Do not redesign Invitation issuance.
5. Follow the latest explicit OIDC policy: a still-live matching Invitation can admit under Only Me or Invitation Only. Ordinary public joining remains closed there. Record this narrow exception to older blanket Only Me wording in CONTEXT and ADRs 0030/0040. Setup revokes Invitations and all pending provider flows.
6. Microsoft `email`, `preferred_username`, and `upn` are not verified-email evidence. Treat Microsoft email as unverified unless documented provider verification semantics are established. Existing identities still sign in. Unlinked people get a generic email/password link form; new people use existing verified email registration, then explicitly link from Your account. No new email-proof mechanism.
7. Keep password-confirmed email changes and User Deletion. Provider-only people first set a password, with an explicit UI next step. Do not add password removal in this PR; provider unlink still enforces the last-method rule.
8. Refuse administrator disablement if it would leave any active User with no enabled sign-in method and no password. Missing environment clients can still interrupt access; document administrator-issued password reset recovery. Disabling does not delete identity bindings.

## Review Focus

- A provider changes an email or reassigns one: existing issuer/subject ownership must never move (Task 4).
- Two tabs, a browser switch, or a User switch race a callback: no silent account switch or cross-User linking (Tasks 3/5).
- A policy, readiness, Invitation, provider switch, or credential changes during exchange: final admission fails safely (Task 4).
- Missing Microsoft email and absent passwords: useful recovery without guessing identity or weakening sensitive actions (Tasks 2/6).
- Key rotation, network stalls, and malformed JWTs: bounded work, no token-controlled fetch, no credential disclosure (Task 3).

## Shared contracts

Paths below are relative to `src/calendar_sync/` unless prefixed with `tests/`, `web/`, `docs/`, or `scripts/`.
Define these types in `domain/provider_identity.py` and `application/identity/provider_sign_in_ports.py`; group related facts rather than exceed seven fields:

- `ProviderIdentityKey(issuer: str, subject: str)`; `ProviderClaims(key, email: str | None, email_verified: bool)`; hide sensitive fields from repr.
- `ProviderAdmissionFacts(policy, operational: bool, verified_email: bool, invitation_matches: bool)`; `LinkDecision` values `existing`, `link`, `password_required`, `refuse`.
- `BrowserProof(value: str)`; `InvitationIntent(token: str, email: str)`; `BoundInvitation(token_hash: str, email: str)`; `LinkOwner(user_id: UserId, session_hash: str, revision: int)`.
- `BeginIntent(provider: str, browser: BrowserProof, invitation: InvitationIntent | None, owner: LinkOwner | None)`.
- `ProviderFlow(state_hash: str, provider: str, browser_hash: str, expires_at: datetime, context: FlowContext)`; `FlowContext(invitation: BoundInvitation | None, owner: LinkOwner | None, config_fingerprint: str)`; seal sensitive context at rest.
- `ProviderCallback(provider: str, state: str, code: str, browser: BrowserProof, owner: LinkOwner | None = None)`; `PendingLink(token: str, expires_at: datetime)`.
- `ProviderSignInResult(session: Session | None, pending: PendingLink | None)`; `AdmissionCommand(claims: ProviderClaims, flow: ProviderFlow, expected: CredentialSnapshot | None)`.
- `LinkedProviderIdentity(id: str, provider: str)`; `SignInMethods(has_password: bool, identities: tuple[LinkedProviderIdentity, ...])`.
- `ProviderAuthorization.begin(state: str, nonce: str, verifier: str) -> str`; `.exchange(code: str, nonce: str, verifier: str) -> ProviderClaims`.
- `ProviderFlows.begin(intent: BeginIntent, state: str) -> ProviderFlow`; `.consume(callback: ProviderCallback) -> ProviderFlow | None`; `.defer(flow: ProviderFlow, claims: ProviderClaims) -> PendingLink`; `.pending(browser: BrowserProof, token: str) -> PendingLink | None`.
- `ProviderAdmission.complete(command: AdmissionCommand) -> ProviderSignInResult`; `.confirm(pending: str, browser: BrowserProof, expected: CredentialSnapshot) -> Session | None`.
- `ProviderMethods.show(user_id: UserId) -> SignInMethods`; `.unlink(owner: LinkOwner, identity_id: str) -> bool`; `.set_password(owner: LinkOwner, expected: CredentialSnapshot, hashed: str) -> bool`.
- `ProviderSignInSettings.list() -> tuple[ProviderSignInSetting, ...]`; `.set_enabled(actor: UserId, provider: str, enabled: bool) -> None`; `ProviderSignInSetting(provider: str, enabled: bool, available: bool, reason: str | None)`.

### Task 1: Identity decisions

**Files:** Create `domain/provider_identity.py`, `tests/domain/test_provider_identity.py`.
**Interfaces:** Produce shared domain types plus `decide_provider_link(existing_owner: UserId | None, signed_in_user: UserId | None, matching_email_user: UserId | None, email_verified: bool) -> LinkDecision`, `may_admit_provider_user(facts: ProviderAdmissionFacts) -> bool`, and `may_remove_sign_in_method(has_password: bool, remaining_enabled: int) -> bool`.

- [x] Write decision tables: `test_identity_key_uses_issuer_and_subject`, `test_link_decision_table`, `test_provider_admission_table`, `test_last_method_table`. Assert existing identity ownership wins over changed email; cross-owner linking refuses; unverified matches require password; only verified matching Invitations admit under closed policies; Open requires verified email and operational readiness; zero remaining methods refuses.
- [x] Run `.venv/bin/pytest tests/domain/test_provider_identity.py -q`; require intended failures before implementation.
- [x] Implement only pure values/decisions, using neutral Provider Kind language and existing normalization.
- [x] Rerun that file and `tests/test_provider_neutrality.py`; require exit 0.
- [x] Reviewer checks tables against every spec rule, fix findings, commit the domain slice.

### Task 2: Password presence and safe method storage

**Files:** Create `infrastructure/persistence/<next>_provider_sign_in.sql`, `provider_methods.py`, `provider_sign_in_settings.py`, `application/identity/sign_in_methods.py`; modify `migrations.py`, `users.py`, `credentials.py` in persistence, verify the existing reset in `registration.py`, and modify identity `credentials.py`, `sign_in.py`.
**Tests:** Create `tests/adapters/test_provider_identity_schema.py`, `test_provider_methods.py`, `tests/application/test_sign_in_methods.py`; extend existing credential/reset/email-change and `test_user_isolation_schema.py` tests.
**Interfaces:** Produce `ProviderMethods`, `ProviderSignInSettings`, nullable `CredentialSnapshot.password_hash`, and `SetOwnPassword.execute(user_id: UserId, new: str, session: str) -> None`.

- [x] Test migration from 38 preserves every User field, session, Plan, trigger/index and foreign key; new provider settings default off. Test `test_set_first_password_requires_live_owner`, `test_passwordless_sign_in_uses_decoy`, `test_reset_sets_first_password`, `test_concurrent_last_method_removal`, and `test_disable_provider_cannot_strand_user`.
- [x] Run those focused files and existing credential/reset tests; record intended failures.
- [x] Fetch origin immediately before allocating the next migration (currently 39, not reserved). Rebuild `users` with nullable password; preserve NULL on reads and use `IS ?` in guarded comparisons. Keep current password hashing limits; first-password input is 12 to 256 characters, confirmation at most 1,024.
- [x] Add `provider_identities(id, user_id, provider, issuer, subject, created_at)` with unique `(issuer, subject)`, unique `(id, user_id)`, and cascading User ownership. Store administrator enablement per provider. Method writes recheck owner session/revision, active state, usable remaining methods, and advance revision while invalidating other sessions and pending credential work. Keep current session; reset still ends all sessions. No memory.py changes.
- [x] Run focused tests plus schema isolation and architecture checks, review/fix, then commit. Document backup/image rollback in `docs/deployment.md` with this migration; no down migration or old binary against upgraded data.

### Task 3: Validated, browser-bound provider protocol

**Files:** Create `application/identity/provider_sign_in_ports.py`, `infrastructure/oidc.py`, `infrastructure/{google,microsoft}/oidc.py`, `infrastructure/persistence/provider_flows.py`, `provider_sign_in_limits.py`; modify `pyproject.toml` and the same new migration.
**Tests:** Create `tests/adapters/test_provider_flows.py`, `tests/adapters/test_provider_sign_in_limits.py`, `tests/adapters/google/test_oidc.py`, `tests/adapters/microsoft/test_oidc.py`, and synthetic `tests/fakes/oidc.py`.
**Interfaces:** Produce shared flow DTOs, `ProviderAuthorization`, `ProviderFlows`; `consume` claims a flow once before exchange. Actual claim validation remains in adapters.

- [x] Test `test_flow_binding_table` across browser/provider/purpose/owner, expiry, replay and cancellation; `test_jwt_rejection_table` covers signature, algorithm, issuer, audience/azp, subject, nonce, expiry, future iat/nbf and malformed/oversized claims. Test `test_tenant_and_signing_key_issuer`, `test_unverified_email_never_becomes_verified`, `test_jwks_rotation_and_fetch_bounds`, `test_denied_flood_does_not_write`.
- [x] Run these tests against signed synthetic JWTs and an injected fake HTTP transport; require intended failures, no live endpoints.
- [x] Add the recommended dependencies. Use S256 PKCE, fresh 32-byte state/browser proof, purpose-separated HMAC-derived nonce/verifier, and ten-minute flows. Pending password links use fresh random 32-byte tokens in a dedicated HttpOnly cookie, storing only hashes and binding to the browser; replacing one invalidates its previous token. Store only bearer hashes plus sealed context; bind configuration fingerprint including client/tenant/redirect. Restrict RS256; require exact validated issuer, client audience/azp, nonce, nonempty sub, exp and iat; allow 60 seconds clock skew.
- [x] Provider packages supply fixed trusted endpoints: discovery at `https://accounts.google.com/.well-known/openid-configuration` and `https://login.microsoftonline.com/{configured-tenant}/v2.0/.well-known/openid-configuration`; code exchange at `https://oauth2.googleapis.com/token` and `https://login.microsoftonline.com/{configured-tenant}/oauth2/v2.0/token`. Accept discovery JWKS only on documented provider HTTPS hosts; never follow redirects to another origin. Google canonicalizes its documented issuer variants. Microsoft validates GUID tid, configured tenant selector (including a validated DNS alias resolved to a concrete GUID issuer by trusted discovery), exact tenant-expanded issuer, and selected JWK issuer scope, including personal-account tenant rules. Email strings or tenant domains never establish verification. Use 10-second request timeouts, 1 MiB response caps, one forced JWKS refresh on unknown kid, and a one-hour bounded cache. Never fetch JWT header URLs or untrusted issuers; discard all provider tokens after translation.
- [x] Add separate anonymous flow/pending-password tables and owned link-flow tables; owned child references include `(id, user_id)`. Anonymous tables are narrow identity exceptions in schema tests. Cap 1,000 live flows; expire after ten minutes and purge in batches of 250 on identity traffic/maintenance. Add purpose-separated durable OIDC counters: begins 20/network/15 minutes and 100/installation/hour; callbacks 20/network/15 minutes; password confirmations 10/network/15 minutes. Reuse network normalization, 10,000-key front gates and 100 ms storage waits; no email-based response differences. Run tests, review/fix, commit.

### Task 4: Atomic sign-in, admission, and linking

**Files:** Create `application/identity/provider_sign_in.py`, `provider_links.py`, `infrastructure/persistence/provider_admission.py`; modify provider flow/method adapters and registration cleanup integration.
**Tests:** Create `tests/application/test_provider_sign_in.py`, `tests/adapters/test_provider_admission.py`.
**Interfaces:** Produce `BeginProviderSignIn.execute(intent: BeginIntent) -> str`, `CompleteProviderSignIn.execute(callback: ProviderCallback) -> ProviderSignInResult`, `ConfirmProviderLink.execute(browser: BrowserProof, pending: str, email: str, password: str, client: str) -> Session`, and `ProviderAdmission`.

- [x] Write `test_existing_identity_ignores_changed_email`, `test_verified_email_auto_links_only_active_owner`, `test_unverified_flow_is_generic_for_unknown_and_existing_email`, `test_invitation_email_and_policy_table`, `test_admission_races`, `test_password_confirmation_revision_race`, `test_wrong_password_keeps_pending_link_usable`, `test_setup_revokes_flows`, `test_provider_sign_in_rotates_session`.
- [x] Run focused files; require failures for missing behavior. Use two SQLite connections and barriers around exchange/password verification to prove races.
- [x] Load facts, call domain decisions, then save through narrow ports. For unverified unlinked identity always present the same email/password form without account lookup in the callback response. Verify submitted credentials with the existing decoy/throttle behavior, then link only that password-proven active User. Unknown/disabled/wrong-password results share status/body; offer the same verified joining and recovery links to everyone. Keep pending identity claims sealed server-side and browser-bound for ten minutes, with no admission until password proof. A wrong password leaves that proof usable; consume it only in the final link/session transaction.
- [x] Under one short write lock recheck exact identity owner, provider enablement/config, active state/revision, live linking session, current policy/readiness, Invitation hash/expiry/email binding and uniqueness. Existing identity signs in by key alone; a verified email match may auto-link; otherwise verified new User creation follows the policy table. Retain claimed flow rows through exchange using a claimed-at CAS; final admission/defer must claim the still-live row and remove browser siblings atomically. Persist a nullable browser hash on provider sessions so subsequent browser sign-ins can revoke them. Add a purpose-keyed email digest to pending records for sibling cleanup, computed before locks. Commit User/identity/Invitation consumption and new seven-day session together; revoke stale pending admissions and registration proofs for that email. Keep no own Plan. A link callback never switches the signed-in User.
- [x] Mint a fresh application session after public sign-in; never reuse the anonymous flow cookie as a session. A concurrent sign-in in another tab refuses this pending flow instead of switching Users. Owned linking/method changes keep the current session and end other sessions/proofs. Setup clears provider enablement and flows. Prove no network/hash operation runs under SQLite write lock; use 100 ms waits throughout public flow storage. Run focused tests, review/fix, commit.

### Task 5: Routes, composition, and response privacy

**Files:** Create `bootstrap/provider_sign_in.py`, `interfaces/api/oidc_schemas.py`, `routes/provider_sign_in.py`, `routes/sign_in_methods.py`, `routes/sign_in_provider_settings.py`; modify `bootstrap/{container,identity,logs}.py`, `interfaces/api/app.py`, `problems.py`, `AGENTS.md`, and the required API-error entries in `web/src/i18n/locales/en/common.json` with their rebuilt static bundle.
**Tests:** Create `tests/adapters/test_provider_sign_in_api.py`, `test_sign_in_methods_api.py`, `test_sign_in_provider_settings_api.py`; extend authorization and logging tests.
**Interfaces:** Expose the exact HTTP surface below; thin routes call one use case and translate stable problem codes. Add `SignInBrowser(previous_token: str | None, proof: str | None)` in identity ports, and optional `browser: SignInBrowser | None = None` to `Sessions.start`, `start_session`, and the `execute` methods of SignIn, SetUpInstallation, AcceptInvitation and CompleteRegistration. Keep legacy callers valid; adapter context comes only from real cookies. Session creation atomically revokes the previous cookie session, sessions/flows/pending records bearing the browser proof hash, and then creates the replacement after credential checks pass. A post-commit cancel alone is insufficient.

- [x] Test every guard with anonymous/session/administrator/Integration Token callers, cross-User method IDs as 404, stale linking sessions, forged Origin, duplicate callback parameters, provider denial, safe fixed redirects and no access-log query secrets. Require failures first.
- [x] Public: `GET /api/v1/sign-in/providers`; `POST /api/v1/sign-in/{slug}/start` with optional `{invitation_token,email}`; `GET /api/v1/sign-in/{slug}/callback`; `GET /api/v1/sign-in/pending` returns only `{password_required: bool}`; `POST /api/v1/sign-in/confirm` with `{email,password}` and dedicated pending-token plus browser-proof cookies. Availability exposes no accounts, secrets, readiness diagnostics or counts.
- [x] Session: `GET /api/v1/account/sign-in-methods`; `POST /api/v1/account/sign-in-methods/{slug}/start`; `DELETE /api/v1/account/sign-in-methods/{identity_id}`; `POST /api/v1/account/password` for first password only. Keep existing `PUT /api/v1/account/password` for replacement. Administrator: `GET /api/v1/settings/sign-in-providers`; `PUT /api/v1/settings/sign-in-providers/{slug}` with `{enabled}`. Callbacks for link intent recheck the same session themselves; Integration Tokens authorize none.
- [x] Use a host-only HttpOnly SameSite=Lax ten-minute flow cookie, Secure on HTTPS; enforce exact configured Origin on mutation POST/DELETE. Start returns `{authorization_url}` only after checks. Refuse public starts from an already signed-in browser and require the browser to remain anonymous through callback/password confirmation; linking uses the owned start route. Callback consumes state, maps failures to a fixed `/sign-in?provider_result=unavailable`, pending links to `/provider-link`, success to `/overview` or owned links to `/settings/account`. No arbitrary return URL. Apply 8 KiB bodies/query, 128 ASCII state/Invitation tokens, 4 KiB codes, 254 email and 1,024 password bounds before work. Auth responses/pages use no-store/no-referrer; redact validation inputs and callback queries from Uvicorn logs, suppress auth transport debug payloads, and document equivalent reverse-proxy log handling. OAuth query code/state is a protocol exception to fragment-only email proofs.
- [x] Compose provider-specific descriptors through neutral ports, run blocking exchange/storage in thread workers, set cookies only after safe response assembly. Export OpenAPI with `.venv/bin/python scripts/export_openapi.py`; run `pnpm run api:types` in web; test/review/fix, commit both artifacts with route changes.

### Task 6: Sign-in and account controls

**Files:** Create `web/src/components/sign-in-provider-button.tsx`, `features/provider-sign-in-options.tsx`, `provider-link-page.tsx`, `settings-sign-in-methods.tsx`, `settings-own-password.tsx`, `settings-sign-in-providers.tsx`; modify auth/sign-up/Invitation/settings/email-change sign-in pages, `app.tsx`, `lib/api.ts`, `lib/public-links.ts`, `index.css`, and English catalogs.
**Tests:** Extend corresponding feature tests; create provider-link, method-management and enablement tests. Extend `scripts/dev_preview.py` through focused synthetic provider fixtures.
**Interfaces:** Reuse AuthFrame/password fields; API calls use generated route/method types. Extract PasswordItem into the named password file without changing existing behavior. Add nullable `callback_uri` to the administrator provider-settings response from the configured validated public origin and fixed callback route; never infer it from browser origin. Prove differing browser/configured origins and regenerate both API artifacts.

- [x] Write tests for enabled-only buttons outside setup, zero-provider layout, generic pending/error states, Invitation email binding under every policy, provider-only Set password, existing-password confirmation, last-method refusal, disabled-provider recovery, toggles off by default, server failure rollback, keyboard focus and late responses after User switch. Assert no secrets enter browser storage/query caches.
- [x] Run targeted `pnpm run test -- <files>`; require expected failures.
- [x] Add local official identity marks with equal-prominence buttons reading `Sign in with Google` and `Sign in with Microsoft`; calendar marks are unsuitable. Keep all strings translated and marks local. Sign-up/Invitation options use the same flow; Only Me Invitation provider actions must not depend on password Invitation usability. Give unverified-provider newcomers the existing email verification path and a clear subsequent link action.
- [x] Your account shows Password and linked providers, Link/Remove, safe last-method explanation, and Set password first for password-confirmed email changes/deletion. Administration shows two off-by-default switches, exact callback URI/client setup guidance and actionable configuration/stranded-user refusals. No provider subject IDs or tokens in UI. Add synthetic preview states for both providers and passwordless accounts, with no public production fixture endpoints.
- [x] Run targeted tests, catalogs, typecheck/lint/doctor/knip and build; review/fix, commit source and regenerated static bundle together. Preserve source URL during rebuilds to avoid SHA-only bundle churn.

### Task 7: Documentation, reviews, and delivery

**Files:** Update `CONTEXT.md`, `README.md`, `docs/{architecture,development,deployment,self-hosting,data-ownership}.md`, ADRs 0022/0030/0040 and spec delivery status; save screenshots under `.context/` and attach to the PR. Do not allocate a new ADR unless an additional hard-to-reverse decision emerges.
**Interfaces:** All preceding tasks complete, ledger records their review/fix outcomes. No hosted backup, billing, Plan Hold activation, or provider calendar changes.

- [ ] Read spec line by line against final diff; document the separate identity-context provider descriptors required by downward context dependencies, Provider Identity, usable sign-in method, Only Me exception, passwordless sensitive-action prerequisite, Microsoft verification fallback, client-ID changes, exact callbacks, log privacy, migration/rollback, configuration loss and administrator recovery. Confirm dependency API and provider branding against sources below.
- [ ] Check port 8001 is free, start `.venv/bin/python scripts/dev_preview.py --scenario healthy`, and capture before/after at 1440 and 390 px in light/dark. Check keyboard order/focus, errors, linking, password setting, admin toggles and overflow. Use `/impeccable critique audit` for the owner's UI review workflow; fix supported findings. Keep screenshots synthetic.
- [ ] Run each gate independently, save actual exit codes: `.venv/bin/ruff format --check .`, `.venv/bin/ruff check .`, `.venv/bin/mypy`, `.venv/bin/lint-imports`, `.venv/bin/pytest --cov --cov-report=term-missing --cov-fail-under=80`; in web `pnpm audit --audit-level=high`, `pnpm run api:check`, `typecheck`, `lint`, `knip`, `doctor`, `test`, `build`. There is no `pnpm run audit` script. Run site gates only if site changes. Run gitleaks 8.30.1 on full history and branch/worktree changes, then `docker compose build`, or record the concrete blocker.
- [ ] Run a whole-branch reviewer and one fix wave plus focused OIDC security review. Obtain read-only Claude outside review with saved credentials and safe mode; exclude `src/calendar_sync/interfaces/api/static`, `web/openapi.json`, `web/src/lib/api-schema.ts` from `git diff origin/main...HEAD`. Fix every P1/P2 test-first and rerun affected gates. Record any review/tool usage limit and resume identifier; never claim a blocked review passed.
- [ ] Use sentence-case observable-change commits with truthful Co-Authored-By trailers. Read and apply ship skill for publication, honor `.github/PULL_REQUEST_TEMPLATE.md`, push this branch, create PR against main, attach screenshot evidence, and watch CI. Verify review comments, fix test-first, push, and reply on each thread with the fixing commit. Do not begin the next PR before merge and approval of its plan.

## Primary references checked for this plan

- [Authlib code flow and PKCE](https://docs.authlib.org/en/latest/oauth2/client/web/) and [package metadata/dependency versions](https://pypi.org/project/Authlib/).
- [Microsoft ID-token claims and email caveats](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference) and [tenant-independent issuer/key validation](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens).
- [Google button guidance](https://developers.google.com/identity/branding-guidelines) and [Microsoft button guidance](https://learn.microsoft.com/en-us/entra/identity-platform/howto-add-branding-in-apps).

## Plan review status

Self-review completed against the OIDC spec and three parallel read-only maps. Recommendations 4, 5, 6 and 8 settle gaps or conflicting older wording explicitly. The owner approved execution with "continue" on 2026-10-21. Execution progress and review evidence are tracked in `.superpowers/sdd/2026-10-21-provider-sign-in/`.
