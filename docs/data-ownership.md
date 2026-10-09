# Data ownership and privacy

Calendar Ghost Community Edition runs on the operator's machine. There is no Calendar Ghost-hosted
coordinator in the self-hosted deployment, and there is no mandatory analytics or telemetry.

## What the installation stores

The SQLite database contains operational state needed to synchronize calendars:

- Directional Sync Rules, calendar and Connected Account identifiers, mappings, cursors, operation
  state, incidents, and run outcomes.
- Connected Account identity details such as the Google email, display name, avatar URL, and cached
  calendar names. OAuth credentials are encrypted with the Installation Master Key.
- Audit Entries, including the source event title and time needed to make Activity useful. These
  values are plain text in SQLite.
- Source Observations and Source Changes. Descriptions, locations, guest addresses, recurrence, and
  conferencing values are sealed with a key derived from the Installation Master Key. Earlier values
  are retained for the configured history window described in [Deployment](deployment.md).
- Password hashes and administrator session hashes. Plaintext administrator passwords and session
  tokens are never stored.
- Integration Tokens: each token's name, scope, and issue, last-use, and revocation times, with a
  SHA-256 hash of the token. The token itself is shown once when issued and never stored.

Service log lines contain identifiers, counts, timings, and provider status categories. They do not
contain event titles, descriptions, locations, guests, calendar identifiers, account emails, or
provider payloads. The operator can turn file logging off and can download or purge the local log
files from Settings.

## What can leave the machine

The installation communicates with:

1. Google APIs, to authorize Connected Accounts and read or write the calendars selected by rules.
2. A webhook URL or SMTP server only when the Installation Administrator explicitly configures an
   Incident Notification channel. Notifications contain an incident category, rule identifier,
   summary, and timestamp; they do not contain event content.
3. Monitors, dashboards, and AI agents the Installation Administrator gives an Integration Token.
   They ask for Installation Status; Calendar Ghost never contacts them. Status contains rule
   identifiers and states, calendar names, Provider Kinds, incident summaries, and times; it never
   contains event content, calendar identifiers, or account emails. An agent may pass what it reads
   to its own model provider, so issue tokens only to tools you trust with that.

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
  to the administrator's choice.
- To remove an entire self-hosted installation, stop the service, retain or destroy backups according
  to the operator's retention policy, remove the Compose data volume, and delete the protected local
  secrets. Verify that no external backup or snapshot still contains the database.

The local operator controls the host, the database, the master key, and the retention policy. Google
continues to control the source and destination data stored in Google Calendar; Calendar Ghost only
manages the projections authorized by the operator's rules.
