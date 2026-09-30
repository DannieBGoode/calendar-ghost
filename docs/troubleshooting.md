# Troubleshooting

## The Web UI cannot reach the service

Check `docker compose ps`, then request `http://localhost:8000/health`. Review container logs without posting credentials or event payloads publicly.

## An event did not synchronize

Open **Activity**, filter by the rule, and choose **Skipped** or **Blocked**. Each row names the event
and why no Event Projection was written; select it to see the full explanation, the event as the run
recorded it, the event as it is in Google now, and a link to open it in Google Calendar. Common reasons:

- **Blocked**: Calendar Sync could not safely write this one event, so the destination was left
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
  event carrying this rule's marker that no mapping owns, so Calendar Sync will never change or
  delete it. Delete it in the destination calendar if you don't want it.
- **Reconcile now says projections still differ**: the check after the sync only reports; it
  changes nothing. A difference that appeared during the check is put back by the next sync.
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

- **Rule Removal stopped: Google authorization expired** or **… calendar access was denied**: an
  Incident is open for the rule. Reauthorize the destination account in **Settings**, then retry.
  If access cannot be restored, retry with **Keep them as ordinary events**; those events then stay in
  Google and are no longer managed.
- **Some events were left**: the rules list reports events whose ownership could not be verified,
  for example because their private Calendar Sync metadata names another rule or was removed.
  They were not deleted. Open **Activity**, choose **Blocked**, and delete them in Google Calendar
  yourself if they are no longer wanted.

## Activity is temporarily unavailable

The Activity screen names the reason it could not load audit entries and incidents:

- **Your administrator session has expired.** Choose **Sign in again**.
- **Calendar Sync was updated.** The open page predates the running service, for example after an
  upgrade renamed an API path. Choose **Reload page**; if the message returns, hard-refresh the tab.
- **The local service returned an error.** The request reached the service or a reverse proxy in
  front of it. Choose **Try again**, then review container and proxy logs.
- **The request did not reach the local service.** The service may have been restarting, or a
  browser extension blocked the request. Check `/health` as above. If the service is healthy, allow
  Calendar Sync's address in content blockers such as uBlock Origin. Audit entries are served from
  `/api/v1/audit-entries` because common filter lists block request paths containing `/activity`.

## A rule is degraded

Open **Activity**. The rule's incident says what stopped it and offers the next step. The rule keeps
its mappings and last successful incremental positions, and writes nothing while degraded.

- **Google authorization expired** or **Google calendar access was denied**: choose **Reauthorize in
  Settings** and reauthorize the Google account Google rejected. Once that account is reauthorized,
  the incident offers **Recover this rule** instead. If the rule's calendars belong to two accounts
  and the other one has also lost access, recovering the rule points the incident back to Settings
  for that account.
- **Google Calendar rejected synchronization**: Google refused a request for a reason other than
  authorization or rate limiting, or answered in a way Calendar Sync could not use. Choose **Review
  this rule** and check that both calendars still exist and are shared with the accounts the rule
  uses. Calendar Sync does not record the error Google returned, so if both calendars are available,
  recover the rule; if it stops again with the same incident, note when the incident opened when
  asking for help.
- **Local synchronization infrastructure failed**: an unexpected error inside Calendar Sync stopped
  the run, not a Google condition. Review the container logs for the error, and check that the data
  volume has free space and the database is writable, before recovering the rule.

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
installation, usually `localhost` while Calendar Sync runs on another host. No account was saved.
To finish this attempt, replace the origin in the address bar with the one you use to open
Calendar Sync, for example `localhost:18000` with `192.168.1.50:18000`, and load it within 10
minutes; each callback works once. To stop it recurring, use an SSH tunnel or an HTTPS redirect
URI as described in [Deployment](deployment.md#google-oauth-redirect-uri-on-a-lan-host).

## Google Calendar permission was not granted

The OAuth callback returns to **Settings → Connected accounts** without saving an account. Choose
**Try again**, select the intended Google identity, and grant both calendar-list and event access.
Calendar Sync verifies those permissions before it stores the Connected Account. Declining consent
does not create an account or retain Google credentials.

## A connected account fails Check access

The Google Calendar API is enabled on the Google Cloud project, not separately on each Google
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

## Incremental cursor expired

The Google adapter must discard the expired cursor, perform a safe initial-window scan, match managed projections through origin metadata, and establish a new cursor without duplicating events.
