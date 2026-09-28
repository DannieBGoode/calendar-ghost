# Deployment

## Docker Compose

Copy `.env.example` to `.env`, configure Google OAuth values when the adapter is enabled, and run:

```sh
docker compose up -d --build
```

The named volume contains SQLite state. Back it up before upgrades. Releases run forward-only, idempotent migrations during startup so `docker compose pull && docker compose up -d` does not require wiping state. Applied versions are recorded in `schema_migrations`, and each upgrade commits atomically with its ledger row.

Migration 2 adds a nullable `connected_accounts.avatar_url` column for Google profile photos. Earlier
releases ignore the column, so rolling back to the previous image works with the same database.

Migration 3 adds nullable `reason` and `run_id` columns to `audit_entries` and backfills reason codes for entries written by earlier releases. Rolling back to an earlier image is safe: older releases ignore the added columns. Entries written by the older release have no reason code or run identifier and appear in Activity with their original wording.

After upgrading, reload every open Calendar Sync tab. The web page is served with
`Cache-Control: no-cache`, so a normal reload picks up the new release. Releases before this header
may be cached by the browser: after the first upgrade from such a release, hard-refresh each tab
once. The upgrade that moves audit entries from `/api/v1/activity` to `/api/v1/audit-entries`
removes the old path, so a page loaded before it cannot show Activity until it is reloaded. Pages
from this release onward recognize a removed API path and ask you to reload.

Migration 4 adds `sync_rules.reprojection_required` (default `0`) and the `rule_run_outcomes`
table, which stores only timestamps, counts, and failure categories for the Rule Details view.
Rolling back to the previous image works with the same database: it ignores the new column and
table and leaves the flag untouched. The previous image does not rewrite existing projections after
a policy change; upgrading again resumes the pending reprojection. Rules whose removal was
interrupted stay inert on the previous image, which cannot finish the removal.

Migration 5 adds the `occurrence_mappings` table for recurring-event ownership and clears every
rule's incremental positions once, so the next run re-reads the Initial Sync Window and backfills
recurring series that earlier releases skipped. Enabled rules project them automatically; to review
recurring projections first, pause rules before upgrading, then preview and enable them. Rolling
back works with the same database: earlier releases ignore the table and skip recurring events, so
existing recurring projections stay unchanged until you upgrade again.

Run one application process per SQLite database. The shipped container uses one Uvicorn process and
serializes concurrent scheduler and manual executions of the same rule in memory. Multi-process
workers are not supported with the SQLite deployment.

For access beyond localhost or a trusted LAN, place the service behind HTTPS and set `CALENDAR_SYNC_SECURE_COOKIES=true`. Do not expose the service directly to the public internet.

## Raspberry Pi

The image targets `linux/arm64` as well as `linux/amd64`. Use a 64-bit Raspberry Pi OS, durable storage for the Docker volume, and a time-synchronized host. Five-minute polling avoids a public Google webhook.

## Google OAuth redirect URI on a LAN host

After consent, Google sends the browser to `CALENDAR_SYNC_GOOGLE_REDIRECT_URI`. The browser, not
the server, follows that redirect, so the address must reach this installation from the machine
you connect accounts from. Google accepts plain `http://` redirect URIs only for `localhost`; LAN IP
addresses such as `http://192.168.1.50:18000` and `.local` names are rejected. For a Raspberry Pi
or another LAN host, choose one:

- **SSH tunnel.** Keep the default `http://localhost:<port>/api/v1/oauth/google/callback`, run
  `ssh -N -L <port>:localhost:<port> <user>@<host>` on your computer, and open Calendar Sync at
  `http://localhost:<port>` while connecting or reauthorizing accounts. Synchronization does not
  need the tunnel.
- **HTTPS name.** Serve the installation over HTTPS with a publicly resolvable name, for example
  Tailscale Serve (`https://<host>.<tailnet>.ts.net`) or your own domain behind a reverse proxy.
  Register `https://<name>/api/v1/oauth/google/callback` on the Google OAuth client, set the same
  value in `CALENDAR_SYNC_GOOGLE_REDIRECT_URI`, and set `CALENDAR_SYNC_SECURE_COOKIES=true`.

The redirect URI must match the Google OAuth client exactly, including scheme and port. When the
address in the browser differs from the configured redirect URI, Settings warns before you connect
an account.

## Secrets

Keep Google client credentials and the installation master key outside the database and repository. Use Docker secrets or a root-readable environment file. Database backups cannot restore connected accounts without the separately backed-up master key.

Disconnecting a Google identity from Settings replaces its encrypted credential payload with an
empty encrypted value. Directional Sync Rules and their mappings remain in SQLite so the same
identity can be reauthorized and reconciled later.

## Incident notifications

Incidents always appear in the authenticated Activity screen. Optionally set
`CALENDAR_SYNC_INCIDENT_WEBHOOK_URL` to receive a JSON POST when an incident opens. SMTP delivery
requires `CALENDAR_SYNC_SMTP_HOST`, `CALENDAR_SYNC_SMTP_SENDER`, and
`CALENDAR_SYNC_SMTP_RECIPIENT`; credentials are optional. Delivery is deduplicated while an
incident remains open and failures never stop synchronization or local incident recording.
