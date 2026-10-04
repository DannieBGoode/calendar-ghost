# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and semantic versioning.

## [0.1.1] - 2026-10-03

### Added

- Overview now opens with a health hero that pairs the synchronization state and next action with a more expressive Calendar Ghost illustration.
- Settings explains the three-step connection flow in a collapsed helper beside Connected accounts.

### Changed

- Overview, Rules, Activity, and Rule Details now share bordered information cards, clearer section summaries, and a calmer visual rhythm.
- Recent Changes reads as a clickable timeline with connected markers, event context, and direct links into Activity and Rules.
- The Ghost mark gains a quiet happy expression for healthy synchronization, while the hero keeps state colors and copy aligned with the existing health model.
- Activity day separators are quiet, non-sticky row labels, and the generated Web UI bundle is refreshed for the release.

### Removed

- Removed the temporary in-app synthetic-data preview layer used to review the redesign; shipped views now stay connected to the installation's live data.

## [Unreleased]

### Changed

- The Web UI's API types are generated from the backend's OpenAPI schema
  ([ADR 0024](docs/adr/0024-generate-web-api-types-from-openapi.md)), so a changed response fails
  the frontend type check instead of breaking a page. The sync, reconcile, and preview routes now
  declare their response bodies, which are unchanged, and each Web UI call is typed by the route it
  names. An unknown `privacy_policy` in a rule request is still rejected with 422, now with
  FastAPI's standard validation detail.
- The frontend quality gate adds stricter TypeScript (`noUncheckedIndexedAccess`,
  `exactOptionalPropertyTypes`), type-aware ESLint with complexity and size bounds and folder
  layering, React Doctor, and `npm audit --audit-level=high`. CI runs all of them.
- Rule Details, Settings, Activity, Rules, and Overview are split into section files, and the
  activity copy into focused modules, so every frontend file and function is within the
  complexity and size bounds. The screens render the same markup.
- The Overview hero says each thing once: the headline gives the state, the detail explains it, the
  facts show running rules and the last sync, and the ghost reacts in a few words. The ghost is
  filled with its state's color, and its speech bubble sits beside it at eye level on every screen
  size.
- The README screenshots show the refreshed dashboard and follow the reader's light or dark
  appearance.
- The Overview distinguishes six health states, most urgent first: stopped (red, a crying ghost
  calling for help) when a rule is suspended until you act, needs a look (ochre, a concerned ghost)
  when events were blocked or a problem kept happening while rules keep running, waiting (indigo)
  when Google is limiting requests and rules retry by themselves, paused (an asleep ghost) when
  rules that synced before are all paused, setup, and healthy. Every other current problem is
  listed under the main one, and stopped rule badges are red to match.
- Recent changes and Activity mark each outcome with one sign set: + (added, including an event
  put back), − (removed), ~ (changed), or × (blocked), with ✓ and ⊘ for events left as they were.
  The bin, refresh, and undo icons are gone, so one outcome never has two icons.
- A disconnected account always shows **Reauthorize account** as its main action, disabled with the
  reason until Google OAuth is configured. While rules depend on it, its badge is red and it says
  how many rules stopped. Accounts that share a name lead with their address. A cancelled event no longer gets a red marker, since red now means you need to act.
- A rule whose Google account lost access is named by its calendar's last known name in the
  development preview, as it already is in a real installation.
- The development preview records a recent sync for each rule, and `--scenario` starts it in any of
  those states.

### Added

- The Community Edition is documented as a single-installation, privacy-first deployment under the
  GNU Affero General Public License, version 3 or later, with a separate trademark policy, data
  ownership guide. `LICENSE` holds the unmodified license text so GitHub and package tools detect
  it, and contributions need no CLA. A future hosted service will run this same open code, with
  billing behind a Commercial Mode that is off by default, so self-hosted installations keep every
  feature (ADR 0023).
- `provider` on Connected Account payloads (`GET /api/v1/accounts`), and `writable` on discovered
  calendars.
- SQLite migration 17 lets `connected_accounts.provider` hold any Provider Kind; code validates the
  value, so adding a provider needs no schema change (see [Deployment](docs/deployment.md) for
  rollback).
