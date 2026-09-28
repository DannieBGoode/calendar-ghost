# Synchronization model

## Initial and incremental synchronization

The first run selects source events ending no earlier than 30 days before the run, with no future
cutoff, and observes the destination endpoint. A successful initial run establishes separate opaque
incremental cursors for source and destination. Later runs request both change feeds every five
minutes or through Sync Now. Source changes project forward; mapped destination changes load their
authoritative source and repair edits or deletions during that same run.

For each changed source event, the decision service chooses one action:

- **Create** when an eligible source has no managed projection or the mapped projection is missing.
- **Update** whenever actual destination content differs from the projection derived from source authority.
- **Delete** when a mapped source is cancelled or becomes excluded by rule policy.
- **Ignore** when content is current, the source is itself managed, or an excluded/cancelled source has no mapping.
- **Conflict** only when identity or ownership is ambiguous.

## Reprojection after a Material Rule Change

Incremental change feeds only report source events that changed, so a new transformation policy
would otherwise reach only future edits. When a rule's reprojection flag is set, its next Sync Run
ignores both cursors, then loads the authoritative source of every remaining Event Mapping,
including events that ended before the Initial Sync Window, and applies the normal decision. A
source that cannot be verified is recorded as a Conflict and its projection is left unchanged. The
run clears the flag with its cursors only if the rule was not changed again meanwhile. Every change
to a rule's state or policy, including saving, pausing, enabling, preview validation, removal, and
degradation, takes a short per-rule lock that also spans each provider write. Lifecycle changes
therefore never overwrite one another and wait for at most one write already in flight; a Sync
Run re-checks the rule before each write and stops without advancing cursors once it is paused or
changed.

## Rule Removal

Removal holds the same per-rule lock as synchronization. Deleting projections uses the normal
ownership checks and `sendUpdates=none`, committing each mapping as it is removed; keeping
projections as Detached Events removes mappings without provider writes. Managed events without a
mapping are never deleted.

## Loop prevention

Managed Google events carry private extended properties containing rule, source, and operation identity. A reverse rule ignores any event bearing managed origin metadata. This permits `A -> B` and `B -> A` while native events flow in both directions without projection loops.

## Recurrence

The domain preserves iCalendar recurrence and occurrence identity at the Google boundary, but the
current pre-alpha synchronization policy excludes recurring series and occurrence exceptions.
Projecting only the series or only an exception can duplicate or resurrect occurrences, and timed
series also require provider timezone identity across daylight-saving changes. The system therefore
fails closed until series-to-series and occurrence-to-occurrence mapping is implemented.
Excluded recurring events are recorded as skipped with the `recurring_unsupported` reason; they are
not Conflicts, because no identity is ambiguous.

## Audit evidence

Every decision in a run appends one Audit Entry carrying the run identifier, the action, and a
stable reason code from `SyncReason` in `domain/model.py`. Skips are recorded as well as writes, so
the Activity view can explain why an event was not synchronized. Updates distinguish a changed
source (`source_changed`) from a repaired destination edit (`destination_drift_repaired`). Entries
store only identities; Activity reads titles and times from Google on demand and never persists them.

## Partial failure

Provider writes use stable Operation Keys. Each acknowledged provider operation commits its mapping
and audit evidence in a short SQLite transaction, while both incremental cursors advance only after
the complete source and destination batches succeed. A retry can therefore reuse completed mappings
without losing its safe position. Temporary failures retry with exponential backoff and jitter.
Three consecutive scheduled failures open one deduplicated incident.

## Reconciliation

Touched mappings reconcile before a run completes. A Full Reconciliation runs daily and through Reconcile Now. It derives expected projections from current sources, fetches managed destination state independently, and reports missing, unexpected, incorrect, or inconsistent mappings. Drift repairs automatically; conflicts require intervention.
