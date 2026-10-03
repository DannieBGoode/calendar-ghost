# Deployment

For the first-time, step-by-step setup—including creating a Google Cloud OAuth application—see
the [self-hosting guide](self-hosting.md).

## Docker Compose

Copy `.env.example` to `.env`, configure Google OAuth values when the adapter is enabled, and run:

```sh
docker compose up -d --build
```

The Community Edition is a single-installation deployment: one administrator, one SQLite database,
one scheduler, and one application process. It does not require a Calendar Ghost account or hosted
control plane. Before using real calendars, read [Data ownership and privacy](data-ownership.md) for
the local data inventory, explicit network egress, backup requirements, and deletion behavior.

The named volume contains SQLite state. Back it up before upgrades. Releases run forward-only, idempotent migrations during startup so `docker compose pull && docker compose up -d` does not require wiping state. Applied versions are recorded in `schema_migrations`, and each upgrade commits atomically with its ledger row.

Migration 2 adds a nullable `connected_accounts.avatar_url` column for Google profile photos. Earlier
releases ignore the column, so rolling back to the previous image works with the same database.

Migration 3 adds nullable `reason` and `run_id` columns to `audit_entries` and backfills reason codes for entries written by earlier releases. Rolling back to an earlier image is safe: older releases ignore the added columns. Entries written by the older release have no reason code or run identifier and appear in Activity with their original wording.

After upgrading, reload every open Calendar Ghost tab. The web page is served with
`Cache-Control: no-cache`, so a normal reload picks up the new release. Releases before this header
may be cached by the browser: after the first upgrade from such a release, hard-refresh each tab
once. The upgrade that moves audit entries from `/api/v1/activity` to `/api/v1/audit-entries`
removes the old path, so a page loaded before it cannot show Activity until it is reloaded. Pages
from this release onward recognize a removed API path and ask you to reload. The favicon is served
from a content-hashed URL, so the same reload replaces a tab icon the browser cached from an earlier
release.

Migration 4 adds `sync_rules.reprojection_required` (default `0`) and the `rule_run_outcomes`
table, which stores only timestamps, counts, and failure categories for the Rule Details view.
Rolling back to the previous image works with the same database: it ignores the new column and
table and leaves the flag untouched. The previous image does not rewrite existing projections after
a policy change; upgrading again resumes the pending reprojection. Rules whose removal was
interrupted stay inert on the previous image, which cannot finish the removal.

Migration 5 adds the `occurrence_mappings` table for recurring-event ownership and clears every
rule's incremental positions once, so the next run re-reads the Initial Sync Window and backfills
recurring series that earlier releases skipped. Enabled rules project them automatically; to review
recurring projections first, pause rules before upgrading, then preview and enable them. Rolling
back works with the same database: earlier releases ignore the table and skip recurring events, so
existing recurring projections stay unchanged until you upgrade again.

Migration 6 adds the `rule_previews` table, which keeps only the timestamp and counts of each
rule's latest Rule Preview so the Web UI can restate them before a rule starts syncing, and a
`rule_run_outcomes.last_succeeded_at` column that keeps the last successful run's time across
later failures, backfilled from existing successful outcomes. Rolling back works with the same
database: earlier releases ignore the table and column, and a rule previewed on the newer release
still enables normally. Rows are removed with their rule.

Migration 7 adds an index on `audit_entries(run_id, id)` so reading one run's audit entries does
not scan the whole audit history. Rolling back works with the same
database: earlier releases ignore the index.

Migration 8 adds `rule_run_outcomes.last_full_succeeded_at`, the time of each rule's last successful
full synchronization, backfilled where the latest recorded run was a successful full run. The
scheduler uses it to run each rule's daily full pass once per UTC day across restarts. Rolling back
works with the same database: earlier releases ignore the column and return to running the daily
pass after every restart. Audit entries are unchanged; entries with reasons that are no longer
recorded stay in the database and are hidden from Activity.

Migration 9 adds nullable `event_title`, `event_starts`, and `event_ends` columns and zero-default
`event_all_day`, `event_recurring`, and `event_cancelled` columns to `audit_entries`, plus an index
on `audit_entries(rule_id, source_event_id, id)`. New entries record their source event's title and
time; existing entries are not backfilled and appear in Activity without an event name. Rolling back
works with the same database: earlier releases ignore the columns and index and look titles up from
Google again, but recorded titles stay in the database until their entries are deleted, including by
clearing old Activity from Settings → Storage
([ADR 0019](adr/0019-administrator-chosen-activity-retention.md)).

