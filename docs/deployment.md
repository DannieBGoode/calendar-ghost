# Deployment

For the first-time, step-by-step setup, including creating a Google Cloud OAuth application and
registering a Microsoft Entra application, see the [self-hosting guide](self-hosting.md).

## Docker Compose

Copy `.env.example` to `.env`, configure the Google or Microsoft OAuth values of each provider you
offer, and run:

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
clearing old Activity from **Settings → Administration → Storage**
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

Migration 19 adds the nullable `message_code` and `message_params` columns to `incidents`: what
each Incident says as a stable code and JSON parameters, which the Web UI translates
([ADR 0026](adr/0026-translate-the-web-ui-through-message-catalogs.md)). No row is rewritten:
Incidents recorded earlier keep no message and the Web UI shows their stored English summary.
Rolling back works with the same database: earlier releases ignore the columns. An earlier release
that refreshes an open Incident updates its summary but not its message, so after upgrading again
that Incident can show a stale message until it is next refreshed.

Migration 20 records Lapsed Authorization
([ADR 0027](adr/0027-lapsed-authorization-and-automatic-recovery.md)). It adds the nullable
`authorization_lapsed_at` column to `connected_accounts` and `awaiting_reauthorization` to
`sync_rules`, and replaces the `incidents.resolution` column, keeping its values, so it also
accepts `access_restored`. On upgrade, a connected account that an open authorization Incident names
and that was not reauthorized since is marked lapsed, and degraded rules that such an Incident
stopped are marked to resume with it, unless the rule was changed materially since or uses a
disconnected account; those still need a recovery preview. Rolling back works with the same database: earlier releases
ignore the new columns, so lapsed accounts show as connected again and their rules need a recovery
preview. An earlier release cannot read an Incident resolved as `access_restored`, so Activity's
incident list fails until those Incidents are removed with their rules or accounts, or the
release is upgraded again.

Migration 21 makes every record belong to a User
([ADR 0029](adr/0029-isolate-users-in-one-sqlite-database.md),
[ADR 0030](adr/0030-users-administrators-and-registration.md)). It adds the `users` table and turns
the single administrator into User #1: an Installation Administrator with the same password and no
email. Every Connected Account, rule, mapping, cursor, Audit Entry, Incident, Integration Token,
and session is given to that User, and the administrator stays signed in. SQLite cannot add the new
references to an existing table, so the migration rebuilds every owned table with a `user_id`
column and a reference to its parent by identifier and User together. Rows an earlier release left
without their rule, such as a failure count of a removed rule, are not copied, because nothing could
read them. Unfinished Google consent started before the upgrade is forgotten; start it again. The
migration runs in one transaction and checks every reference before it commits: if any record would
refer to one that does not exist, the service stops with a message naming the table and the database
is left exactly as it was. Back up the data directory before upgrading, as always: the rebuild
rewrites every owned table, so the database is briefly about twice its size. Rolling back past
migration 21 means restoring that backup: an earlier release cannot read the rebuilt tables, and
records made after the upgrade are lost with the restore. After upgrading, the administrator signs
in with their password alone once and must then add an email; from then on they sign in with email
and password. The installation starts with the Only Me Registration Policy, so nothing changes for
anyone else until the administrator invites someone.

Migration 22 adds the Registration Policy, Only Me for new and upgraded installations, and the
hashed Invitations and Password Reset Links. Migration 23 gives Integration Tokens scopes: every
token issued before the upgrade keeps `status:read` and gains `installation:read`, so an existing
monitor keeps receiving the answer it received before. Rolling back past either means restoring the
backup taken before the upgrade, as for migration 21.

Migration 24 adds `sync_rules.creation_order`, the order each User's rules were created in, so the
Operator Overview numbers a User's calendars the same way on every visit ("Calendar 1",
"Calendar 2"). Rules that existed before the upgrade are numbered in the order the database holds
them, which is the order they were created unless the database was compacted since. Rolling back is
safe: earlier releases ignore the column. A rule an earlier release creates has no place in that
order, so after upgrading again its calendars are numbered first, and the other labels move up.