- The new-rule account selectors show each Connected Account's photo or initials alongside its name and email.
- An optional blue dark palette, **Midnight**, in Settings → Appearance → Dark palette. It applies whenever the interface is dark, including when it follows the device, and is saved in the browser like the theme. Twilight remains the default.
- Connected Account management with permission checks, safe disconnection, reauthorization, and permanent local deletion.
- Stable URLs for Overview, Rules, Activity, and Settings, with account identity markers throughout rule management.
- A warning before connecting a Google account when the browser address differs from the configured OAuth redirect URI, with LAN and Raspberry Pi redirect guidance.
- Google profile names and photos for Connected Accounts through optional basic profile access. Reconnect existing accounts to show their photos.
- Rule Details at `/rules/{id}` showing calendars, projection policy, all-day eligibility, initial window, state, managed projection count, and the last synchronization and reconciliation outcomes.
- Transformation Policy and all-day eligibility editing as a Material Rule Change that pauses the rule, requires a new preview, and rewrites every existing projection on the next run.
- Rule Removal with an explicit choice to delete mapped projections or keep them as Detached Events, and Rule Replacement for changing a rule's calendars.
- Activity groups decisions by synchronization run, names the rule's calendars, explains every skipped, blocked, or changed event in plain language, and can be filtered by rule and outcome with older entries loaded on demand.
- Activity entries can look up their source event and Managed Projection live from Google, showing the title, time, recurrence, and a Google Calendar link without storing any event content.
- Activity is a table grouped by day with Time, Event, What happened, and Rule columns. Event titles and times are read live from Google in small deduplicated batches for the rows on screen (`GET /api/v1/audit-entries/events`), and selecting an entry opens its details beside the table, led by the event and what happened, with a way to open the rule when a change was blocked. Checks that found an event already up to date are counted in one expandable row per run by default, consecutive runs that only made such checks share one summary row, and **All decisions** lists every check. A rule picker shows each rule's calendars with their account photos, lists removed rules separately, and follows the accessible select-only combobox pattern. The rule, filter, and open entry are kept in the page address.
- A development-only preview (`scripts/dev_preview.py`) serves the Web UI with synthetic data from its own marked database and a read-only fake Google; it refuses any other database and is excluded from the package and image.
- `GET /api/v1/audit-entries/{id}` returns one audit entry, `category` may be repeated to combine outcomes, `run_id` filters to one run, and `GET /api/v1/audit-entries/no-change-runs` lists recent runs with how many no-change checks each made, including runs that made nothing else.
- SQLite migration 7 indexes audit entries by run so Activity counts and expands runs without scanning the whole history.
- SQLite migration 3 adds stable reason codes and run identifiers to audit entries and backfills reason codes for existing entries.
- The Overview derives its headline, health strip, and single next action from one health model, so it never reports healthy while an incident, a stopped rule, or a lost authorization needs attention. It lists every rule with its state and last successful sync, and first-run guidance stays until a rule is running.
- Rule rows and Rule Details show when each rule last synchronized, move Sync Now, Reconcile Now, and Pause into a "More actions" menu that explains how each differs, report each command's result on its own rule, and restate the privacy consequence of the latest preview before a rule starts syncing.
- `GET /api/v1/dashboard` adds `disconnected_accounts`, `enabled_rules`, `stopped_rules`, and `last_synced_at`, and reports `attention` for stopped rules as well as open incidents. `GET /api/v1/rules` adds each rule's `last_sync` outcome.
- The Overview shows recent changes: the last runs that added, updated, removed, or repaired events, per rule and in plain language, with blocked changes linked to that rule's Activity. "Show events" looks up the affected events' titles and times live from Google on request and never stores them. When something needs attention, the status names the affected rule and links straight to it.
- `GET /api/v1/recent-changes` summarizes recent runs that changed or blocked events, using counts and entry identifiers only.
- SQLite migration 6 keeps the counts of each rule's latest preview, so "Start syncing" always restates how many events will appear. Rules and Rule Details expose them as `latest_preview`. It also keeps each rule's last successful run time across later failures (`last_succeeded_at`), so the Overview's last sync never disappears after a failed run.
- Activity filters live in the address (`/activity?rule=…`), and Rule Details links to that rule's activity.
- Recurring series and single-occurrence changes synchronize under the same ownership, privacy, drift-repair, reprojection, and removal guarantees as single events, and Rule Preview reports recurring series and changed occurrences with their planned actions.
- Rules, Rule Details, and the Overview show a rule's preview, sync, reconciliation, or removal while it runs, including runs the scheduler started and work that began before the page was reloaded. `GET /api/v1/rules` and `GET /api/v1/rules/{id}` add `running` (kind, start time, and a removal's handled and total projections), kept in memory by the single service process. A removal that is still running is never shown as incomplete, and Rule Details says when it finished.
- A rule whose preview passed shows **Start syncing** inline with one line saying how many events will appear and how many are excluded, replacing the review panel.
- The Activity rule filter has a clear button, and Delete or Backspace on the picker clears it.
- Overview rules show each calendar's account photo, list running rules first, and come before recent changes.
- Activity searches event titles as each run recorded them (`GET /api/v1/audit-entries?q=…`), ignoring case and accents so “reunion” finds “Reunión”. The search lives in the address as `q` and lists matching entries only, without per-run counts of no-change checks.

