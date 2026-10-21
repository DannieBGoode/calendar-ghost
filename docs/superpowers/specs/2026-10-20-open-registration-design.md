# Open registration: design

Status: design approved for planning on 2026-10-20 after the HTTPS decision and the owner's
"continue" instruction. Each implementation PR still requires its own approved plan. No product
code is authorized until that plan is reviewed. The second Claude review completed on 2026-10-20,
with clarifications below. The owner delegated PR 2 plan review to Claude and authorized execution.

Delivery status on 2026-10-21: PR #129 identity email readiness and PR #130 self-service
password recovery are merged, including migrations 35 and 36. The five remaining PRs below
replace the original eight-slice sequence. Only Me is still the default and Open is unavailable.

Builds on [the multi-user delivery order](2026-10-09-multi-user-design.md),
[ADR 0029](../../adr/0029-isolate-users-in-one-sqlite-database.md),
[ADR 0030](../../adr/0030-users-administrators-and-registration.md),
[ADR 0028](../../adr/0028-plans-apart-from-commercial-mode.md), and
[ADR 0040](../../adr/0040-open-registration-and-email-ownership.md).

## Intent and boundaries

Let a person join the Hosted Service without an Invitation, after proving ownership of their
email. Use the same open code on self-hosted installations. Only an Installation Administrator
may choose Open. Only Me remains the default for new and upgraded installations. Plans and
Commercial Mode remain independent and off by default. This phase builds no billing.

Keep the application as one process with one SQLite database. Do not change synchronization,
Plan Hold, provider authorization, or the Operator Overview's privacy boundary. Do not introduce
an external identity service, challenge provider, telemetry, or a general-purpose mail platform.
Backup tooling stays optional. A narrow offline recovery command supports the runbook; it does not
change normal scheduling or become an Open activation gate. Plans are never required by Open.
Administration explains that Plans off leaves every User unlimited; it does not turn Plans on.

## Decisions approved by the owner

- Require email verification before sign-in for people joining under Open.
- Limit requests per IP address and per email, without a challenge.
- Offer self-service password reset under every Registration Policy when SMTP is configured.
  Never reveal whether the email belongs to an existing, disabled, or unknown User.
- Require configured SMTP and a successful test email before an administrator may choose Open.
- Show completed registrations in People with the existing disable and delete controls. Do not
  show pending sign-ups or require administrator approval. Pending sign-ups expire automatically.
- Keep existing Invitations valid under Open, but require email verification when redeemed there.
- Switching to Invitation Only cancels pending public sign-ups. Existing Users and Invitations
  remain valid.
- Write a concrete Hosted Service backup runbook covering continuous backup, keys, retention,
  alerts, and restore drills. Backup tools remain optional for self-hosting.
- Verification links last 24 hours; self-service Password Reset Links last 1 hour. Both are
  single-use. Administrator-issued Invitations and Password Reset Links retain 7 days.
- Keep existing Users' access when Open is enabled; do not require retroactive verification.
- Ask for email first. Choose the password only after opening the verification link.
- Verify email changes whenever SMTP is configured, under every Registration Policy. Keep the
  current sign-in email until the new address has been verified.
- Require HTTPS for identity email links, with HTTP allowed only on loopback for development.
  SMTP with an HTTP LAN address does not enable email recovery or verified email changes. Keep
  existing email and sign-in access. Exempt the upgraded first User's initial add-email step
  from verification so the upgrade cannot lock them out.

## Joining and email proof

The sign-in page offers Create account only when public registration is available. Its form asks
for email only. The response is generic: "If this address can join, we will send a verification
link." Resend uses the same form, response, and limits. An existing or disabled User receives no
registration link and is not changed. The response does not disclose that decision.

A pending sign-up is not a User: it has no password, role, session, Plan assignment, or owned
calendar records. A request cannot reserve an email or displace an existing User. It records the
normalized email, a token hash, expiry, and optional Invitation reference. Use the existing email
normalization; do not strip plus tags or apply provider-specific rules.

