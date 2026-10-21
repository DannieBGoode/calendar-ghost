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

## Migration 34: Plan Hold engine

Migration 34 is additive: `sync_rules.plan_kept` defaults to 0; `users.plan_holds_at`,
`plan_grace_limit`, and `plan_grace_admissions` are nullable; and `users.plan_admissions` defaults
to 0. There is no new table and no existing rule becomes held on upgrade (ADR 0039). This PR 2
build explicitly disables settlement in production composition. Lowering a rule limit continues
to refuse new Starts and stops nothing; no grace or Plan notice starts. PR 3 will activate the
engine together with visible grace/hold state, status, Dashboard, MCP, and the keep form.

A database from a future activated release may contain hold code 2 in
`sync_rules.awaiting_reauthorization`. Code from before migration 34 ignores the new columns,
reads 2 as Lapsed Authorization, and still counts it at Start. Older raw `plan_use` display counts
may omit it because they select exact code 1. Every old save replaces 2 with 0 or 1.
Unfinished-lapse discovery also selects exact code 1, so a User with only code-2 rules can remain
stopped. Restoring an account or a passing access check can recover them under that older code;
otherwise preview and Start within the limit. On re-upgrade, code 1 may automatically resume
without a new limit check; if that creates excess, an activated engine starts a new seven-day grace.

Rolling back to this PR 2 build behaves differently: it recognizes code 2 as Plan Hold and
Reauthorization never releases it, but its production scheduler does not run releases. Upgrade to
an active release, or pause the rule to clear its hold, then preview and Start within the limit.
Preview alone preserves a hold. Back up the data directory before changing releases.

Sign-in failures are counted per email and per client address for 15 minutes: after five failures
for one email, or twenty from one address, sign-in answers `429` with a `Retry-After` header until
the oldest failure leaves the window. The per-address key is the client Uvicorn resolves. Without
trusted forwarded headers, proxy clients share the proxy's peer address; correctly configured
trusted proxies can separate them. Docker NAT may expose only one gateway address even for direct
clients. These sign-in counts are kept in memory, so a restart forgets them. Reset limits are
separate and persist when a Master Key exists, as described below.

## Trusted proxy headers

The container and packaged entry point explicitly default `FORWARDED_ALLOW_IPS` to an empty string:
no peer, including localhost, may supply trusted forwarded headers. Compose passes an empty string
when it is unset. Direct installations should keep this empty. Raw Uvicorn's own default is different;
when starting it yourself, use `FORWARDED_ALLOW_IPS=` and `--proxy-headers` explicitly.

Behind a reverse proxy, set `FORWARDED_ALLOW_IPS` to a comma-separated list of its actual peer IPs
or narrowly scoped networks, for example `192.0.2.10` or a dedicated proxy subnet. Never use `*`.
Use the addresses the application sees inside Docker, which may differ from host addresses. Restart
after changing the setting and verify separate clients receive separate allowances. IPv6 reset
and registration clients within one /64 intentionally share their purpose's allowance; another
/64 has its own.

The edge proxy must overwrite client-supplied forwarded headers with values derived from the
connection, including `X-Forwarded-For` and `X-Forwarded-Proto`; strip or overwrite unused
`Forwarded` and `X-Forwarded-Host` too. Restrict the application's published port to the proxy or
its private network so clients cannot bypass it. With multiple proxies, each trusted hop must
enforce the same rule. Preserve `Authorization`, route `/mcp` as well as `/api/`, use HTTPS, and
set `CALENDAR_SYNC_SECURE_COOKIES=true`. Header trust never selects the email link origin:
only the validated `CALENDAR_SYNC_PUBLIC_URL` does that.

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

## Identity email test readiness

In **Settings → Administration → Identity email**, **Send test email** tests the current identity
SMTP configuration to the signed-in Installation Administrator's email address. There is no
recipient field. This test ignores **Email notifications** and `CALENDAR_SYNC_SMTP_RECIPIENT`;
incident email retains its existing transport and preferences.

