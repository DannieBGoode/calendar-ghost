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
- **Update** whenever actual destination content differs from the projection derived from source authority. A new source revision whose projection matches the destination, such as another guest's reply to an invitation or a title change under a Busy-Only rule, is ignored as `projection_current`, and the mapping records the revision without a provider write. An update is `source_changed` only when the projection the source calls for differs from the one last written. During reprojection, an update of a projection still as the rule last wrote it is `policy_applied`; otherwise it repairs drift.
- **Delete** when a mapped source is cancelled or becomes excluded by rule policy: an all-day event under an all-day exclusion, a declined event, an event answered Maybe under a rule that skips them, or an unanswered invitation under a rule that waits for an answer ([ADR 0018](adr/0018-project-by-invitation-response.md)).
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
| Series content, time, or recurrence change | Update the destination series if its projection changed, then re-verify every Occurrence Mapping. The Series Mapping records the new revision only after that, so a retry re-verifies again |
| "This and following" split | Truncate the old destination series and create the new one; retire Occurrence Mappings that no longer exist on either side |
| Moved or edited occurrence | Update the matching destination occurrence |
| Occurrence answered on its own | Mark it as tentative, unmark it, or cancel it in the destination, as the rule's policy calls for |
| Cancelled occurrence | Cancel the matching destination occurrence and keep a `cancelled` Occurrence Mapping |
| Deleted series | Delete the destination series with its occurrences |
| No occurrence left to project (all cancelled, or excluded by the rule, such as declined or all-day under an exclusion) | Do not create or restore the destination series; keep its Series Mapping and Occurrence Mappings dormant |

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
whether the source series has any occurrence that is not cancelled and that the rule projects.
Occurrences the rule excludes do not count, such as one the Source Calendar declined, one awaiting
an answer or answered Maybe when the rule skips those, or an all-day one when the rule excludes
all-day events, since those are cancelled in the destination too. If none remains, the series is ignored (`series_without_occurrences`) instead of being
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
source series' cancelled and edited occurrences whose original slot or current time reaches the
sync window, and applies each one, besides
re-applying every Occurrence Mapping. Occurrences cancelled while the series had no projection, or
whose cancellation response was lost, therefore stay cancelled. The replay is recorded with the new
Series Mapping and cleared only when it completes, so a run that fails midway leaves it for the
retry, and an exception it already applied is not applied again when the feed reports it. A full listing already reports
every exception in the window, so series it creates are not listed again. An exception is any
occurrence that is cancelled or differs from the series' regular occurrence in start, length,
title, description, or location. The listing stops after a page limit because it runs under the
rule's write lock; exceptions of a series longer than that are applied by the next full listing.

`recurring_unsupported` is no longer produced; it remains for audit entries recorded by earlier
releases.

## Audit evidence

Every write, block, and meaningful skip in a run appends one Audit Entry carrying the run
identifier, an `AuditAction` and `AuditOutcome` from `application/ports.py`, and a stable reason
code from `SyncReason` in `domain/model.py`, so the Activity view can explain what changed and why an expected event was not synchronized. Updates
distinguish a changed
source (`source_changed`) from a repaired destination edit (`destination_drift_repaired`). Entries
also record the source event's title, time, recurrence, and cancellation as the run saw them. When an entry saw no title, such as a cancellation Google
reported without one, an occurrence removed from its series, or a projection removed with its rule,
Activity names it from the latest earlier entry for the same rule and source event that saw one. A
confirmed event with an empty title keeps it. An entry whose title differs from that earlier one is
marked as renamed. Entries recorded before this behavior name no event (ADR 0014).

Each recorded decision about a confirmed source event also observes it (ADR 0017). The rule keeps
a Source Observation of the event's title, time, description, location, guest addresses,
recurrence, and conferencing links. When a later run sees a new revision, the entry records the
Source Change: the fields that differ and their values before and after. The first observation,
and a revision that changed no tracked field, such as a reply to an invitation, record none.
Decisions Activity does not record never observe, so they cannot absorb a change. Titles and the
names of changed fields are plain text; the other values are sealed with the History Cipher. Every
scheduler pass clears sealed values older than 90 days from every rule's entries, including paused
and removed rules. A run that lists both calendars in full also forgets that rule's observations of
single events that ended more than 90 days ago or of calendars it no longer uses. Activity lists the changed fields, and
`GET /api/v1/audit-entries/{id}/changes` shows one entry's values.

That 90-day expiry only clears sealed Source Change values; the Audit Entries themselves are kept
until an Installation Administrator clears them. Settings → Storage shows the database size and the
number and age of Activity entries, and clears every User's entries older than 30, 90, 180, or 365
days, keeping, per rule and source event, the older entries that newer ones are compared with,
found by id: normally the
latest entry older than the cutoff and the latest that recorded a title. See
[ADR 0019](adr/0019-administrator-chosen-activity-retention.md).

