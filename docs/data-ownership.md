# Data ownership and privacy

Calendar Ghost Community Edition runs on the operator's machine. There is no Calendar Ghost-hosted
coordinator in the self-hosted deployment, and there is no mandatory analytics or telemetry.

## What the installation stores

The SQLite database contains operational state needed to synchronize calendars. Every record
belongs to one User, and no User can read, change, or delete another User's records; an
Installation Administrator operates the installation but never sees another User's calendars,
rules, or events ([ADR 0029](adr/0029-isolate-users-in-one-sqlite-database.md),
[ADR 0030](adr/0030-users-administrators-and-registration.md)).

- Users: each one's email, role, state, language, notification and Instant Sync preferences, and
  when they joined and last signed in. An upgraded installation's first User has no email until they add one.

- Directional Sync Rules, calendar and Connected Account identifiers, mappings, cursors, operation
  state, incidents, and run outcomes.
- Connected Account identity details such as the Google or Microsoft email, display name, avatar URL, and cached
  calendar names. OAuth credentials are encrypted with the Installation Master Key.
- Audit Entries, including the source event title and time needed to make Activity useful. These
  values are plain text in SQLite.
- Source Observations and Source Changes. Descriptions, locations, guest addresses, recurrence, and
  conferencing values are sealed with a key derived from the Installation Master Key. Earlier values
  are retained for the configured history window described in [Deployment](deployment.md).
- Password hashes and session hashes. Plaintext passwords and session tokens are never stored.
- Invitations and Password Reset Links: who created them, when, and when they expire or were used,
  with a SHA-256 hash of each link's token. The link is shown once and never stored, and an
  administrator never sees or sets anyone's password.
- Integration Tokens: each token's User, name, scopes, and issue, last-use, and revocation times,
  with a SHA-256 hash of the token. The token itself is shown once when issued and never stored.
- The Registration Policy.
- Plans, once an administrator defines one: each Plan's key, name, limits, and sync interval, and
  when it was defined and last changed; whether Plans are on, and which Plan is the default. For
  each User an administrator or billing gave a Plan, or returned to the Default Plan: their own
  Plan, if they have one, whether an administrator or billing set it, which administrator, and
  when. A User nobody has given a Plan has the default, and nothing more is stored for them. Each
  rule also records whether it keeps the place of the rule it replaced under its User's Plan
  ([ADR 0038](adr/0038-plans-allowances-and-limits.md)).
- Provider call counts: for each User, calendar provider, and UTC day, how many calls their runs
  made, how many the provider refused for its rate limit, and how many failed. Only counts are
  kept, never what a call asked for, and days older than 30 are discarded.