Set `CALENDAR_SYNC_SMTP_HOST` and `CALENDAR_SYNC_SMTP_SENDER`, with optional SMTP credentials.
For identity email, the sender must be a bare address such as `ghost@example.com`, without a
display name or address list. A malformed sender can appear configured but fail every test;
each admitted test still counts toward the hourly limit. Keep `CALENDAR_SYNC_SMTP_STARTTLS=true`
for a remote server. Identity email verifies the
server certificate with the system trust store and uses a 10-second socket timeout. Cleartext
is permitted only when the SMTP host is `localhost` or a literal loopback address, never merely
because a hostname resolves to one. Set `CALENDAR_SYNC_MASTER_KEY` and
`CALENDAR_SYNC_PUBLIC_URL` too. The latter must be an HTTPS root origin, such as
`https://calendar.example.com`; HTTP is permitted only for `localhost` or literal loopback
development. User information, a path other than `/`, query, fragment, invalid port, or another
scheme makes identity email unavailable. Restart the service after changing environment settings.

A queued request is not success. The UI polls while queued or sending, then reports whether the
mail server accepted the test. Acceptance does not prove inbox delivery: check the administrator's
inbox and spam folder. **Last verified for these settings** is durable evidence for the matching
configuration; a failed latest attempt does not erase it. A failure can also mean that SMTP
accepted the mail but readiness could not be stored. Changed SMTP settings, credentials, public
origin, or Master Key invalidate the matching verification status. Returning to setup clears it.

Each administrator may request three tests per rolling hour. One worker and one sending thread
serve at most ten waiting requests, without retries or a persistent mail outbox. Shutdown,
restart, queue saturation, or a delivery/storage failure can lose a test; request another after
checking the settings and respecting the hourly cap. No passwords enter queued work.
Preparation, SMTP, or readiness-storage exceptions emit the generic warning
`Identity email test failed`, without identifiers, addresses, settings, exception text, or
tracebacks. Normal stale eligibility and cancellation emit no failure warning.

### Migration 35 identity email readiness

Migration 35 adds an installation-wide readiness record and per-administrator test admission
counters. It preserves existing accounts, registration policies, and ordinary email changes. That
migration alone enabled no new registration or email-change flow; migration 38 adds Open. A
successful test never changes the selected Registration Policy. Password recovery is independently
available with usable configuration, without requiring a successful test.

Before upgrading, stop the service and back up the complete database and its matching Master Key,
keeping the previous image version. Migrations run at startup. For rollback, stop the service and
restore the matching pre-upgrade database backup and previous image together. Do not open the
upgraded database with the previous image or manually remove migration records. Changes made
after the backup are lost on restore. A later upgrade from that pre-upgrade backup creates fresh
readiness with no restored test verification.

## Migration 36 reset proof binding

Migration 36 adds a monotonic credential revision and binds Password Reset Links to it. It
revokes outstanding reset links from earlier releases because they have no trustworthy binding.
An administrator must issue a replacement link after upgrading. Existing passwords, sessions,
owned calendar data, Plans, and installation settings are preserved. Issued administrator links
still last seven days. Reset completion checks the active User, credential revision, and expiry
under the final write lock, then changes the password and ends every browser session and other
reset proof together. Password or email changes and disabling a User invalidate earlier proofs;
changing the email back or enabling the User again never revives one.

Stop the service and back up the complete database and matching Master Key before upgrading,
keeping the previous image. Startup applies the migration once; a failure rolls it back. To roll
back releases, stop the service and restore the pre-upgrade database and previous image together.
Do not run the previous image against the upgraded database or remove migration records by hand.
Restoring discards changes since the backup. An administrator-issued link remains the recovery
fallback; an offline recovery command is not shipped.

## Migration 37 email-change proofs

Migration 37 adds only email-change storage: owned, expiring proofs and issuance allowances,
plus anonymous network-attempt counters. User ownership is non-null on proofs and issuance
rows, with deletion cascading from the User; network counters contain only purpose-separated
HMAC digests and times. Existing Users, passwords, sessions, calendars, reset proofs, and
installation settings are preserved. Startup applies the migration once, atomically.

Stop the service and back up the complete database with its matching Master Key before upgrading,
keeping the previous image. To roll back, stop the service and restore that pre-upgrade database
and previous image together. Do not run the previous image against the upgraded database or remove
migration records. Restoring discards changes since the backup, including later proof and allowance
records. There is no down migration; the old binary must not open the upgraded schema. Do not
commit the backup, Master Key, or `.env`. New proofs store only token hashes and are never reusable
after a credential revision changes; a successful email change retains only its confirming session.

## Verified email changes

