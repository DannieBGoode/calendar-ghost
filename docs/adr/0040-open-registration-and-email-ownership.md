# Open registration and email ownership

Status: accepted for planned phase 4 on 2026-10-20 with
[the design](../superpowers/specs/2026-10-20-open-registration-design.md).
This is not a description of shipped behavior. The owner approved the revised design for planning;
implementation still requires each PR's approved plan. The second Claude design/PR 2 plan review
completed on 2026-10-20; the owner delegated PR 2 plan review and authorized continued execution.

Delivery status on 2026-10-20: PR 1 identity email readiness is implemented. PR 2 self-service
password recovery is implemented on its unmerged branch, including migration 36, deliberate
proxy trust, and operational guidance; final gates, reviews, and PR delivery remain pending.
Only Me and Invitation Only remain the supported policies. Verified email changes (PR 3), offline
recovery (PR 4), backup tooling/runbook, and Open activation are later, unshipped slices. The
decisions below describe the complete intended phase, not features all present in this build.

Amends [ADR 0030](0030-users-administrators-and-registration.md), within the isolation boundary of
[ADR 0029](0029-isolate-users-in-one-sqlite-database.md) and the optional switches of
[ADR 0028](0028-plans-apart-from-commercial-mode.md).

## Context

The Hosted Service needs people to join without an Invitation and recover their own passwords.
For new joins under Open, an unverified address must not grant access, reserve another person's
identity, or become a recovery address without proof. Existing and Invitation Only emails remain
trusted recovery addresses under the approved compatibility policy. Until PR 3, direct email
changes retain that behavior: a wrong address can let its mailbox owner reset the account, so
recovery docs must make that trust explicit. Self-hosted installations keep their current default
and operate without email unless their administrator chooses otherwise.

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
  write. Under Open it must use verified registration. Stage the enum/schema and SQLite guards
  before production activation; do not rely on lets_people_join to authorize direct acceptance.
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

Email is a dependency of public admission and self-service recovery, not of existing sign-in or
synchronization. Missing or changed SMTP configuration suspends public admission until tested,
without silently changing the administrator's chosen policy. Pending proof records have bounded
retention and no calendar access. A successful test means SMTP accepted a message, not a guarantee
that a person's inbox received it.

The policy change needs a forward migration because SQLite currently constrains Registration
Policy to Only Me and Invitation Only. Allocate migration numbers per implementation PR after
checking origin/main. The prepared-schema release still refuses Open in production. Rollback
from active Open uses a matching backup and image; do not run an old binary against a policy it
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
