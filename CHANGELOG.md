# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and semantic versioning.

## [Unreleased]

### Added

- Plans let an administrator limit how much each person uses
  ([ADR 0038](docs/adr/0038-plans-allowances-and-limits.md)). Plans are off by default, and while
  they are off nothing changes. Administrators are never limited, and under **Only me** Plans stay
  hidden. Under **People → Plans**, one **Plans** switch turns them on, and a table compares the
  Plans: the most active rules, calendar accounts, and Integration Tokens a person may have, each
  No limit or Up to a number, the sync speed, from Instant to every hour, and how many people have
  each Plan and are over a limit. A Plan opens in a full-height drawer at its own address
  (`/people/plans/{key}`) to edit it, or to give it to people after a dry run says who would be
  over. Everyone without a Plan of their own has the default; turning Plans on with no default adds
  a Plan named No limits, which limits nobody, as the default. **Everyone** shows each person's
  Plan, lists who has a Plan or is over a limit, and gives the people selected another Plan, with
  **Undo**. A person's page and **Settings → Your account → Your plan** show a meter for each
  limit. Once a Plan is the default, **Invitations** says which Plan someone invited will get.
- With Plans on, starting a rule, connecting a new calendar account, and issuing a token respect
  the person's Plan, and each control says so at the limit and links to Your plan. A Plan that
  syncs every 5, 10, 15, or 30 minutes, or every hour, has no Instant Sync, and runs each rule once
  per interval, each at its own time within it, so an hourly Plan's rules spread over the hour; a
  rule that never ran, is failing, or was just previewed still runs at the next five-minute pass.
  A rule's page and the Overview say how often the person's Plan syncs. Reauthorization is never
  refused. A lowered limit refuses only what is new and stops nothing: rules beyond it keep
  syncing, and existing accounts and tokens keep working. Returning to setup turns Plans off and
  keeps their definitions.
- The Plans API: `GET` and `POST /api/v1/plans`, `PUT` and `DELETE /api/v1/plans/{plan_key}`,
  `PUT /api/v1/plan-settings`, and `POST /api/v1/plan-assignments`, which gives each of up to 100
  people the Plan it names for them, all or none, so Undo never gives back only some, and with
  `dry_run` only says who would be over; giving the default's key means following the default.
  `GET /api/v1/account/plan` answers Your plan. People rows and a person's overview gain `plan`,
  `GET /api/v1/users` filters by `?plan=` and `?over=true`, rule details gain `can_start` and
  `rule_limit`, and rules and rule details gain `keeps_place`. A Plan's key is made from its name
  unless `POST` names one; no Plan has the key `new`. New problem codes: `plan_limit_reached`,
  `plans_need_default`, `plan_not_found`, `plan_key_taken`,
  `plan_name_taken`, `plan_in_use`, `plan_is_default`, `invalid_plan`, and `invalid_assignment`; a
  new account past the limit returns to Connections with the OAuth outcome `account_limit_reached`.
- Migration 33 adds the `plans` table and the Plan columns. Rolling back to an earlier release
  works with the same database, which ignores them and limits nobody; after upgrading again,
  Plans are as the administrator left them.
- Instant Sync: with a public HTTPS address in `CALENDAR_SYNC_PUBLIC_URL` that Google and Microsoft
  reach at `/api/v1/watch-notices/`, a rule runs soon after its provider reports a change in its
  Source Calendar instead of waiting for the next five-minute sync. Scheduled syncs and the daily
  pass still run and catch any report that is lost. Each person can turn it off under
  **Settings → Your account**, where the switch says why when it cannot run and links to the guide.
  Each rule says "Syncs instantly" or "Syncs every 5 minutes" and why. Installation Health tells
  administrators when the public address uses plain HTTP at a host the internet reaches, or a
  provider cannot reach it. Migration
  31 adds the tables; see [Instant Sync](docs/instant-sync.md) for proxy and tunnel examples.
- Installation Health warns before the Microsoft client secret expires. Copy the secret's
  **Expires** date from Entra into `CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET_EXPIRES`: from 30 days
  before it, an installation Incident needs the administrator on People and in
  `GET /api/v1/installation/health`, and goes to the installation's email and webhook. Calendar
  Ghost cannot read the date from Microsoft, so without the setting nothing changes.
- Accounts an administrator's Cause stopped restart on their own once it is fixed, such as an
  expired client secret, a Google OAuth client that was reset, or the Google Calendar API turned
  off. The scheduled pass checks each such account again, at most once an hour per person and at
  once after a restart, and a check that passes restarts its rules. Before, each person had to
  choose **Check access**. A check that still fails changes nothing and notifies nobody again.

