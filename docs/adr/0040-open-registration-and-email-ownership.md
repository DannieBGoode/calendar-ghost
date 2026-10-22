# Open registration and email ownership

Status: accepted; verified email changes, context splits, and end-to-end Open registration
implemented on 2026-10-21 under [the design](../superpowers/specs/2026-10-20-open-registration-design.md).

Delivery status on 2026-10-21: PR #129 identity email readiness and PR #130 self-service
password recovery are merged, including migrations 35 and 36. PR #131 verified email changes
(migration 37), PR #132 context splits, and PR #133 Open registration (migration 38) are merged.
Their delivery evidence remains in the corresponding implementation plans.
Only Me remains the default. Provider sign-in (migration 39) is implemented on its delivery branch
under the [approved plan](../superpowers/plans/2026-10-21-provider-sign-in.md); its whole-branch
reviews, final gates, publication, and CI remain tracked there. Hosted backup/restore and offline
recovery tooling remain planned.

Amends [ADR 0030](0030-users-administrators-and-registration.md), within the isolation boundary of
[ADR 0029](0029-isolate-users-in-one-sqlite-database.md) and the optional switches of
[ADR 0028](0028-plans-apart-from-commercial-mode.md).

## Context

The Hosted Service needs people to join without an Invitation and recover their own passwords.
For new joins under Open, an unverified address must not grant access, reserve another person's
identity, or become a recovery address without proof. Existing and Invitation Only emails remain
trusted recovery addresses under the approved compatibility policy. During a pending email change,
the old address remains the sign-in and recovery address until confirmation. Self-hosted
installations keep their current default and operate without email unless their administrator
chooses otherwise.

## Policy approved by the owner

- Only Me stays the default. Only an Installation Administrator chooses Open, after configuring
  SMTP and successfully sending a test email. Plans and Commercial Mode remain independent and
  off by default. Open never requires Plans or turns it on.
- Public registration asks for email first. A 24-hour single-use verification link opens the
  password form. A pending registration has no sign-in access. Verification precedes sign-in.
- Existing Users keep their access without retroactive verification. Invitations keep their
  7-day lifetime and remain valid under Open, but joining there requires email verification.
- Returning to Invitation Only cancels pending public sign-ups, without removing existing Users
  or Invitations. Administrators manage completed Users through People's existing disable/delete
  controls; no approval queue or pending sign-up list is added.
- Self-service password reset is offered under every Registration Policy when email is configured.
  Responses never disclose whether an email belongs to an existing, disabled, or unknown User.
  Self-service Password Reset Links last 1 hour. Administrator-issued links retain 7 days.
- Email changes require verification whenever SMTP is configured, keeping the current address
  until proof succeeds. Identity email links require HTTPS, except HTTP loopback for development.
  SMTP with an HTTP LAN origin leaves email recovery and verified email changes unavailable;
  existing email and sign-in access remain. The upgraded first User's initial add-email step
  keeps its direct restricted-session behavior without verification, preventing upgrade lockout.
- Limit sign-up and email requests per client network and per email, without a challenge provider.
- Provide a concrete continuous-backup runbook for the Hosted Service. Keep tools optional on
  self-hosted installations. No billing or mandatory hosted coordinator belongs to this phase.

## Engineering decisions accepted with the design

These decisions were presented as builder recommendations rather than individual interview choices.
They were accepted with the revised design; their complete behavior and delivery order are in it.

- Create a User only when a purpose-bound verification proof is consumed atomically. Assign Role.USER
  and no own Plan, so the existing Default Plan behavior applies. Start a normal session afterward.
  Pending Registration has no password, Plan assignment, or owned calendar records.
- Direct Invitation acceptance requires exactly Invitation Only in both use case and atomic SQLite
  write. Under Open it must use verified registration. Deliver the enum/schema, SQLite guards,
  and verified admission in one PR; do not rely on lets_people_join to authorize direct acceptance.
- Only Me cancels every pending registration proof, including Invitation-bound proofs. Reopening
  never revives cancelled proofs. Returning to setup also clears readiness and revokes Invitations.
- All active Users, including Installation Administrators, may request self-service reset. A reset
  ends sessions and other reset proofs atomically, cancels pending email changes, never re-enables
  a disabled User, and does not sign them in. Bind it to current email/password state.
- Email-change confirmation requires the owning session and current password. Security email
  ignores Email notifications. Keep token values only in URL fragments and bounded POST bodies,
  store only hashes, and never log message bodies, tokens, addresses, or credentials.