Occurrence decisions that found the destination already matching (`occurrence_current`,
`occurrence_already_cancelled`) are listed as no change, like `projection_current`. When an
occurrence is missing from its destination series, the run checks the series before blocking; that
series check is not recorded as a no-change entry of its own. The block's detail records how the
series was found and the occurrence's original start instead.

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
Three consecutive scheduled failures open one deduplicated incident, resolved by the rule's next
successful scheduled run. Only scheduled runs report their success to rule health, so Sync Now and
Reconcile Now never resolve it. Each resolved incident records why it resolved (`sync_succeeded`,
`blocks_cleared`, or `rule_removed`, SQLite migration 12), and reopening one resets its opening
time, so "First seen" on the Overview measures only the current episode. An authorization failure
lapses the Connected Account Google rejected and opens one Incident for that account at once,
covering every rule it stops; a preview that finds another account's authorization lost lapses
that account too. Reauthorization, or an access check Google passes, resolves the account's
Incident (`access_restored`, migration 20) and resumes the rules the lapse alone stopped
([ADR 0027](adr/0027-lapsed-authorization-and-automatic-recovery.md)).

## Reconciliation

Touched mappings reconcile before a run completes. The scheduler's daily full pass is a Sync Run
that lists both calendars from the rolling window start; it repairs the drift it reaches and decides
every blocked event in the window again. A conflict blocks writes to that one event and leaves the
destination unchanged while the rest of the rule keeps synchronizing; a block still there at the
daily pass opens one `blocked:{rule}` Incident. It persists only when the event was already blocked before the pass began and the pass's own run blocked it again, so a retried attempt or a Sync Now interleaved with the pass is not earlier evidence, which a later daily pass without persisting blocks resolves. A rule's open blocks are those recorded since its latest successful daily pass began (SQLite migration 11); an older block that pass did not repeat, such as one of an occurrence whose series was deleted or of an event that ended before the sync window, is no longer open. Reconcile Now, and a scheduled run that lists both calendars in full because of a reprojection or a rejected cursor, count as that day's pass. Incident notifications are sent after the rule lock is released.

Reconcile Now runs that full pass and then a Full Reconciliation. The reconciliation is read-only:
it covers the same range the daily pass keeps current, from the rolling window start onward. It
lists the source calendar and this rule's managed destination events from that instant, each in
one paginated request, then verifies every mapping whose source or projection either listing
returned. A listed source needs no further read; a source that only its projection's listing
reached, such as one moved before the window or deleted, is read directly. A mapping neither
listing reaches belongs to an event that ended before the window: it is not read, checked,
counted, or reported, unless it lies outside the rule's relationship, which is a
`mapping_inconsistent` Conflict at any age and needs no read to prove. A series reaches the window while any occurrence does, however long ago it
began, and its Occurrence Mappings are checked when their original start is in the window or
either listing returned the occurrence as an exception, so an old occurrence moved into the window
is checked and a past one is not. It never writes to Google, so the Web UI never calls what it
found repaired ([ADR 0016](adr/0016-reconcile-within-the-sync-window.md)).

| Finding | Kind | Why it can remain after the full pass |
| --- | --- | --- |
| Projection missing | Drift `missing` | It was deleted after the pass, or the pass blocked writing it |
| Projection differs from its source | Drift `incorrect_projection` | Either calendar changed after the pass |
| Projection left for a source that is cancelled or excluded | Drift `unexpected` | The source's cancellation was not reported to any run that could reach it |
| Mapping outside the rule's relationship, or whose source is itself a managed projection | Conflict `mapping_inconsistent` | No run writes through a mapping it cannot prove |
| Mapping whose source cannot be read | Conflict `source_unverifiable` | An unverifiable source never authorizes deletion |
| Managed event with this rule's marker but no mapping | Conflict `projection_unmapped` | No mapping proves ownership, so nothing changes or deletes it |

Drift that changed during the check is repaired by the next Sync Run. Each Conflict the reconciliation finds appends one blocked Audit Entry with its
reason code under the full pass's run, so Activity lists it under **Blocked**, and it counts as
earlier evidence for the next daily pass's `blocked:{rule}` check. A finding about an event the full
pass already blocked is left out, because that block is already recorded and counted. The Reconcile
Now response keeps `conflicts` as the full pass's blocked count and lists the reconciliation's own
in `reconciliation_conflicts`; the stored reconciliation outcome counts drift in `drift` and those
conflicts in `conflicts` ([ADR 0015](adr/0015-reconciliation-reports-conflicts-apart-from-drift.md)).

For recurring projections, Full Reconciliation verifies each series and every Occurrence Mapping
without expanding the series, and reports a managed exception of a mapped series that has no
Occurrence Mapping as an incorrect projection rather than a `projection_unmapped` Conflict.