Migration 25 adds `provider_calls`: for each User, calendar provider, and UTC day, how many calls
their Sync Runs, reconciliations, and Rule Removals made, how many the provider refused for its
rate limit, and how many failed. It holds counts only, never what a call asked for. Each scheduler
pass discards days older than 30, so the table stays small, and User Deletion removes a User's
counts with them. The Operator Overview shows these counts. Rolling back is safe: earlier releases
ignore the table, and its counts stop growing until the next upgrade.

Migration 26 adds the nullable `incidents.cause` and `rule_run_outcomes.failure_cause` columns:
why each failure happened, as a Cause read from the provider's reason code, never its message
([ADR 0031](adr/0031-keep-the-providers-reason-as-a-cause.md)). No row is rewritten: failures
recorded earlier read as `unknown`. A failure no provider answer explains, such as one inside
Calendar Ghost, is stored as `none` and has no Cause, as Incidents about blocked events do. Rolling back
works with the same database: earlier releases ignore the columns. An earlier release that refreshes
an open Incident or records a failed run leaves the Cause it found, so after upgrading again that
Incident or run can show a stale Cause until it fails again.

Migration 27 adds the nullable `incidents.provider` and `rule_run_outcomes.failure_provider`
columns: the Provider Kind whose answer gave a failure its Cause, so Installation Hints and the Web
UI name the provider and link its own troubleshooting section. Every Cause recorded before it was
Google's, so the migration fills in `google` wherever a Cause was recorded. Migration 28 adds
`oauth_states.provider`, so a consent that returns to another provider's callback is refused;
consent begun before the upgrade was Google's. Rolling back past either is safe: earlier releases
ignore the columns.

Migration 30 adds `sync_rules.birthday_policy` (default `exclude`) and sets every rule's
reprojection flag ([ADR 0035](adr/0035-leave-out-birthdays-unless-a-rule-syncs-them.md)). Existing
rules keep running without a new preview: their next run lists both calendars in full and deletes
the projections of the contacts' birthdays Google keeps in a primary calendar. Activity records
these as `birthday_removed`. Rolling back works with the same database: earlier releases ignore the
column and project birthdays again on their next full pass.

Migration 31 adds the owned tables `calendar_watches`, `watch_coverage`, `watch_registrations`,
and `instant_sync_requests`, each with `user_id` and references that are removed with their
account, rule, and User; the column `users.instant_sync` (default `1`, on); and the installation
table `delivery_evidence` ([ADR 0036](adr/0036-instant-sync-through-provider-notices.md)). Nothing
is rewritten: watches appear at the first upkeep after start, within five minutes, and only when
`CALENDAR_SYNC_PUBLIC_URL` is an `https` address. Rolling back works with the same database:
earlier releases ignore the tables and column and no longer answer at `/api/v1/watch-notices/`,
so Google and Microsoft receive `404` until their registrations expire, within about 7 days,
while rules keep syncing every five minutes. Upgrading again keeps registrations that are still
live, and deletes and creates again those that expired.

Migration 32 adds the nullable `audit_entries.run_reason`, `found_by`, and `source_comparison`
columns: codes that say why a Sync Run read the calendars, which work found the event, and how the
source compared with the rule's Source Observation ([ADR 0037](adr/0037-record-a-decision-only-when-it-says-something-new.md)).
Earlier entries keep `NULL`. Rolling back works with the same database: earlier releases ignore the
columns, and record the repeated skips the newer release leaves out.

Migration 33 adds Plans ([ADR 0028](adr/0028-plans-apart-from-commercial-mode.md),
[ADR 0038](adr/0038-plans-allowances-and-limits.md)): the installation table `plans`; the columns
`installation_settings.plans_enabled` (default `0`, off) and
`installation_settings.default_plan_key`; each User's own Plan in `users.plan_key`, with who
assigned it and when (`plan_assigned_by`, `plan_assigner_id`, `plan_assigned_at`); and
`sync_rules.keeps_place`, which marks a Rule Replacement draft that keeps the place of the rule it
replaced under its User's rule limit. Nothing is backfilled: Plans start off and limit nobody, and
a User with no Plan of their own has the Default Plan once one exists. The database refuses to
delete a Plan that a User or the default still names. Once an administrator turns Plans on, a
lowered rule limit refuses new Starts and stops nothing. Rolling back works with the same
database: earlier releases ignore the table and the columns, and limit nobody. After upgrading
again, Plans are as the administrator left them.

