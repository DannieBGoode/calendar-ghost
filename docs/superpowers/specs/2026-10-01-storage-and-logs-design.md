# Storage and logs in Settings

Date: 2026-10-01. Status: proposed.

## Why

A 40-minute Sync Run on a Raspberry Pi could be diagnosed only by querying SQLite over SSH. The
container logs said nothing, and Docker's default log driver keeps everything forever. The
administrator wants to read and share logs without SSH, see how much space the installation
uses, and remove what they no longer need.

## What the administrator gets

A **Storage** section in Settings, below Operations:

```
Storage
  Database              48.2 MB · 61,204 Activity entries since 12 Jun 2026
                        [Clear Activity older than ▾ 90 days]   (shows: 41,880 entries will be removed)
  Logs                  7.9 MB · 12 Sep – 1 Oct 2026            [Download]  [Purge logs]
```

- Every destructive action uses the inline `DestructiveConfirmation` pattern from Rule Details:
  - **Clear Activity** says how many entries will go and that this cannot be undone.
  - **Purge logs** says the logs cannot be recovered.
- Sizes refresh after each action.
- Everything here is admin-only, like the rest of `/api/v1`.

## Logs

- **Where they go.** The logging configured in the run-logging change also writes to
  `<data dir>/logs/calendar-sync.log`, next to the database. `CALENDAR_SYNC_LOG_DIR` overrides the
  location; an empty value turns file logging off.
- **Rotation.** `RotatingFileHandler` with 5 MB files, the current file plus 4 rotated ones, so
  at most 25 MB in total. When the current file reaches 5 MB:
  - it is renamed to `.1`, each older file moves up one number, and the oldest (`.4`) is deleted;
  - logging continues in a new, empty current file.

  Logs are never lost because a limit was reached, and logging never stops. The oldest 5 MB is
  always what goes first, so the files always hold the most recent roughly 25 MB of lines.
- **Docker's copy.** Docker's own copy is capped by `docker-compose.yml` (10 MB × 3), which is part
  of the run-logging change.
- **Content.** The same content rules as the console: rule and run IDs, operation names, counts,
  durations, and statuses. Never event content, calendar IDs, emails, URLs, or tokens. This holds
  because both handlers format the same records. A test asserts it for the file.
- **API.**
  - `GET /api/v1/storage` reports the log bytes, the file count, and the times of the first and
    last line.
  - `GET /api/v1/storage/logs` downloads every file, oldest first, as one `text/plain` attachment
    named `calendar-sync-logs-<date>.txt`.
  - `DELETE /api/v1/storage/logs` purges the logs. It truncates the current file under the
    handler's lock, deletes the rotated files, and writes one line saying the logs were purged.
- **File paths.** Paths are resolved against the log directory and never taken from the request,
  in line with the AGENTS.md rule on trusted roots.

## Database size

`GET /api/v1/storage` also reports:

- **Size.** `page_count × page_size`.
- **Reclaimable bytes.** `freelist_count × page_size`.
- **Activity.** The number of Activity entries (Audit Entries) and the date of the oldest.

## Clearing old Activity

`GET /api/v1/storage/activity?older_than_days=N` counts what would be removed. Clearing is
`POST /api/v1/storage/activity/clear {older_than_days: N}`.

- **Allowed values for N:** 30, 90, 180 and 365. Nothing shorter than 30 days, so a Sync Run
  window or a recent investigation is never cut short.

**Kept regardless of age**, because the run-health bookkeeping depends on them:

1. Each rule's latest entry for each source event. This keeps open blocks, the dashboard's
   blocked-entry links, and the names Activity shows for renames and cancellations.
2. Each rule's latest entry for each source event at or before that rule's last block check
   (`rule_block_checks.audit_floor`). Without it, a block that persists across a daily pass could
   miss its "blocked" incident.

**Removed:** every other entry older than the cutoff, including those of removed rules. These are
history, not state. Incidents keep no Audit Entry IDs, so they are unaffected.

**Deletion and space reclaim**

- The delete runs in batches of 5,000 with short transactions, following the AGENTS.md rule on
  write locks.
- Then `VACUUM` returns the space to the filesystem. VACUUM briefly blocks writes, so it waits for
  any running rule work to finish:
  - Clearing acquires every rule's run lock (`RuleLocks.for_rule`) and holds them only for the
    vacuum itself, which is seconds on a database of this size. No provider call happens while they
    are held.
  - If the locks cannot all be acquired within 30 s, the answer is 409 "A rule is synchronizing;
    try again when it finishes."
- Pagination still works, because Activity pages by ID with `before`, and AUTOINCREMENT IDs are
  never reused.

**Record and docs**

- **ADR 0019, "Administrator-chosen Activity retention."** It replaces "Audit history still has no
  retention limit" in ADR 0013 and ADR 0014.
- **Updated docs:** `CONTEXT.md`, `docs/sync-model.md` (retention), `docs/deployment.md` (backups
  keep cleared entries until they rotate) and `README.md`.

## Out of scope

- Automatic retention schedules. Clearing is manual. A "keep for N days" setting can come later
  on top of the same rules.
- Cleaning up `oauth_states`. It grows by one small row per connection attempt.
- Reading logs in the browser beyond downloading them.

## Testing

**Storage queries (SQLite-backed)**

- Size, reclaimable bytes, the entry count and the oldest entry are reported correctly.
- Clearing keeps both protected entries for each event, and removes the rest older than the
  cutoff, across several rules, including removed ones.
- After clearing, open blocks, persisting-block incidents and renamed-from names are unchanged.
  These tests seed SQLite, run the existing queries, and compare the results before and after.
- Batching works across several batches.
- `VACUUM` shrinks the file.

**Clearing use case**

- It waits for a running rule, then answers 409.
- It rejects disallowed values for N.

**Logs**

- Rotation sizes are respected.
- Downloading concatenates the files oldest first.
- Purging empties them and logs one "logs purged" line.
- `CALENDAR_SYNC_LOG_DIR` is honoured, and an empty value disables file logging.
- No event content reaches the file.

**API**

- Every route requires admin. `test_api_authorization.py` covers this automatically.
- The response schemas are checked.

**Web (vitest)**

- Formatting of sizes and date ranges.
- The confirmation flows and the counts they show.
- The section shows a disabled state while an action runs.