Migration 10 adds the `pending_exception_replays` table, which stores only the identifier of each
Series Mapping whose source Occurrence Exceptions still have to be applied after an incremental run
created or restored its series. Rows are removed once the replay completes, and with their Series
Mapping. No state is rewritten: a recurring series that earlier releases kept restoring and
removing because every occurrence was cancelled settles on the first run after upgrading. Rolling
back works with the same database: earlier releases ignore the table, leave unfinished replays to
their daily full pass, and resume recreating such series on every run. Upgrading again finishes or
clears any remaining rows.

Migration 11 adds the `rule_block_checks` table, which stores for each rule only the identifier of
the newest audit entry before its latest successful daily pass and when that pass finished. Blocks
recorded since then are the rule's open blocks; the daily pass decides every blocked event again,
so an older block it did not repeat is no longer open. Rows are removed with their rule. No state is
rewritten: until a rule's first daily pass after upgrading, all of its blocks that are still the
latest decision about their event count as open. Rolling back works with the same database: earlier
releases ignore the table and do not report blocked events on the Overview.

Migration 12 adds the `resolution` column to `incidents`, recording why each Incident resolved: a
successful sync, a daily pass that found nothing still blocked, or the removal of its rule.
Incidents resolved earlier keep no resolution, because the reason was not recorded, and Activity
shows them only as resolved. Rolling back works with the same database: earlier releases ignore
the column. An Incident an earlier release reopens keeps its stale resolution until it resolves
again, which Activity never shows while the Incident is open.

Migration 13 adds the `account_id` column to `incidents`, naming the Connected Account whose
failure opened or last refreshed each Incident. Activity offers to recover a rule after an
authorization failure only once that account was reauthorized. Incidents recorded earlier keep no
account, and for them Activity waits until every account of the rule was reauthorized after the
failure. Rolling back works with the same database: earlier releases ignore the column.

Migration 14 adds the `source_observations` table and the nullable `change_fields`,
`change_title_before`, and `change_sealed` columns to `audit_entries`, plus a partial index on
`audit_entries(occurred_at)` for entries that still have sealed values
([ADR 0017](adr/0017-record-source-changes.md)). Observations hold each source event's title in
plain text and its other tracked details sealed with a key derived from the master key; rows are
removed with their rule. No state is rewritten: existing entries record no Source Change, and each
event's first decision after upgrading records its observation without a change, so changes are
described from the next revision on. Rolling back works with the same database: earlier releases
ignore the table, columns, and index, and again rewrite projections on every new source revision.
They also do not clear sealed values after 90 days, so values recorded before the rollback stay in
the database until a later release clears them. Upgrading again compares each event with the
observation recorded before the rollback, so changes made in between are described as one change.

Migration 15 adds `sync_rules.tentative_policy` (default `mark`) and
`sync_rules.unanswered_policy` (default `as_tentative`), and sets every rule's reprojection flag
([ADR 0018](adr/0018-project-by-invitation-response.md)). Existing rules keep running without a new
preview: their next run lists both calendars in full, retitles projections of events answered Maybe
as "Busy (tentative)" or "Maybe: …", and deletes projections of declined events. Activity records
these as `policy_applied` and `declined_removed`. Rolling back works with the same database: earlier
releases ignore the columns, rewrite the tentative titles back on their next full pass, and recreate
projections of declined events still in the sync window.

Migration 16 adds `calendar_names`, the name each calendar last had in Google. It is filled whenever
an account's calendars are listed, so rules show their calendars' names on a reload before Google
answers, and after their account is disconnected; deleting an account deletes its names. Existing
rules show placeholder names until their calendars are next listed, which opening the Rules view
does. Rolling back works with the same database: earlier releases ignore the table.

Migration 17 rebuilds `connected_accounts` so its `provider` column accepts any Provider Kind; code
validates the value, so adding a provider needs no further schema change
([ADR 0022](adr/0022-route-calendar-requests-by-provider.md)). Every account and every recorded
calendar name is kept. Rolling back past it means restoring the backup taken before the upgrade: a
database that stores another provider's account cannot be opened by a release that does not know
that Provider Kind.

Run one application process per SQLite database. The shipped container uses one Uvicorn process and
serializes concurrent scheduler and manual executions of the same rule in memory. Multi-process
workers are not supported with the SQLite deployment.

