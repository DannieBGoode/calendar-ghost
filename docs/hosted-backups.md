# Hosted backups and stopped-service recovery

This optional operator procedure keeps the standard Docker Compose quick start unchanged.
Run one application process per database and a separate Litestream process. Never start another
application writer to inspect a backup. Local compatibility evidence is recorded in
[the synthetic drill record](hosted-backup-drill.md). Hosted launch still requires a measured
remote drill in the actual hosting environment.

**v0.5.17 is qualified only for the stopped maintenance procedure. Never use Clear activity or
Reclaim space while Litestream runs: a successful live VACUUM can produce a malformed restore
even when sync and restore processes exit 0.** See [compaction maintenance](#compaction-maintenance).

## Recovery objectives and isolation

Targets are a remote recovery point within one minute while healthy, an alert after five minutes
of unsuccessful replication, 30 days of independent daily exports, recovery within 30 minutes,
and an isolated restore drill every month. These are objectives to measure, not durability or
availability guarantees. Record the last remotely recoverable UTC marker, replication lag,
restore and preparation time, database size, image digest, schema version, operator and drill date.

Use a private S3 prefix in a different host/account failure boundary, HTTPS with certificate
verification, server-side encryption and a least-privilege backup identity restricted to the
replica prefix. Litestream needs list, read, write and delete for its own chain maintenance.
Give a separate restore identity read access. Test the actual IAM and KMS permissions rather
than assuming that a successful upload implies a usable restore. Never expose the control socket
or metrics publicly: use a protected local Unix socket and loopback-only metrics.

Keep the matching Installation Master Key, provider/application secrets and image/schema versions
in an encrypted recovery store separate from the database host and backup account. Application
host recovery access may read this store. The backup identity must never read the Master Key.
Litestream 0.5 has no built-in Age encryption; use store encryption and separately encrypted
secrets. Never print keys or credential plaintext in drill records.

## Pinned configuration

Use the official [v0.5.17 release](https://github.com/benbjohnson/litestream/releases/tag/v0.5.17).
Download the asset for the deployment platform, verify its published SHA-256 checksum before
execution, and require `litestream version` to print `0.5.17`. Do not silently upgrade it.
The drill accepts an explicit local binary; it downloads nothing or installs nothing globally.

The following is the v0.5.17 nested configuration structure. Substitute protected absolute paths
and your private TLS S3 URL. Supply credentials outside source control through the process's
protected environment or workload identity. Protect the configuration and socket directory.

```yaml
socket:
  enabled: true
  path: /run/calendar-ghost-backup/control.sock
snapshot:
  interval: 24h
  retention: 720h
retention:
  enabled: true
l0-retention: 5m
l0-retention-check-interval: 15s
dbs:
  - path: /data/calendar-sync.db
    replica:
      url: s3://REPLACE_PRIVATE_BUCKET/REPLACE_PRIVATE_PREFIX
      sync-interval: 1s
```

Leave compaction levels at release defaults: L1 every 30 seconds, L2 every five minutes, and
L3 every hour. The tagged [configuration parser](https://github.com/benbjohnson/litestream/blob/v0.5.17/cmd/litestream/main.go)
uses permissive YAML decoding, so a process starting does not prove that a misspelled key took
effect. Inspect effective monitor intervals and observe actual object creation and removal.
The [tagged compaction levels](https://github.com/benbjohnson/litestream/blob/v0.5.17/compaction_level.go)
and [store retention implementation](https://github.com/benbjohnson/litestream/blob/v0.5.17/store.go)
govern this procedure when rolling documentation differs.

L0 holds fine-grained LTX endpoints. Higher levels merge consecutive ranges. Once L0 cleanup
removes an endpoint, a timestamp or TXID inside a merged range need not remain independently
recoverable. Snapshots form the floor for restoring the surviving chain; retention keeps the
last snapshot even when it is older than the configured window. `720h` neither preserves every
transaction endpoint nor guarantees deletion on an exact date. Never apply bucket-age lifecycle
expiration to objects in the live replica: it can remove dependencies of retained restore points.
Let Litestream manage the live chain.

Start the side process under your supervisor:

```sh
litestream replicate -config /protected/litestream.yml
```

Check process health, successful remote sync and recoverable markers, not just local WAL size.
Alert after five minutes without successful replication, on any failed daily export, and on a
failed or overdue monthly drill. Route alarms outside the failed application host. Validate the
replication alarm by stopping the replica process, requiring the sync probe to fail, and checking
the real alert reaches its operator after the configured five-minute threshold. A local failed
probe validates only the alarm input, not hosted alert delivery.

## Daily independent exports

Once daily, restore into a new, absent path on the application host:

```sh
litestream restore -o /protected/exports/NEW_DATABASE REPLICA_URL
calendar-ghost-restore inspect --database /protected/exports/NEW_DATABASE
```

The application host uses its existing protected matching Master Key access for inspection.
Also verify expected schema and known operational content; a restore exit 0 alone is insufficient.
Encrypt the complete finished database as one independently recoverable export, upload it outside
the live prefix, and record capture UTC, image digest and schema version. Retain each completed
export for 720h; expire whole completed export objects, never pieces of the live chain. Failed
restore, inspection, encryption or upload must not replace the last good export. Verify a detached
export after its original live-chain endpoint expires. Daily exports supply historical daily
points, not every transaction between them.

User Deletion does not erase retained backups. Removed Users and old authority remain in live
replicas, independent exports and protected local preparation backups until every applicable
retention expires. Track and expire the local preparation backups explicitly too.

## Restore order

1. Close ingress, including sign-in, password recovery, webhooks and provider callbacks. Stop the
   application and Litestream through their supervisors; check both processes are absent and
   disable automatic restarts. No sleeping application writer may remain. A SQLite lock alone
   cannot prove that the service is stopped. Preserve the newer failed-host database and sidecars
   untouched for comparison if recoverable.
2. Restore to a **new** database path using the matching image and secrets. Do not overwrite the
   failed database or use an API startup as an inspection step: API lifespan starts scheduler,
   Instant Sync and mail work. Require the restore process to exit zero.
3. With `CALENDAR_SYNC_MASTER_KEY` available through protected application-host access, run
   `calendar-ghost-restore inspect --database NEW_PATH`. It checks the exact shipped schema,
   SQLite integrity, foreign keys and credential authentication, emitting fixed status/counts.
   Keyless self-hosted installations cannot use these commands. A missing or mismatched key fails
   closed. This tool supports only its shipped schema. For an older-schema backup, keep ingress
   and all writers stopped, preserve the backup, and obtain separately reviewed schema-compatible
   offline tooling. This change provides no migration command, ledger edits or API-start workaround.
4. Create an operator-owned mode-0700 directory with no symlink path components for a new local
   before-change backup. Select an existing Installation Administrator by its identifier:

   ```sh
   calendar-ghost-restore prepare --database NEW_PATH --backup /protected/recovery/NEW_BEFORE.db \
     --administrator-id EXISTING_ADMINISTRATOR_ID --acknowledge-services-stopped
   ```

   Use a controlling terminal. Enter and confirm a fresh password, 12 to 256 characters, at the
   hidden prompts. Never put it in command arguments, an environment variable, a pipe or a log.
   Preparation creates a protected verified backup before changing authority, closes Open,
   clears email readiness, revokes sessions, invitations, Integration Tokens, OAuth states and
   all identity proofs/flows, removes Provider Identities, disables provider sign-in, abandons
   Watch Registrations and handles queued Instant Sync requests. It disables every User except
   the selected administrator and disconnects every Connected Account by sealing empty credentials.
   Rules, mappings and all Plan fields stay unchanged. Exit codes are 0 success, 1 operational
   refusal/failure, 2 usage or confirmation failure. Any nonzero exit keeps ingress closed.
5. Configure **fresh local Litestream metadata and a new private replica prefix** for the restored
   database. Keep the original prefix and its metadata untouched until their retention expires.
   Never reconnect an older recovered database to the failed host's newer replica. A disposable
   ahead-replica experiment is not an authorized production recovery procedure.
6. Configure the single application writer and Litestream to exactly `NEW_PATH`, using the
   override below for Compose. Before startup, inspect the exact configured path again. Require
   no `NEW_PATH-wal`, `NEW_PATH-shm` or `NEW_PATH-journal` from another database.
   Do not delete valid preparation sidecars; preserve the prepared database's own SQLite files
   together. Never copy over the failed database or its sidecars;
   retain that separate file set untouched. Start exactly one application writer with operator-only
   access. Check administrator sign-in
   and Installation Health. Compare the preserved newer database and authoritative operational
   records; replay known deletions, disables, disconnections and credential changes. Confirm
   mailbox ownership before exposing password recovery. Reset and re-enable only confirmed Users.
   Provider sign-in stays disabled until current email ownership is confirmed and an administrator
   explicitly enables it. Owners explicitly reauthorize Connected Accounts and reconcile rules;
   preserve Plan Holds and do not release them by hand.
7. Verify replication to the new prefix and a fresh restore. Reopen ingress only after review.
   Open requires a new normal identity email test and an explicit administrator choice.

For Compose, keep ingress closed and both processes stopped. Set `CALENDAR_GHOST_RECOVERY_IMAGE`
to the matching image digest already available locally, `CALENDAR_GHOST_RECOVERY_DIR` to the
absolute host directory containing the new restored `prepared.db`, and
`CALENDAR_GHOST_RECOVERY_BACKUP_DIR` to a separate absolute host mode-0700 backup directory.
Both directories must be writable by the matching image's runtime UID; use trusted nonsymlink
paths. Save `/protected/compose.restore.json` (JSON is valid Compose YAML):

```json
{
  "services": {
    "app": {
      "image": "${CALENDAR_GHOST_RECOVERY_IMAGE:?set matching image digest}",
      "environment": {"CALENDAR_SYNC_DATABASE_PATH": "/recovery/prepared.db"},
      "volumes": [
        {"type": "bind", "source": "${CALENDAR_GHOST_RECOVERY_DIR:?set absolute restore directory}", "target": "/recovery"},
        {"type": "bind", "source": "${CALENDAR_GHOST_RECOVERY_BACKUP_DIR:?set absolute backup directory}", "target": "/protected/recovery"}
      ]
    }
  }
}
```

## Persistent Compose configuration

Before startup, make the override this installation's permanent configuration. Edit the existing
protected project `.env`, preserving its other settings and secrets; never commit it. Persist:

```dotenv
COMPOSE_FILE=docker-compose.yml:/protected/compose.restore.json
CALENDAR_GHOST_RECOVERY_IMAGE=MATCHING_IMAGE_DIGEST
CALENDAR_GHOST_RECOVERY_DIR=/ABSOLUTE/RESTORED_DIRECTORY
CALENDAR_GHOST_RECOVERY_BACKUP_DIR=/ABSOLUTE/PROTECTED_BACKUP_DIRECTORY
```

Replace the three recovery values as specified above. Run all commands from the same Compose
project working directory so its `.env` loads; unset conflicting shell overrides. Plain
`docker compose` now loads both files. Never drop the override while the failed database set remains
at `/data`; keep it for all later recreations and maintenance. The explicit flags below select
those same files. To upgrade a recovered installation, obtain the desired new image and update
`CALENDAR_GHOST_RECOVERY_IMAGE` to its digest in this `.env`, retaining paths and mounts, then run
`docker compose up -d --no-build app`. Do not use the ordinary `--build` upgrade or drop the override.

Here `NEW_PATH` is `/recovery/prepared.db` inside the container; configure Litestream's database
path to `/recovery/prepared.db`; its separate process must also see that same directory mounted
at `/recovery`. Keep the matching protected secrets environment. Use the override
for every recovery command and startup, so the CLI and single writer use the same image and mounts:

```sh
docker compose -f docker-compose.yml -f /protected/compose.restore.json run --rm -it --no-deps app calendar-ghost-restore inspect --database /recovery/prepared.db
docker compose -f docker-compose.yml -f /protected/compose.restore.json run --rm -it --no-deps app calendar-ghost-restore prepare --database /recovery/prepared.db \
  --backup /protected/recovery/NEW_BEFORE.db --administrator-id EXISTING_ADMINISTRATOR_ID \
  --acknowledge-services-stopped
docker compose -f docker-compose.yml -f /protected/compose.restore.json run --rm -it --no-deps app calendar-ghost-restore inspect --database /recovery/prepared.db
docker compose -f docker-compose.yml -f /protected/compose.restore.json up -d --no-build app
```

Require every command to succeed. The final inspection checks the configured prepared path before
operator-only startup, never the failed database at Compose's original `/data/calendar-sync.db`.
`run` invokes only the explicit offline command. Keep both processes stopped throughout inspection
and preparation.

## Compaction maintenance

Calendar Ghost's existing `SqliteStorage.compact()` performs `VACUUM` followed by
`wal_checkpoint(TRUNCATE)`. An active reader can cause StorageBusy. Never weaken that protection
or retry while pretending a failed checkpoint succeeded. The WAL guide describes contention,
not a guarantee that every live compaction fails. **Do not use Clear activity or Reclaim space while Litestream runs.** Clear activity always attempts
compaction. The pinned release produced a malformed restore after a successful live
VACUUM, despite matching synced TXIDs and restore exit 0. An initial fresh restore was valid;
the source remained valid. No sleep or later snapshot is a repair guarantee. Compatibility is
limited to the stopped maintenance procedure below; the live experiment remains a negative finding.

After accidental live compaction, stop both processes and close ingress. Inspect the source and a
fresh restore, including known content, before trusting either. If the replica restore is invalid,
preserve that prefix and local metadata. From an independently validated source, establish fresh
local metadata and a new prefix, then verify another fresh restore before reopening. If the source
is invalid too, use the last independently verified export and the conservative restore order.
Never assume that subsequent snapshots heal the old chain. See the measured drill record.

For maintenance: close traffic, stop and check the application, run
`litestream sync -socket /run/calendar-ghost-backup/control.sock -wait DB_PATH`, and require the
returned replica TXID to match the source TXID. Send Litestream SIGTERM, wait at most 30 seconds,
and require exit 0. A signal exit or forced kill fails the procedure. Tagged
[signal handling](https://github.com/benbjohnson/litestream/blob/v0.5.17/cmd/litestream/main.go)
handles SIGTERM through shutdown; verify observed behavior in the deployed supervisor too.
With both stopped, inspect exactly the configured database path before invoking the existing
storage adapter without the API. For a recovered installation, add
`-f docker-compose.yml -f /protected/compose.restore.json` to both commands below. The standard Compose path is `/data/calendar-sync.db`; if yours
differs, use that same path for both commands. Stop on any inspection or compaction failure;
do not restart replication:

```sh
docker compose run --rm -it --no-deps app calendar-ghost-restore inspect --database /data/calendar-sync.db
docker compose run --rm --no-deps app python -c 'import os; from pathlib import Path; from calendar_sync.infrastructure.persistence.storage import SqliteStorage; SqliteStorage(Path(os.environ["CALENDAR_SYNC_DATABASE_PATH"])).compact()'
```

This uses the existing data mount and configured database path. Require exit 0.
Restart replication, write a synthetic validation marker in an isolated drill, sync and stop,
then restore to another absent path and inspect it. Only reopen after the completed VACUUM and
restart sequence has a verified restore. Do not add another application writer for maintenance.

## Reproduce and qualify

From a development checkout with the installed console entry:

```sh
.venv/bin/python -m scripts.verify_hosted_backups \
  --litestream .context/litestream-v0.5.17/litestream --output-dir .context/NEW_EMPTY_DRILL
```

The drill uses only synthetic multi-User state and local file replication, short snapshot/L0
retention with the same YAML nesting, unchanged default compaction levels, and fresh restore paths.
It records actual child exits, retained/expired endpoints, detached export recovery, authority
invalidation, unchanged Plans, live and stopped compaction, and a new replica prefix. Do not commit
fixture databases, keys or raw terminal output. Default pytest uses subprocess fakes and never
downloads or executes Litestream.

Before hosted launch and monthly thereafter, repeat in an isolated instance of the actual remote
store with the deployed binary/image, network, IAM, KMS and alert routing. Measure remote marker
lag against one minute and restore/preparation/operator recovery against 30 minutes. Test completed
exports at real retention ages, remote unavailability, and the five-minute alert threshold.
A local file run cannot prove remote durability, access separation, retention age, alert delivery,
or the remote recovery objectives. Keep launch blocked until those measurements pass.