Opening the verification link checks usability without consuming it. The page shows the bound
email and asks for a new password with confirmation, using the existing minimum of 12 characters.
The submit, not a GET or link check, proves possession and consumes the proof. An atomic write
rechecks expiry, admission policy, Invitation ownership if present, and email uniqueness; creates
one active User with Role.USER; and consumes the proof and its sibling proofs. The person cannot
choose the role or Plan. Their own Plan is unset, so they follow the Default Plan, including future
changes, through the existing Allowance behavior. Plans off still gives every feature.

Start the normal session only after that commit, using the existing password/state race guard.
If session creation fails, the User still exists and can sign in normally. Never create another
User on retry. A race with an existing account gives a neutral unusable-link result with sign-in
and reset options, without altering that account. No verified/pending UserState is needed.

Allow multiple unexpired proofs for one email within the request limits. Requesting another email
does not invalidate a delivered link. Completing one consumes all proofs for that email and
purpose atomically. Purge expired and consumed pending records within 24 hours, including through
bounded cleanup on identity traffic, without depending on a working scheduler. Retain no sign-up
history beyond this window. A replay cannot create a second User.

## Invitations and Registration Policy transitions

Under Invitation Only, keep the current Invitation form and behavior: email and password create a
User without email verification. Under Open, a usable Invitation leads to an email-only request
and then the same verification/password flow. Keep the Invitation unconsumed until final account
creation. Never reserve it on an email request. Multiple requests can race, but at most one can
consume it. The Invitation's original 7-day deadline also bounds its verification proof.

Revoking or expiring an Invitation invalidates its pending proofs. If the policy changes to Open
while an old Invitation form is being submitted, its atomic acceptance must refuse direct account
creation and require the verification flow. A stale page cannot bypass verification.

Direct Invitation acceptance requires exactly Invitation Only at the final SQLite write. Do not
use lets_people_join for this decision: the ability to issue an Invitation, accept one directly,
and finish a verified registration are different rules. Introduce only the named decisions each
implemented path uses. Test the Open value with real SQLite before activation, including a policy
change while password hashing runs. The end-to-end Open PR adds the stored value and these tests together with verified admission.

Switching Open to Invitation Only atomically invalidates pending public proofs. Turning Open on
again does not revive them. An Invitation-bound proof may finish under Invitation Only, with its
verification requirement retained. Switching to Only Me atomically cancels all pending
registration proofs, both public and Invitation-bound; reopening never revives them. Under Only Me
nobody joins, by either route. The existing
one-User restriction on returning to Only Me remains. Returning to setup revokes all pending
registration proofs and Invitations, turns Plans off as today, and clears email-test readiness.

Open becomes selectable in the end-to-end Open PR only after its complete verified admission
path and readiness checks are wired. The administrator must explicitly choose it, and identity
email must be ready. No separate prepared-schema release, dormant backend, or temporary
production closure guards are needed.

## Password reset and email changes

Forgot password is available when identity email is configured as defined below, independently
of Registration Policy and Email notifications. It asks for email and always
returns the same status and message for active, disabled, and unknown Users. Send only to an
eligible active User's current address, including Installation Administrators. This follows the
approved self-service recovery policy for existing Users; administrator mailboxes are therefore
security credentials and the runbook requires strong mailbox protection. A pending sign-up is not
eligible for password reset. Keep the generic no-send behavior for existing-email sign-up requests;
do not add unsolicited account-exists messages.

A self-service Password Reset Link lasts 1 hour, is bound to the User and current email/password
revision, and cannot be used after the User is disabled, deleted, changes email, or changes their
password. The completion checks usability before expensive hashing and again at the atomic write.
It sets the new password, consumes all that User's outstanding reset links, cancels pending email
changes, and ends every session atomically. It never re-enables a disabled User or signs the person
in automatically. Send them to sign-in. Keep administrator-issued reset links at 7 days and keep
the existing administrator permissions; successful resets invalidate both kinds.

