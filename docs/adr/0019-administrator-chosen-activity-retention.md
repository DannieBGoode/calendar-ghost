# Let the administrator clear Activity older than a chosen age

Amends [ADR 0013](0013-record-decisions-worth-explaining.md) and
[ADR 0014](0014-record-event-titles-on-audit-entries.md), which left Audit history with no
retention limit.

## Context

ADR 0013 and ADR 0014 recorded every decision worth explaining and the source event's title and
time on each one, with no retention limit: Activity was meant to be read, not pruned. On a
Raspberry Pi installation that runs for months, `audit_entries` and its recorded titles grow
without bound, and the only way to see how large the database had become, or to find and remove
old rows, was to SSH in and run SQLite commands directly.

## Decision

- Settings → Storage shows the database size, reclaimable space, the number of Activity entries,
  and the oldest one. The administrator can clear Activity older than 30, 90, 180, or 365 days; an
  inline confirmation shows how many entries that removes before it runs. Nothing shorter than 30
  days is offered, so a Sync Run window or a recent investigation is never cut short.
- Every entry newer than the cutoff is kept untouched. For each Directional Sync Rule and source
  event, two entries older than the cutoff are also kept:
  1. **The latest entry older than the cutoff.** Activity compares an entry with the event's
     previous one, both to show a repair as repeated and to show an earlier name or time it was
     renamed or moved from. A block check compares a block with the event's decision before the
     pass began. Each reads at most one entry past the cutoff, and this is it. It also keeps an
     event's latest entry when every entry is old, which keeps open blocks and the dashboard's
     blocked-entry links.
  2. **The latest entry older than the cutoff that recorded a title.** Activity names a
     cancellation recorded without a title from the event's previous titled entry.
  Every other entry older than the cutoff is removed, including those of removed rules: that
  history is evidence, not state, and Incidents keep no Audit Entry IDs, so they are unaffected.
- Clearing deletes in batches of 5,000 rows, each its own short write transaction, then runs
  `VACUUM` to return the space to the filesystem. `VACUUM` briefly blocks writes, so it waits for
  every rule's run lock. Locks acquired first stay held while it waits for the rest, up to 30
  seconds in total, and all are released once the vacuum finishes or the wait gives up. If the locks
  cannot all be acquired within those 30 seconds, or SQLite still reports the database locked after that, the answer is
  409: "Old Activity was cleared, but its space could not be reclaimed while a rule is
  synchronizing. Try again when it finishes." The rows are already gone by then; clearing again
  later reclaims the space without deleting anything further.

## Consequences

- Entries newer than the cutoff show exactly what they showed before. The two entries kept per
  rule and source event lose the earlier entries they were compared with: a kept old entry may stop
  reading as a repeated repair, or lose the earlier name or time it was renamed or moved from. That
  loss is accepted in exchange for a bounded database.
- Backups keep cleared entries until they rotate, so a restored backup can briefly show more
  history than the live database.
- Incidents keep no Audit Entry IDs and are unaffected by clearing.
- Removed rules' history is cleared by the same cutoff as any other rule's; nothing exempts it.

## Alternatives considered

- **Automatic retention on a schedule.** Deferred rather than rejected: a "keep for N days" setting
  can be built on the same protected-entry rules later. Clearing stays a manual, confirmed action
  for now.
- **Deleting everything older than the cutoff, with no protected entries.** Rejected: it breaks
  open blocks and the dashboard's blocked-entry links, and lets a persisting-block incident miss
  its "blocked" comparison, because the entry a block check or repeated-repair check would have read
  one step back is gone.
- **Protecting the latest entry at or before each rule's stored `rule_block_checks.audit_floor`**
  instead of a floor computed fresh at clearing time. Rejected: production's persisting-block check
  reads a fresh floor taken just before each pass begins, not the floor stored after the previous
  pass finished. Protecting entries at the stale stored floor could let a pass already in progress
  compare against an entry that clearing had already removed, missing its "blocked" incident; it
  would also have changed what Activity shows for entries newer than the cutoff, which this design
  leaves untouched.
- **Hiding old entries instead of deleting them**, as ADR 0013 did for unrecorded reasons. Rejected
  for this feature: hiding reclaims no space, and an unbounded Raspberry Pi database was the problem
  being solved.