Sign-in failures are counted per email and per client address for 15 minutes: after five failures
for one email, or twenty from one address, sign-in answers `429` with a `Retry-After` header until
the oldest failure leaves the window. Behind a reverse proxy every request comes from the proxy's
address, so the per-address limit is shared by everyone behind it. The counts are kept in memory,
so a restart forgets them.

Run one application process per SQLite database. The shipped container uses one Uvicorn process and
serializes concurrent scheduler and manual executions of the same rule in memory. A scheduler pass
runs up to four different rules at once, so one rule waiting on its provider does not hold up the rest.
Instant Sync runs up to two more at once, apart from the scheduler's, so scheduled and instant
runs together reach at most six; a manual run, such as **Sync now**, comes on top. Each of these
loops has worker threads of its own, apart from those the Web UI's requests use, so neither holds
up the other.
Multi-process workers are not supported with the SQLite deployment.

The database uses SQLite's write-ahead log, so Web UI reads and scheduler writes do not wait for
each other. SQLite keeps it in `calendar-sync.db-wal` and `calendar-sync.db-shm` beside the
database; they belong to it, so keep all three together, and keep the data directory on a local
disk rather than a network share, where SQLite cannot coordinate the log. The first start of this
release switches an existing database to the write-ahead log, and rolling back keeps it: earlier
releases read it without change.