With SMTP configured and a valid identity-email origin, changing email still requires the current
password. Send a 24-hour proof to
the proposed address, keep the old address active, and show the pending address and Cancel in Your
account. A replacement request revokes the previous pending email change. Only the currently
signed-in owning User may confirm the proof, with the current password again; opening the link
alone is not enough. Completion checks the User's current email/password revision and uniqueness
atomically, changes email, cancels other pending changes and reset links, and ends other sessions.
A taken address is handled without disclosing another User's identity. Cancel and any password
change invalidate pending email-change proofs. Send a content-free notice to the previous address
on completion. This notice failing does not roll back a verified change.

Without SMTP, preserve password-confirmed direct email changes. If SMTP is configured but the
identity-link origin or SMTP security settings are invalid, refuse new email changes with an
actionable configuration error and keep the current email and sign-in access. Never silently
fall back to an unverified change because TLS, the origin, or a send failed.

The upgraded first User is the existing Installation Administrator whose email is still absent
after migration. Their one initial add-email step keeps its existing restricted-session behavior,
without verification, whether SMTP is configured or not. The session already followed password
sign-in; no email send is required to finish the upgrade. This exception ends once an email is
stored and does not apply to later changes or a new registration. No extra restricted-session
verification routes are needed for this exception.

An already active User is never locked out while a change is pending. Removing SMTP does not
convert a pending change into a direct change; cancel it and explicitly start the applicable
flow. Previously issued valid reset/email-change proofs may finish without a new SMTP send.
The HTTPS or loopback rule governs emailed link issuance, not administrator hand-delivered reset
completion; administrator recovery remains available on HTTP LAN installations. Public joining
also needs Open to be operational.

## Transactional email and readiness

Use the existing CALENDAR_SYNC_SMTP_* settings and harden the transport for identity messages:
STARTTLS must verify certificate chains and hostnames using a default SSL context. Refuse a remote
relay without STARTTLS; only a literal loopback relay or localhost may use cleartext for local
operation. An operator using a loopback relay owns that relay's onward transport security. Do not
add implicit TLS or a new mail provider in this phase. Test a trusted certificate, an untrusted
certificate, a hostname mismatch, STARTTLS refusal, and cleartext remote-relay refusal. Reusing
transport code may improve certificate verification for existing notifications, but must not
change their preferences, recipients, delivery policy, or workers.

Verification, reset, email-change, and test messages do not depend on the User's Email
notifications preference. Incident and Plan
notice behavior and workers are outside this change. Never send auth links to the installation's
SMTP_RECIPIENT or webhook. Use separate, literal templates with no event content.

Use CALENDAR_SYNC_PUBLIC_URL as the only link origin, validated as an absolute HTTPS root origin
with no user information, query, fragment, or path. Permit HTTP only on localhost/loopback for local
development. Never construct a link from Host, forwarded headers, or a return URL from the caller.
This stricter rule applies to identity email, not existing incident links or Instant Sync.

Define identity email as configured only when SMTP host/sender are present, its security settings
permit verified STARTTLS (or the local-relay exception), and this validated identity-link origin
is present. Use this one predicate for public reset availability, email-change requests, identity
test readiness, and the SMTP/origin portion of Open eligibility. It describes configuration, not
a promise that the next send will succeed. Only Open additionally needs a successful test for
that configuration. An HTTP LAN origin fails the predicate even with otherwise working SMTP.
Explain the HTTPS setup requirement without affecting existing Users' sign-in or current email.
Do not mark SMTP as absent to select the direct-email-change fallback.

Administration shows whether SMTP and the public origin are usable and offers Send test email to
the signed-in administrator's current email, never an arbitrary recipient. A successful test
means SMTP accepted the message, not proof of inbox delivery; the UI says to check the inbox.
Persist test success tied to the exact effective SMTP configuration and link origin using a keyed
fingerprint, without storing credentials. A changed configuration needs a new test. The current
configuration and readiness are rechecked when Open is chosen. Do not put network calls inside
SQLite write transactions.

If SMTP settings disappear or no longer match the tested configuration while Open is selected,
keep the chosen policy but make public requests and final public admission unavailable. Explain
why and how to send a new test in Administration; show only a generic temporary-unavailability
message publicly. Existing sign-in, synchronization, and Invitations under Invitation Only remain
usable. A transient send failure does not silently change Registration Policy. Record a safe
operator diagnostic without message body, address, token, or provider exception text.

