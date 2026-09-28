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

### Changed

- Disconnected-account rules now stop clearly and preserve recovery data until reauthorization or permanent deletion.
- Appearance and color-theme preferences now share one Settings control.
- Rules name each Source and Destination Calendar and its account email instead of showing provider calendar identifiers.
- Migration 3 records pending reprojection and the latest run outcomes for each rule.

### Fixed

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
