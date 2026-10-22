# Verify local email before provider auto-link

Status: accepted, 2026-10-22. Amends the provider sign-in rules in
[ADR 0030](0030-users-administrators-and-registration.md) and
[ADR 0040](0040-open-registration-and-email-ownership.md).

## Context

Invitation Only, initial setup, and direct email changes accept a typed address without mailbox
proof. A provider's verified matching address therefore cannot by itself prove ownership of the
existing Calendar Ghost User. Automatic linking could put the mailbox owner into an account
created by someone else, whose password and sessions remain usable. Explicitly linking an
attacker's own provider before the mailbox owner recovers the password also leaves that provider
usable unless recovery removes it.

## Decision

A User carries Local Email Verification for their current address. Migration 39, still unshipped,
adds `users.email_verified`, a constrained boolean defaulting to false. Every pre-upgrade User
starts false, including Users who may previously have completed verification: no historical
proof is inferred. Existing passwords, sessions, and records remain intact.

A new Provider Identity can automatically link by email only when both the provider verifies the
matching email and Calendar Ghost has Local Email Verification for that address. Otherwise the
existing generic password-confirmation flow proves the chosen User. The final SQLite admission
transaction reads the current marker and honors `PASSWORD_REQUIRED` before identity or session
writes. A matching unverified local email never authorizes creating another User. Existing exact
issuer/subject bindings continue to identify their owner regardless of email. Explicit linking
still requires the live owning session; no identity can move to another User.

Only these successful, atomic writes establish Local Email Verification:

- Verified registration, including Invitation-bound email verification.
- Confirmation of a verified email change.
- New User admission with provider-verified email.

Initial setup, direct Invitation acceptance, and direct email assignment leave it false. Direct
email changes clear it, including the upgraded first User's add-email path. Password-confirmed or
session-owned provider linking does not change it, including a provider whose email differs from
the User's address. Password changes and recovery preserve its existing value. No retroactive
verification step is required for ordinary sign-in.

Every completed Password Reset Link, whether emailed or issued by an administrator, removes all
Provider Identities of its User atomically with password/revision replacement, proof consumption,
and session invalidation. It preserves Connected Accounts, calendar credentials, rules, and
Integration Tokens. The recovered User signs in with the new password and explicitly links the
providers they trust again. Ordinary authenticated password replacement and setting a first
password keep their existing method behavior.

A reset never establishes Local Email Verification. `password_reset_links.created_by IS NULL`
is insufficient evidence of email delivery: deleting the issuing administrator also sets that
column to NULL. We do not introduce reset-provenance storage merely to change the marker. Recovery
already supplies a usable password for subsequent explicit linking.

## Consequences

Upgraded Users may see password confirmation on their first provider sign-in. Users admitted
through verified registration or new verified-provider admission retain automatic linking with
other verified matching providers. A provider-only User can still set a first password or recover
through an administrator. Reset removes even legitimate provider methods; the form, completion
message, administrator hint, and recovery docs explain relinking. Provider calendar consent stays
separate and is never revoked by this policy.

Migration 39 retains its stopped-service backup requirement and has no down migration. Restore
the matching pre-upgrade database, Master Key, and image together to roll back, losing later
writes. Never run an earlier binary against the new schema. Development databases created with
an earlier unshipped migration 39 must be rebuilt from fixtures or restored from version 38;
this is not an additional released migration.

## Validation

Real SQLite regressions reproduce unverified local-email auto-link and surviving provider access
after reset on the earlier behavior. Tests cover both local/provider verification states,
password fallback, current assurance at final admission, exact existing ownership, verified
writers, unverified Invitation acceptance, direct email changes, reset kinds, deleted issuers,
foreign identities, calendar preservation, replay and transactional rollback. Provider exchange,
password hashing, and sealing stay outside write transactions.
