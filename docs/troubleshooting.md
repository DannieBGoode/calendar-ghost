# Troubleshooting

## The Web UI cannot reach the service

Check `docker compose ps`, then request `http://localhost:8000/health`. Review container logs without posting credentials or event payloads publicly.

## A monitor or agent cannot read status

`GET /api/v1/status` and `/mcp` accept an Integration Token from **Settings → Connections →
Integrations** ([self-hosting guide](self-hosting.md#6-connect-monitors-and-agents)). Check the
answer with `curl -i`:

- **401 `valid credentials required`.** The token is missing, mistyped, or revoked; every reason
  gets the same answer. Send it as `Authorization: Bearer cgs_…`, never in the address. A token is
  `cgs_` and 43 more characters; a partial copy is refused. If it was revoked or lost, issue a new
  one. An invalid `Authorization` header is refused even when the same
  browser is signed in, so a broken monitor credential never hides behind your session.
- **401 behind a reverse proxy, although `curl` on the host works.** The proxy is dropping the
  `Authorization` header. Configure it to pass the header through to Calendar Ghost.
- **401 on any other `/api/` route.** Expected. A token reads status only; Rules, Activity, and
  Settings need a signed-in session.
- **403 `insufficient_scope` from `/api/v1/installation/health`.** The token was issued without
  Installation Health. Issue one with it ticked; only an administrator can.
- **403 `administrator_required` from `/api/v1/installation/health`.** The person who issued the
  token is no longer an administrator, so the token reads only their own status now.
- **405 from `/mcp`.** The client sent `GET` or `DELETE`. The MCP server is stateless and answers
  `POST` only; use a client that speaks MCP over streamable HTTP.
- **404 from `/mcp/`.** The address has a trailing slash or a longer path. Use exactly `/mcp`.
- **503 from `/mcp`.** The service is starting or stopping. Try again after `/health` answers.

If status answers but its verdict surprises you:

- **`stalled` with `"scheduler": {"configured": false}`.** This installation has no scheduler,
  usually because the master key or Google credentials are missing from `.env`. Configure them and
  restart.
- **`stalled` with a configured scheduler.** No scheduled pass has completed for more than 15
  minutes, or one has run for more than 3 hours. Check the container logs, then restart the service.
- **A rule shows "Not synced in over a day".** The last pass tried the rule, but it has not
  succeeded for more than 24 hours. Open the rule; a rule you just resumed is not counted until a
  pass has tried it.
- **"Unnamed calendar" in rule names.** Status never shows a calendar name that is an email address
  or a calendar ID. The Web UI still shows the full name.

## Reading the logs

The service writes one line per record to the container's standard error, timestamped in UTC:

```text
2026-10-01T18:04:12Z INFO calendar_sync.application.sync.sync_run run started rule=7f3c… run=ab12… mode=incremental reason=changes
```

Follow the logs live, or read the last hour:

```sh
docker compose logs -f app
docker compose logs --since 1h app
```

The service's own lines, those of the `calendar_sync` loggers, are also kept in its rotating log
files beside the database, so **Settings → Administration → Storage** → **Download** gets them without
SSH access to the host. Uvicorn's request and error lines stay in the container logs only.

Lines name a rule and a run only by their internal identifiers. They never contain event titles,
descriptions, calendar identifiers, account emails, URLs, or tokens, but review them before
posting them publicly anyway. Uvicorn's own request and startup lines appear alongside them in
their own format.

Each Sync Run, scheduled or started with **Sync now**, writes:

- `run started … mode=… reason=…`: how the run reads its calendars and why. `mode=incremental
  reason=changes` follows the saved cursors. `mode=full` lists every event in the window, because
  it is the rule's `first-run` or its `daily-pass`; `mode=reprojection` rewrites every projection
  after a Material Rule Change.
- `listing done … source events=N destination events=M`: what both calendars reported. A full
  listing reports every event in the window, so it is much larger than an incremental one.
- `cursor rejected … feed=source; listed in full`: Google no longer accepted the saved cursor, so
  that calendar was listed in full instead. Expect a longer run.
- `reprojecting remaining … mappings=N` and `pending replays … series=N`: later phases, logged only
  when the run has them.
- `run progress … decided=412 handled=380/840 created=3 … elapsed=12m03s provider_calls=1630`:
  written at most every 30 seconds while the run decides events. `handled` counts the events both
  calendars reported, plus the mappings a reprojection rewrites, that the run has finished;
  `decided` also counts each occurrence of a recurring event, so it can be larger.
- `run finished … in 28m14s created=… conflicts=… unrecorded=… provider_calls=… token_refreshes=…
  rate_limited=… server_errors=… slowest_call=1.3s`: the run's counts and how its provider calls
  went. The decision counts (`created`, `updated`, `deleted`, `ignored`, `conflicts`) come first.
  `unrecorded` follows them and counts the skips left out of Activity because they repeated the
  event's previous entry. A large `ignored` with a large `unrecorded` means the provider sent many
  events again with no change Calendar Ghost tracks.
- `run failed … kind=rate_limit at=provider.update_projection>graph.request after 3m02s` (WARNING):
  the run stopped with this failure kind. `at=` names the last two of Calendar Ghost's own functions
  the failure passed through, which tells which check or request failed; it names code only, never
  an event. The scheduler retries temporary and rate-limit failures as a new run with a new `run=`
  identifier.
- `run stopped … rule changed`: the rule was paused, edited, or removed while the run was in
  progress. Nothing needs fixing.

Reconcile now and Rule Removal write one `reconciliation started`/`removal started` line and one
`finished`, `failed`, or `interrupted` line each. A provider call slower than 10 seconds is a WARNING
`slow provider call provider=google op=events.instances status=200 took=12.4s`.

To judge whether a long run is still working, compare consecutive `run progress` lines for the same
`run=`. Rules and Rule Details show the same count while a sync runs, as "380 of 840 checked". If
`handled`, `decided`, and `provider_calls` grow, the run is progressing; a large calendar on its
`first-run`, `daily-pass`, or `reprojection` can take many minutes. A growing `rate_limited` count
means Google is slowing the run down and it will finish later. If no `run progress` line appears for
several minutes and no `run finished` or `run failed` follows, the run is waiting on a single Google
call; look for `slow provider call` warnings, or turn on debug logging.

`unrecognized provider reason provider=google status=403 reason=someNewReason` (WARNING): Google
refused a request for a reason Calendar Ghost does not recognize, so its Cause is `unknown`. The
line names only Google's short reason code, never its message, and says `reason=unreadable` when
the code is not a short token. When **Installation health** says that two or more people fail for
a reason Calendar Ghost does not recognize, look for these lines, and include the reason code when
you report it so a later release can recognize it.

Set `CALENDAR_SYNC_LOG_LEVEL=DEBUG` in `.env` and run `docker compose up -d` to also log every
provider call as `provider call provider=google op=events.get status=200 took=84ms`. Debug logging
is verbose; set it back to
`INFO` when you are done.

## Database is large

**Settings → Administration → Storage** shows the database's size, the number of Activity entries, and
the oldest one. Clear Activity older than 30, 90, 180, or 365 days; the confirmation shows how many
entries that removes before you confirm. Clearing deletes in batches and then compacts the database,
which briefly waits for any rule that is synchronizing; if every rule's lock cannot be taken, or
SQLite stays locked, within 30 seconds, the response is "Old Activity was cleared, but its space
could not be reclaimed while a rule is synchronizing. Try again when it finishes." The entries are
already gone at that point, so clearing again later reclaims the space without deleting anything
further. See [ADR 0019](adr/0019-administrator-chosen-activity-retention.md) for which entries are
kept and why.

## An event did not synchronize

Open **Activity**, filter by the rule, and choose **Skipped** or **Blocked**. Each row names the event
and why no Event Projection was written; select it to see the full explanation, the event as the run
recorded it, the event as it is in Google now, and a link to open it in Google Calendar. Common reasons:

- **Blocked**: Calendar Ghost could not safely write this one event, so the destination was left
  unchanged; the rest of the rule keeps synchronizing. The entry's **What to do** says whether you
  need to act. Otherwise the daily check decides the event again, and a block still there opens an
  Incident. For a missing occurrence, **Technical details** records how the series was found and the
  occurrence's original start.
- **Skipped a recurring event**: recorded by a release before recurring-event support. The next
  run after upgrading projects the series.
- **Skipped an occurrence**: the occurrence belongs to a series this rule does not project, such as
  a Managed Projection or an all-day series under a timed-only rule.
- **Skipped: no occurrence left to sync**: every occurrence of the recurring event is cancelled in
  the source, or is an all-day occurrence the rule excludes, so there is nothing to show in the
  destination calendar. This is common for the remainder of a "this and following" split. The
  series is synchronized again once one of its occurrences is restored.
- **Blocked: the destination calendar cannot show it exactly**: nothing was written for this
  event, and the destination was left unchanged. For an Outlook destination, this means one of:
  - someone invited guests to the event, or to one occurrence of it, in Outlook. Changing or
    deleting it would email them, so Calendar Ghost leaves it as it is from then on. Delete it in
    Outlook yourself if you no longer want it; Outlook then tells its guests.
  - its recurrence is one Outlook cannot repeat exactly, such as an hourly rule, several days of
    the month, or a yearly rule on a weekday without a month. Change it in the source to a
    simpler one.
  - it is a series in a time zone whose UTC offsets no Windows time zone keeps for the series'
    whole lifetime, which happens mostly with dates long ago.
  - it is an occurrence cancelled in Outlook, which Outlook cannot bring back.
- **Blocked: the occurrence was not found in the destination series**: the destination series no
  longer expands to the source occurrence even after repair. Run **Reconcile now**; if it persists,
  remove the rule and create it again.
- **Skipped an all-day event**: the rule syncs timed events only.
- **Skipped a managed projection**: Managed Projections never become sources, which prevents loops.
- **Blocked**: identity or ownership was ambiguous, so nothing was written. Run **Reconcile now**
  from Rules and review any incident.
- **Blocked: marked as written by this rule, but not linked to an event**: Reconcile now found an
  event carrying this rule's marker that no mapping owns, so Calendar Ghost will never change or
  delete it. Delete it in the destination calendar if you don't want it.
- **Reconcile now says differences remain after the sync**: the check after the sync only
  reports; it changes nothing. The sync before it has just put back everything it can, so a
  remaining difference is rarely an edit made in the seconds between them. Choose **Reconcile now**
  again: a difference that is still there means the sync cannot settle it, or the check disagrees
  with the sync about what the destination should hold. Both are Calendar Ghost problems, not
  something to fix in your calendars. Look in Activity for the same event being put back and then
  removed on every run, and report the rule's service log lines starting `reconciliation finished`,
  which count what the check found. The count of events checked counts a recurring series once,
  while differences include single occurrences, so the two numbers do not compare.
- **An old event looks different in the destination calendar**: Reconcile now and the daily check
  cover events from the rule's starting point onward (the past 30 days by default), plus every
  recurring event that still has occurrences in that range. Older events are not checked. Editing
  the event in the source calendar still updates it.

## A rule removal stopped or left events behind

A removal that is still running shows **Removing** with its progress, even after the page is
reloaded, and keeps running if you leave. Restarting the service stops it partway.

**Removal incomplete** means the rule stopped partway and does not synchronize. Temporary Google
errors are already retried with backoff before removal stops; choose **Retry removal** to continue
from the remaining projections.

- **Rule Removal stopped: Authorization for Google Calendar expired** or **Access to Google
  Calendar was denied**: an Incident is open for the rule. Reauthorize the destination account in
  **Settings**, then retry. If access cannot be restored, retry with **Keep them as ordinary
  events**; those events then stay in Google and are no longer managed.
- **Some events were left**: the rules list reports events whose ownership could not be verified,
  for example because their private Calendar Ghost metadata names another rule or was removed.
  They were not deleted. Open **Activity**, choose **Blocked**, and delete them in Google Calendar
  yourself if they are no longer wanted.
- **Left because deleting them would notify someone**: someone invited guests to these Outlook
  events, or to an occurrence of them, so deleting them would email the guests. They were not
  deleted. Delete them in Outlook yourself if they are no longer wanted.

## Activity is temporarily unavailable

The Activity screen names the reason it could not load audit entries and incidents:

- **Your session has expired.** Choose **Sign in again**.
- **Calendar Ghost was updated.** The open page predates the running service, for example after an
  upgrade renamed an API path. Choose **Reload page**; if the message returns, hard-refresh the tab.
- **The local service returned an error.** The request reached the service or a reverse proxy in
  front of it. Choose **Try again**, then review container and proxy logs.
- **The request did not reach the local service.** The service may have been restarting, or a
  browser extension blocked the request. Check `/health` as above. If the service is healthy, allow
  Calendar Ghost's address in content blockers such as uBlock Origin. Audit entries are served from
  `/api/v1/audit-entries` because common filter lists block request paths containing `/activity`.

## A rule is degraded

Open **Activity**. The rule's incident says what stopped it and offers the next step. The rule keeps
its mappings and last successful incremental positions, and writes nothing while degraded.

- **Authorization for Google Calendar expired** or **Access to Google Calendar was denied**: Google
  stopped accepting a connected account (Lapsed Authorization). The incident names the account, and
  **Settings → Connections → Connected accounts** marks it **Needs reauthorization**. The stopped
  rule's **Reauthorize account**, the Overview, and the incident each open Settings at that account.
  Choose **Reauthorize account** there; Google offers that account first. Once Google accepts it
  again, every rule the lapse alone stopped restarts on its own, with no preview, and the return to
  Settings says how many. If the rule's calendars belong to two accounts and both lost access, it
  restarts once both are reauthorized. If you think Google's refusal was momentary, choose **Check
  access** first: a check that passes clears the lapse and restarts the same rules.
  If a later failure requires intervention while the rule is stopped, reauthorizing alone no longer
  restarts it: resolve that failure and recover the rule with a preview.
- **Google Calendar rejected synchronization**: Google refused a request for a reason other than
  authorization or rate limiting, or answered in a way Calendar Ghost could not use. Choose **Review
  this rule** and check that both calendars still exist and are shared with the accounts the rule
  uses. Calendar Ghost records only why Google refused, as a likely cause, never the message Google
  returned; the sections below say what each one means. If both calendars are available, recover
  the rule; if it stops again with the same incident, note when the incident opened and its likely
  cause when asking for help.
- **Local synchronization infrastructure failed**: an unexpected error inside Calendar Ghost stopped
  the run, not a Google condition. Review the container logs for the error, and check that the data
  volume has free space and the database is writable, before recovering the rule.
- **The calendar provider rejected synchronization**: the rule names a Connected Account that no
  longer exists (ADR 0022's router could not find it). Re-create the rule, choosing calendars from
  accounts that still exist.

To recover the rule, open it, choose **Preview to restart**, inspect the preview, and choose **Start
syncing**. Its next run repairs drift before advancing either cursor. The next successful scheduled
run, within five minutes, resolves the incident; **Sync Now** and **Reconcile Now** do not.

## Problems only an administrator can fix

Some failures come from the installation's Google Cloud project or Microsoft Entra application,
not from anyone's account or calendars, so only an Installation Administrator can fix them.
Outlook is verified with personal Microsoft accounts, such as Outlook.com and Hotmail. Microsoft
365 work or school accounts can connect, but are not yet verified: the checks in
[ADR 0034](adr/0034-outlook-through-microsoft-graph.md) have not yet run against one.
Calendar Ghost reads why the provider refused from its reason code, never its message, and records
it as a Cause. Each person's own Overview says only that the calendar service is temporarily
unavailable, without the cause or a mention of you, so people are not prompted to contact you. On
**People**, **Installation health** says **Needs you**, People is marked in the navigation, and the
likely cause is shown as soon as anyone meets it, with **How to fix** linking to the section below; a person's page shows the
likely cause of each of their problems. Administrators never need to contact anyone: once the
project is fixed, each person's dashboard tells them what, if anything, is left for them.

### The Google Calendar API is turned off

**Symptom.** Rules stop with "Access to Google Calendar was denied" for several people at once, and
the likely cause reads "the Google Calendar API is turned off for this installation". Check access
fails the same way for every account.

**Confirm.** In the [Google Cloud Console](https://console.cloud.google.com/), select the project
that owns the OAuth client in `CALENDAR_SYNC_GOOGLE_CLIENT_ID`, open **APIs & Services → Enabled
APIs & services**, and look for **Google Calendar API**. If it is missing, or its page offers
**Enable**, it is off. A project that was suspended or marked for deletion answers the same way.

**Fix.** Choose **Enable** on the Google Calendar API page, and wait a few minutes for Google to
apply it. Google refused each affected account while the API was off, so their rules stay stopped
until each account is checked again. Calendar Ghost does that on its own within an hour, and a
check that passes restarts every rule it stopped, with no preview. Meanwhile each person's Overview
says Google Calendar is temporarily unavailable and offers **Check access** on their Google account
in **Settings → Connections** to try at once.

### The Google Cloud project's daily quota is used up

**Symptom.** Several people's rules wait on Google, and the likely cause reads "this installation's
daily quota of Google requests is used up". Nobody's rules stop; they retry by themselves.

**Confirm.** In the Google Cloud Console, open **APIs & Services → Google Calendar API → Quotas &
System Limits** for the project that owns the OAuth client, and compare the requests per day with
the limit.

**Fix.** Google resets the daily quota at midnight Pacific Time, and rules catch up on their own
after it. If it runs out again, request a higher limit on the same page, or reduce how much
Calendar Ghost asks for: fewer rules, or rules over smaller calendars.

### Google no longer accepts the OAuth client

**Symptom.** Every person's Google accounts stop at the same time, the likely cause reads "Google
no longer accepts this installation's OAuth client", and reauthorizing fails too.

**Confirm.** In the Google Cloud Console, open **Google Auth Platform → Clients** (older consoles:
**APIs & Services → Credentials**) and find the OAuth 2.0 client whose ID is
`CALENDAR_SYNC_GOOGLE_CLIENT_ID`. It may have been deleted, or its secret reset, so that
`CALENDAR_SYNC_GOOGLE_CLIENT_SECRET` no longer matches. Do not post either value publicly.

**Fix.** Put the client's current ID and secret in `.env` and run `docker compose up -d`. The first
scheduled pass after the restart checks every stopped Google account again, and each check that
passes restarts its rules. Each person's Overview, which says Google Calendar is temporarily
unavailable, also offers **Check access** on their Google account. If you had to create a new
client, Google's grants to the old one do not carry over: each person's dashboard asks them to
choose **Reauthorize account** once.

### Google accounts stop working 7 days after connecting

**Symptom.** People's Google accounts need reauthorization about a week after they connected or
last reauthorized them, again and again. **Installation health** says so when it happens to two or
more people.

**Confirm.** Google gives a refresh token that expires after 7 days to an OAuth app whose user
type is External and whose publishing status is **Testing**. In the Google Cloud Console, open
**Google Auth Platform → Audience** (older consoles: **APIs & Services → OAuth consent screen**) and
read **Publishing status**.

**Fix.** Choose **Publish app** to move it to **In production**. Google may show people an
"unverified app" warning until the app is verified; a household installation can continue past
it. Grants given while the app was in Testing still expire, so each affected person reauthorizes
once from their own dashboard; after that their access lasts. A Google Workspace organization can
instead set the user type to **Internal**, which has no 7-day limit.

### Microsoft no longer accepts the OAuth client

**Symptom.** Every person's Microsoft accounts stop at the same time, the likely cause reads
"Microsoft no longer accepts this installation's OAuth client", and reauthorizing fails too.

**Confirm.** In the [Microsoft Entra admin center](https://entra.microsoft.com/), or the
[Azure portal](https://portal.azure.com/) for a directory a personal account owns, open **App
registrations**, find the application whose **Application (client) ID** is
`CALENDAR_SYNC_MICROSOFT_CLIENT_ID`, and open **Certificates & secrets**. The secret in
`CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET` has most likely expired: each secret has an expiry date,
at most 24 months after it was created. The application may also have been deleted. The service
logs name Microsoft's code, such as `AADSTS7000222` for an expired secret
([Reading the logs](#reading-the-logs)). Do not post either value publicly.

**Fix.** Choose **New client secret**, copy its **Value** (shown only once), put it in `.env` as
`CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET`, put its **Expires** date in
`CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET_EXPIRES`, and run `docker compose up -d`. The first scheduled
pass after the restart checks every stopped Microsoft account again, and each check that passes
restarts its rules; each person's Overview also offers **Check access** on their Microsoft account.
If you had to register a new application, Microsoft's grants to the old one do not carry over: each
person reauthorizes once. With the expiry date in `.env`, People warns you 30 days before the next
secret expires, so you can create its successor in time.

## Instant Sync cannot reach the installation

Instant Sync runs a rule soon after Google or Microsoft reports a change, and needs them to reach
this installation from the internet. While it cannot, rules sync on their schedule, every five
minutes, and nothing is lost. **Installation health** on **People** names the cause below as soon
as anyone wants Instant Sync, with **How to fix** linking here.

### Instant Sync needs an HTTPS public address

**Symptom.** Installation health says people want instant sync, but this installation's public
address uses plain HTTP. Each person's **Instant sync** under **Settings → Your account** says
Calendar Ghost needs a public HTTPS address.

**Confirm.** `CALENDAR_SYNC_PUBLIC_URL` in `.env` starts with `http://` and names a host on the
internet. A plain HTTP address on this machine or your home network is never hinted: providers
cannot reach it, and people's settings already say so.

**Fix.** Google and Microsoft report changes only to an `https` address with a valid certificate.
Serve `/api/v1/watch-notices/` through HTTPS, for example with a reverse proxy or Cloudflare
Tunnel, set `CALENDAR_SYNC_PUBLIC_URL` to that `https` address, and run `docker compose up -d`.
Within five minutes, Calendar Ghost asks each provider to report changes there. If you do not want
Instant Sync, the hint does no harm: without an HTTPS address, Calendar Ghost asks no provider to
report changes, and rules sync on their schedule. See
[Instant Sync](instant-sync.md#no-public-https-address) for the requirements and proxy examples.

### Calendar providers cannot reach the installation

**Symptom.** Installation health says people want instant sync, but Google or Microsoft cannot
reach this installation. When no provider a person uses reaches it, their **Instant sync** says so
beside its choice, and their rules say "Syncs every 5 minutes". Calendar Ghost keeps asking the
providers meanwhile; choosing **On schedule** there stops it.

**Confirm.** From a machine outside your network, send a request shaped like Google's to an
unknown registration. It changes nothing:

```sh
curl -i -X POST https://calendar.example.com/api/v1/watch-notices/google/00000000000000000000000000000000 \
  -H 'X-Goog-Channel-ID: 00000000000000000000000000000000' \
  -H 'X-Goog-Channel-Token: reachability-check' \
  -H 'X-Goog-Resource-ID: reachability-check' \
  -H 'X-Goog-Resource-State: exists'
```

Calendar Ghost answers `202 Accepted`. A timeout, a `502` or `504`, a `403` from a firewall, or a
sign-in page means the proxy or tunnel stops the request before it reaches Calendar Ghost.

**Fix.** Make the proxy or tunnel forward `POST /api/v1/watch-notices/` with its query string,
headers, and body unchanged, and let it through any sign-in gate, such as Cloudflare Access, and any
bot challenge. The certificate must be valid for the public name: providers refuse a self-signed
one. Google's notices count again with the next change in a watched calendar; Microsoft is asked
again on Calendar Ghost's next try, which waits longer after each failure, at most a day. See
[Forward the notices path](instant-sync.md#forward-the-notices-path) for working proxy and tunnel
examples.

## Problems you fix yourself

When Google or Microsoft refuses one of your requests for a reason that is yours to handle, your Overview and
the rule say what happened and your one next step. Your administrator sees only that you can fix it from your dashboard, and does not
contact you about it. If the installation sends email and has a public address, the incident email
links straight to that step.

### Google no longer accepts your Google account

**What you see.** "A Google account needs reauthorization", with the likely cause "Google
no longer accepts this Google account's permission". You removed Calendar Ghost's access in your
Google account, changed something Google treats as ending the grant, or the grant expired.

**What to do.** Choose **Reauthorize account** in **Settings → Connections**, for the account it
names. Every rule the lapse alone stopped restarts on its own, with no preview. If it happens again about
a week after each reauthorization, tell your administrator: the installation's Google app is
probably in Testing mode ([Google accounts stop working 7 days after
connecting](#google-accounts-stop-working-7-days-after-connecting)).

### Your Google account may not change the calendar

**What you see.** The rule stopped, with the likely cause "the Google account may not change this
calendar". The calendar's owner took away your account's permission to make changes, or a Google
Workspace policy limits it.

**What to do.** Open the rule. Choose another calendar for it, or remove it. To keep the same
calendar, ask its owner to share it with your Google account with **Make changes to events**, then
preview the rule again to restart it.

### The calendar no longer exists

**What you see.** The rule stopped, with the likely cause "the calendar no longer exists, or is no
longer shared with the account". The calendar was deleted, or unshared from the account the rule
uses.

**What to do.** Open the rule and choose another calendar for it, or remove the rule.

### Google is slowing Calendar Ghost down

**What you see.** "Waiting for Google", with the likely cause "Google asked Calendar Ghost to slow
down" or "Google failed for a moment", when the rule was last tried, and when it tries again.

**What to do.** Nothing. Calendar Ghost tries again by itself and catches up afterwards. If it lasts
more than a day, check the Google Workspace Status Dashboard.

### Google refused for a reason Calendar Ghost does not recognize

**What you see.** The rule stopped or needs a look, with the likely cause "Google refused for a
reason Calendar Ghost does not recognize".

**What to do.** Try the rule's usual step again: open the rule and preview it to restart it, or read
what Activity says. If it keeps happening, tell your administrator; the service logs name Google's
reason ([Reading the logs](#reading-the-logs)).

### Microsoft no longer accepts your Microsoft account

**What you see.** "A Microsoft account needs reauthorization", with the likely cause "Microsoft no
longer accepts this Microsoft account's permission". You removed Calendar Ghost's access, your
password was reset, your sign-in now needs another step such as multifactor authentication, or the
grant went unused for 90 days.

**What to do.** Choose **Reauthorize account** in **Settings → Connections**, for the account it
names. Every rule the lapse alone stopped restarts on its own, with no preview. With a work or school
account, your organization may require its administrator to approve applications: if Microsoft
says the application needs approval, ask your organization's IT administrator to grant consent to
it, then reauthorize.

### Your Microsoft account may not change the calendar

**What you see.** The rule stopped, with the likely cause "the Microsoft account may not change
this calendar". The calendar was shared with your account to read only, or its owner took away
your permission to edit it.

**What to do.** Open the rule. Choose another calendar for it, or remove it. To keep the same
calendar, ask its owner to share it with your Microsoft account with **Can edit**, then preview the
rule again to restart it.

### Microsoft is slowing Calendar Ghost down

**What you see.** "Waiting for Microsoft", with the likely cause "Microsoft asked Calendar Ghost to
slow down" or "Microsoft failed for a moment", when the rule was last tried, and when it tries
again.

**What to do.** Nothing. Calendar Ghost tries again by itself, waiting as long as Microsoft asks,
and catches up afterwards. If it lasts more than a day, check the Microsoft 365 service health
status page.

### Microsoft refused for a reason Calendar Ghost does not recognize

**What you see.** The rule stopped or needs a look, with the likely cause "Microsoft refused for a
reason Calendar Ghost does not recognize".

**What to do.** Try the rule's usual step again: open the rule and preview it to restart it, or read
what Activity says. If it keeps happening, tell your administrator; the service logs name
Microsoft's code ([Reading the logs](#reading-the-logs)).

## A calendar account was disconnected

Open **Settings → Connections → Connected accounts** and choose **Reauthorize account** for the same
Google or Microsoft identity. The installation no longer retains credentials for a disconnected account, and
enabled rules that reference it remain degraded. After reauthorization, open Rules, choose
**Validate recovery**, inspect the preview, and enable each affected rule. Existing mappings,
Managed Projections, and incremental positions are preserved throughout recovery.

To remove the local identity permanently, choose **Delete account** and review the destructive
confirmation. Permanent deletion removes every affected Directional Sync Rule and its mappings,
cursors, incidents, and audit activity. Existing Managed Projections are not deleted from Google
Calendar or Outlook and will no longer be managed. Unrelated accounts and rules are unchanged.

## Consent ends on "Unable to connect"

After Google or Microsoft consent, the browser followed the configured redirect URI to an address that does not reach this
installation, usually `localhost` while Calendar Ghost runs on another host. No account was saved.
When the redirect URI is at another address than the one Calendar Ghost is open at, consent opens
in a new tab, so the tab you started from stays on Calendar Ghost. To finish this attempt, copy the
whole address from the new tab's address bar, return to the Calendar Ghost tab, paste it into
**Address Google returned to** (or **Address Microsoft returned to**) under **Finish connecting
your Google account** (or **Microsoft account**), and choose **Finish connecting** within 10
minutes; each callback works once. From another browser, sign in there as the same person first; the same field is in the note
at the foot of Connected accounts. Replacing the origin in the address bar by hand, for example
`localhost:18000` with `192.168.1.50:18000`, does the same. Only the person who started connecting
can finish: a callback opened without signing in, or by anyone else, connects nothing and reports
that authorization failed. To stop it recurring, use an HTTPS redirect URI or an SSH tunnel as
described in [Deployment](deployment.md#google-oauth-redirect-uri-on-a-lan-host).

## Calendar permission was not granted

The OAuth callback returns to **Settings → Connections → Connected accounts** without saving an
account. Choose **Try again**, select the intended Google or Microsoft identity, and grant calendar
access: for Google, both calendar-list and event access; for Microsoft, **Have full access to your
calendars**. Calendar Ghost verifies those permissions before it stores the Connected Account.
Declining consent does not create an account or retain any credentials.

## Connect is unavailable: your plan's calendar accounts

When an administrator has turned Plans on, your Plan may limit how many calendar accounts you
have. Every account under **Settings → Connections → Connected accounts** counts, Disconnected
Accounts too: connecting one of them again is Reauthorization, which a Plan never refuses. At the
limit, **Connect an account** is unavailable and says why, but Reauthorization is never refused
by the account limit: an account that needs it still offers **Reauthorize account**.
**Settings → Your account → Your plan** shows how many
calendar accounts you have and how many your Plan allows, as "2 of 1" beside a meter, and past the
limit a sentence that links to **Connections**. Installation Administrators are never limited.

Calendar Ghost learns an account's address only after the provider's consent. So when you choose
an address you have not connected, and your Plan has no room for it, you return to Connections
with "Your plan's calendar accounts are all in use". No account was saved, and your existing
accounts and rules are unchanged. The provider may keep the consent you gave; you can remove
Calendar Ghost from your Google or Microsoft account's security settings.

To make room, delete an account you no longer use ([A calendar account was
disconnected](#a-calendar-account-was-disconnected) explains what deleting removes), or ask your
administrator for a larger Plan.

If connecting a new account ends on an error page instead of Connections while Plans are on,
Calendar Ghost could not read your Plan, for example because its database was busy. No account was
saved; connect again. Reauthorizing an account you already have never reads your Plan.

### An account's address changed

Calendar Ghost knows each account by its provider and email address. When the address of a
Microsoft or Google Workspace account changes, for example after a rename, the provider reports
the new address, so reauthorizing connects a new account and the old one stays. At the limit, the
new address is refused. To move every rule to the new address without losing one:

1. Free one account place: delete an account you no longer use, or ask your administrator to raise
   your Plan's account limit, or give you a larger Plan, for the move.
2. Connect the new address.
3. On each rule that uses the old account, choose **Replace calendars…** and choose the same
   calendar under the new address. Where the old account holds the rule's destination, keep its
   events as ordinary events: the old account may no longer be able to delete them.
4. Disconnect the old account, then delete it.

Delete the old account only after every rule has moved: deleting an account deletes the rules that
use it.

## Microsoft sign-in stops with an error

Microsoft shows its own page, with a code beginning `AADSTS`, instead of returning to Calendar
Ghost. No account was saved.

- **AADSTS50011**, the redirect URI does not match: the address in
  `CALENDAR_SYNC_MICROSOFT_REDIRECT_URI` must be registered exactly under the application's
  **Authentication → Web → Redirect URIs** ([Register a Microsoft Entra
  application](self-hosting.md#register-a-microsoft-entra-application)).
- **Need admin approval**, or **AADSTS65001** or **AADSTS90094**: the person's organization lets
  only its IT administrator approve applications. They ask that administrator to grant consent to
  the application, then connect again.
- **AADSTS50020** or "You can't sign in here with a personal Microsoft account": the application's
  **Supported account types** does not include this kind of account, or
  `CALENDAR_SYNC_MICROSOFT_TENANT` names one organization. Use `common` with **Accounts in any
  organizational directory and personal Microsoft accounts** to accept both.
- **AADSTS7000215** or **AADSTS7000222**, after consent: the client secret is wrong or expired
  ([Microsoft no longer accepts the OAuth client](#microsoft-no-longer-accepts-the-oauth-client)).

## A connected account fails Check access

If its provider no longer accepts the account, the check says so and the account is marked **Needs
reauthorization**; choose **Reauthorize account**. If Google denied calendar access, the Google
Calendar API may be off: it is enabled on the Google Cloud project, not separately on each Google
identity. Confirm that the API remains enabled for the project owning the OAuth client, then choose
**Reauthorize account** for the affected identity. If Microsoft denied calendar access, the grant
most likely lacks calendar permission: choose **Reauthorize account** and accept calendar access.
**Check access** verifies both calendar-list and event access through read-only requests. A
successful check also reports the number of writable calendars; an account with zero writable
calendars can be a Source Calendar but cannot provide a Destination Calendar.

## Destination edits return

This is expected. Destination events are Managed Projections and source content is authoritative.
Pause the rule before changing a destination projection that should temporarily remain untouched.

## A destination event was recreated

Deleting a Managed Projection is Drift while its source remains eligible. Synchronization recreates
it on the next destination change poll. Delete or exclude the source, or pause the rule instead.

## A projected series appears twice after "this and following"

Editing or deleting a projected series in the destination with **This and all following events**
splits it in two: the calendar service ends the series Calendar Ghost wrote, and makes a new series
for the rest. Calendar Ghost puts its own series back as the source has it, but it did not write the
new one, so it never changes or deletes it, as it would not change one of your own events. Delete
the new series yourself. To change a projected series, change it in the source instead.

## The first sync of a large calendar is slow

The first sync writes every event of the window one at a time, about one event a second into Google
or Outlook; a calendar of a few hundred events takes several minutes, and Activity shows its
progress. The runs after it write only what changed.

## A recurring event keeps being restored and removed

Earlier releases showed a recurring event in Activity as added to the destination and then removed
on every run when every occurrence of its Event Series was cancelled in the source, often after a
"this and following" split. Google cancels a series once its last occurrence is cancelled, so the
next run found no Event Projection and created it again. Upgrade to a release that includes
migration 10 (see [Deployment](deployment.md#docker-compose)): the next run stops recreating the
series, may record **Skipped: no occurrence left to sync** for it, and keeps the Series Mapping
dormant until an occurrence is restored. An entry such as **Removed from Work: no occurrence left
to sync** means the run removed a projection that an interrupted run had created; no action is
needed.

The same happened, with **Missing from Work, so put back again** followed by **Declined, so removed
from Work**, when every remaining occurrence of the series was declined, awaiting an answer, or
answered Maybe under a rule that skips those. Upgrade to a release with that fix; the next run stops
recreating the series and keeps it dormant until you accept one of its occurrences.

## Incremental cursor expired

The Google adapter must discard the expired cursor, perform a safe initial-window scan, match managed projections through origin metadata, and establish a new cursor without duplicating events.

## I cannot sign in

- **The email and password do not match.** Sign in with the email you added or were invited with;
  its case does not matter. If you forgot your password, ask an administrator for a password reset
  link from the **People** page. It works once, for 7 days, and signs you out
  everywhere once you choose a new password. An administrator never sees or sets your password.
- **Too many failed attempts.** After five failures for one email, or twenty from one address, in
  15 minutes, sign-in waits until the oldest failure is 15 minutes old. Invitation and password
  reset links work the same way: after twenty unusable links from one address in 15 minutes, every
  link waits. Behind a reverse proxy the address is the proxy's, so wait before trying again.
- **Your access is turned off.** An administrator disabled you; ask them to enable you again. Your
  rules were held meanwhile and resume by themselves.
- **After upgrading, the sign-in page asks for an email you never had.** Leave the email empty and
  sign in with your password; Calendar Ghost then asks for the email you sign in with from now on.
- **The only administrator forgot their password.** Nobody can create a reset link for them. Make a
  second person an administrator while you can, so each can help the other.

<div id="incident-emails-are-unavailable-or-never-arrive"></div>

## Email notifications are unavailable or never arrive

**Email notifications** under **Settings → Your account** appears only when the installation
sends email. Until then that page says who can set email up. **Activity** keeps every incident;
**Your plan** and held-rule views retain Plan state. These are also the fallback when a notice
is lost during failed pass preparation, cancellation, shutdown, restart, or SMTP failure. A newer
pending Plan notice can replace an older one for the same User; there is no outbox or retry.
Identity and security mail is independent of this preference.

- **The installation does not send email.** An administrator sets `CALENDAR_SYNC_SMTP_HOST` and
  `CALENDAR_SYNC_SMTP_SENDER`, plus credentials if the server needs them, in `.env` and restarts.
  See [Incident notifications](deployment.md#incident-notifications).
- **You have no email yet.** After an upgrade, the first User adds one when they next sign in.
- **You turned them off.** Turn **Email notifications** on again.
- **The SMTP recipient and webhook stopped receiving rule incidents.** Since Users, they receive only
  incidents about the installation itself, such as a stalled scheduler. Each person receives their
  own rule incidents at their email.

## Start syncing is unavailable: your plan's rule limit

Start syncing is unavailable on a rule's preview page, or starting it answers that your plan's
limit is reached, when an administrator turned Plans on and the rules that count toward your Plan
already reach its rule limit. Under **Settings → Your account → Your plan**, **Active rules**
shows how many rules count and how many your Plan allows, as "1 of 1" with **Limit reached**, and
beside **Create sync rule** on Rules a note says how many your Plan lets sync at once.

- Rules that count are enabled rules, rules stopped only because an account's access lapsed,
  and replacement drafts keeping a reserved place. Other drafts, previewed and paused rules,
  and held rules do not count. Creating or previewing a rule is never limited.
- Pause or remove a rule you no longer need, then start this one.
- A rule stopped by any other error, or paused by a change to its policy, gave up its place. Its
  restart is checked like any Start, so it may be refused while other rules fill your Plan. When
  more rules count than your Plan allows or other rules are held, Calendar Ghost warns
  "Your plan may not let this rule start again." before a policy edit, Pause, or Disconnect.
- **Replace calendars…** on a rule that counts (enabled, or stopped only because an account's
  access lapsed) gives the new draft that rule's place, so the new rule can start whatever the
  limit. Replacing a paused rule, or one stopped by any other error, keeps no place.
- A rule that stopped because an account's access lapsed already counts, so it resumes after
  Reauthorization whatever the limit.
- After a lower limit, running rules beyond it keep syncing during a seven-day grace. At expiry,
  excess running or lapse-stopped rules are held until the Plan has room; excess replacement
  drafts give up their reserved places instead. New Starts still need room throughout the grace. Ask your administrator
  for a larger Plan; administrators are never limited. Your plan shows the grace deadline and
  lets you choose which rules keep syncing.

An API client receives `409` with the code `plan_limit_reached` and the reason `rules`, or
`rules_with_held` when the User also has rules on Plan Hold. Both carry `limit` and `count` for
the same limit. Rule details expose `can_start`, `rule_limit`, and `held_rules` for the matching
preflight explanation; Start checks the Allowance again and refuses if it cannot be read.
Held rules can take a free place at the next scheduled check; saving keep choices applies swaps
immediately. See [Held by your plan](#held-by-your-plan).

## Issue token is unavailable: your plan's token limit

Under **Settings → Connections → Integrations**, **Issue token** is unavailable when your
unrevoked Integration Tokens reach your Plan's token limit, and the form says why: "Your plan
allows 2 integration tokens, and all are in use. Revoke one to issue another." Revoke a token you
no longer use, then issue the new one: revoked tokens do not count. A Plan may include no
Integration Tokens at all; the form then says "Your plan does not include integration tokens. To
get one, ask your administrator." **Integration tokens** under **Settings → Your account → Your
plan** shows how many you have against the limit, or **Not included**. Tokens you already have
keep working when a limit is lowered,
so no monitor stops on its own. A token that reads Installation Health is for administrators, who
are never limited. An API client receives `409` with the code `plan_limit_reached` and the reason
`integration_tokens`.

## Someone has more than their plan allows

This is for administrators. After you lower a limit, or give someone a smaller Plan, some people
can have more than their Plan allows. Rules counting beyond the limit get a seven-day grace.
At expiry, excess running or lapse-stopped rules are held until there is room; excess replacement
drafts give up their reserved places instead. Existing calendar accounts and Integration Tokens keep working. New Starts,
connections, and token issues still require room within their corresponding limit. Before you save
a lower limit, the Plan form says how many people it would leave with more: "1 person on Free has
more calendar accounts than this. They keep them, but can't connect another."

**People** shows who they are, in Attention Ochre with an icon:

- On **Plans**, the card at the top counts everyone over a limit, a number you select to list them, and
  each Plan's row says how many of the people it limits are over: "1 over a limit", which lists
  them too. A Plan's **People** tab lists who has it now, each with any limit they are over.
- On **Everyone**, the **Plan** column marks a person over a limit with **Over a limit** beside
  their Plan, and says which limit under it ("2 calendar accounts, 1 allowed"). Choose the Plan in the **Plan** filter to list only the people who have it, and
  **Over a limit** in the **Limits** filter to list only the people over one.
- On the person's page, the **Plan** card shows a meter for each limit with how much they use,
  "2 of 1" and **Over** past it, and says under it what keeps working: "robin@example.test has 2
  calendar accounts and Free allows 1. Their accounts keep syncing, but they can't connect another
  until one is removed."

The person sees the same under **Settings → Your account → Your plan**, in their own words, with
**Over a limit** beside their Plan's name: "You have 2 calendar accounts and your plan allows 1.
They keep syncing, but you can't connect another until you remove one in Connections."

Each count is made as the limit counts it: rules that count toward the Plan ([Start syncing is
unavailable](#start-syncing-is-unavailable-your-plans-rule-limit) says which), every calendar
account, Disconnected Accounts too, and Integration Tokens not revoked. Administrators and
disabled people are never limited, so they are never shown over a limit. While Plans are off, the
same marks show what turning them on would do.

To fix it, do one of these:

- Give the person a larger Plan with **Change plan** on their page's **Plan** card, in their
  **More actions** under **Everyone**, or beside them in the Plan's **People** tab. To move several
  people at once, tick them under **Everyone** and choose **Change plan** above the table.
- Raise the limit on the Plan's **Limits** tab, which **Edit** in its menu opens.
- Ask the person to make room: pause a rule, delete a calendar account they no longer use, or
  revoke a token.

## A plan cannot be removed, or its name is refused

- **Remove is unavailable on the default Plan.** In its **More actions** menu, Remove says "Make
  another plan the default first." Choose **Make default** on another Plan, then remove it.
- **Remove names who has the Plan.** A Plan someone has cannot be removed. In its menu, Remove says
  who has it, the first three by email and then how many more: "robin@example.test has Family. Give
  them another plan first." Choose how many people have it, in the Plan's **People** column, to
  list everyone who has it, give each of them another Plan with **Change plan**, or **Assign
  people** on another Plan, then remove it.
- **"Another plan is named Free. Choose a different name."** Two Plans cannot share a name, whatever
  its case or the spaces around it. Choose another name, or rename the other Plan first.

An API client receives `409` with the code `plan_in_use`, `plan_is_default`, or `plan_name_taken`.

## Held by your plan

A neutral **Held by your plan** label means the rule is beyond its Plan's rule limit after a
seven-day grace, or your saved choice gave its place to another rule. Existing projections,
mappings, and incremental positions remain. It is not a failure and creates no Incident or Audit
Entry. Sync now and Reconcile now are unavailable while held; Preview is allowed and preserves
the hold.

Open **Choose which rules sync** on the rule or under **Settings → Your account → Your plan**.
Save the complete set of preferred rules, up to your current limit. Choose none to prefer the
oldest rules. A save can swap a kept held rule with an active rule immediately, without email.
The scheduled pass never swaps: if a competing Start filled a place before automatic release,
save the choice again. When a place is free, the next scheduled check releases the best-ranked
held rule without a new preview. Release checks both accounts; if either needs Reauthorization,
the released rule waits for it instead. Reauthorization alone never releases a hold.

Pausing a held rule clears its hold, gives up no place, and needs a preview before a normal Start.
A policy change, disconnection, or intervention failure also ends the hold and can leave recovery
Start without room. The UI warns before capacity-losing actions. Plans off or administrator status
releases holds on the next successful settlement. Disabled Users retain holds and clear grace.
No scheduler means no automatic release: check Installation Status for `stalled` and restore the
scheduler. Monitors read `stop_cause` or `needs_attention`; a held rule can be `degraded` without a
Stopped problem. Status incident/block totals and Activity retain held-owned records even though
Dashboard attention counts omit them.

## A rule held by an activated release stays stopped after rollback

The older inert PR 2 and PR 3a builds recognize Plan Hold but their production scheduler does not
release it. Restoring account access never releases a hold on those builds. Upgrade to an active
release, or pause the rule to clear its hold, then preview and Start within your Plan's limit.
Preview alone keeps a hold. See [migration 34](deployment.md#migration-34-plan-hold-engine) for
the different behavior and re-upgrade risks of releases from before this migration.

## Getting more help

If this guide does not solve the problem, ask in
[GitHub Discussions](https://github.com/DannieBGoode/calendar-ghost/discussions). Search earlier
answers first. To report a bug, open an issue with the
[bug report form](https://github.com/DannieBGoode/calendar-ghost/issues/new/choose). Discussions
and issues are public: do not include event content, calendar IDs, email addresses, credentials, or
unredacted logs. If you cannot use GitHub, email support@calendarghost.com. Report security
vulnerabilities privately, as [SECURITY.md](../SECURITY.md) describes.