- Activity says what changed in a source event: "Title and description changed in Personal → updated in Work". Opening an entry lists each changed field's value before and after, with guests and video call links as added and removed, read on request from `GET /api/v1/audit-entries/{id}/changes`; `GET /api/v1/audit-entries` adds `changed_fields`. Title, time, description, location, guests, repeat pattern, and video call links are tracked; responses to invitations are not. Who made a change is not known to Google's API and is never shown. SQLite migration 14 keeps each rule's latest Source Observation of an event and each entry's Source Change. Titles stay plain text; the other values are sealed with a key derived from the installation master key and kept for 90 days ([ADR 0017](docs/adr/0017-record-source-changes.md)).
- Rules follow the source calendar's answer to each invitation. Events answered Maybe are synced marked as tentative ("Busy (tentative)", or "Maybe: Standup" when copying details) by default, or can be synced like accepted events or skipped. Invitations not answered yet are synced as Maybe by default, or can wait until answered. Declined events are never synced. Answering an invitation updates or removes its projection, an occurrence answered on its own changes only that occurrence, and Activity shows "Your response: Maybe → Yes". `POST /api/v1/rules`, `PATCH /api/v1/rules/{id}`, and rule responses add `tentative_events` and `unanswered_invitations`; `PATCH` requires both. SQLite migration 15 gives existing rules the defaults and reprojects them on their next run ([ADR 0018](docs/adr/0018-project-by-invitation-response.md)).
- Sync Runs, Reconcile now, and Rule Removal log what they are doing: when a run starts and why it lists what it lists, what each calendar reported, progress at most every 30 seconds while it decides events, and how it finished or failed, with its Google call count, token refreshes, rate-limited and server-error responses, and slowest call. A Google call slower than 10 seconds is logged as a warning, and `CALENDAR_SYNC_LOG_LEVEL=DEBUG` logs every call. Lines name rules and runs by their identifiers only and never contain event content, calendar identifiers, or account emails. Docker Compose caps the container's logs at three files of 10 MB. See [Reading the logs](docs/troubleshooting.md#reading-the-logs).
- A running sync shows how far it got on Rules and Rule Details: "380 of 840 checked · Running for 12 min 3 s", with a progress bar, counting the events both calendars reported and, after a Material Rule Change, the projections being rewritten. `running` in `GET /api/v1/rules` and `GET /api/v1/rules/{id}` now reports a sync's `total` and `done` as well as a removal's.
- Settings → Storage shows the database size, reclaimable space, the number of Activity entries, and the oldest one, and clears Activity older than 30, 90, 180, or 365 days, with an inline confirmation that shows the count first. Clearing keeps, per rule and source event, the older entries newer ones are compared with, found by id so a clock stepping back cannot reorder them (normally the latest entry older than the cutoff and the latest that recorded a title), deletes in batches of 5,000, then compacts the database while every rule's run lock is held, answering 409 when a rule is still synchronizing after 30 seconds; the entries are removed by then, and their space stays unreclaimed until a later clear, which Settings offers as Reclaim space ([ADR 0019](docs/adr/0019-administrator-chosen-activity-retention.md)). The service also writes its own rotating log files beside the database (`CALENDAR_SYNC_LOG_DIR` to relocate them, empty to turn file logging off), capped at 25 MB across five files, and Settings → Storage offers Download and Purge logs. `GET /api/v1/storage`, `GET /api/v1/storage/activity`, `POST /api/v1/storage/activity/clear`, `GET /api/v1/storage/logs`, and `DELETE /api/v1/storage/logs` are admin-only.

