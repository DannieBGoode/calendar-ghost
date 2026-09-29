# Synchronization model

## Initial and incremental synchronization

The first run selects source events ending no earlier than 30 days before the run, with no future
cutoff, and observes the destination endpoint. A successful initial run establishes separate opaque
incremental cursors for source and destination. Later runs request both change feeds every five
minutes or through Sync Now. Source changes project forward; mapped destination changes load their
authoritative source and repair edits or deletions during that same run. Google's incremental feed
is not bounded by the initial `timeMin`, so it also reports changes to events that ended long ago.
An unmapped single event that ended before the rolling window start (30 days before the run) is
ignored with reason `before_sync_window`; mapped events and recurring series are decided normally.
Before skipping, the run looks up a projection created with the event's create Operation Key, so a
create Google acknowledged before an interrupted run recorded its mapping is adopted, not orphaned.

## Cost of a run

A run with nothing to do makes two provider requests per rule: one incremental listing each for the
source and destination, which return no changes. Per-event reads are spent only where something
could have drifted:

- The destination feed reports this rule's own writes back on the next run. A reported projection
  or occurrence that still carries this rule's Managed Origin and matches the fingerprint recorded
  when it was written has not drifted, so it is counted as ignored without reading its source.
  Source changes arrive through the source feed. Any other content, status, or ownership repairs
  from the source as before. This applies only when both feeds returned changes since a cursor; a
  missing cursor, or one Google rejects (HTTP 410), yields a full listing, and every reported
  projection is then verified against its source.
- A mapping already decided from the source feed in the same run is not decided again from the
  destination feed.
- A full listing (the daily pass, the first run, or reprojection) reuses each listed projection for
  its decision instead of reading it again. Each listed projection is used once; a projection the
  listing did not include is read directly, and absence from the listing never counts as deletion.

The scheduler runs each rule's daily full pass when that rule has not completed one on the current
UTC day. Any successful run that listed both calendars in full, including a rule's first run,
completes that day's pass. The completion time is stored with the rule's run outcome, so restarting the service or
another rule failing does not repeat a full pass that already completed.

For each changed source event, the decision service chooses one action:

- **Create** when an eligible source has no managed projection or the mapped projection is missing.
- **Update** whenever actual destination content differs from the projection derived from source authority.
- **Delete** when a mapped source is cancelled or becomes excluded by rule policy.
- **Ignore** when content is current, the source is itself managed, an excluded/cancelled source has no mapping, or an unmapped single event ended before the window.
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

A mapped event whose Managed Origin metadata does not match the rule and source is a Conflict for
that event only: it stays in Google untouched, its mapping is removed, a `removal_conflict` audit
entry records it under **Blocked**, and removal continues. Temporary and rate-limited failures retry
each deletion up to three times with exponential backoff and jitter under the same Operation Key
before removal stops as interrupted. Google's `Retry-After` hint, bounded to 60 seconds, replaces
the backoff delay for removal and scheduled runs alike. Authentication and authorization failures stop removal at once
and open one Incident for the rule, resolved when the removal completes. See
[ADR 0012](adr/0012-rule-removal-conflicts-and-retries.md).

## Loop prevention

Managed Google events carry private extended properties containing rule, source, and operation identity. A reverse rule ignores any event bearing managed origin metadata. This permits `A -> B` and `B -> A` while native events flow in both directions without projection loops.

## Recurrence

[ADR 0011](adr/0011-recurring-event-synchronization.md) records the design.

A source Event Series projects as one destination series through a Series Mapping, keeping its
recurrence lines and time zone. Each occurrence the application writes gets an Occurrence Mapping
keyed by its original start. Destination occurrences are resolved through the provider by series
and original start (`events.instances(originalStart=...)`), never by constructing identifiers.

Within a batch, series masters are processed before occurrence exceptions. An exception whose series
is not yet mapped loads the series and creates it first; an exception of a managed, ineligible,
cancelled, or never-mapped missing series is ignored, so metadata-less cancelled instances never
become sources of a reverse rule. A mapped series that the source no longer returns is a Conflict.

| Source change | Destination behavior |
| --- | --- |
| Series content, time, or recurrence change | Update the destination series, then re-verify every Occurrence Mapping |
| "This and following" split | Truncate the old destination series and create the new one; retire Occurrence Mappings that no longer exist on either side |
| Moved or edited occurrence | Update the matching destination occurrence |
| Cancelled occurrence | Cancel the matching destination occurrence and keep a `cancelled` Occurrence Mapping |
| Deleted series | Delete the destination series with its occurrences |
| No occurrence left to project (all cancelled, or all-day under an exclusion) | Do not create or restore the destination series; keep its Series Mapping and Occurrence Mappings dormant |