- Require certificate-verified STARTTLS for remote identity SMTP; allow a local loopback relay to
  own onward transport. Use a validated configured link origin, never request headers. Define
  identity email configuration consistently for reset, email changes, and Open. Invalid SMTP/origin
  security settings must not silently select the no-SMTP direct-email-change fallback.
- Use the operator's explicit narrow trusted-proxy allowlist for client resolution and group IPv6
  clients by /64. Keep reset/sign-up budgets and queue capacity separate. Apply bounded in-memory
  limits before writing durable, short-lived admitted counters. Per-email suppression stays generic.
  Document administrator/offline recovery when attackers exhaust a person's email allowance.
- Use bounded in-memory mail lanes and no persistent plaintext-token outbox. Never expose queue
  fullness or account-dependent worker outcomes in HTTP responses. Document the remaining aggregate
  delivery-latency risk instead of claiming constant-time SMTP privacy.
- The HTTPS origin rule governs emailed links; administrator hand-delivered resets still complete
  on HTTP LAN installations. Without a Master Key, administrator reset token/completion limits
  remain bounded in memory; self-service email recovery is unavailable. The approved global reset
  allowance can be exhausted by two networks; document this availability risk and the
  administrator-issued fallback without silently changing the limits.
- New public writers receive narrow identity ports, never InstallationUnitOfWork. Commit proof,
  policy, credential, state, Invitation, and uniqueness checks with their mutation. Keep mail and
  password hashing outside SQLite locks. Add storage only with the slice that uses it.
- Add narrow offline recovery tooling before publishing the backup runbook. Inspect restored data
  without starting the API or workers; revoke restored sessions, links, OAuth states, and
  Integration Tokens. When later authorization history cannot be established, disable Users
  except a selected administrator with a fresh password and disconnect restored calendar
  credentials, preserving mappings and existing holds. Require deliberate recovery of access.
- Test the pinned backup tool across VACUUM/checkpoint and isolated restore. Do not claim every
  Litestream compaction fails. Backup retention keeps deleted Users until expiration; a restore
  cannot treat revived records as proof that their access remains authorized.

## Consequences