### Changed

- The run log key `google_calls=` is now `provider_calls=`, and the debug and slow-call log lines
  read `provider call provider=google op=…` and `slow provider call provider=google op=…`. Anyone
  grepping or alerting on the old text must update it.
- Incident summaries name the provider that failed: "Authorization for Google Calendar expired",
  "Access to Google Calendar was denied" (unchanged for Google). Provider-neutral code no longer
  assumes Google when it names the failed provider.
- When Google returns to a different address than the one Calendar Ghost is open at, Settings and Overview take the address Google landed on: paste it and choose **Finish connecting** to complete the connection here, instead of editing the address bar or opening an SSH tunnel. The mismatch is no longer a permanent warning: it is a quiet note at the foot of Connected accounts, whose details lead with the permanent fix, an HTTPS redirect URI, and it asks for the address only for 10 minutes after you start connecting from that browser.
- Settings is regrouped: Connected accounts, Storage, then Appearance, which applies to this browser only. Each section's rows sit in one bordered group under its heading, so a section heading no longer reads as an empty row. Connected accounts collapse to one summary line ("2 accounts connected", or "1 account connected, 1 needs reauthorization"), which opens by itself when an account needs attention or was just connected; the note that Google returns to a different address closes that group instead of floating beside it. Connect Google account is the primary action only while no account is connected. The Operations section is gone: it had no controls, and its "Active" badge was shown whether or not anything ran. Accounts say which rules use them in plain words, Logs explains how to turn file logging on when it is off, and a connection result is announced once rather than again on every reload.
- The product is now called **Calendar Ghost**, with a ghost mark, a twilight palette led by Lantern Indigo, and bundled Fraunces and Figtree typefaces that render without internet access. Package, environment variable, image, and database names are unchanged, so existing installations upgrade in place and keep their appearance setting.
- Reconcile Now's result counts what still differs after its sync by kind, such as missing from the destination or different from the source event, names the destination calendar, and says a recurring series counts once among the events checked. It no longer says the next sync puts back what changed during the check: a difference that survives the sync before the check is one the sync cannot settle, so the message says so when Reconcile Now finds it again.
- Activity leads only with open incidents, each saying what happens next and offering its next step: reauthorizing in Settings, then recovering the rule once the Google account that failed was reauthorized (a recovery preview that finds the rule's other account also lost access points back to Settings, and every rule command refreshes incidents), reviewing the stopped rule, or filtering to the rule's blocked events. Resolved incidents move behind **Show resolved incidents** and say when they opened and closed and why: after a successful sync, when the daily check found nothing still blocked, or because the rule was removed (`GET /api/v1/incidents` adds `resolved_at`, `resolution`, and `account_id`, and `GET /api/v1/accounts` adds `authorized_at`; SQLite migrations 12 and 13). Previously a resolved incident occupied the top of Activity indefinitely, and one closed by removing its rule looked fixed.
- Activity's default view lists only changes, skips, and blocks. It no longer adds a row to each run counting the events already up to date, or a summary row for runs that found nothing to change. **All decisions** and **No change needed** still list every check. `GET /api/v1/audit-entries/no-change-runs` and the `run_id` filter on `GET /api/v1/audit-entries` are removed.
- Activity and the Overview say what triggered each change: what Calendar Sync observed and in which calendar, then what it did, such as "Cancelled in Personal → removed from Work", "Moved from 10:00 AM in Personal → updated in Work", or "Missing from Work → put back". They never guess who made a change, say "again" when a repair redoes the previous run's, and label recurring entries as the whole series or one occurrence. `GET /api/v1/audit-entries` adds `event.moved_from` and `repeated`.
- Blocked entries say what is now different in the destination calendar and who acts. A block the daily full pass still finds opens one Incident per rule, resolved by a later daily pass without persisting blocks, and the Overview's health strip names events that could not be synced, linking to the newest one (`GET /api/v1/dashboard` adds `blocked_events`, `blocked_entry_id`, and `blocked_rule_id`). SQLite migration 11 records where each rule's latest daily pass began, so only blocks decided since then count as open.
- The Overview's recent changes list the latest written events instead of run summaries, one line each, counting an identical repair repeated across runs on one line. `GET /api/v1/recent-changes` now returns each event's audit entry with `repeats` and `first_occurred_at`.
- A series check made only to repair a missing occurrence is no longer recorded as its own "already up to date" entry beside the block; the block's detail records the check and the occurrence's original start.

- Activity names events from what each run recorded instead of reading them from Google, so the Event column appears with the table and removed rules' history keeps its event names. Audit entries now record the source event's title, time, recurrence, and cancellation in plain text (SQLite migration 9, [ADR 0014](docs/adr/0014-record-event-titles-on-audit-entries.md)); descriptions, locations, and attendees are still never stored. `GET /api/v1/audit-entries` returns each entry's `event`, filled from the event's previous entry when Google reported no title and marked `renamed_from` when the title changed. Entries recorded earlier are not backfilled and show no event name. `GET /api/v1/audit-entries/events` is removed, and the Overview's recent changes name their events the same way. Opening an entry still looks its event up live in Google.
- Synchronization runs spend fewer Google requests. A projection or occurrence that the incremental destination feed reports back unchanged after this rule wrote it is no longer re-checked against its source, a mapping reported by both feeds in one run is decided once, and full passes reuse the destination listing instead of reading each projection again.
- Each rule's daily full pass runs once per UTC day, tracked per rule in SQLite migration 8 (`last_full_succeeded_at`). A rule's first run counts as that day's pass, and restarting the service or another rule failing no longer repeats it.
- Activity no longer records loop prevention (`managed_projection_source`), events outside the rule's scope (`outside_source_calendar`, `cancelled_without_projection`, `before_sync_window`), or retired occurrence records (`occurrence_retired`); runs still count them. The daily full pass no longer repeats `all_day_excluded` and `series_not_synchronized` skips. Earlier entries with these reasons are hidden from `GET /api/v1/audit-entries`.
- Rule Removal leaves an event whose ownership cannot be verified in place and continues instead of stopping, retries temporary and rate-limited Google failures with backoff and Google's `Retry-After` hint (bounded to 60 seconds, also used by scheduled runs), opens an Incident when destination authorization is lost, and reports deleted, detached, and left-behind events on the rules list. The removal and replacement API responses include a `conflicts` count.
- Disconnected-account rules now stop clearly and preserve recovery data until reauthorization or permanent deletion.
- Appearance and color-theme preferences now share one Settings control.
- Rules name each Source and Destination Calendar and its account email instead of showing provider calendar identifiers.
- Migration 4 records pending reprojection and the latest run outcomes for each rule.
- Migration 5 records Occurrence Mappings and resets incremental positions once so enabled rules backfill recurring events on their next run. Pause a rule before upgrading to preview its recurring projections first.
- Audit entries moved from `/api/v1/activity` to `/api/v1/audit-entries`, and the old path is removed. After upgrading, reload or hard-refresh every Calendar Sync tab and bookmark: pages loaded from the previous release still call the old path, and browsers may have cached them.
- Unknown `/api/` paths now return a JSON 404 for every method, known paths called with the wrong method return 405 with an `Allow` header, and known paths with an extra or missing trailing slash redirect, instead of the web app page.
- Rule Removal is collapsed until requested, confirms with a message on the rules list, and returns focus to the next view. Navigation now moves focus into the new view, names each page in the browser title, and closes the mobile menu with Escape.
- Rule Removal is a single step with the choice, its consequence, and a named confirm button together. Widening a rule from Busy only to event details now warns who will see them and names the effect on its button.
- A stopped rule's details explain what stopped it and that nothing was lost, and its next step reads "Preview to restart".
- Keyboard focus stays on the page after preview, start syncing, pause, and saving a policy; the "More actions" menu shows a visible focus ring, stays inside the viewport on small screens, and keeps focus while a command runs. Relative times such as "3 minutes ago" keep updating while a page is open.
- Buttons, labels, and supporting text use one compact type scale, the top bar is opaque, and focus rings remain visible in forced-colors mode.
- The web app page is now revalidated on every load, so future upgrades take effect without a hard refresh.

### Fixed

- The calendar replacement form no longer shows a rule's previous calendars after the rule
  refreshes; untouched fields follow the rule, and edits are kept.
- The Web UI's request helper keeps headers passed as a `Headers` object.
- A request validation error (422) shows its messages instead of `[object Object]`.
- Reconcile Now returns a completed rule to **Enabled** immediately, without requiring a page refresh.
- Rules keep their calendars' names when the page reloads. Names were read from Google on every load, so rules showed "Secondary calendar" until Google answered, and always for an account that was disconnected. Each calendar's name is now kept when its account's calendars are listed (SQLite migration 16) and returned with the rule as `source.calendar_name` and `destination.calendar_name` by `GET /api/v1/rules` and `GET /api/v1/rules/{id}`; a rename in Google replaces it the next time the calendars are listed, and only a changed name is written.
- Reconcile now shows its progress without reloading the page. Rules and Rule Details refresh every two seconds while a command they sent runs, so its progress appears as soon as the service reports it. Reconcile now counts its full pass ("Syncing every event from Family to Work, then checking each one this rule wrote."), times itself from its start through the check, and stays named Reconciling after a reload: `running` reports it as one reconciliation and adds `stage`, `"sync"` during the full pass and `"reconciliation"` during the check.
- A recurring event whose remaining occurrences you all declined is no longer added back and removed again on every full run and Reconcile Now. The check for whether a series has an occurrence left to sync counted declined occurrences, so the run recreated the series, removed its declined occurrence, and Google then cancelled the whole series; Reconcile Now reported it as still different. The check now follows the rule's choices for declined, unanswered, tentative, and all-day events, so such a series stays dormant until you accept an occurrence, and Rule Preview leaves it out.
- `CALENDAR_SYNC_LOG_LEVEL` now takes effect. The service never configured its own logging, so under Uvicorn its informational lines were dropped and container logs showed nothing about running work.
- Refreshed Google access tokens are kept, encrypted, with their Connected Account. Every request after the first hour of a connection refreshed its token first, which added a token request to each Google call; a refresh never counts as a reauthorization and never replaces a newer one.
- A run reads each destination series once, however many of its occurrences it re-checks, and again only after it rewrote the series. A rule with 700 recorded occurrences read the same series for every one of them, which made a full re-check take about 40 minutes on a Raspberry Pi. Occurrence writes still verify the series' ownership with their own fresh read.
- Re-checking a series' recorded occurrences lists the series once in each calendar instead of looking every occurrence up, and an occurrence a listing did not find is still looked up on its own, so a missing answer never reads as absent. A full run also no longer looks up the source of each destination occurrence it already decided from the source listing. Together these were most of a 40-minute re-check on a Raspberry Pi, and of every daily pass.
- A rule no longer rewrites a projection whose content would not change. Google gives an event a new revision for any edit, including a reply to its invitation, so a Busy-Only rule used to rewrite "Busy" and Activity said the event was updated. Such a revision is now "already up to date", and the mapping records it without a provider write; occurrences behave the same way. A series whose revision changed still re-checks its occurrences, and records the revision only once they were re-checked, so a failed run re-checks them on its retry. An update now reads as a repaired destination edit unless the source asks for a different projection than the one last written.
- A Google account whose access Google revoked or let expire is now reported as needing reauthorization. The failed access-token refresh carries no HTTP status, so it was classified as a permanent rejection: its incident read "Google Calendar rejected synchronization" and pointed to the rule instead of Settings. A token-endpoint outage or a network failure while refreshing is now temporary and retried.
- An incident that opens again after resolving shows when this episode began. The Overview's "Since" previously reached back to the incident's first opening, possibly weeks earlier.
- Permanently deleting a Disconnected Account can no longer race synchronization, reauthorization, or rule creation. It waits for in-flight work of every affected rule, then deletes the account and its rules in one transaction that rechecks the account is disconnected. `POST /api/v1/rules` and `POST /api/v1/rules/{id}/replace` now answer `409` ("connect both Google accounts before creating a rule") when either calendar belongs to an account the installation does not have, instead of creating a rule no account can serve.
- A single occurrence moved to another time, such as this week's Tuesday meeting moved to Thursday, now moves in the destination calendar instead of being blocked as `destination_occurrence_missing` on every run. Google returns no match for a moved occurrence when its lookup asks for one result, so the lookup now reads Google's full answer, following further pages, and reports an occurrence absent only once every page was read. The same lookup on the source side could treat a moved occurrence as removed from its series and cancel it in the destination (`occurrence_removed_from_series`); the daily check restores such occurrences within the sync window.
- A recurring event whose every occurrence is cancelled, such as what remains of a "this and following" split, is no longer restored and cancelled again on every run. Google cancels a series once its last occurrence is cancelled, so the run now checks that the source series has an occurrence left that the rule projects (all-day occurrences do not count when the rule excludes them) before creating or restoring it. Otherwise it skips the series (`series_without_occurrences`) and keeps any existing mappings dormant. When an incremental run creates or restores a series, it now applies the source's cancelled and moved occurrences too, so restoring one occurrence never brings back the others, even ones cancelled while the series had no projection. A replay interrupted by a failed run is finished by the retry (migration `0010_pending_exception_replays.sql`). Reconciliation no longer reports such a series as missing once it confirms the projection is gone, Rule Preview excludes it, a series Google cannot expand no longer fails the rule, and a projection left by an interrupted first create is removed (`series_without_occurrences_removed`).
- A running Rule Removal shows live progress ("Handled 84 of 312 projections in Family", a progress bar, and elapsed time) instead of a static "Removing…" button, and no longer reports itself as "Removal incomplete" when the page refreshes mid-run. Rule Details, the rules list, and Overview show the rule as Removing, editing is hidden from the start, and keyboard focus follows the progress. A dropped connection or proxy timeout explains the removal may still be running, and a retry that finds the rule already removed finishes with a notice to check Activity under Blocked for events left in place. A removal that finishes after the administrator has moved to another page no longer pulls them back to the rules list, and Overview health does not count a running removal as a stopped rule.
- Incremental synchronization no longer projects single events that ended before the 30-day window and were never synced. Google's change feed reports edits to events of any age, which could copy events from years ago; these are now skipped with the reason `before_sync_window`, while already-synced events keep updating.
- Recurring events excluded by the pre-alpha policy are recorded as skipped instead of as conflicts, so they no longer appear as blocked; existing entries are shown as skipped as well.
- Google OAuth callbacks now support local HTTP development, preserve PKCE verification across redirects, and recover cleanly when Calendar permissions are declined.
- Activity request failures, empty activity, and low-contrast actions now have distinct, accessible interface states.
- Activity now loads when browser content blockers such as uBlock Origin are enabled.
- The Activity page now explains why it could not load: an expired session, an updated installation that needs a reload, a service error, or a request that never reached the service, such as one stopped by a content blocker.
- Changing the Activity rule or outcome filter keeps the page, its filters, and keyboard focus on screen while the new entries load, instead of replacing the whole page with a loading placeholder.
- Occurrences of a recurring event that already matched their projection are listed as no change instead of as skipped.
- Every database connection now enforces foreign keys and closes when it is done, so a failure
  recorded for a rule removed meanwhile no longer leaves a stray failure count behind.

## [0.1.0] - 2026-08-30

### Added

- Provider-independent synchronization and reconciliation domain foundation.
- SQLite persistence boundary and initial schema migration.
- Single-administrator setup and authenticated API sessions.
- React, TypeScript, Vite, and shadcn/ui operational interface.
- Open-source project documentation, CI, and architecture decisions.
- Source-authoritative sync for timed and all-day events, cancellations, destination repair, and incident notifications.
