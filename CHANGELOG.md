# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and semantic versioning.

## [Unreleased]

### Added

- Connected Account management with permission checks, safe disconnection, reauthorization, and permanent local deletion.
- Stable URLs for Overview, Rules, Activity, and Settings, with account identity markers throughout rule management.
- A warning before connecting a Google account when the browser address differs from the configured OAuth redirect URI, with LAN and Raspberry Pi redirect guidance.
- Google profile names and photos for Connected Accounts through optional basic profile access. Reconnect existing accounts to show their photos.
- Rule Details at `/rules/{id}` showing calendars, projection policy, all-day eligibility, initial window, state, managed projection count, and the last synchronization and reconciliation outcomes.
- Transformation Policy and all-day eligibility editing as a Material Rule Change that pauses the rule, requires a new preview, and rewrites every existing projection on the next run.
- Rule Removal with an explicit choice to delete mapped projections or keep them as Detached Events, and Rule Replacement for changing a rule's calendars.
- Activity groups decisions by synchronization run, names the rule's calendars, explains every skipped, blocked, or changed event in plain language, and can be filtered by rule and outcome with older entries loaded on demand.
- Activity entries can look up their source event and Managed Projection live from Google, showing the title, time, recurrence, and a Google Calendar link without storing any event content.
- SQLite migration 3 adds stable reason codes and run identifiers to audit entries and backfills reason codes for existing entries.
- The Overview derives its headline, health strip, and single next action from one health model, so it never reports healthy while an incident, a stopped rule, or a lost authorization needs attention. It lists every rule with its state and last successful sync, and first-run guidance stays until a rule is running.
- Rule rows and Rule Details show when each rule last synchronized, move Sync Now, Reconcile Now, and Pause into a "More actions" menu that explains how each differs, report each command's result on its own rule, and restate the privacy consequence of the latest preview before a rule starts syncing.
- `GET /api/v1/dashboard` adds `disconnected_accounts`, `enabled_rules`, `stopped_rules`, and `last_synced_at`, and reports `attention` for stopped rules as well as open incidents. `GET /api/v1/rules` adds each rule's `last_sync` outcome.
- The Overview shows recent changes: the last runs that added, updated, removed, or repaired events, per rule and in plain language, with blocked changes linked to that rule's Activity. "Show events" looks up the affected events' titles and times live from Google on request and never stores them. When something needs attention, the status names the affected rule and links straight to it.
- `GET /api/v1/recent-changes` summarizes recent runs that changed or blocked events, using counts and entry identifiers only.
- SQLite migration 6 keeps the counts of each rule's latest preview, so "Start syncing" always restates how many events will appear. Rules and Rule Details expose them as `latest_preview`.
- Activity filters live in the address (`/activity?rule=…`), and Rule Details links to that rule's activity.
- Recurring series and single-occurrence changes synchronize under the same ownership, privacy, drift-repair, reprojection, and removal guarantees as single events, and Rule Preview reports recurring series and changed occurrences with their planned actions.

### Changed

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

- Recurring events excluded by the pre-alpha policy are recorded as skipped instead of as conflicts, so they no longer appear as blocked; existing entries are shown as skipped as well.
- Google OAuth callbacks now support local HTTP development, preserve PKCE verification across redirects, and recover cleanly when Calendar permissions are declined.
- Activity request failures, empty activity, and low-contrast actions now have distinct, accessible interface states.
- Activity now loads when browser content blockers such as uBlock Origin are enabled.
- The Activity page now explains why it could not load: an expired session, an updated installation that needs a reload, a service error, or a request that never reached the service, such as one stopped by a content blocker.

## [0.1.0] - 2026-08-30

### Added

- Provider-independent synchronization and reconciliation domain foundation.
- SQLite persistence boundary and initial schema migration.
- Single-administrator setup and authenticated API sessions.
- React, TypeScript, Vite, and shadcn/ui operational interface.
- Open-source project documentation, CI, and architecture decisions.
- Source-authoritative sync for timed and all-day events, cancellations, destination repair, and incident notifications.
