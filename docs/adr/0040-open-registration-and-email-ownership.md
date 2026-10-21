# Open registration and email ownership

Status: accepted; verified email changes implemented on 2026-10-21, with later phases planned under
[the design](../superpowers/specs/2026-10-20-open-registration-design.md).
The owner approved the revised design for planning. This record distinguishes the implemented
email-change slice from later Open registration, provider sign-in, and backup work.

Delivery status on 2026-10-21: PR #129 identity email readiness and PR #130 self-service
password recovery are merged, including migrations 35 and 36. The verified email-change slice
implements migration 37 and its signed-in request, proof, cancellation, and confirmation flow;
delivery review remains in progress. Only Me and Invitation Only remain supported. The later
PRs below remain planned until each ships.

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

The policy change needs a forward migration because SQLite currently constrains Registration
Policy to Only Me and Invitation Only. Allocate migration numbers per implementation PR after
checking origin/main. Open is selectable only with administrator choice and ready identity email
in the end-to-end PR. Rollback from active Open uses a matching backup and image; do not run an old binary against a policy it
cannot read.

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
   ownership and time helpers in `sqlite/shared.py`; the bootstrap and API schema splits remain
   planned.
3. **Open sign-up end to end.** Deliver the Open policy value and migration, verified joining,
   email-first sign-up, verified Invitations, administrator choice and readiness checks, and
   screens together. Open stays unselectable until the administrator chooses it and identity
   email is ready. Drop the temporary preparation guards required by the old split.
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

OIDC is now planned in remaining PR 4, amending ADR 0030's password-only scope. Provider identities
use issuer plus `sub`, never email. Linking starts from Your account while signed in; auto-link
at sign-in requires a provider-verified email. Under Only Me and Invitation Only, admit only an
existing person or an invited person whose verified email matches. Under Open, create an ordinary
User following the Default Plan. Each provider is off by default and enabled by the administrator.
Reuse the installation's Google and Microsoft OAuth clients with `openid email profile` scopes;
calendar consent is separate. A person may keep or set a password, and the last sign-in method
cannot be removed. Use maintained OIDC library support, such as Authlib or the existing Google
libraries, with no new service and no ORM. Each remaining PR needs its own approved plan.