### Changed

- Inspect Activity entries and incidents, or edit a Plan, in a full-height drawer without changing
  the table underneath. Drawers fill narrow screens, keep navigation and edit protections, and
  leave notifications and Undo reachable.

- Menus never leave the window: a **More actions** menu near the foot of the window, or above a
  message at the bottom of it, opens above its button and scrolls inside itself when it must, so
  the message never covers an item. A disabled item's reason stays readable. On a touch screen,
  buttons, fields, and selects are 44 pixels tall. Links that fill a table cell, such as a Plan's
  name or a person's email, are underlined only under the pointer or keyboard focus, and each
  names its row for a screen reader. The footer keeps the space before **AGPLv3+ license**.
- What opens in place scrolls fully into view as it opens: a confirmation under a row, such as
  **Remove** on the last Plan or **Delete** on a person's page, and **Change plan** in a person's
  **Plan** card, so its buttons are never below the window. It scrolls at once when the device
  asks for reduced motion, and focus stays where it was put.
- **Replace calendars…** creates the new draft rule in the same step that begins the previous
  rule's removal, once that rule's run ends, instead of before it. A duplicate relationship found
  meanwhile, or a calendar account that is gone, now leaves the previous rule as it was and
  creates no draft, and a removal that fails after it began keeps the new draft. With Plans on,
  the new draft keeps the previous rule's place when that rule counted, so it can start whatever
  the limit.
- Rule Details labels each of the rule's choices with the icon its preview shows for it, and both
  pages list the choices in the same order: how events look, then which events the rule includes.
  Unanswered invitations keep one icon on the preview whatever the rule decides. How many
  projections the rule keeps moved to **Latest runs**.
