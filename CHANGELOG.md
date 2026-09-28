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
- Activity is a table grouped by day with Time, Event, What happened, and Rule columns. Event titles and times are read live from Google in small deduplicated batches for the rows on screen (`GET /api/v1/audit-entries/events`), and selecting an entry opens its details beside the table, led by the event and what happened, with a way to open the rule when a change was blocked. Checks that found an event already up to date are counted in one expandable row per run by default and listed individually under **All decisions**. A rule picker shows each rule's calendars with their account photos, lists removed rules separately, and follows the accessible select-only combobox pattern. The rule, filter, and open entry are kept in the page address.
- A development-only preview (`scripts/dev_preview.py`) serves the Web UI with synthetic data from its own marked database and a read-only fake Google; it refuses any other database and is excluded from the package and image.
- `GET /api/v1/audit-entries/{id}` returns one audit entry, `category` may be repeated to combine outcomes, `run_id` filters to one run, and `GET /api/v1/audit-entries/no-change-counts` counts each run's no-change checks.
- SQLite migration 3 adds stable reason codes and run identifiers to audit entries and backfills reason codes for existing entries.
- Recurring series and single-occurrence changes synchronize under the same ownership, privacy, drift-repair, reprojection, and removal guarantees as single events, and Rule Preview reports recurring series and changed occurrences with their planned actions.

### Changed

- Rule Removal leaves an event whose ownership cannot be verified in place and continues instead of stopping, retries temporary and rate-limited Google failures with backoff and Google's `Retry-After` hint (bounded to 60 seconds, also used by scheduled runs), opens an Incident when destination authorization is lost, and reports deleted, detached, and left-behind events on the rules list. The removal and replacement API responses include a `conflicts` count.
- Disconnected-account rules now stop clearly and preserve recovery data until reauthorization or permanent deletion.
- Appearance and color-theme preferences now share one Settings control.
- Rules name each Source and Destination Calendar and its account email instead of showing provider calendar identifiers.
- Migration 4 records pending reprojection and the latest run outcomes for each rule.
- Migration 5 records Occurrence Mappings and resets incremental positions once so enabled rules backfill recurring events on their next run. Pause a rule before upgrading to preview its recurring projections first.
- Audit entries moved from `/api/v1/activity` to `/api/v1/audit-entries`, and the old path is removed. After upgrading, reload or hard-refresh every Calendar Sync tab and bookmark: pages loaded from the previous release still call the old path, and browsers may have cached them.
- Unknown `/api/` paths now return a JSON 404 for every method, known paths called with the wrong method return 405 with an `Allow` header, and known paths with an extra or missing trailing slash redirect, instead of the web app page.
- The web app page is now revalidated on every load, so future upgrades take effect without a hard refresh.

### Fixed

- Recurring events excluded by the pre-alpha policy are recorded as skipped instead of as conflicts, so they no longer appear as blocked; existing entries are shown as skipped as well.
- Google OAuth callbacks now support local HTTP development, preserve PKCE verification across redirects, and recover cleanly when Calendar permissions are declined.
- Activity request failures, empty activity, and low-contrast actions now have distinct, accessible interface states.
- Activity now loads when browser content blockers such as uBlock Origin are enabled.
- The Activity page now explains why it could not load: an expired session, an updated installation that needs a reload, a service error, or a request that never reached the service, such as one stopped by a content blocker.
- Changing the Activity rule or outcome filter keeps the page, its filters, and keyboard focus on screen while the new entries load, instead of replacing the whole page with a loading placeholder.
- Occurrences of a recurring event that already matched their projection are listed as no change instead of as skipped.

## [0.1.0] - 2026-08-30

### Added

- Provider-independent synchronization and reconciliation domain foundation.
- SQLite persistence boundary and initial schema migration.
- Single-administrator setup and authenticated API sessions.
- React, TypeScript, Vite, and shadcn/ui operational interface.
- Open-source project documentation, CI, and architecture decisions.
- Source-authoritative sync for timed and all-day events, cancellations, destination repair, and incident notifications.
