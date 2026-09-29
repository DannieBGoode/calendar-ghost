# Troubleshooting

## The Web UI cannot reach the service

Check `docker compose ps`, then request `http://localhost:8000/health`. Review container logs without posting credentials or event payloads publicly.

## An event did not synchronize

Open **Activity**, filter by the rule, and choose **Skipped** or **Blocked**. Each row names the event
and why no Event Projection was written; select it to see the full explanation, the event as the run
recorded it, the event as it is in Google now, and a link to open it in Google Calendar. Common reasons:

- **Skipped a recurring event**: recorded by a release before recurring-event support. The next
  run after upgrading projects the series.
- **Skipped an occurrence**: the occurrence belongs to a series this rule does not project, such as
  a Managed Projection or an all-day series under a timed-only rule.
- **Blocked: the occurrence was not found in the destination series**: the destination series no
  longer expands to the source occurrence even after repair. Run **Reconcile now**; if it persists,
  remove the rule and create it again.
- **Skipped an all-day event**: the rule syncs timed events only.
- **Skipped a managed projection**: Managed Projections never become sources, which prevents loops.
- **Blocked**: identity or ownership was ambiguous, so nothing was written. Run **Reconcile now**
  from Rules and review any incident.

## A rule removal stopped or left events behind

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

Open the incident in the Web UI. Authorization incidents require reauthorizing the affected identity
from Settings. The rule keeps mappings and its last successful incremental positions and performs no
writes while degraded. After reauthorization, choose **Validate recovery** in Rules, inspect the
preview, and enable the rule; its next run repairs drift before advancing either cursor.

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

## Incremental cursor expired

The Google adapter must discard the expired cursor, perform a safe initial-window scan, match managed projections through origin metadata, and establish a new cursor without duplicating events.