The service logs to standard error at `CALENDAR_SYNC_LOG_LEVEL` (`INFO` by default; `DEBUG` adds a
line per Google call). Compose keeps the container's logs with the `json-file` driver capped at
three files of 10 MB, so a long-running Raspberry Pi does not fill its storage. Read them with
`docker compose logs -f app`; [Troubleshooting](troubleshooting.md#reading-the-logs) explains each
line.

The service also writes its own lines, those of the `calendar_sync` loggers, to rotating log
files, next to the database by default: `<database directory>/logs/calendar-sync.log` plus up to
four rotated files: at most five files of 5 MB each, 25 MB in total. The oldest is deleted when the
current file fills. Uvicorn's request and error lines stay on standard error only, so they appear in
`docker compose logs` but not in these files. Compose passes `CALENDAR_SYNC_LOG_DIR`
from `.env` and defaults it to `/data/logs` on the data volume when it is unset, as it is in
`.env.example`. Set it to another path to use a different directory (inside the container, on a
mounted volume so the files survive a rebuild), or set it to an empty value to turn file logging
off; if the configured directory cannot be used, the service logs one warning, keeps logging to
standard error, and Settings shows file logging as off. Settings
→ Storage shows these files' size and date range and offers Download and Purge logs, so an
administrator can retrieve or clear them without SSH access to the host.

For access beyond localhost or a trusted LAN, place the service behind HTTPS and set `CALENDAR_SYNC_SECURE_COOKIES=true`. Do not expose the service directly to the public internet.

## Raspberry Pi

The image targets `linux/arm64` as well as `linux/amd64`. Use a 64-bit Raspberry Pi OS, durable storage for the Docker volume, and a time-synchronized host. Five-minute polling avoids a public Google webhook.

## Google OAuth redirect URI on a LAN host

After consent, Google sends the browser to `CALENDAR_SYNC_GOOGLE_REDIRECT_URI`. The browser, not
the server, follows that redirect, so the address must reach this installation from the machine
you connect accounts from. Google accepts plain `http://` redirect URIs only for `localhost`; LAN IP
addresses such as `http://192.168.1.50:18000` and `.local` names are rejected. For a Raspberry Pi
or another LAN host, choose one:

- **SSH tunnel.** Keep the default `http://localhost:<port>/api/v1/oauth/google/callback`, run
  `ssh -N -L <port>:localhost:<port> <user>@<host>` on your computer, and open Calendar Ghost at
  `http://localhost:<port>` while connecting or reauthorizing accounts. Synchronization does not
  need the tunnel.
- **HTTPS name.** Serve the installation over HTTPS with a publicly resolvable name, for example
  Tailscale Serve (`https://<host>.<tailnet>.ts.net`) or your own domain behind a reverse proxy.
  Register `https://<name>/api/v1/oauth/google/callback` on the Google OAuth client, set the same
  value in `CALENDAR_SYNC_GOOGLE_REDIRECT_URI`, and set `CALENDAR_SYNC_SECURE_COOKIES=true`.

The redirect URI must match the Google OAuth client exactly, including scheme and port. When the
address in the browser differs from the configured redirect URI, Settings says so in a quiet note
at the foot of Connected accounts. For 10 minutes after you start connecting from that browser, it asks
for the address Google returned to instead: pasting it finishes the connection at the address you
are using, without a tunnel.

## Secrets

Keep Google client credentials and the installation master key outside the database and repository. Use Docker secrets or a root-readable environment file. Database backups cannot restore connected accounts without the separately backed-up master key.

The database also holds each observed event's description, location, guest addresses, recurrence,
and conferencing links, sealed with a key derived from the master key, and 90 days of their earlier
values ([ADR 0017](adr/0017-record-source-changes.md)). A backup kept with the master key can
reveal them, and a backup keeps values older than 90 days until it rotates. Replacing or losing the
master key makes that history unreadable: Activity then lists which fields changed without their
values, and each event's next change is described afresh.

Clearing old Activity from Settings → Storage removes rows from the live database only; a backup
taken before the clear keeps those entries until it rotates out of your backup schedule
([ADR 0019](adr/0019-administrator-chosen-activity-retention.md)).

Disconnecting a Google identity from Settings replaces its encrypted credential payload with an
empty encrypted value. Directional Sync Rules and their mappings remain in SQLite so the same
identity can be reauthorized and reconciled later.

## Incident notifications

Incidents always appear in the authenticated Activity screen. Optionally set
`CALENDAR_SYNC_INCIDENT_WEBHOOK_URL` to receive a JSON POST when an incident opens. SMTP delivery
requires `CALENDAR_SYNC_SMTP_HOST`, `CALENDAR_SYNC_SMTP_SENDER`, and
`CALENDAR_SYNC_SMTP_RECIPIENT`; credentials are optional. Delivery is deduplicated while an
incident remains open and failures never stop synchronization or local incident recording.