## Abuse controls and response privacy

The following exact defaults are builder recommendations for approval with this design:

| Boundary | Limit |
| --- | --- |
| Sign-up/resend, per normalized email | 5 per hour, at least 60 seconds between sends |
| Self-service reset, per normalized email | 5 per hour, at least 60 seconds between sends |
| Either purpose, per (email, client network), separate per purpose | 2 per hour |
| Public requests, per client network, separate per purpose | 20 per 15 minutes |
| Sign-up email admission across the installation | 100 per hour |
| Reset email admission across the installation | 100 per hour, reserved for reset |
| Signed-in email-change requests | 5 per User per hour, plus the email cooldown |
| Administrator test email | 3 per administrator per hour |
| Invalid token checks/submissions, separate from sign-in | 20 per client network per 15 minutes |
| Password-bearing completion submissions, including usable tokens | 10 per client network per 15 minutes |

A client network is one IPv4 address or one IPv6 /64, so rotating IPv6 interface addresses cannot
reset the allowance. Limits do not solve distributed denial of service. A targeted attacker can
still consume a person's per-email send cap. A delivered proof stays valid on resend, and the UI
and recovery guide explain the administrator-issued reset fallback. Under Only Me, the operator
can use the offline recovery command if the sole administrator cannot recover by email. These
fallbacks are required, not a claim that a per-email limit can distinguish the mailbox owner.
The installation-wide reset cap can also be exhausted by two networks requesting distinct unknown
emails. Keep the approved limits and document administrator-issued recovery as the fallback.
Per-email and global suppression remain residual availability risks.

Apply a bounded in-memory per-client gate before any SQLite write, for both issuance and token
completion. Cap this gate at 10,000 live network keys with expiration; at capacity refuse new
keys until space expires, rather than evicting entries to give attempts back. Persist only admitted
requests, with keyed digests of email/network keys and per-purpose global counts. Rejected floods
perform no write. Use an atomic short transaction and a 100 ms identity-throttle lock timeout;
contention returns a generic temporary-unavailability result without weakening a limit. This
keeps provider synchronization away from long anonymous write-lock waits. A restart clears the
front gate but not the durable admitted allowance. Purge expired counters within 24 hours.

Count admitted requests before account lookup, including unknown and disabled emails. Per-email
and (email, network) suppression keep the generic success response and do not give an email-specific
Retry-After. Network/global limits may return 429 with Retry-After, independently of account
existence. Separate reset and sign-up counters and queue capacity so sign-up alone cannot exhaust
recovery delivery. Do not reset abuse counters after proof success. Keep this apart from sign-in.

Use the client address resolved by Uvicorn, with FORWARDED_ALLOW_IPS explicitly set to the exact
reverse-proxy IPs or networks by the operator. The deployment examples use an empty trust list
without a proxy and a narrow allowlist behind one; never use '*'. Set proxy_headers deliberately
rather than reading arbitrary headers in application code. Reject spoofed X-Forwarded-For from
untrusted peers. Proxy deployment acceptance tests must demonstrate two clients receive distinct
limits and IPv6 /64 grouping works. Administration links to this setup guide before Open is chosen;
do not guess that every private address is a proxy or block legitimate LAN clients based on it.
Correct the existing deployment text that all proxy traffic necessarily shares one limit.

Cap request bodies at 8 KiB, normalized email at the existing 254-character limit, tokens at 128
ASCII characters, and new passwords at 1,024 characters before database work or hashing.
Sign-in and current-password confirmations accept up to 1,024 characters so every reset password
remains usable. Setup, Invitation, and ordinary new-password creation bounds stay unchanged.
Keep 12 as the new-password minimum. Apply the completion gate before hashing even for usable proofs.

Public request handlers do not perform or await account lookup or SMTP delivery. Worker scheduling
may start that work before the client receives the response; no strict ordering is promised.
Use bounded in-memory identity-mail queues, separate from scheduler/Plan mail, with 50 pending
sign-up requests and
50 pending reset requests. Security changes and administrator tests have their own bounded lane
of 10 requests. These are purpose-specific lanes in the same small mail service, not a general
job framework. Use fair scheduling so each nonempty lane gets a turn. Queued requests contain no
password. Recheck eligibility before sending and issue the proof close to send time. Use verified
TLS and the existing 10-second socket timeout, with no automatic SMTP delivery retry.