In **Settings → Your account**, a signed-in User requests a change with the current password.
Their old address remains the sign-in and password-recovery address until confirmation, so its
mailbox owner can still request a reset link. A request does not reserve the proposed address.
The pending request lasts 24 hours from request; the worker issues a single-use Email Change Link
that lasts 24 hours from preparation. Open the link in the requesting User's session (sign in there
if needed), then submit the current password again. The proof cannot be checked or completed with
an Integration Token or another User's session. A new request replaces the previous one; Cancel
invalidates it. A changed password, completed reset, direct email change, or disabled User also
invalidates it. Confirmation keeps the confirming session and Integration Tokens, ends other
browser sessions, and queues a notice to the old address after the database commit. Notice loss
cannot undo the change.

When SMTP host and sender are both absent, the ordinary password-confirmed direct change remains
available. A live pending request must be cancelled first. If either SMTP host or sender is set,
an incomplete or unsafe identity mail configuration refuses changes instead of selecting direct
mode. Remote SMTP requires certificate-verified STARTTLS, a bare sender, a Master Key, and a valid
HTTPS root `CALENDAR_SYNC_PUBLIC_URL`; localhost or literal loopback HTTP is for development.
An HTTP LAN origin cannot send verification links. The upgraded first active administrator who
has no email may still add one directly in the restricted session. A prior successful identity
test is useful but is not required for a change. Restart after changing environment settings.

Request acceptance does not promise a delivered link. The ten-slot security mail lane is shared
with administrator identity tests and old-address notices. Queue saturation, shutdown, restart,
or SMTP failure can lose proof or notice mail; there is no persistent outbox or automatic retry.
Check spam and configuration, then request a replacement when the limit permits. Each User has
five requests per rolling hour; a target address has a 60-second cooldown across Users. Each
client network has 20 requests, 20 invalid proof checks, and 10 current-password submissions per
15 minutes. IPv6 is grouped by /64 and at most 10,000 live network keys are held. A throttled
response includes `Retry-After`; an invalid or stale proof calls for a new request. An address
already held by another User is revealed only as a neutral failure at confirmation.

SQLite retains only hashed link tokens and pending address/revision/expiry state, not plaintext
tokens or mail bodies. With a Master Key, short-lived issuance and network counters survive
restart as purpose-separated HMAC digests; without it, new verified requests are unavailable
and existing proof completion uses bounded memory admission. The worker and admitted traffic
remove obsolete proofs and counters in batches of at most 500, aiming for removal within 24
hours while running. A stopped service, storage fault, or backup can retain them longer. Master
Key replacement changes digest keys, so old address/network allowances no longer match. It also
makes stored provider credentials and sealed history unreadable and invalidates matching email
readiness. There is no supported in-place rotation tool: retain the matching key with backups.

## Password recovery

With usable identity email configuration, **Forgot password?** on sign-in lets an active User,
including an Installation Administrator, request a single-use Password Reset Link lasting one
hour. Set the Master Key, SMTP host and bare sender address, and an HTTPS root
`CALENDAR_SYNC_PUBLIC_URL`; HTTP localhost or literal loopback is allowed only for development.
Remote SMTP requires certificate-verified STARTTLS. The same configuration predicate controls the
sign-in entry and request API; prior test-mail success is not required. Missing or unsafe settings
leave public recovery unavailable, while existing sign-in and synchronization continue.

An Installation Administrator can still create a hand-delivered seven-day link, including on an
HTTP LAN installation without SMTP or a Master Key. Previously issued valid links can complete
after email settings change. Both kinds change only an active User's password, end every existing
browser session and reset proof, and require the person to sign in afterward. They never enable a
disabled User. Requesting another emailed link preserves earlier delivered links until completion;
an administrator issuing a replacement revokes earlier reset links.
Reset retains Integration Tokens. After recovering access, review them in Settings and revoke any
you do not recognize.

The request response says, "If this address can receive a reset link, we will send one." The API
returns generic 202 acceptance for eligible, disabled, and unknown addresses, email suppression,
queue loss, and SMTP failure. Malformed input returns account-independent 422; network/global
throttling returns 429 with `Retry-After`, and unavailable configuration/storage returns 503.
No response promises delivery. Check spam and configuration, wait for limits, then retry the same
form if needed. There is no outbox or automatic retry: restart, shutdown, queue saturation, or
transport failure can lose mail. Aggregate queue/delivery latency can still vary with eligibility;
this flow does not claim constant-time SMTP privacy.
Request timing can also reveal recent reset-request activity for an address, because admitted and
silently suppressed requests do different storage work. This is independent of account existence.