The verified email-change slice keeps the old address until an owned, 24-hour proof is confirmed
with the current password. The confirming browser session and Integration Tokens remain; other
sessions end, and a best-effort notice goes to the old address after commit. A pending request
must be cancelled before direct change when SMTP host and sender are both absent. Partial or unsafe
identity SMTP cannot select direct change. Migration 37 has no down migration; rollback requires
the matching pre-upgrade database and image, losing later writes. See
[deployment](../deployment.md#verified-email-changes) for operation and retention.

Email is a dependency of public admission and self-service recovery, not of existing sign-in or
synchronization. Missing or changed SMTP configuration suspends public admission until tested,
without silently changing the administrator's chosen policy. Pending proof records have bounded
retention and no calendar access. A successful test means SMTP accepted a message, not a guarantee
that a person's inbox received it.

Migration 38 rebuilds installation settings to admit Open while preserving the selected policy,
Plans setting, and Default Plan; no upgrade selects Open. It adds registration proofs and separate
purpose-keyed counters. Open is selectable only by an active administrator with matching ready
identity email, checked atomically with the write. All new registration SQLite phases use 100 ms
waits, including post-commit session/sign-in writes and complete response assembly through User
and Instant Sync availability reads. Plans retain fail-open behavior. A post-commit storage read
failure offers private sign-in recovery with no cookie; set the cookie only after assembling the
response. Ordinary identity and direct Invitation reads/writes retain five seconds.

No down migration is provided. Before upgrade, stop and back up the complete database with its
matching key and image. Rollback closes public joining, stops the service, and restores that
matching pre-upgrade set, losing later writes. Never run an old binary against stored Open or the
upgraded schema. See [migration 38](../deployment.md#migration-38-open-registration).
Registration maintenance reserves 250 proofs and 250 counters per batch independently and yields
to fair mail turns between full batches, aiming for deletion within 24 hours while running.
Maintenance starts without SMTP or a Master Key, while mail and public joining remain unavailable
without ready identity email and keyless token/completion admission stays in bounded memory.
Stopped services, storage faults, and backups may retain records longer.
Sign-up/reset allowances and 50-request lanes are independent, alongside ten security/test slots;
queue loss stays generic. [Registration operations](../deployment.md#verified-registration)
documents exact limits, resend, targeted/global suppression, and administrator fallback without
claiming constant-time SMTP privacy or shipped offline recovery.

Offline recovery is a deliberate maintenance operation on a stopped installation. It does not
introduce another runtime receiver of InstallationUnitOfWork, a public maintenance route, a general
scheduler mode, or an administrator-action ledger. The conservative recovery path trades automatic
resumption for proof that restored Users and credentials may still operate calendars.

## Alternatives considered

- Full or restricted sign-in before verification: rejected by the owner; access follows proof.
- Challenge provider: rejected in favor of IP and email rate limits.
- Password before verification: rejected; email-first admission avoids pending credentials.
- Retroactive verification for existing Users: rejected; preserve established access.
- Revoking Invitations when Open is chosen: rejected; retain them with verification under Open.
- Administrator approval for verified sign-ups: rejected; People retains disable/delete controls.
- Reset responses that distinguish known accounts: rejected; account status stays private.
- Requiring Plans for Open: conflicts with the settled independent switches in ADR 0028.
- Mandatory hosted backup infrastructure on self-hosting: rejected; tooling remains optional.

## Amendment: five remaining PRs and provider sign-in (2026-10-21)

The owner replaced the original eight delivery slices after PR #129 and PR #130 merged:

1. **Verified email changes.** This PR adds its own proof records, request/cancel/confirm UI,
   old-address notice, upgraded first User's direct add-email exception, and reset/session races.
   Reuse the shipped mechanisms without generalizing for sign-up. Preserve direct changes when
   SMTP is absent. Add no storage for later PRs.
2. **Split growing files by context, with no behavior change.** Split `bootstrap/container.py`,
   `interfaces/api/schemas.py`, `infrastructure/persistence/sqlite.py`, and
   `application/sync/ports.py` into context-named modules. Preserve public names and the existing
   import-linter contracts. The Synchronization port split now keeps `UnitOfWork` and
   `UnitOfWorkFactory` in `application/sync/ports.py`, with provider, account, record, health,
   plan, and run ports in focused sibling `*_ports.py` modules. The SQLite split now keeps
   the User's unit of work in `infrastructure/persistence/sqlite/unit_of_work.py`, its
   Synchronization repositories in `sqlite/sync/{accounts,rules,mappings,records}.py`, and
   ownership and time helpers in `sqlite/shared.py`. The API schema split now keeps its models
   in `interfaces/api/schemas/{shared,sync,identity,operations}.py`, with direct caller imports
   and `interfaces/api/identity_schemas.py` unchanged. The bootstrap split now keeps the root
   factories, `Container`, and `Adapters` in `bootstrap/container.py`, with composition in
   sibling `shared.py`, `sync.py`, `identity.py`, and `operations.py`; existing identity email
   modules stay in place. All four module splits are complete.
3. **Open sign-up end to end.** Deliver the Open policy value and migration, verified joining,
   email-first sign-up, verified Invitations, administrator choice and readiness checks, and
   screens together. Merged as PR #133 with migration 38. Open requires explicit administrator
   choice and matching ready identity email. There is no separate preparation release.
4. **Sign in and sign up with Google or Microsoft.** Follow the OIDC decisions below. This has
   its own plan and does not change calendar consent.
5. **Hosted backup and restore.** Combine narrow offline inspection/preparation and their
   SQLite safety tests with the optional backup tooling and tested hosted runbook. Ship before
   hosted launch, after its own plan; this work is outside the current PR. No mandatory backup
   service, public maintenance endpoint, scheduler mode, or Plan Hold edits.

New identity rules are pure domain decisions with decision-table tests. New identity records
receive SQLite adapters only, tested on temporary databases; do not grow the in-memory adapter.
New identity code stays out of the four growing files until their context split. No future proof
tables or abstractions belong in the email-change PR.

OIDC in remaining PR 4 amends ADR 0030's password-only scope. Provider identities
use issuer plus `sub`, never email. Linking starts from Your account while signed in; auto-link
at sign-in requires provider-verified email and matching Local Email Verification (ADR 0041).
Under Only Me and Invitation Only, admit only an
existing person or an invited person whose verified email matches. Under Open, create an ordinary
User following the Default Plan. Each provider is off by default and enabled by the administrator.
Reuse the installation's Google and Microsoft OAuth clients with `openid email profile` scopes;
calendar consent is separate. A person may keep or set a password, and the last sign-in method
cannot be removed. Use maintained OIDC library support, such as Authlib or the existing Google
libraries, with no new service and no ORM. Each remaining PR needs its own approved plan.

## Amendment: provider sign-in implementation (2026-10-21)

The approved provider sign-in plan settles these details without adding another registration or
email-proof system:

- **Identity and calendar access stay separate.** Provider Identity is the validated issuer plus
  `sub`, uniquely owned by one User, never the provider's mutable email. Sign-in links automatically
  to an existing active User only with provider-verified email and matching Local Email Verification
  (ADR 0041); explicit linking proves the live
  owning session. Existing bindings win over changed email. No Provider Identity grants calendar
  access, creates a Connected Account, or uses its Allowance. New admitted Users have Role.USER,
  no own Plan, and follow the Default Plan. Open still requires matching Identity Email Readiness.
- **Only Me has a narrow provider exception.** The one-User restriction applies when choosing Only
  Me. Later provider admission may consume a still-live Invitation whose presented email matches
  the provider-verified email, while that policy remains selected. Choosing Only Me cancels all
  registration proofs, not live Invitations. Ordinary Invitation issuance, password acceptance,
  and public joining without an Invitation remain forbidden. People remains available whenever
  other Users or live Invitations exist. Returning to setup revokes Invitations, provider work, and enablement.
- **Microsoft email is not verification.** `email`, `preferred_username`, and `upn` cannot prove
  email ownership. The adapter always treats Microsoft email as unverified. Existing bindings
  sign in; unlinked identities receive a generic password-link flow, with no callback account
  lookup or existence signal based on unverified email. Newcomers complete existing verified email
  registration under Open, then explicitly link from Your account. Microsoft subjects are pairwise
  to the client ID: replacing it needs another usable method and explicit relinking.
- **Passwords are optional, sensitive actions keep their confirmation.** SQL NULL represents no
  password. A live owning session with the same credential revision may set a first password.
  Replacing a password, changing email, and User Deletion still require the current password;
  provider-only Users first set one. No password removal is added. A usable method is a password
  or a linked provider both configured and enabled. Unlinking and administrator disablement
  atomically refuse to strand an active User. Disablement keeps bindings. Environment loss can
  still interrupt access; restore configuration or use an administrator-issued Password Reset
  Link, which can set a first password without re-enabling a disabled User.
- **OIDC has its own bounded boundary.** Authlib handles authorization-code/S256 PKCE mechanics,
  joserfc verifies RS256 signatures and claims, and provider packages own issuer/tenant validation
  through separate Identity descriptors (ADR 0022). Existing clients request only
  `openid email profile`. Callbacks derive from the trusted public origin; no caller return URL
  chooses a redirect. The Master Key seals context, bearer proofs persist only as hashes, and
  provider tokens are discarded. Final identity/admission/session mutation rechecks authorization
  under a short SQLite lock, with provider calls and hashing outside it.

Migration 39 preserves existing User fields, passwords, sessions, Plans, and foreign keys while
making passwords nullable and adding provider identities, settings, bounded flows and counters.
Both providers are off by default. Upgrade requires a stopped-service backup of the complete
database, matching Master Key, and previous image; rollback restores those together, losing later
writes. Never run an old binary on the upgraded schema. See
[migration 39](../deployment.md#migration-39-provider-sign-in-storage).

Flows and pending proofs last at most ten minutes. Begins allow 20 per network per 15 minutes
and 100 across the installation per hour, callbacks 20 per network per 15 minutes, and password
confirmations 10 per network per 15 minutes. The global cap can temporarily lock provider-only
Users out; password sign-in and administrator-issued recovery remain independent alternatives,
with their own limits. Network groups are IPv4 addresses or IPv6 /64s; memory admits at most
10,000 live network keys and storage at most 1,000 live flows/pending proofs. Public flow SQLite
waits are 100 ms. These bounds do not promise distributed denial-of-service protection.

OIDC callback code/state queries are the necessary exception to email proofs' fragment-only URLs.
Application access logs remove them, authentication transport logs reveal no payload, and every
reverse proxy must use path-only logging. No address, token, provider reply, or body belongs in
logs. See [limits and recovery](../deployment.md#provider-sign-in-limits-and-recovery) and
[proxy logging](../deployment.md#provider-sign-in-http-and-proxy-logs). No live provider sign-in
verification is claimed by the synthetic tests or preview.


## Amendment: local email assurance and complete password recovery (2026-10-22)

[ADR 0041](0041-verify-local-email-before-provider-auto-link.md) tightens automatic linking to
require both provider verification and Local Email Verification of the matching address. Existing
unproven addresses use password confirmation. Every completed password recovery removes all old
Provider Identities atomically, preserves Connected Accounts, and leaves local verification
unchanged. This is the authoritative refinement of the original provider-only verification condition.
