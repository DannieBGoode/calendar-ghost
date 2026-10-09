# Data ownership and privacy

Calendar Ghost Community Edition runs on the operator's machine. There is no Calendar Ghost-hosted
coordinator in the self-hosted deployment, and there is no mandatory analytics or telemetry.

## What the installation stores

The SQLite database contains operational state needed to synchronize calendars. Every record
belongs to one User, and no User can read, change, or delete another User's records; an
Installation Administrator operates the installation but never sees another User's calendars,
rules, or events ([ADR 0029](adr/0029-isolate-users-in-one-sqlite-database.md),
[ADR 0030](adr/0030-users-administrators-and-registration.md)).

- Users: each one's email, role, state, language, notification preference, and when they joined
  and last signed in. An upgraded installation's first User has no email until they add one.

- Directional Sync Rules, calendar and Connected Account identifiers, mappings, cursors, operation
  state, incidents, and run outcomes.
- Connected Account identity details such as the Google email, display name, avatar URL, and cached
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
- Provider call counts: for each User, calendar provider, and UTC day, how many calls their runs
  made, how many the provider refused for its rate limit, and how many failed. Only counts are
  kept, never what a call asked for, and days older than 30 are discarded.

Service log lines contain identifiers, counts, timings, and provider status categories. They do not
contain event titles, descriptions, locations, guests, calendar identifiers, account emails, or
provider payloads. The operator can turn file logging off and can download or purge the local log
files from Settings.

## What an Installation Administrator can see

The Operator Overview, on the People page, shows administrators whether each User's synchronization
works and why not ([ADR 0030](adr/0030-users-administrators-and-registration.md)). For each User it
shows:

- their email, role, state, when they joined, and when they last signed in;
- their Installation Status: its verdict, each problem, and each rule's state and last successful
  sync, with every calendar named only "Calendar 1", "Calendar 2", and so on, numbered in the order
  their rules were created; and
- their resource use: how many rules, Google accounts, and Activity entries they have, and the calls
  their rules made to each calendar provider over the last 30 days.

It never shows a User's calendar names or identifiers, their Google account emails, or any event
title or other event content, and there is no setting that shows more. Installation Health, above
the list, counts Users by status and names nobody. Every User sees exactly what administrators see
about them under **Settings → Your account → What your administrator can see**, which is shown
whenever someone else can be on the installation. Tests seed calendar names, Google account emails,
calendar identifiers, and event titles with markers for two Users and check that none reaches the
Operator Overview, Installation Health, the installation's notifications, or the logs.

An administrator can still disable or delete a User, issue them a password reset link, and change
their role. Calendar Ghost does not yet record which administrator did what.

## What can leave the machine

The installation communicates with:

1. Google APIs, to authorize Connected Accounts and read or write the calendars selected by rules.
2. An SMTP server and a webhook URL only when the operator configures them. With SMTP, each User
   receives their own Incident Notifications at their email, unless they turn them off; the
   configured SMTP recipient and the webhook receive only incidents about the installation itself,
   such as a scheduler that stopped running. Notifications contain an incident category, rule
   identifier, summary, and timestamp; they do not contain event content.
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
- the Google OAuth client settings and notification settings from the operator's protected `.env`
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
- Disconnecting a Connected Account removes its stored Google credentials while retaining mappings
  and rules for safe reauthorization.
- Permanently deleting a disconnected Connected Account removes its local identity, affected rules,
  mappings, incidents, and Activity. Existing Managed Projections remain in Google because the
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

The local operator controls the host, the database, the master key, and the retention policy. Google
continues to control the source and destination data stored in Google Calendar; Calendar Ghost only
manages the projections authorized by the operator's rules.