A destination occurrence is cancelled only when the source proves it cancelled or absent from an
existing series; an unverifiable source series is a Conflict. When the destination series has no
matching occurrence, the series is repaired from the source and resolved once more before a
Conflict is recorded. Direct destination edits or deletions of an occurrence are restored from the
source, and a recreated destination series re-applies every Occurrence Mapping. A Material Rule
Change re-decides every Series Mapping and each of its Occurrence Mappings, including exceptions
outside the Initial Sync Window. Rule Preview reports recurring series and changed occurrences with
their planned actions.

Google cancels a whole series once its last live occurrence is cancelled, and a cancelled
projection reads as missing. A source series whose every occurrence is cancelled, such as the
single-occurrence remainder of a "this and following" split, therefore cannot be projected: before
creating or restoring a series projection, the run asks the provider, once per series per run,
whether the source series has any occurrence that is not cancelled, not counting all-day
occurrences when the rule excludes all-day events, since those are cancelled in the destination
too. If none remains, the series is ignored (`series_without_occurrences`) instead of being
recreated on every run. A mapped series stays dormant: its Series Mapping and `cancelled`
Occurrence Mappings are kept, and its occurrences are ignored rather than reported as a missing
destination occurrence. Full Reconciliation accepts a dormant series once it confirms the
projection is really gone, and Rule Preview excludes it. For a series that was never mapped, a
projection that Google created before an interrupted run could record its mapping is found by its
create Operation Key and removed (`series_without_occurrences_removed`). Only an answered lookup
may report that none remain: a series Google cannot expand counts as live, and so does one whose
occurrences run past the page limit.

A series projection created from an incremental feed, including a dormant series restored when
one of its occurrences comes back, starts from its recurrence alone. The run therefore lists the
source series' cancelled and moved occurrences in the sync window and applies each one, besides
re-applying every Occurrence Mapping. Occurrences cancelled while the series had no projection, or
whose cancellation response was lost, therefore stay cancelled. The replay is recorded with the new
Series Mapping and cleared only when it completes, so a run that fails midway leaves it for the
retry, and an exception it already applied is not applied again when the feed reports it. A full listing already reports
every exception in the window, so series it creates are not listed again. Edits to an occurrence's
title, description, or location alone are not detected by this listing; the next full pass applies
them.

`recurring_unsupported` is no longer produced; it remains for audit entries recorded by earlier
releases.

## Audit evidence

Every write, block, and meaningful skip in a run appends one Audit Entry carrying the run
identifier, the action, and a stable reason code from `SyncReason` in `domain/model.py`, so the
Activity view can explain what changed and why an expected event was not synchronized. Updates
distinguish a changed
source (`source_changed`) from a repaired destination edit (`destination_drift_repaired`). Entries
store only identities; Activity reads titles and times from Google on demand and never persists them.
Occurrence decisions that found the destination already matching (`occurrence_current`,
`occurrence_already_cancelled`) are listed as no change, like `projection_current`.

Decisions that answer no question an administrator would ask are counted in the run's ignored
total but not recorded: `managed_projection_source` (loop prevention), `outside_source_calendar`,
`cancelled_without_projection`, `before_sync_window`, and `occurrence_retired` (bookkeeping with no
provider write). `all_day_excluded`, `series_not_synchronized`, and `series_without_occurrences`
are recorded by the first run and
by incremental runs that saw the event change, but not by the daily full pass, which would repeat
them for every unchanged event each day. Entries with the unrecorded reasons written by earlier
releases are hidden from Activity. See
[ADR 0013](adr/0013-record-decisions-worth-explaining.md).

## Partial failure

Provider writes use stable Operation Keys. Each acknowledged provider operation commits its mapping
and audit evidence in a short SQLite transaction, while both incremental cursors advance only after
the complete source and destination batches succeed. A retry can therefore reuse completed mappings
without losing its safe position. Temporary failures retry with exponential backoff and jitter.
Three consecutive scheduled failures open one deduplicated incident.

## Reconciliation

Touched mappings reconcile before a run completes. A Full Reconciliation runs daily and through Reconcile Now. It derives expected projections from current sources, fetches managed destination state independently, and reports missing, unexpected, incorrect, or inconsistent mappings. Drift repairs automatically; conflicts require intervention.

For recurring projections, Full Reconciliation verifies each series and every Occurrence Mapping
without expanding the series, and reports a managed exception of a mapped series that has no
Occurrence Mapping as an incorrect projection rather than an unexpected event.
