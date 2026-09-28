# Deployment

## Docker Compose

Copy `.env.example` to `.env`, configure Google OAuth values when the adapter is enabled, and run:

```sh
docker compose up -d --build
```

The named volume contains SQLite state. Back it up before upgrades. Releases run forward-only, idempotent migrations during startup so `docker compose pull && docker compose up -d` does not require wiping state. Applied versions are recorded in `schema_migrations`, and each upgrade commits atomically with its ledger row.

Migration 2 adds nullable `reason` and `run_id` columns to `audit_entries` and backfills reason codes for entries written by earlier releases. Rolling back to an earlier image is safe: older releases ignore the added columns. Entries written by the older release have no reason code or run identifier and appear in Activity with their original wording.

Run one application process per SQLite database. The shipped container uses one Uvicorn process and
serializes concurrent scheduler and manual executions of the same rule in memory. Multi-process
workers are not supported with the SQLite deployment.

For access beyond localhost or a trusted LAN, place the service behind HTTPS and set `CALENDAR_SYNC_SECURE_COOKIES=true`. Do not expose the service directly to the public internet.

## Raspberry Pi

The image targets `linux/arm64` as well as `linux/amd64`. Use a 64-bit Raspberry Pi OS, durable storage for the Docker volume, and a time-synchronized host. Five-minute polling avoids a public Google webhook.

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