Shutdown blocks old-generation delivery that has not already been authorized and old-generation
readiness updates. An already-authorized bounded SMTP send may finish. Short reset preparation
already in flight may finish after stop and leave an unused hash-only proof, without sending its
token. That proof expires and is cleaned up normally.

Identity security mail ignores **Email notifications** and the installation's incident recipient.
It goes to the User's current account email. Existing and Invitation Only addresses, including
direct email changes, remain eligible without retroactive verification. Check these addresses:
a typo or an address belonging to somebody else gives that mailbox owner password recovery access.
Only me remains the default. Open requires explicit administrator choice and tested identity email;
offline recovery tooling and the hosted backup runbook remain planned. Plans are independent.

### Recovery allowances and fallback

Reset admission has separate budgets from sign-in and Invitations. Per client network, a rolling
15-minute window permits 20 requests, 20 invalid-token checks, and 10 completion attempts. Valid
checks do not consume the invalid-token budget, but completion attempts consume their own budget
before proof lookup or hashing. The memory gate holds at most 10,000 networks and refuses new
ones when full rather than evicting a live allowance. IPv4 uses its address; IPv6 uses its /64.
A full memory gate also delays checking or completing an administrator-issued link from a new
network until capacity becomes available; a hand-delivered proof does not bypass that gate.

Durable requests additionally allow one request per email per minute, five per email per hour,
two per email/network pair per hour, and 100 across the installation per hour. Email and pair
suppression keep the generic acceptance response; network and global caps use 429. All admitted
requests count, including unknown addresses and mail lost later. An attacker can exhaust a
person's email allowance, or two sustained networks can exhaust the global allowance and delay
recovery for everyone. Wait for the window, or use an administrator-issued link. Global/email
request caps do not block administrator issuance, though token and completion network limits still
apply. If no administrator can sign in, use the existing stopped-service backup recovery procedure;
there is no offline password recovery command in this release.

### Recovery retention and Master Key rotation

Reset records retain hashed proofs, expiry/use/revocation times, issuer when administrator-issued,
and credential revision bindings. Admitted counters contain times and purpose-separated HMAC
digests of normalized emails, client networks, and pairs, derived from the Master Key with HKDF.
No plaintext counter addresses, networks, passwords, or mail bodies persist. Queued addresses and
delivery tokens live only in process memory. Auth diagnostics never include addresses, tokens,
passwords, request bodies, or provider exception text. The application sends no telemetry.

With a Master Key, allowances survive restart even without usable identity email, and the durable
reset admission adapter enables reset cleanup. Admitted requests, completion attempts, and hourly
worker maintenance then remove obsolete reset counters and expired, consumed, or revoked reset
proofs in batches of at most 500, aiming for removal within 24 hours while running. Token checks
do not remove proofs; invalid checks may remove obsolete counters only. The worker still runs
without SMTP or a Master Key for registration cleanup, which retains its 24-hour running target.
Without a Master Key, reset cleanup and public recovery are unavailable; reset records may remain
until the key is restored, and administrator token/completion limits use bounded memory only,
forgotten on restart. A stopped service or storage failure can delay cleanup. Backups retain
records until their own retention expires.
After an admission commits, a cleanup storage failure leaves that admitted request or completion
free to proceed. Cleanup retries during later admitted work or hourly maintenance; admission
decision failures still refuse work before queueing, proof lookup, or password hashing.

The digest keys are stable until the Master Key changes. Rotation changes email/network/pair
digests, so old address-specific allowances no longer match. Do not rotate the key to clear a
throttle. Planned key maintenance requires stopping the service and waiting at least one hour
after its last identity admission before restarting, so all previous allowances have elapsed.
Back up the matching key and database first. There is no supported in-place key rotation tool:
replacing the key also makes stored provider credentials and sealed history unreadable and clears
matching email readiness. A reset proof remains hash-bound, not encrypted with that digest key.

## Migration 38 Open registration