- Activity no longer lists a skip that repeats the event's previous entry when the provider sent a
  new version of the event and Calendar Ghost detected no change in what it tracks. A bulk change
  to responses or reminders used to add hundreds of identical entries. The run log counts these as
  `unrecorded=N`. The daily check, writes, blocks, and every decision that differs from the
  event's previous entry are still recorded. An entry's details now say why it was checked ("Why it
  was checked") and how the event compared with the version Calendar Ghost last saw. Entries
  recorded before this release show neither line.
- The rule builder and the policy editor group a rule's policy the same way: how events look
  (event information, Maybe events, unanswered invitations) beside which events to include
  (all-day events, birthdays). Event information now says what the destination shows, and in
  Attention Ochre who sees the details when a rule copies them. The builder lines its policy up
  with the calendars above, has a Cancel button, announces loading, empty, and saving states to
  screen readers, and keeps an empty calendar list and the saving button reachable by keyboard.
- Preview rule opens its own page, `/rules/<id>/preview`. It lists every event in the rule's
  starting window beside what the destination will hold ("Busy", "Busy (tentative)", or the title
  under Details Projection), with Activity's signs for what happens and the reason for each event
  that stays out ("Not synced: birthday"). One row of filters narrows it to what will or will not
  sync, combined with any of all-day, birthday, recurring, declined, Maybe, or unanswered events.
  A recurring series shows at its next date, and earlier events fold away unless one would be
  removed. A date outside the current year names its year ("Tue, Jul 9, 2030"). "Start syncing"
  is only on this page, in a footer that stays in view beside the counts, and names sharing
  details when the rule copies them. A new rule's builder ends there, a rule ready to start
  offers "Review and start", and Refresh reads the calendars again.
- A preview reads the destination through one listing of the rule's projections instead of one
  request per mapped event, and returns every event instead of a sample of 10.
- While a preview reads the calendars, the page says so where the results appear: the ghost
  moves, the placeholder rows shimmer, and a line counts the seconds and, after a while, says that
  large calendars can take up to a minute. With reduced motion, only the words change. The rule's
  settings under the privacy line are a row of short items, each with its own icon, and the ones
  that leave events out are quieter.

### Fixed

- A new rule no longer copies recurring series that ended before its starting point. A rule
  "from the past 30 days" previewed, and its first sync added, series whose last occurrence was
  years ago, because Google still lists them. A series now syncs only while one of its occurrences
  ends at the starting point or later, including an upcoming one; one that started long ago
  but still repeats syncs as before. Series a rule already synced stay current, and past
  occurrences of a series the rule leaves out are no longer listed in Activity or the preview.
- A new rule no longer lists, in Activity and its preview, the occurrences of a series deleted
  from the source before the rule existed. A deleted series stays readable for some weeks, so its
  cancelled occurrences read "Its series isn't synced, so skipped". Deleting a series the rule
  projects records only the series' removal, not an extra skip for each moved occurrence, and a
  cancelled occurrence of a series the rule leaves out, such as one you declined, is no longer
  listed either. Entries earlier releases recorded for cancelled occurrences are hidden.
- A deleted series is removed from the destination even when the source reports only one of its
  occurrences, or when the destination reports an edit before the source reports the deletion.
  The single projection of an occurrence whose series the calendar did not show is removed once
  that series shows as deleted. Before, these stayed in the destination.
- Preview plans every event exactly as the next run decides it. An occurrence of a series the
  rule will write reads as part of adding it, an occurrence of a series the rule leaves out reads
  "Its series isn't synced", and the preview leaves out and does not count what Activity would not record, such as an event deleted before the rule projected
  it. An occurrence whose series the rule projected but the source no longer shows is blocked, as
  in a run.
- A new rule's preview counts every date of a series it adds as added, or as not synced when that
  date is cancelled ("Not synced: cancelled"). Before, a date the run corrects after it writes the
  series read as an update, a removal, or already up to date, though nothing was written yet.
  Activity still records each correction the run makes.

## [0.2.0] - 2026-10-12

### Added

- `scripts/live_provider_checks.py` runs the Outlook and Google release checks against real test
  calendars on demand, in about 5 minutes. Recorded provider answers from those checks now run in
  CI as adapter tests. Troubleshooting explains a projected series that appears twice after an
  edit with "this and following" in the destination (#99).
- Outlook is the second calendar provider, for Microsoft 365 work or school accounts and personal
  Outlook.com accounts, through Microsoft Graph v1.0
  ([ADR 0034](docs/adr/0034-outlook-through-microsoft-graph.md)). An installation that registers a
  Microsoft Entra application and sets `CALENDAR_SYNC_MICROSOFT_CLIENT_ID`,
  `CALENDAR_SYNC_MICROSOFT_CLIENT_SECRET`, `CALENDAR_SYNC_MICROSOFT_REDIRECT_URI` (default
  `http://localhost:8000/api/v1/oauth/microsoft/callback`), and `CALENDAR_SYNC_MICROSOFT_TENANT`
  (default `common`) offers **Connect Microsoft account**; without them nothing changes. A rule may
  read from one provider and write to the other. Outlook projections are appointments with no
  attendees, so no write emails anyone, and a repeat pattern Outlook cannot express exactly blocks
  that event as a Conflict instead of being approximated. Microsoft's reasons become Causes from
  its codes alone; an expired client secret is the administrator's `oauth_client_invalid`, with its
  own troubleshooting section, and the self-hosting guide explains registering the application and
  rotating its secret before it expires. Outlook is verified with personal Outlook.com and Hotmail
  accounts; Microsoft 365 work or school accounts can connect but are not yet verified, and the
  landing page, the documentation, and the Connect menu say so.
- `httpx` and `tzdata` are runtime dependencies: `httpx` reaches Microsoft Graph and stays inside
  the Microsoft adapter, and `tzdata` maps Outlook's Windows time zone names on any host.
- Run outcomes and Incidents carry the Provider Kind that failed (`failure_provider`,
  `provider`), and an access check a provider refuses names it in `params.provider`, so the Web UI
  names Google or Microsoft in each message.
- Migration 28 binds each OAuth state to the provider whose consent began it, so a state returned to
  another provider's callback connects nothing. Rolling back is safe.
- An event write the destination provider cannot represent exactly is recorded as a Conflict with
  the reason `projection_unsupported`, and the rest of the rule keeps syncing.
- The development preview makes Sam's and Robin's Work accounts Microsoft's, offers both
  providers, and adds the `outlook-client` scenario.
- `GET /api/v1/providers` lists each calendar provider people can connect on this installation:
  its Provider Kind, name, connect address, redirect URI, and the troubleshooting section for each
  Cause it can raise ([ADR 0022](docs/adr/0022-route-calendar-requests-by-provider.md), amended).
  Connection flows live at `/api/v1/oauth/{provider}/start` and `/api/v1/oauth/{provider}/callback`.
  Google's addresses, including the redirect URI every installation registered with Google, are
  unchanged, and `GET /api/v1/google/configuration` keeps answering as before for earlier clients.
- Installation Hints and every problem in Installation Status, the dashboard, and the Operator
  Overview carry `provider`, the Provider Kind whose answer explains them. Migration 27 records the
  provider with each Cause; every Cause recorded before names Google. Rolling back is safe.
- Several people can share one installation, each with private Google accounts, rules, Activity,
  incidents, and tokens ([ADR 0029](docs/adr/0029-isolate-users-in-one-sqlite-database.md),
  [ADR 0030](docs/adr/0030-users-administrators-and-registration.md)). People sign in with email and
  password. The Registration Policy is **Only me** by default; an administrator may choose
  **Invitation only** and send single-use invitation links that expire after 7 days. A **People**
  page lists everyone with search, filters, sorting, and pages, and holds invitations, roles,
  disabling, password reset links, and deletion. Settings is split into **Your account** (email,
  password, incident emails, appearance, and deleting your own account), **Connections** (Google
  accounts and Integrations), and, for administrators, **Administration** (Who can join and
  Storage). An administrator never sees anyone's calendars or events. The last person may delete
  their own account, which returns the installation to setup.
- Migrations 21 to 23 give every record a User, turn the existing administrator into the first User
  with every existing record, add the Registration Policy and hashed links, and give Integration
  Tokens scopes. Rolling back past them means restoring the backup taken before the upgrade.
- Installation Health, for administrators and their monitors, at `GET /api/v1/installation/health`
  and as the MCP tool `get_installation_health`, through the new `installation:read` token scope:
  incidents about the installation itself and how many people are in each status.
- The installation's SMTP recipient and webhook are told when the scheduler stops completing passes.
- The Operator Overview. **People** shows everyone first, with Installation Health above them, and
  keeps invitations waiting in an **Invitations** tab that counts them; "Invite someone" sits beside
  the page title. Each person's sync status is a chip with an icon, and the list filters and sorts
  by it. Installation Health's counts, including one for disabled people, set the list's filters,
  and "What each sync status means" explains every status. Each person's page at `/people/{id}`
  shows their Installation Status, with calendars only as "Calendar 1", "Calendar 2", and their
  resource use: rules, Google accounts, Activity entries, and Google calls over the last 30 days.
  `GET /api/v1/users` now includes each person's `verdict`, `problems`, `last_synced_at`, and
  `resources`, and accepts `verdict` and `sort=verdict`; `GET /api/v1/users/{id}/overview` answers
  administrators and 404 to anyone else. Administrators never see calendar names, Google account
  emails, or events.
- Each calendar in Installation Status has a `number`: in the Operator Overview, the number its
  neutral label carries ("Calendar 2" has 2), so the Web UI can name it in the reader's language;
  `null` in a User's own status, which names the calendar.
- A person's page leads with sync health and says who takes the next step for each problem.
- Causes ([ADR 0031](docs/adr/0031-keep-the-providers-reason-as-a-cause.md)). When Google refuses a
  request, Calendar Ghost reads why from Google's reason code, never its message, and records it as
  a Cause on the Incident and the run: the Calendar API is turned off, the project's daily quota is
  used up, or Google no longer accepts the OAuth client, which only an administrator can fix; or
  the account's grant was revoked, the calendar is closed to the account or gone, Google is limiting
  requests or failed for a moment, or a reason Calendar Ghost does not recognize, which the person
  handles from their own dashboard. Problems and incidents in `GET /api/v1/status`,
  `GET /api/v1/dashboard`, and `GET /api/v1/incidents` carry `cause`, problems say when they were
  last tried, and the status and dashboard say when the scheduler next tries. **People** says
  **Needs you** and is marked in the navigation when anyone meets an administrator's Cause, or two
  or more people fail for an unrecognized reason or lose Google about 7 days after connecting (an
  OAuth app in Testing mode), each with **How to fix**; people's own problems are not flagged, and
  their page says what they do if they ask for help; `GET /api/v1/installation/health` returns them as `hints`. A person's page
  says each problem's likely cause. For an administrator's Cause, each person's Overview says
  only "Temporarily unavailable", naming neither the cause nor the administrator; otherwise they
  give its one step. Administrators
  never contact anyone through Calendar Ghost about a problem.
- `CALENDAR_SYNC_PUBLIC_URL`: with it, each incident email links to the person's next step in the
  Web UI. The link names no calendar, account, or event.
- Migration 26 adds `incidents.cause` and `rule_run_outcomes.failure_cause`. Earlier failures read
  as unknown. Rolling back is safe.
- Google's `dailyLimitExceeded` is now retried as a rate limit, and a calendar the account may not
  change (`requiredAccessLevel`, `forbidden`, `forbiddenForNonOrganizer`) now stops only its rule;
  earlier both lapsed the whole account as if its authorization had been refused.
- `GET /api/v1/installation/health` reports `needs_attention` while it has a hint, even when every
  rule is only waiting.

- Migration 24 records the order rules were created in, and migration 25 counts each person's
  calendar provider calls per day, kept for 30 days. Rolling back past either is safe.
- Failed sign-ins are throttled per email and per client address. Unusable invitation and password
  reset links are throttled per client address, twenty in 15 minutes, and are refused before any
  password is hashed.

- The Web UI footer links to the troubleshooting guide ("Get help"), which ends with where to ask
  questions (GitHub Discussions), report bugs (a new bug report form), or email
  support@calendarghost.com.
- Monitors, homelab dashboards, and AI agents can read Installation Status with an Integration
  Token: `GET /api/v1/status` for tools like Uptime Kuma and Homepage, and an MCP server at `/mcp`
  for Claude Code, Codex, and other agents. Settings → Connections → Integrations, collapsed until
  opened, issues and revokes tokens and shows setup examples for each tool.
- Installation Status notices a scheduler that stopped running passes and a rule that has not
  synced in over a day.
- The Web UI is ready for translation: catalogs, plural rules, and locale-aware dates and numbers.
- Every Web API error body carries a stable `code` and `params` beside its unchanged English
  `detail` and status ([ADR 0026](docs/adr/0026-translate-the-web-ui-through-message-catalogs.md)).
  The MCP endpoint's HTTP refusals use the same shape.
- Incidents record what they say as a message code and parameters (migration 19), returned as
  `message` by the Incidents API and on each Installation Status problem an Incident explains.
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

- The Web UI and the landing page install with pnpm instead of npm. No dependency runs an install
  script unless it is allowed, a package version is installed only once it is 7 days old, and a
  package whose provenance weakens since an earlier version is refused. The landing page now
  declares `sharp`, which it used without declaring, at 0.35.5, which fixes CVE-2026-96889.
- The rule health policy, which decides when a failed run stops its rule and when it opens an
  Incident, moves into the domain (`domain/health.py`), with the failure kinds that need
  reauthorization or a retry (`domain/providers.py`). Behavior is unchanged (#104).
- Connecting or reauthorizing an account opens the provider's consent in a new tab when its
  redirect URI is at another address than the one Calendar Ghost is open at, such as `localhost`
  while Calendar Ghost runs on a LAN host. The tab you started from stays on Calendar Ghost and
  shows **Finish connecting** at once, ready for the address the new tab ends on. When the
  redirect URI is this address, consent still opens in the same tab.
- Providers that return to another address share one note at the foot of Connected accounts
  instead of one note per address. It has one field that finishes a connection for any of them,
  without a placeholder that looked like a filled-in value, and gives the fix once. When providers
  return to different addresses, it lists each one and says an installation usually answers at
  only one.
- Connecting an account is one action instead of one equal button per provider. With one provider
  configured it stays a direct button, such as "Connect Google account"; with several, "Connect an
  account" opens a menu that names each provider's account beside its mark. It is the primary
  action only while no account exists, in the Getting started step and in the Connected accounts
  empty state, and a quiet outline button in the section heading after that.
- The Overview counts stopped and running rules as the status API does: a rule has stopped when it
  does not synchronize until someone acts. An enabled rule whose account was disconnected or whose
  authorization lapsed now counts as stopped on the Overview (`stopped_rules`) instead of running,
  and the Overview's "rules running" and "rules still running" facts count only the rules that
  still run, from the new `running_rules` field, instead of every enabled rule. A rule whose
  removal is running is not counted by either. `RuleCounts` in
  `application/operations/status.py` is the one place both are counted.
- What a scheduled pass does moves from `infrastructure/scheduling.py` to `ScheduledPass` in
  `application/operations/scheduled_pass.py`, with no change in behavior: expiring Source Change
  values and provider call counts, finishing interrupted lapses, choosing each rule's daily full
  pass, taking turns between Users, retrying, and recording each run's outcome. The scheduler
  keeps only its timing, its progress, and how many rules run at once, and an import contract
  keeps it from importing the Synchronization context. `SystemClock` moves to
  `infrastructure/clock.py`.
- The Web UI names the provider wherever one is known: account rows read "Google account" or
  "Microsoft account" beside the address, each avatar and Connect button carries its provider's
  mark, a lapsed account's fix reads "Reauthorize with Microsoft", the collapsed account summary
  groups addresses by provider, and the note about a provider returning to another address names
  every provider that does, and causes, waiting messages, and next steps name Google
  or Microsoft, their consoles, and their status pages. Where no one provider is meant, copy says
  "calendar account" or "the calendar provider"; the People verdict reads "Waiting for the
  provider".
- Settings and the Overview offer one Connect button per configured calendar provider, and each
  account's **Reauthorize account** goes to its own provider. A connection returns to Settings as
  `?oauth=<outcome>&provider=<kind>` instead of `?google=<outcome>`.
- The OpenAPI schemas `GoogleConfigurationResponse` and `GoogleAccountAccessResponse` are now
  `ProviderConfigurationResponse` and `AccountAccessResponse`; their JSON is unchanged.
- The Sync Run's code is split by responsibility, with no change in behavior: `ExecuteSyncRule`
  composes `ChangeFeedCursors`, `SynchronizeEvents`, and `ExceptionReplays`, and
  `SyncDecisionService.decide_occurrence` takes one `OccurrenceSituation` and no longer needs a
  complexity exception.
- Synchronization safety is enforced by tests, with no change in behavior: every use case that
  runs, previews, reconciles, or changes a rule must receive the installation's one rule lock
  registry instead of creating its own, and a test fails on a complexity suppression in
  production code or an application dataclass whose constructor exceeds Ruff's argument bound.
- A run's failure kind, and each Connected Account's state and Provider Kind in Installation
  Status, are typed as their domain enums instead of strings. `ProviderFailureKind` moves to
  `domain/providers.py`, and `application/sync/events.py` is now `event_sync.py`, so it is not
  mistaken for domain events. Stored values, API payloads, and the OpenAPI document are unchanged.
- Both units of work refuse a write with the same errors: `DuplicateDirectionalRelationship`,
  `IdentityCollision`, or `MissingReference`, each a `RecordRefused`. SQLite raises them in place
  of `sqlite3.IntegrityError`, also when a rule's accounts are checked at commit. The in-memory
  store that application tests use now behaves as SQLite does: it refuses a rule whose accounts
  are not its User's, resolves a removed rule's Incidents and deletes a purged rule's or a deleted
  account's, and its Installation Status reads open Incidents, blocks, and Incident Causes. The
  persistence contract checks each of these for both stores.
- Synchronization rules live in the domain, with no change in behavior: `SyncRule` says whether
  it synchronizes, whether a preview may validate it, whether it is stopped only by Lapsed
  Authorization, what disconnecting one of its accounts makes of it, and which source events it
  projects, so Rule Preview and Full Reconciliation share one eligibility rule. A Source
  Observation keeps the last complete guest list itself (`SourceObservation.completed_by`). A test
  fails when an API schema's `Literal` alias and the enum it mirrors list different values, or a
  new alias mirrors no enum.
- Activity's reads of a rule's earlier entries and block checks also match the User, so another
  User's entries with the same rule and event identifiers never name, repeat, or clear this
  User's events. Clearing Activity keeps the entries those reads need, matched the same way.
- Activity has a History tab and an Incidents tab, each at its own address (`/activity` and
  `/activity/incidents`), while any Incident is kept; the Incidents tab counts the open ones.
  Incidents list in one table, open first, each with when it opened, the rule or account, and when
  it closed and how long it lasted, or "Still open". Selecting one opens it beside the table at
  `/activity/incidents/<id>` with what it means or how it closed, its likely Cause, and its next
  step. Open incidents no longer lead the History page.
- Each Incident's next step is decided once, in the domain, from its Cause, category, and rule
  as it is now, and the Web UI and the incident email offer the same one
  ([ADR 0033](docs/adr/0033-decide-an-incidents-next-step-in-the-domain.md)). Before, a calendar
  the account may no longer use sent the email to the rule while Activity offered to reauthorize.
  The email for blocked events now opens that rule's blocked events. `GET /api/v1/incidents`
  returns each Incident's `step`.
- An Incident's `category` is one of a closed set in the domain (`IncidentCategory`): a provider
  failure's kind, `conflict` for events still blocked, or `unknown` for a category another release
  stored. `GET /api/v1/incidents` and `GET /api/v1/status` return it as an enum, and a new
  provider failure kind fails a test until the domain's categories, and so its next steps,
  know it.
- Activity lists every incident: `GET /api/v1/incidents` pages with `before`, the last incident's
  `cursor`, the table ends in
  "Load older incidents" while there are more, and `GET /api/v1/incidents/{incident_id}` opens an
  incident the list does not hold.
- An administrator's Cause in Activity's incident details names the Cause and How to fix only to
  an administrator; anyone else reads that their calendar is not available right now, with Check
  access, as on the Overview (ADR 0031).
- Form fields have borders with enough contrast again: a global reset no longer overrides them.
  Midnight's primary color is calmer, so a red status draws the eye first.
- Settings groups share the border, fill, radius, and padding of the app's other cards. "Your
  account" opens with **Sign-in and email**. Cancelling the email or password form forgets what was
  typed.
- After upgrading, the administrator signs in with their password once and then adds the email they
  sign in with from now on. Setup asks for an email and a password.
- Incident Notifications go to the person who owns the rule or account, by email when SMTP is
  configured, unless they turn it off. `CALENDAR_SYNC_SMTP_RECIPIENT` and
  `CALENDAR_SYNC_INCIDENT_WEBHOOK_URL` now receive only incidents about the installation itself, so
  a webhook that received rule incidents before no longer does.
- `GET /api/v1/status` and MCP answer for the person who issued the token, in the same shape.
  Existing tokens belong to the first User and keep both scopes, so their answers do not change.
  The Integration Token list returns `scopes` instead of `scope`.
- Google's OAuth callback connects an account only in a browser signed in as the person who
  started connecting it. A consent link opened by anyone else, or without signing in, connects
  nothing and returns to Connections with "authorization failed".
- Storage settings are for administrators only. Sync now, Reconcile now, and Preview answer `404`
  instead of `409` for a rule that does not exist.

- The database uses SQLite's write-ahead log, so the Web UI no longer waits for a scheduler write,
  nor a write for a Web UI read. The first start switches an existing database over; back up the
  `calendar-sync.db-wal` and `calendar-sync.db-shm` files beside the database with it.
- A scheduler pass runs up to four rules at once instead of one after another, so a rule waiting on
  a slow or rate-limited calendar no longer delays every rule behind it.
- When Google stops accepting a connected account, Calendar Ghost now says which account and how
  to fix it ([ADR 0027](docs/adr/0027-lapsed-authorization-and-automatic-recovery.md)). Settings
  lists that account first as **Needs reauthorization** with **Reauthorize account**, which asks
  Google to offer that account. A rule it stopped names the account, and its next step opens
  Settings at that account instead of offering a preview that could only fail. The Overview,
  Activity, the status API, and MCP count it as an account to reauthorize. Once Google accepts the
  account again, by reauthorizing or by a **Check access** that passes, the rules its lapse alone
  stopped restart on their own and Settings says how many. One Incident and one notification
  cover the account instead of one per rule. Check access names why Google refused, and a preview
  that meets an account Google refuses answers with a clear error instead of a server error.
- The Web UI's API types are generated from the backend's OpenAPI schema
  ([ADR 0025](docs/adr/0025-generate-web-api-types-from-openapi.md)), so a changed response fails
  the frontend type check instead of breaking a page. The sync, reconcile, and preview routes now
  declare their response bodies, which are unchanged, and each Web UI call is typed by the route it
  names. An unknown `privacy_policy` in a rule request is still rejected with 422, now with
  FastAPI's standard validation detail.
- The frontend quality gate adds stricter TypeScript (`noUncheckedIndexedAccess`,
  `exactOptionalPropertyTypes`), type-aware ESLint with complexity and size bounds and folder
  layering, React Doctor, and `npm audit --audit-level=high`. CI runs all of them.
- The Overview shows the server's health verdict, so it always agrees with the status API.
- Settings → No Google accounts connected explains the next step in quiet text instead of red: an
  installation without an account yet is not failing.
- Rule Details, Settings, Activity, Rules, and Overview are split into section files, and the
  activity copy into focused modules, so every frontend file and function is within the
  complexity and size bounds. The screens render the same markup.
- The backend's use cases are grouped into one package per bounded context: synchronization,
  identity, and operations ([ADR 0032](docs/adr/0032-bounded-contexts-as-application-packages.md)).
  `lint-imports` fails when a context imports one above it. Behavior is unchanged, and API
  payloads return every time Calendar Ghost stores exactly as before. Log lines from these modules carry their new logger names, such as
  `calendar_sync.application.sync.sync_run`.
- Large numbers are grouped.
- An Activity entry whose action this version does not know reads "Something happened" instead of
  its raw action code, and its recorded detail moves to Technical details instead of standing in
  for the explanation.
- Error alerts no longer show the browser's own wording: a request that cannot reach the service
  says "The browser could not reach Calendar Ghost.", and other unexpected failures say "The request
  could not be completed."
- Error alerts explain a known server error, including a rejected field, in a full sentence of the
  Web UI's language, such as "That password is incorrect." for a wrong password. The server's
  English detail shows only for an error this version has no message for. Incidents and the Overview's problem sentences
  render each Incident's message in the Web UI's language, keeping the stored summary for
  Incidents recorded earlier.
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

- An occurrence projected on its own, because its calendar did not show its series, is now
  removed once the calendar shows a series the rule leaves out, such as one you declined. Before,
  the single projection stayed in the destination for good, though the rule projects no
  occurrence of that series (#110).
- Rules no longer copy the contacts' birthdays Google keeps in a primary calendar. Google Calendar
  lists them as a separate "Birthdays" calendar, but they are events of the primary calendar, so a
  rule from it copied every one. A new rule setting, "Sync birthdays", is off by default; upgrading
  deletes the birthdays rules already copied on their next run
  ([ADR 0035](docs/adr/0035-leave-out-birthdays-unless-a-rule-syncs-them.md)) (#108).
- A provider failure, an interrupted Rule Removal or Rule Replacement, or a refusal from Microsoft
  raised through a context manager keeps its kind. Before, Python 3.12 replaced it with a
  `TypeError`, because these errors were frozen dataclasses, so a failure could read as a local
  infrastructure failure. A test now fails if any error is a frozen dataclass (#103).
- An occurrence whose series its calendar does not show, such as one meeting of a recurring event
  someone invited you to, now projects as a single event. Before, it was skipped as
  `series_not_synchronized`, so its time never reached the destination. If the calendar later shows
  the whole series, the single event is removed once the series shows the occurrence, recorded as
  `occurrence_joined_series` (migration 29, ADR 0011) (#102).
- Deleting the first occurrence of an Outlook series with no end no longer stops its rule. Graph
  lists such a series at most five years at a time, so the search for a missing first occurrence
  now reads it in 1825-day windows (#98).
- A timed event that ends as it starts, as some reminders do, no longer fails Preview and stops its
  rule. Both providers accept such events (#97).
- Sync now and Reconcile now lapse an account the provider refused, as a scheduled run does: its
  rules stop, an Incident opens, and the message asks to reauthorize (#96).
- A Google series is no longer rewritten on every run of an Outlook to Google rule. Google stores
  the parts of a repeat rule in its own order, so recurrence rules are now compared by their parts
  (#95).
- An occurrence deleted in Outlook comes back: the run rebuilds the Outlook series from the source,
  with its moved and cancelled occurrences, and records `series_rebuilt`. Each blocked event in
  Activity now says why it is blocked (#94).
- Sync now and Reconcile now answer a provider failure as `424 provider_failed` instead of a server
  error. A calendar listing the provider refuses lapses the account, and a failed run's log line
  names where it failed (`at=`) (#93).
- An Outlook series with a moved occurrence can change again, and Rule Removal no longer stops at
  it. The guest check before a series write reads the series' exceptions whole, since Graph leaves
  out their attendees from any narrower read (#92).
- Outlook now holds a yearly series on a day its month always has, such as a birthday on
  November 30. It refused every yearly series from the 29th on, as if every month could be
  shorter, and Activity showed such a series as blocked. February 29 and the 31st of a 30-day
  month stay blocked, because Outlook would move them to another day.
- Rules that a Lapsed Authorization stopped resume even when the process stopped or failed while
  restoring them. Before, Reauthorization could clear the lapse and leave its rules stopped, with
  the account's Incident open, until the account was reauthorized or checked again. Each
  scheduled pass now resumes them and resolves that Incident (ADR 0027).
- A rule resuming after Reauthorization stays stopped when another rule's run records a new lapse
  of the same account at that moment. Before, it could resume against the lapsed account.
- An account's Lapsed Authorization Incident resolves once the account is authorized again, even
  when no rule still waits for it, as after the User paused or removed the rule it stopped. Before,
  a restoration interrupted at that point left the Incident open. Each scheduled pass now resolves
  it.
- A lapse that the process stopped partway is finished at the next scheduled pass: the account's
  enabled rules stop, and its Incident opens, with one notification, if it had not opened. Before,
  those rules kept running until their own next authorization failure, and the Incident could
  stay unopened. Without the provider's refusal at hand, that Incident says the account's
  authorization expired and has no Cause (ADR 0027).
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

## [0.1.0] - 2026-08-30

### Added

- Provider-independent synchronization and reconciliation domain foundation.
- SQLite persistence boundary and initial schema migration.
- Single-administrator setup and authenticated API sessions.
- React, TypeScript, Vite, and shadcn/ui operational interface.
- Open-source project documentation, CI, and architecture decisions.
- Source-authoritative sync for timed and all-day events, cancellations, destination repair, and incident notifications.