The service logs to standard error at `CALENDAR_SYNC_LOG_LEVEL` (`INFO` by default; `DEBUG` adds a
line per provider call). Compose keeps the container's logs with the `json-file` driver capped at
three files of 10 MB, so a long-running Raspberry Pi does not fill its storage. Read them with
`docker compose logs -f app`; [Troubleshooting](troubleshooting.md#reading-the-logs) explains each
line.

The service also writes its own lines, those of the `calendar_sync` loggers, to rotating log files,
next to the database by default: `<database directory>/logs/calendar-sync.log` plus up to four
rotated files: at most five files of 5 MB each, 25 MB in total. The oldest is deleted when the
current file fills. Uvicorn's request and error lines stay on standard error only, so they appear in
`docker compose logs` but not in these files. Compose passes `CALENDAR_SYNC_LOG_DIR` from `.env` and
defaults it to `/data/logs` on the data volume when it is unset, as it is in `.env.example`. Set it
to another path to use a different directory (inside the container, on a mounted volume so the files
survive a rebuild), or set it to an empty value to turn file logging off; if the configured
directory cannot be used, the service logs one warning, keeps logging to standard error, and
Settings shows file logging as off. **Settings → Administration → Storage** shows these files' size
and date range and offers Download and Purge logs, so an administrator can retrieve or clear them
without SSH access to the host.

For access beyond localhost or a trusted LAN, place the service behind HTTPS and set `CALENDAR_SYNC_SECURE_COOKIES=true`. Do not expose the service directly to the public internet. [Instant Sync](instant-sync.md) needs
Google and Microsoft to reach only `/api/v1/watch-notices/`: forward that path through HTTPS and
keep the rest on your network.

## Raspberry Pi

The image targets `linux/arm64` as well as `linux/amd64`. Use a 64-bit Raspberry Pi OS, durable storage for the Docker volume, and a time-synchronized host. Scheduled Sync every five minutes needs no public address, so a Pi on a home network works as
it is. [Instant Sync](instant-sync.md) is optional: Google and Microsoft must reach the Pi at a
public HTTPS address, which a home network usually gets through Cloudflare Tunnel rather than an
open router port.

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

If you serve the installation through a reverse proxy, pass the `Authorization` request header
through unchanged, and route `/mcp` as well as `/api/`: monitors and agents send their Integration
Token in that header ([self-hosting guide](self-hosting.md#6-connect-monitors-and-agents)).

The redirect URI must match the Google OAuth client exactly, including scheme and port. When the
address in the browser differs from the configured redirect URI, Settings says so in a quiet note
at the foot of Connected accounts. For 10 minutes after you start connecting from that browser, it asks
for the address Google returned to instead: pasting it finishes the connection at the address you
are using, without a tunnel.

## Microsoft (Outlook) settings

Outlook calendars connect through a Microsoft Entra application the installation registers
([self-hosting guide](self-hosting.md), [ADR 0034](adr/0034-outlook-through-microsoft-graph.md)).
Without its settings, the installation behaves as before and offers no Microsoft account.

- `CALENDAR_SYNC_MICROSOFT_CLIENT_ID` and `CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET`: the
  application's client ID and a client secret. A secret expires on the date chosen when it was
  created, at most 24 months later; create the next one and put it here before then
  ([rotating the secret](self-hosting.md#register-a-microsoft-entra-application)).
- `CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET_EXPIRES`: optional, the secret's **Expires** date from
  Entra, such as `2027-04-12`. Calendar Ghost cannot read the date from Microsoft. With it,
  Installation Health raises an installation Incident from 30 days before the date, which People,
  `GET /api/v1/installation/health`, and the installation's email and webhook report. Change it
  together with the secret.
- `CALENDAR_SYNC_MICROSOFT_REDIRECT_URI`: the redirect URI registered on the application, by default
  `http://localhost:8000/api/v1/oauth/microsoft/callback`. Microsoft, like Google, accepts plain
  `http://` only for `localhost`, so a LAN host uses an SSH tunnel or an HTTPS name exactly as
  described above, with `/api/v1/oauth/microsoft/callback` as the path.
- `CALENDAR_SYNC_MICROSOFT_TENANT`: which accounts may sign in, `common` by default for personal
  and work or school accounts. `organizations` admits work or school accounts only, `consumers`
  personal ones only, and a tenant ID only that organization's accounts.

## Secrets

Keep Google and Microsoft client credentials and the installation master key outside the database
and repository. Use Docker secrets or a root-readable environment file. Database backups cannot restore connected accounts without the separately backed-up master key.

The database also holds each observed event's description, location, guest addresses, recurrence,
and conferencing links, sealed with a key derived from the master key, and 90 days of their earlier
values ([ADR 0017](adr/0017-record-source-changes.md)). A backup kept with the master key can
reveal them, and a backup keeps values older than 90 days until it rotates. Replacing or losing the
master key makes that history unreadable: Activity then lists which fields changed without their
values, and each event's next change is described afresh.

Clearing old Activity from **Settings → Administration → Storage** removes rows from the live database
only; a backup taken before the clear keeps those entries until it rotates out of your backup
schedule ([ADR 0019](adr/0019-administrator-chosen-activity-retention.md)).

Disconnecting a Google or Microsoft identity from **Settings → Connections** replaces its encrypted credential
payload with an empty encrypted value. Directional Sync Rules and their mappings remain in SQLite so
the same identity can be reauthorized and reconciled later.

## Incident notifications

Incidents always appear in the Activity screen of the User they belong to
([ADR 0030](adr/0030-users-administrators-and-registration.md)).

Set `CALENDAR_SYNC_SMTP_HOST` and `CALENDAR_SYNC_SMTP_SENDER` (credentials are optional) and the
installation sends email: each User then also receives their own rules' and accounts' Incident
Notifications at their email, unless they turn them off in **Settings → Your account**. No User
receives another User's incidents.

Set `CALENDAR_SYNC_PUBLIC_URL` to the address people open Calendar Ghost at, such as
`https://calendar.example.com` or `http://192.168.1.50:8000`, and each email links to the page
holding the incident's one next step, the same one Activity offers
([ADR 0031](adr/0031-keep-the-providers-reason-as-a-cause.md),
[ADR 0033](adr/0033-decide-an-incidents-next-step-in-the-domain.md)): their calendar connections to
reauthorize, the rule to review or choose another calendar, the rule's blocked events, or the
Overview when there is nothing for them to do. The link names a page and at most a rule's internal identifier, never a calendar,
account, or event. Only an `http` or `https` address at the root of its host, with no path or query, is used, because
the Web UI is served at the root of its address; otherwise email is sent without a link, as before.
An `https` address also makes [Instant Sync](instant-sync.md) possible.

The installation's own channels hear only of incidents about the installation itself, which affect
every User; the first is a scheduler that stopped completing passes. Set
`CALENDAR_SYNC_SMTP_RECIPIENT` to email them to an operator, and
`CALENDAR_SYNC_INCIDENT_WEBHOOK_URL` to receive a JSON POST, whose `rule_id` is `null` and whose
`category` is `scheduler_stalled`. Before Users existed these channels received every rule incident;
after upgrading, rule incidents reach the first User by email once they add an email and SMTP is
configured. Delivery is deduplicated while an incident remains open and failures never stop
synchronization or local incident recording.