Migration 38 rebuilds `installation_settings` to accept `open`, preserving the selected
Registration Policy, `plans_enabled`, and `default_plan_key`. Fresh installations still start
Only Me; upgraded installations keep their existing policy. No upgrade selects Open or turns Plans
on. It adds `registration_proofs` and `registration_request_attempts` with expiry indexes and
independent admission keys; existing Users, passwords, sessions, calendar records, Invitations,
reset/email-change proofs, and Plans are preserved. Startup applies the migration atomically.

Before upgrading, stop the service, take a complete database/data-directory backup with its matching
Master Key, and retain the previous image version. There is no down migration. For rollback:

1. Close public registration by choosing Invitation Only before stopping the upgraded service.
   This cancels unfinished public proofs. If the service cannot operate, close ingress instead.
2. Stop the service and restore the matching pre-upgrade data directory, Master Key, and image
   together. All writes after that backup are lost, including new Users and calendar state.
3. Keep access closed while checking the restored policy and access. Do not start two writers.

Never run an old image against stored Open or the upgraded schema, even after changing the policy
back. Do not remove migration records or hand-edit the enum constraint. Restoring a backup can
revive previously revoked access; see [backup risks](data-ownership.md#backups-and-recovery).
The optional hosted backup runbook and offline recovery tooling remain unshipped.

## Verified registration

Only an Installation Administrator can choose Open, after usable identity email configuration and
a successful test for that exact fingerprint. See [identity email](#identity-email-test-readiness).
The policy write rechecks the actor's active administrator role and readiness atomically. Open
requires neither Plans nor Commercial Mode; both stay off by default. Joining creates an ordinary
User with no own Plan, so they follow the Default Plan, including later changes, when Plans are on.
Existing Users retain access without retroactive verification.

Sign-in shows **Create account** only while public joining is available. Requests ask for email
first and always say, "If this address can join, we will send a verification link." No account
lookup or SMTP is awaited by the handler. Existing and disabled addresses receive no sign-up mail
and are never changed; no account-exists message is sent. Pending Registration is not a User,
reserves nothing, and has no password or calendar access. People lists only completed Users with
the existing disable/delete actions, without a pending list or approval step.

A single-use Email Verification Link opens a password form bound to that address. It lasts 24
hours from issuance; an Invitation-bound link cannot outlive the Invitation's original seven-day
expiry. Checking the link consumes nothing. Completion rechecks current time, policy, readiness
under Open, Invitation validity, and address uniqueness under the final write lock; it creates
one User and consumes all registration proofs for the email atomically. The Invitation, if any,
is consumed only then. Hashing, SMTP, and session creation run outside that lock. A stale direct
Invitation form cannot bypass verification after switching to Open. If another operation takes
the address or Invitation first, completion refuses neutrally without changing that User.

Under Invitation Only, Invitations still join directly without SMTP. A previously issued
Invitation-bound verification link may also finish there without current SMTP/readiness. Only Me
refuses every join. Returning to Invitation Only atomically cancels pending public proofs; Only Me
cancels all registration proofs and still requires the sole-User condition. Reopening never revives
cancelled proofs. Returning to setup also revokes Invitations and clears readiness.

Lost or changed SMTP configuration, trusted origin, or matching readiness keeps Open selected but
makes public requests and completion under Open temporarily unavailable. Valid proofs are not
revoked merely by readiness loss. Fix configuration, restart if changed, and test the current
settings again. Existing sign-in and synchronization continue. A transient send failure does not
change policy or erase a previous matching successful test.

The normal session starts only after account creation commits, with the credential/state race
guard. If that phase fails, the account and consumed proof remain committed: sign in with the
password just chosen, rather than retrying registration. A replay cannot create another User.
All registration storage phases use at most 100 ms SQLite waits, including reads, cleanup, and
post-commit session creation, last-sign-in recording, and the User and Instant Sync reads needed
to assemble the complete response. If those reads fail after the account commits, the response
privately directs you to sign in; it sets no cookie. Plans reads still fail open. Ordinary identity
and direct Invitation reads/writes retain their five-second wait. New bodies are capped at 8 KiB,
normalized email at 254 characters, tokens at 128 ASCII characters, and verification passwords at 12 to 1,024 characters before storage or hashing.
Setup, direct Invitation, and ordinary new-password bounds remain unchanged.

### Registration limits, mail loss, and retention

Registration and reset have separate memory gates, purpose-separated HKDF/HMAC digest keys,
durable counters, and queue capacity. A sign-up flood cannot consume reset's reserved allowances
or waiting lane. Registration uses these rolling limits, without refunds after success:

| Boundary | Limit |
| --- | --- |
| Normalized email | 5 requests/hour, with a 60-second cooldown |
| Email and client network together | 2 requests/hour |
| Client network requests | 20/15 minutes |
| Installation requests | 100/hour |
| Invalid proof checks per client network | 20/15 minutes |
| Password completions per client network, including usable proofs | 10/15 minutes |

A network is one IPv4 address or IPv6 /64. The front gate holds at most 10,000 live networks and
refuses new keys when full. Admitted requests count before eligibility lookup, including unknown
and disabled addresses. Email/pair suppression keeps generic acceptance; network/global limits
return 429 with `Retry-After`. Malformed input is account-independent, and configuration/storage
failure returns temporary unavailability. Proofs are purpose-bound and cannot reset passwords or
change email. Tokens use 32 random bytes with only SHA-256 hashes persisted, appear in fragments
and bounded POST bodies, and never in query strings. Identity pages and responses, including
errors, use no-store/no-referrer. Logs exclude addresses, tokens, passwords, request bodies,
eligibility, and provider exception text.

The mail worker gives fair turns to 50 waiting registrations, 50 resets, and 10 shared security/test
messages on one SMTP thread, with the existing 10-second timeout. No passwords are queued. Queue
rejection, SMTP failure, restart, or shutdown can lose mail and still return generic acceptance;
there is no retry or durable outbox. Resend uses the same form and limits and preserves earlier
delivered links until one completes. Check spam and identity email configuration before resending.
Aggregate delivery latency and recent request activity may remain observable; this does not claim
constant-time SMTP or resistance to distributed denial of service.

Attackers can exhaust a person's email allowance or the installation allowance and delay joining.
Wait for the window or have an administrator close Open and use Invitation Only. Sign-up itself
gives existing Users no recovery access. For reset suppression, use an administrator-issued reset
link or wait; token/completion network limits still apply. If no administrator can sign in, use
the existing stopped-service backup recovery procedure. No offline recovery command is shipped.

SQLite keeps the Pending Registration email, optional Invitation reference, hash, and lifecycle
times, with no password, mail body, or plaintext token. Counters keep times and keyed digests,
separate from reset. Allowances survive restart with the same Master Key; rotating it changes
digest keys and invalidates matching email readiness, as well as making sealed data unreadable.
Do not rotate a key to bypass a throttle; follow [Master Key maintenance](#recovery-retention-and-master-key-rotation).
Maintenance and admitted traffic remove expired, consumed, or revoked proofs and obsolete counters
without the scheduler, aiming for removal within 24 hours while running. Batches reserve at most
250 deletions for proofs and 250 for counters, attempt both independently, and yield to mail between
full batches. A cleanup failure after admission commits does not reverse admission. Read-only
checks never purge proofs. Cleanup continues without SMTP or a Master Key. Stopped services and
storage faults can delay cleanup; backups keep records until their own retention expires.

## Incident notifications

Incidents always appear in the Activity screen of the User they belong to
([ADR 0030](adr/0030-users-administrators-and-registration.md)).

Set `CALENDAR_SYNC_SMTP_HOST` and `CALENDAR_SYNC_SMTP_SENDER` (credentials are optional) and the
installation sends email: each User then also receives their own rules' and accounts' Incident
Notifications at their email, unless they turn off **Email notifications** in **Settings → Your account**. No User
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

## Plan notice delivery when activated

The engine's Plan notices reuse each User's **Email notifications** preference, email address,
active state, and SMTP configuration. PR 2 production composition sends none; PR 3 must add the
visible Plan fallback before activation. Notices disclose counts and UTC deadlines only, with an
optional link to Your plan at the configured public address. They never reach the operator's
SMTP recipient or webhook, and create neither an Incident nor an Audit Entry.

Delivery uses one scheduler-owned mail worker, separate from rule slots and pass completion.
Notices leave a pass-local collector only after successful rule listing. A sending batch has at
most 100 notices; a newer pending notice replaces an older one for the same User. Pending notices
live only in memory. Failed or cancelled preparation, shutdown, restart, or SMTP failure can lose
them; there is no delivery retry or outbox. Stopping the scheduler cancels and awaits its sender,
without waiting for a bounded SMTP call already running or blocking the event loop on executor
shutdown. The same sole executor lasts for the Scheduler object's lifetime.
