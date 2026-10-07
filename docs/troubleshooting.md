# Troubleshooting

## The Web UI cannot reach the service

Check `docker compose ps`, then request `http://localhost:8000/health`. Review container logs without posting credentials or event payloads publicly.

## A monitor or agent cannot read status

`GET /api/v1/status` and `/mcp` accept an Integration Token from **Settings → Integrations**
([self-hosting guide](self-hosting.md#6-connect-monitors-and-agents)). Check the answer with `curl -i`:

- **401 `valid credentials required`.** The token is missing, mistyped, or revoked; every reason
  gets the same answer. Send it as `Authorization: Bearer cgs_…`, never in the address. A token is
  `cgs_` and 43 more characters; a partial copy is refused. If it was revoked or lost, issue a new
  one. An invalid `Authorization` header is refused even when the same
  browser is signed in, so a broken monitor credential never hides behind your session.
- **401 behind a reverse proxy, although `curl` on the host works.** The proxy is dropping the
  `Authorization` header. Configure it to pass the header through to Calendar Ghost.
- **401 on any other `/api/` route.** Expected. A token reads status only; Rules, Activity, and
  Settings need the administrator session.
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
2026-10-01T18:04:12Z INFO calendar_sync.application.sync_run run started rule=7f3c… run=ab12… mode=incremental reason=changes
```

Follow the logs live, or read the last hour:

```sh
docker compose logs -f app
docker compose logs --since 1h app
```

The service's own lines, those of the `calendar_sync` loggers, are also kept in its rotating log
files beside the database, so Settings → Storage → Download gets them without SSH access to the
host. Uvicorn's request and error lines stay in the container logs only.

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
- `run finished … in 28m14s created=… provider_calls=… token_refreshes=… rate_limited=…
  server_errors=… slowest_call=1.3s`: the run's counts and how its provider calls went.
- `run failed … kind=rate_limit after 3m02s` (WARNING): the run stopped with this failure kind; the
  scheduler retries temporary and rate-limit failures as a new run with a new `run=` identifier.
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

Set `CALENDAR_SYNC_LOG_LEVEL=DEBUG` in `.env` and run `docker compose up -d` to also log every
provider call as `provider call provider=google op=events.get status=200 took=84ms`. Debug logging
is verbose; set it back to
`INFO` when you are done.

## Database is large

Settings → Storage shows the database's size, the number of Activity entries, and the oldest one.
Clear Activity older than 30, 90, 180, or 365 days; the confirmation shows how many entries that
removes before you confirm. Clearing deletes in batches and then compacts the database, which
briefly waits for any rule that is synchronizing; if every rule's lock cannot be taken, or SQLite
stays locked, within 30 seconds, the response is "Old Activity was cleared, but its space could not
be reclaimed while a rule is synchronizing. Try again when it finishes." The entries are already
gone at that point, so clearing again later reclaims the space without deleting anything further.
See [ADR 0019](adr/0019-administrator-chosen-activity-retention.md) for which entries are kept and
why.

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

## Activity is temporarily unavailable

The Activity screen names the reason it could not load audit entries and incidents:

- **Your administrator session has expired.** Choose **Sign in again**.
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
  **Settings → Connected accounts** marks it **Needs reauthorization**. The stopped rule's
  **Reauthorize account**, the Overview, and the incident each open Settings at that account. Choose
  **Reauthorize account** there; Google offers that account first. Once Google accepts it again,
  every rule the lapse alone stopped restarts on its own, with no preview, and the return to
  Settings says how many. If the rule's calendars belong to two accounts and both lost access, it
  restarts once both are reauthorized. If you think Google's refusal was momentary, choose **Check
  access** first: a check that passes clears the lapse and restarts the same rules.
- **Google Calendar rejected synchronization**: Google refused a request for a reason other than
  authorization or rate limiting, or answered in a way Calendar Ghost could not use. Choose **Review
  this rule** and check that both calendars still exist and are shared with the accounts the rule
  uses. Calendar Ghost does not record the error Google returned, so if both calendars are available,
  recover the rule; if it stops again with the same incident, note when the incident opened when
  asking for help.
- **Local synchronization infrastructure failed**: an unexpected error inside Calendar Ghost stopped
  the run, not a Google condition. Review the container logs for the error, and check that the data
  volume has free space and the database is writable, before recovering the rule.
- **The calendar provider rejected synchronization**: the rule names a Connected Account that no
  longer exists (ADR 0022's router could not find it). Re-create the rule, choosing calendars from
  accounts that still exist.

To recover the rule, open it, choose **Preview to restart**, inspect the preview, and choose **Start
syncing**. Its next run repairs drift before advancing either cursor. The next successful scheduled
run, within five minutes, resolves the incident; **Sync Now** and **Reconcile Now** do not.

## A Google account was disconnected

Open **Settings → Connected accounts** and choose **Reauthorize account** for the same Google
identity. The installation no longer retains credentials for a disconnected account, and enabled
rules that reference it remain degraded. After reauthorization, open Rules, choose **Validate
recovery**, inspect the preview, and enable each affected rule. Existing mappings, Managed
Projections, and incremental positions are preserved throughout recovery.

To remove the local identity permanently, choose **Delete account** and review the destructive
confirmation. Permanent deletion removes every affected Directional Sync Rule and its mappings,
cursors, incidents, and audit activity. Existing Managed Projections are not deleted from Google
Calendar and will no longer be managed. Unrelated accounts and rules are unchanged.

## Google consent ends on "Unable to connect"

The browser followed the configured redirect URI to an address that does not reach this
installation, usually `localhost` while Calendar Ghost runs on another host. No account was saved.
To finish this attempt, copy the whole address from the address bar, return to Settings in the
browser you started from, paste it into **Address Google returned to** under **Finish connecting
your Google account**, and choose **Finish connecting** within 10 minutes; each callback works
once. From another browser, the same field is in the note at the foot of Connected accounts. Replacing the origin in the address bar by hand, for example
`localhost:18000` with `192.168.1.50:18000`, does the same. To stop it recurring, use an HTTPS
redirect URI or an SSH tunnel as described in
[Deployment](deployment.md#google-oauth-redirect-uri-on-a-lan-host).

## Google Calendar permission was not granted

The OAuth callback returns to **Settings → Connected accounts** without saving an account. Choose
**Try again**, select the intended Google identity, and grant both calendar-list and event access.
Calendar Ghost verifies those permissions before it stores the Connected Account. Declining consent
does not create an account or retain Google credentials.

## A connected account fails Check access

If Google no longer accepts the account, the check says so and the account is marked **Needs
reauthorization**; choose **Reauthorize account**. If Google denied calendar access, the Google
Calendar API may be off: it is enabled on the Google Cloud project, not separately on each Google
identity. Confirm that the API remains enabled for the project owning the OAuth client, then choose
**Reauthorize account** for the affected identity. **Check access** verifies both calendar-list and
event access through read-only requests. A successful check also reports the number of writable
calendars; an account with zero writable calendars can be a Source Calendar but cannot provide a
Destination Calendar.

## Destination edits return

This is expected. Destination events are Managed Projections and source content is authoritative.
Pause the rule before changing a destination projection that should temporarily remain untouched.

## A destination event was recreated

Deleting a Managed Projection is Drift while its source remains eligible. Synchronization recreates
it on the next destination change poll. Delete or exclude the source, or pause the rule instead.

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

## Getting more help

If this guide does not solve the problem, ask in
[GitHub Discussions](https://github.com/DannieBGoode/calendar-ghost/discussions). Search earlier
answers first. To report a bug, open an issue with the
[bug report form](https://github.com/DannieBGoode/calendar-ghost/issues/new/choose). Discussions
and issues are public: do not include event content, calendar IDs, email addresses, credentials, or
unredacted logs. If you cannot use GitHub, email support@calendarghost.com. Report security
vulnerabilities privately, as [SECURITY.md](../SECURITY.md) describes.