Queue saturation or a dropped item does not change the public 202 status or generic body; record
only aggregate safe capacity diagnostics. Only account-independent gates may return 429/503.
Do not expose queue depth or worker outcome in public status. Shutdown, restart, or SMTP failure
can lose a request; the UI permits retry within limits and never promises delivery. Do not persist
plaintext tokens or build an outbox. A public response never awaits a lookup or send.
Shutdown blocks old-generation delivery that has not already been authorized and old-generation
readiness updates. Already-authorized bounded SMTP may finish. Short reset preparation in flight
may finish after stop and leave an unused hash-only proof without sending its token; normal expiry
and cleanup apply.

This prevents the review's direct queue-full response oracle. It does not promise that someone
controlling enough traffic and receiving their own email can never infer aggregate worker load
from delivery latency. SMTP latency is already outside the application. Treat that residual as a
P3 risk of this small bounded service, disclosed with the approved design; do not describe the
queue as a proof of constant-time privacy. No HTTP result may identify another email's account
status. Do not add a complex fixed-slot mail scheduler just to hide aggregate timing.

## Security, ownership, and persistence

Use 32 cryptographically random bytes per token and store only its hash. Separate token purposes
so verification cannot reset a password or change email. URLs carry tokens in the fragment, as
existing Invitations do; APIs receive them in bounded POST bodies. Keep them out of query strings,
logs, telemetry, errors, cache persistence, and notifications. Use no-store and no-referrer for
identity pages/responses. Link-check GETs and mail scanners must not mutate state.

Registration proofs without a User are narrow installation-level records, like Invitations.
Reset and email-change records carry user_id and reference their parent by identifier and User
together where applicable. Extend isolation schema tests and persistence contracts. New public
writers receive narrow identity ports, never InstallationUnitOfWork. Application modules stay in
Identity and Access; SMTP and SQLite remain adapters composed in bootstrap.

Check policy, proof expiry at commit time, current User state, expected credential revision,
Invitation validity, and email uniqueness under one short write lock. Perform SMTP and password
hashing outside it. Cover race outcomes, not only successful sequential requests. Fail closed on
proof, admission, readiness, or rate-limit storage failure without changing any User. End sessions
inside the same credential-change transaction so an old reset cannot end a newer session later.

Add only the migrations each PR needs. Recheck origin/main's next free migration and ADR numbers
immediately before allocating them. Do not reserve migration numbers here. Preserve every existing
setting and default when rebuilding installation_settings in the end-to-end Open PR. Open
remains unavailable until its administrator chooses it with identity email ready. Each
migration needs SQLite tests and upgrade/rollback guidance. Rollback from active Open requires
closing public registration and restoring a matching pre-upgrade backup and image; do not let an
old binary read a policy it cannot understand.

## Web UI and documentation

Follow DESIGN.md, reuse AuthFrame and existing password fields, and keep a single clear next step
on sign-up, email-sent, verification, reset, and unusable-link pages. Show safe retry options for
expired links. Auth flows must work at 1440 and 390 px, in light/dark, and with keyboard alone.
Use t() for all Web UI copy and i18n.format for values. Avoid raw technical failures and never show
whether an email is registered. Verification and reset email subjects/bodies use literal security
language; do not add calendar content or marketing.

Administration adds Open alongside the existing policies, states its email requirements, and warns
that returning to Invitation Only cancels unfinished public sign-ups. Existing People controls need
no new approval queue or pending-state column. Describe the new public routes in AGENTS.md and the
authorization tests; name exact routes and generated API changes in each PR plan.

Update CONTEXT.md with Pending Registration, Email Verification Link, and the two Password Reset
Link lifetimes, plus the amended email-change behavior. Update README, architecture, development,
deployment, self-hosting, and data-ownership references when their behavior ships, not earlier.
Keep ADR 0030 linked to the new decision. Only the design and proposed ADR change in this stage.

