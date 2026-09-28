# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and semantic versioning.

## [Unreleased]

### Added

- Connected Account management with permission checks, safe disconnection, reauthorization, and permanent local deletion.
- Stable URLs for Overview, Rules, Activity, and Settings, with account identity markers throughout rule management.
- Activity groups decisions by synchronization run, names the rule's calendars, explains every skipped, blocked, or changed event in plain language, and can be filtered by rule and outcome with older entries loaded on demand.
- Activity entries can look up their source event and copy live from Google, showing the title, time, recurrence, and a Google Calendar link without storing any event content.
- SQLite migration 2 adds stable reason codes and run identifiers to audit entries and backfills reason codes for existing entries.

### Changed

- Disconnected-account rules now stop clearly and preserve recovery data until reauthorization or permanent deletion.
- Appearance and color-theme preferences now share one Settings control.

### Fixed

- Recurring events excluded by the pre-alpha policy are recorded as skipped instead of as conflicts, so they no longer appear as blocked; existing entries are shown as skipped as well.
- Google OAuth callbacks now support local HTTP development, preserve PKCE verification across redirects, and recover cleanly when Calendar permissions are declined.
- Activity request failures, empty activity, and low-contrast actions now have distinct, accessible interface states.

## [0.1.0] - 2026-08-30

### Added

- Provider-independent synchronization and reconciliation domain foundation.
- SQLite persistence boundary and initial schema migration.
- Single-administrator setup and authenticated API sessions.
- React, TypeScript, Vite, and shadcn/ui operational interface.
- Open-source project documentation, CI, and architecture decisions.
- Source-authoritative sync for timed and all-day events, cancellations, destination repair, and incident notifications.