- Instant Sync, when the installation has a public HTTPS address: each Calendar Watch's Connected
  Account, what it covers, and which Source Calendars; each Watch Registration's provider handle,
  a SHA-256 hash of its secret token, the address it points at, its state, and its times; per
  rule, counters of requested and handled runs and when they happened; and, for the installation,
  when each provider last reached the public address and last failed to. Reports from Google and
  Microsoft carry no event content and are never stored or logged
  ([Instant Sync](instant-sync.md#privacy)).

Service log lines contain identifiers, counts, timings, and provider status categories. They do not
contain event titles, descriptions, locations, guests, calendar identifiers, account emails, or
provider payloads. The operator can turn file logging off and can download or purge the local log
files from Settings.

## What an Installation Administrator can see

The Operator Overview, on the People page, shows administrators whether each User's synchronization
works and why not ([ADR 0030](adr/0030-users-administrators-and-registration.md)). For each User it
shows:

- their email, role, state, when they joined, and when they last signed in;
- once any Plan exists, their Plan: which Plan limits them and whether it is their own or the
  default, or, while Plans are off or for an administrator, the Plan they were given that does not
  apply yet; the Plan they have, their own or the default; which administrator last gave them
  their own Plan, by email, and when; how much of it they use, as counts of the rules that count
  toward it, every calendar account, and unrevoked Integration Tokens, never a token's name or
  scopes ([ADR 0030](adr/0030-users-administrators-and-registration.md), amended); and each limit
  of it they have more of than it allows, such as "2 calendar accounts, 1 allowed", whether or not
  Plans are on. No Plan limits an administrator or a disabled User, so neither is ever shown over a
  limit;
- their Installation Status: its verdict, each problem, and each rule's state and last successful
  sync, with every calendar named only "Calendar 1", "Calendar 2", and so on, numbered in the order
  their rules were created; and
- their resource use: how many rules, calendar accounts, and Activity entries they have, and the calls
  their rules made to each calendar provider over the last 30 days.

People can list everyone who has a given Plan. People's Plans tab shows, for each Plan, how
many people have it, how many it limits, how many of those have more than it allows, and, for
rules, calendar accounts, and Integration Tokens, how many people have each count, so an
administrator can see what a lower limit would do; it names nobody, though on a Plan only one
person has, the counts are theirs
([ADR 0038](adr/0038-plans-allowances-and-limits.md)). Before an administrator gives people a
Plan, People says which of its limits each of them would have more of, from the same counts.

It never shows a User's calendar names or identifiers, their Google or Microsoft account emails, or any event
title or other event content, and there is no setting that shows more. Installation Health, above
the list, counts Users by status and names nobody. This page is where every User learns what
administrators see; the Web UI does not repeat it to them. Tests seed calendar names, Google and Microsoft account emails,
calendar identifiers, event titles, and a provider's own error message with markers for three Users and check that none reaches the
Operator Overview, Installation Health, the installation's notifications, or the logs.

An administrator can still disable or delete a User, issue them a password reset link, change
their role, and give them a Plan. Calendar Ghost records which administrator last gave each User
their Plan, and when, but does not yet record which administrator did anything else.

## What can leave the machine

The installation communicates with:

1. Google APIs and Microsoft Graph, with Microsoft's identity platform, for whichever providers the
   operator configured: to authorize Connected Accounts and to read or write the calendars selected
   by rules. Calendar Ghost marks the events it writes with extended properties in its own
   namespace, which Outlook does not display: the rule, the operation, and the source event's
   identifiers, start, and repeat pattern, never its title or other content. Writes to Outlook never invite or email
   anyone. With Instant Sync, the installation also tells Google and Microsoft its public address
   so they can report that a watched calendar or mailbox changed; their reports carry no event
   content.
2. An SMTP server and a webhook URL only when the operator configures them. With SMTP, each User
   receives their own Incident Notifications at their email, unless they turn them off; the
   configured SMTP recipient and the webhook receive only incidents about the installation itself,
   such as a scheduler that stopped running. Notifications contain an incident category, rule
   identifier, summary, and timestamp; they do not contain event content. An administrator can
   separately request an identity email test to their own signed-in address. It ignores incident
   preferences and the configured SMTP recipient. Identity Email Readiness stores a keyed
   configuration fingerprint and successful test time, and admission counters store administrator
   identifiers and request times. They store no email bodies or SMTP credentials. Attempt states
   and queued work are in memory, with no persistent delivery outbox. Acceptance by SMTP does not
   prove inbox delivery. See [identity email setup](deployment.md#identity-email-test-readiness).
3. Monitors, dashboards, and AI agents a User gives an Integration Token. They ask for that User's
   Installation Status; Calendar Ghost never contacts them. Status contains rule identifiers and
   states, calendar names, Provider Kinds, incident summaries, and times; it never contains event
   content, calendar identifiers, or account emails. An Installation Administrator's token with the
   `installation:read` scope may also read Installation Health: installation incidents and how many
   Users are in each status, naming no rule, calendar, or User. An agent may pass what it reads to
   its own model provider, so issue tokens only to tools you trust with that.

The service does not contact a Calendar Ghost account, send analytics, or upload the database.

## Backups and recovery

A usable backup contains both the SQLite data and the secrets that are intentionally kept outside
the database:

- the application data directory, including `calendar-sync.db` with its `calendar-sync.db-wal` and
  `calendar-sync.db-shm` files, and any retained local logs;
- the Installation Master Key;
- the Google and Microsoft OAuth client settings and notification settings from the operator's protected `.env`
  or secret store; and
- the image version and migration version used when the backup was made.

Back up the data volume while the service is stopped, or use a storage snapshot that guarantees a
consistent SQLite backup. Never copy or restore the database while a process is writing it. Store
the backup and the Installation Master Key separately from the live host, and never attach either
to a public issue or support request. A database without its master key cannot restore encrypted
Connected Account credentials or sealed Source Change values.

To restore, stop the service, restore the data directory and matching secrets, start the same or a
newer compatible image, and check `/health` and Activity before allowing scheduled runs to resume.
Keep the previous database and image available until the restored installation has been verified.
Do not use `docker compose down -v` as an upgrade step: removing the named volume removes the local
installation state.

## Deletion and retention

- Settings can clear older Activity and purge local log files. A backup made before that action may
  still contain the cleared values until the backup is rotated out.
- Disconnecting a Connected Account removes its stored credentials while retaining mappings
  and rules for safe reauthorization.
- Permanently deleting a disconnected Connected Account removes its local identity, affected rules,
  mappings, incidents, and Activity. Existing Managed Projections remain in Google Calendar or Outlook because the
  installation no longer has authorization or ownership evidence to change them.
- Rule Removal can delete owned destination projections or retain them as Detached Events, according
  to its User's choice.
- User Deletion runs Rule Removal for each of the User's rules, then removes the User and every
  record they own: Connected Accounts and their credentials, rules, mappings, Activity, incidents,
  Integration Tokens, and sessions. A User deleting themself chooses whether their projections are
  deleted or kept; an Installation Administrator deleting another User always deletes them where the
  destination can still be reached, and leaves them, no longer managed, where it cannot. Deletion
  removes the User from the live database only: a backup made before it keeps their records until
  the backup is rotated out.
- To remove an entire self-hosted installation, stop the service, retain or destroy backups according
  to the operator's retention policy, remove the Compose data volume, and delete the protected local
  secrets. Verify that no external backup or snapshot still contains the database.

The local operator controls the host, the database, the master key, and the retention policy. Google and
Microsoft continue to control the source and destination data stored in Google Calendar and Outlook;
Calendar Ghost only
manages the projections authorized by the operator's rules.

## Email notifications and Plan Hold data

The **Email notifications** preference in Settings, Your account stores `notify_by_email` and
controls optional Incident Notifications. The Plan Hold engine reuses that same per-User
preference, active-User, email-address, and SMTP gates for Plan notices when PR 3 activates it.
In PR 2 production composition cannot start a grace, hold a rule, or send a Plan notice.
A Plan notice carries counts, limit, and a UTC deadline, with an optional link to
`/settings/account#your-plan` at the configured public address. It names no rule, calendar,
Connected Account, or event. It creates neither an Incident nor an Audit Entry and never goes to
the installation SMTP recipient or webhook. Incident Notifications retain their existing content
and Activity fallback. PR 3 will supply the visible fallback for Plan notices.

Migration 34 stores keep marks on each User's rules and grace/admission fields on their User row.
Only the User-scoped unit of work writes them. Plan mail is held in memory only; a newer pending
notice replaces an older one for the same User, and failed preparation, cancellation, shutdown,
restart, or SMTP failure can lose it. There is no delivery outbox.