## Hosted Service backup runbook

Add docs/hosted-backups.md, linked from deployment and data ownership. Use Litestream as an optional
continuous SQLite backup tool, pinned to a tested release at implementation time, with a separate
process beside the one application writer. Explain configuration, start/stop, private remote
storage on a different host/account failure boundary, encryption, and least-privilege credentials.
The standard Compose quick start must not acquire a backup service or remote dependency.

Operational targets proposed by the builder: remote recovery point within 1 minute while healthy,
alert after 5 minutes of unsuccessful replication, latest recoverable state retained for 30 days,
and a monthly isolated restore drill. Distinguish these targets from a guarantee; measure them.
Verify actual Litestream retention/compaction semantics for the pinned release, and test recovery
at the documented retained points. Do not apply a bucket age rule that removes files needed by a
retained restore point. Daily independently recoverable snapshots may provide the 30-day history.

Back up the Installation Master Key and matching provider/application secrets separately in an
encrypted recovery store; record image and migration versions. Never put key material in the
runbook or repository. Describe deletion retention explicitly: removed Users remain in backups
until those backups expire. Monitor both replication and successful restore drills.

Restore with both the application and Litestream stopped, traffic closed, and a new database path,
using matching secrets and image. Never overwrite a running database or start the API to inspect
it: the current API lifespan starts scheduling and Instant Sync. First run supported offline
inspection and preparation commands, which start no application, scheduler, mail, or provider
adapter and open SQLite only through connections.py. Add this small operator interface in the hosted backup and restore PR;
it is absent today and cannot be satisfied by documentation alone.

Offline inspection checks schema compatibility, SQLite integrity and foreign keys, and that the
matching Master Key can authenticate sealed credentials without printing them. Preparation must
require an explicit stopped-service acknowledgement, create a protected local before-change backup,
and be retry-safe. A SQLite lock alone cannot prove a sleeping application process is stopped;
the runbook makes stopping and checking the process a prerequisite. Preparation atomically closes
Open to Invitation Only (Only Me if only one User remains), clears test readiness, revokes all
sessions, Invitations, Integration Tokens, OAuth states, registration/reset/email-change proofs,
and marks queued Instant Sync work and Watch Registrations unusable. Clear in-memory queues by
keeping all processes stopped. Emit counts and safe completion status, never credentials, tokens,
email addresses, or calendar content.

A restore can revive deleted Users, old passwords, disconnected credentials, and revoked tokens.
Do not assume the restored database records the actions that happened after its recovery point.
Keep public access closed and every scheduled/Instant Sync path unable to write while the operator
replays known deletions, disables, disconnections, and credential changes. Preserve the failed host's
newer database for comparison if it is recoverable; do not add an administrator-action ledger or
hosted coordinator in this phase.

When that comparison cannot establish current authorization, use the conservative preparation
path: disable all Users except a selected existing Installation Administrator, give that
administrator a fresh password through a hidden terminal prompt, and disconnect every Connected
Account by sealing an empty credential value while retaining mappings and rules. Existing
Disconnected Account behavior blocks provider calls. Do not edit Plan Hold fields or release any
holds. Other Users stay disabled until the administrator confirms they should still have access
and resets their credentials. Owners must explicitly reauthorize Connected Accounts before
synchronization can resume. Old watch registrations and dispatch requests stay invalid, so provider
callbacks cannot restore authority. The tool prints no fresh password and sends no email.

The conservative path is the runbook default when restoring an older point with uncertain history.
It sacrifices automatic resumption to avoid writing to a departed person's calendars. A safe
inspection smoke test uses the offline command, not an API server. After preparation, permit only
operator access, check sign-in and Installation Health, replay authoritative changes, then allow
eligible Users to reconnect and reconcile. Reopen Open only after the normal email test and an
explicit administrator choice. Never start two application writers against one database.

The runbook must test the pinned Litestream version with Calendar Ghost's VACUUM followed by
wal_checkpoint(TRUNCATE). Current code returns StorageBusy when a reader prevents truncation.
The official WAL guide establishes possible read/checkpoint contention, not that every compaction
will fail. Document a maintenance procedure: close traffic, stop the application, sync the replica,
stop Litestream, perform offline compaction, restart replication, and verify a fresh restore before
reopening. Do not weaken StorageBusy or change normal storage behavior for the backup tool.
Require a successful restore across VACUUM and the stop/restart sequence as implementation evidence.

Sources checked while drafting: [replicate](https://litestream.io/reference/replicate/),
[restore](https://litestream.io/reference/restore/), and
[retention and compaction](https://litestream.io/reference/config/), and
[WAL checkpoint tradeoffs](https://litestream.io/guides/wal-truncate-threshold/). The implementation PR must
verify and exercise the selected version; this spec does not claim the current deployment already
has continuous backups.

## Delivery slices

PR #129 and PR #130 are merged. The owner replaced the original eight-slice delivery plan on
2026-10-21 with these five remaining PRs, in order. Each PR merges safely alone and gets its own
approved plan. Every web module has a live caller and passes knip. Add only records, ports, and
callers required by the current PR.

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
   screens together. Open stays unselectable until the administrator chooses it and identity
   email is ready. Drop the temporary preparation guards required by the old split.
4. **Sign in and sign up with Google or Microsoft.** Follow the OIDC decisions below. This has
   its own plan and does not change calendar consent.
5. **Hosted backup and restore.** Combine narrow offline inspection/preparation and their
   SQLite safety tests with the optional backup tooling and tested hosted runbook. Ship before
   hosted launch, after its own plan; this work is outside the current PR. No mandatory backup
   service, public maintenance endpoint, scheduler mode, or Plan Hold edits.

Identity rules belong in pure domain values and decisions, with decision-table tests: hashed,
expiring, single-use email proofs, credential revision, and admission under each Registration
Policy. Use cases load, decide, and save. New email-change proofs, registration proofs, and provider
identities have SQLite adapters and temporary-database tests only; do not extend `memory.py`.
Do not grow the four files named in remaining PR 2 while adding identity work. Keep import-linter
contracts unchanged, constructors within seven fields, and no new WIDE_DATACLASSES entry or
complexity suppression.

Commit this delivery revision separately before mapping verified email changes with parallel
read-only agents. Write its lean plan with superpowers:writing-plans, naming files, signatures,
exact values, and test assertions in about 300 lines or fewer. Stop for owner review before code.
Use subagent-driven implementation/review/fix loops and a `.superpowers/sdd/` ledger afterward.
Before each PR, run all repository gates with real exit codes, auth/email security review, and
outside read-only Claude review excluding compiled assets and generated OpenAPI files. Fix P1/P2
issues test-first, follow the PR template, check diff size after each commit, push, and watch CI.
Do not start the next PR before this one merges and its own plan is approved. Keep Plan Hold out.

## Google and Microsoft sign-in decisions

The fourth remaining PR adds optional OIDC sign-in and sign-up. Each provider is off by default;
the Installation Administrator enables it. A provider identity is its issuer plus `sub`, never
its email. Linking is initiated from Your account while signed in. Sign-in may auto-link only
when the provider states that the email is verified.

Only Me and Invitation Only admit only existing people or an invited person whose verified email
matches. Open may create an ordinary User following the Default Plan. Provider sign-in must obey
Registration Policy at the final admission write. This is a separate admission decision from
password-based Invitation acceptance; it does not open public joining under Only Me.

Reuse the installation's Google and Microsoft OAuth clients with sign-in scopes only:
`openid email profile`. Calendar consent remains a separate step. A person can always keep or
set a password, and cannot remove their last sign-in method. Use a maintained OIDC library such
as Authlib or the Google libraries already in use. Add no service or ORM. These are planned
features; this document change enables none of them.

## Acceptance evidence

- Fresh/upgraded installations remain Only Me; no earlier slice admits a public User.
- Verified joining creates exactly one ordinary User, follows the Default Plan when Plans are on,
  and remains unlimited when Plans are off. Existing Users retain access.
- Unverified, expired, revoked, replayed, cross-purpose, and raced proofs never create or change
  a User. Invitation revocation, policy closure/reopen, and return-to-setup are covered with SQLite.
- Generic requests have equal status/body and no account-dependent SMTP or lookup delay in the
  request path. Per-IP/email/global limits, cooldown, concurrent admission, restart persistence,
  queue overflow, and worker failure are tested without real mail accounts. A sign-up flood cannot
  consume the reserved reset budget or queue lane; denied front-gate floods do not write SQLite.
- Reset cannot revive a disabled User, change another User, survive credential/email changes, or
  leave old sessions valid. Email changes keep the old address until verification and current
  credential checks succeed. Test upgrade/add-email behavior with and without SMTP.
- SMTP tests and Open activation require an administrator; configuration changes invalidate
  readiness; forged hosts/forwarded headers cannot redirect auth mail. Email notifications off
  does not suppress security mail. No token, password, address, or body enters auth mail logs.
- Every route has the intended public/session/administrator guard and refuses Integration Tokens
  outside the existing allowlist. Extend authorization, isolation, and architecture tests.
- Complete backend/frontend gates, CI-version gitleaks, container build (or a stated blocker),
  live responsive/theme/keyboard checks for each UI slice, security review, and outside review.
- Exercise a synthetic continuous backup and restore, including secret matching, SQLite checks,
  token/session/Integration Token invalidation, conservative recovery of revived Users/credentials,
  offline inspection, VACUUM/checkpoint compatibility, and no duplicate application writers.

## Builder calls accepted with the revised design

The interview decisions above were approved individually. The following builder recommendations
were accepted with the revised design for planning, not as permission to implement before each
PR plan is reviewed:

- Certificate-verified TLS for remote identity SMTP. The HTTPS identity-link requirement and
  upgraded-first-User exception have been individually approved by the owner.
- Email-change confirmation with the owning session and current password; reset never signs in.
- Existing administrators are eligible for self-service reset; existing-email sign-up sends nothing.
- Explicit trusted-proxy configuration and IPv6 /64 grouping.
- Separate reset/sign-up budgets, durable admitted counts, bounded in-memory front gates, and the
  exact limits above. Administrator/offline fallback for targeted recovery suppression.
- Bounded lossy email lanes with no HTTP queue-full oracle, plus the documented residual aggregate
  delivery-latency risk. This phase does not promise constant-time SMTP delivery.
- Configuration-bound persistent test readiness and the five remaining PRs recorded above.
- Optional Litestream runbook, the proposed operational targets, and narrow offline recovery tools,
  including the conservative disable/disconnect path for uncertain restore history.

## Review disposition

The first independent Claude review requested changes. The revision confirms and addresses the
TLS issue, proxy ambiguity, direct-Invitation guard, shared recovery budgets, anonymous SQLite
write contention, early unused persistence/screens, oversized activation slice, and missing restore
support. Only Me explicitly cancels proofs. The proposed ADR separates owner-approved policy from
builder recommendations. The owner chose HTTPS identity links, the loopback development exception,
and direct initial add-email for the upgraded first User. An earlier second review attempt was
blocked by its session limit.

The second read-only design and PR 2 plan review completed on 2026-10-20. Earlier retries used
`--bare`, which skips saved OAuth credentials; this was a command-mode error, not missing
authentication. The corrected review used `--safe-mode`.

Accepted findings: preserve HTTP LAN administrator reset completion; refuse disabled-target
administrator issuance with 409; keep reset prepare/purge off the event loop with 100 ms storage
waits; move reset use cases off the shared sign-in throttle; preserve keyless administrator
recovery with bounded memory limits. Keep the approved global/network limits and document their
aggregate exhaustion risk instead of adding a /48 policy. Existing email addresses, including
Invitation Only and direct changes before verified email changes ship, remain trusted recovery addresses as approved;
document the wrong-address mailbox takeover risk without retroactive verification. These clarify
approved behavior and delivery order rather than add policy.

Do not adopt the review's suggestion that Open require Plans: it contradicts ADR 0028 and the
approved independent switches. Do not claim Litestream makes every compaction fail: compatibility
is a version-specific test and operational requirement. Review recommendations that broaden policy
remain recommendations, never implied owner approval.
