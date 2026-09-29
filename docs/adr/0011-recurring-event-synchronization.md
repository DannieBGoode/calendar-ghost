# Synchronize recurring series through series and occurrence mappings

## Context

Recurring series and occurrence exceptions were excluded from synchronization because projecting
only a series, or only its exceptions, can duplicate or resurrect occurrences. Recurring meetings
are often the majority of a work calendar, so the exclusion leaves most availability unprojected.
Recurring events must follow the same Directional Sync Rule guarantees as single events: source
authority, exact ownership before update or deletion, loop prevention, drift repair, rule-wide
transformation, Material Rule Change reprojection, and Rule Removal
([ADR 0010](0010-rule-removal-and-calendar-replacement.md)).

Google Calendar represents a series as one master event carrying iCalendar `recurrence` lines.
Modified and cancelled occurrences are separate exception events that carry `recurringEventId`
and `originalStartTime`; cancelled exceptions may contain nothing else. Unmodified occurrences
exist only as expansions of the master. Instance identifiers follow an undocumented
`<seriesId>_<originalStart>` convention, while `events.instances(originalStart=...)` resolves an
occurrence through the documented API. Recurrence expansion depends on the series time zone: a
fixed UTC offset shifts local meeting times across daylight-saving changes.

## Decision

### Series identity

A source Event Series maps to one destination Event Series through an ordinary Event Mapping,
called a Series Mapping when its source is a series master. The destination remains a recurring
series; occurrences are never flattened into unrelated single events. Series creation, update,
and deletion use the existing single-event paths with recurrence lines included in the
projection.

An **Occurrence Mapping** is a child of a Series Mapping. It records one occurrence the
application has written on the destination:

- the normalized Occurrence Start (a UTC instant for timed series, a date for all-day series);
- the source instance and destination instance identities;
- the state, `modified` or `cancelled`;
- the source revision and, for `modified`, the Projection Fingerprint.

An Occurrence Mapping is created when a source Occurrence Exception is applied, or when a direct
destination edit to an otherwise unmodified occurrence is repaired. Occurrences unmodified on both
sides need no row. `cancelled` rows are retained so a recreated destination series cannot
resurrect occurrences the source cancelled. Deleting a Series Mapping deletes its Occurrence
Mappings. Occurrence Mappings are not Event Mappings: the rule's managed projection count keeps
counting a series once.

`OccurrenceIdentity.original_start` becomes a typed Occurrence Start (UTC `datetime` or `date`)
so source and destination representations of the same occurrence compare equal regardless of
provider formatting.

### Resolving destination occurrences

The destination occurrence is resolved through the provider by destination series identity and
Occurrence Start. The Google adapter uses `events.instances(eventId, originalStart, showDeleted)`
and never constructs instance identifiers. "No such occurrence" is distinct from "cancelled
occurrence", and only an answered lookup may report absence: a series that cannot be read during
the lookup (404 or 410) is a temporary provider failure, because absence can authorize cancelling
a destination occurrence.

### Ownership and loop prevention

Before writing an occurrence, the domain requires all of:

1. a Series Mapping for this rule and the occurrence's source series;
2. a destination master whose Managed Origin names this rule and source series;
3. a destination instance whose parent series is exactly the mapped destination series;
4. when present on the instance, a Managed Origin naming this rule and source series.

Any mismatch is a Conflict and nothing is written. Occurrence writes carry the series Managed
Origin plus the private properties `gcs_source_original_start` and `gcs_operation_key`, so every
destination instance identifies its source series.

Occurrence update, cancellation, and restoration use dedicated provider operations that verify
the instance's parent series and ownership. They never use `delete_projection`, which applies only
to single events and series masters. The single-event decision rejects occurrence input, so an
exception cannot reach a single-event write path.

A source exception is processed only through its parent series. An exception whose parent is a
Managed Projection, is ineligible under rule policy, or is unmapped and cannot be created is
ignored. Metadata-less cancelled instances of a managed series therefore never become sources of
a reverse rule. This also holds for Detached Events: a detached series keeps its origin metadata,
so its master, modified instances, and cancelled instances stay ignored.

Operation Keys for series reuse the single-event formula. Occurrence Operation Keys hash rule,
source series, Occurrence Start, source revision, and action. Every write uses
`sendUpdates=none`.

### Ordering within a batch

Within each source batch, series masters and single events are processed before occurrence
exceptions. When an exception's series has no Series Mapping, the application loads the source
series and decides it first; if the series is eligible it is created, then the exception is
applied. If the series is ineligible the exception is ignored. A provider failure while loading the
series fails the run before any occurrence write, and the cursors do not advance. A series the
provider reports as absent is ignored when this rule never mapped it (`series_not_synchronized`),
and is a Conflict (`source_unverifiable`) with no write when it is mapped.

Every occurrence write, cancellation, restoration, and mapping retirement is preceded by the same
stop check as single-event writes: if the rule was paused, edited, or removed during the run, the
run stops with `RuleNotExecutable` and the cursors do not advance.

### Source updates

| Source change | Destination behavior |
| --- | --- |
| Series content, time, RRULE, EXDATE, or RDATE change | Update the destination master, then re-verify every Occurrence Mapping of the series in the same run |
| "This and following" split | The truncated master (`UNTIL`) updates the destination master; the new native series creates a new destination series; Occurrence Mappings beyond `UNTIL` whose occurrences no longer exist on either side are retired without provider writes |
| Moved or edited occurrence | Update the matching destination instance |
| Cancelled occurrence | Cancel the matching destination instance and retain a `cancelled` Occurrence Mapping |
| Cancelled series | Delete the destination master, removing its instances, and delete the Series Mapping and its Occurrence Mappings |
| Every occurrence cancelled | Do not create or restore the destination master; the series is ignored, and a mapped series keeps its Series Mapping and Occurrence Mappings as a dormant series |

Google cancels a series once its last live instance is cancelled, and `showDeleted=false` lookups no
longer find it. Creating a series whose every source occurrence is cancelled and then cancelling
those occurrences would leave a cancelled projection that the next run reads as missing and
recreates, indefinitely. Before creating or restoring a series projection, the application
therefore asks the provider (`has_live_occurrences`, an `instances` listing without cancelled
instances, cached per run) whether any source occurrence remains. Only an answered lookup may
report that none remain; a 404 or 410 is a temporary provider failure. A mapped series is kept
dormant rather than deleted, because its `cancelled` Occurrence Mappings are what stop a later
restore of one occurrence from resurrecting the others. Occurrence decisions against a dormant
series are ignored instead of reported as `destination_occurrence_missing`, Full Reconciliation
accepts it without a projection, and Rule Preview excludes it. A projection created before an
interrupted run recorded its mapping is found by its create Operation Key, verified like any mapped
projection, and removed.

A destination occurrence is cancelled only when the source proves the occurrence is cancelled or
no longer part of an existing source series. When the source series cannot be verified, the
decision is a Conflict (`source_unverifiable`) and no deletion occurs. When the destination series
has no occurrence at the required Occurrence Start, the application repairs the destination
master from the source and resolves again once; a remaining mismatch is a Conflict.

### Transformations and eligibility

The rule's Transformation Policy applies to the series and to every occurrence it writes.
Busy-Only Projection copies timing, recurrence, and the busy title; Details Projection
additionally copies title, description, and location per series and per exception. Attendees,
organizer identity, conferencing data, attachments, and invitations are never copied.

An all-day series follows the rule's All-Day Sync Policy; when excluded, the series and its
exceptions are ignored, and a mapped series is deleted. An exception whose own time is all-day
under an excluding rule cancels its destination occurrence, matching single-event exclusion.

### Material Rule Change reprojection

When `reprojection_required` forces a full window after a policy change, the sweep of mappings the
change feeds did not report routes each Series Mapping through the series path: the master is
re-decided under the new policy, and then every Occurrence Mapping of the series not already
handled in the run is re-decided and rewritten. A Details-to-Busy-Only change therefore removes
titles, descriptions, and locations from modified occurrences, including exceptions outside the
Initial Sync Window. An all-day exclusion deletes an all-day series master and cancels all-day
exceptions of timed series. Source instances handled by the change feeds are recorded so the sweep
does not process them twice. A source series or occurrence that cannot be verified is a Conflict
and nothing is deleted. The flag clears only under the existing rule-signature check.

### Time zones

`TimedInterval` carries an optional IANA time zone read from the provider. The projection of a
timed series master preserves it and the Google adapter writes `start.timeZone` and
`end.timeZone`. For non-recurring projections and occurrence writes, the time zone is normalized
away before fingerprinting and writing, so existing single-event projections are not rewritten
on upgrade.

### Drift and reconciliation

Destination changes are repaired from the source during every Sync Run. A destination instance
reported by the destination feed is matched by its Occurrence Mapping or, failing that, by the
Series Mapping of its parent series; unrelated instances are skipped. Edited instances are
rewritten from the authoritative source occurrence and gain an Occurrence Mapping; cancelled
instances are restored when the source occurrence is confirmed; a deleted destination master is
recreated and every Occurrence Mapping is re-applied to the new series.

Full Reconciliation verifies each Series Mapping and each Occurrence Mapping against the source,
and reports managed destination exceptions of a mapped series without an Occurrence Mapping as
incorrect projections rather than unexpected events. It does not expand series occurrences:
identical recurrence lines and time zone produce identical expansion, so the master and the
recorded exceptions are sufficient evidence. The recorded reconciliation outcome keeps
`checked_mappings` as the number of Event Mappings and includes occurrence drift in `drift`.

Restoring a cancelled destination occurrence patches it back to `confirmed`. If the provider
rejects the restore, the permanent provider failure stops the run and opens an incident rather than
deleting and recreating the series; this provider behavior must be confirmed against a test
calendar before release. When a repair recreates or rewrites a destination series, every
Occurrence Mapping of that series is re-applied in the same run.

### Audit evidence

Every occurrence decision is recorded with its `run_id` and a content-free `SyncReason`, using
instance identifiers only. New reasons:

| Reason | Action | Meaning |
| --- | --- | --- |
| `occurrence_changed` | update | A source occurrence was moved or edited |
| `occurrence_cancelled` | delete | A source occurrence was cancelled |
| `occurrence_removed_from_series` | delete | The source series no longer contains the occurrence |
| `occurrence_drift_repaired` | update | A destination occurrence was edited or deleted directly and was restored |
| `occurrence_current` | ignore | The destination occurrence already matches the source |
| `occurrence_already_cancelled` | ignore | Source and destination occurrences are both cancelled |
| `occurrence_retired` | ignore | The occurrence no longer exists on either side; its mapping was removed |
| `series_not_synchronized` | ignore | The occurrence belongs to a series this rule does not project |
| `destination_occurrence_missing` | conflict | The destination series has no matching occurrence after repair |
| `series_without_occurrences` | ignore | Every occurrence of the source series is cancelled; no projection is created |
| `series_without_occurrences_removed` | delete | Every occurrence is cancelled; a projection left by an interrupted create was removed |

Existing reasons are reused where the meaning is identical (`source_unverifiable`,
`destination_ownership_inconsistent`, `mapping_inconsistent`, `all_day_excluded_removed`).
`recurring_unsupported` is no longer produced but remains for audit entries recorded by earlier
releases. The Activity feed describes each reason.

### Persistence, upgrade, and rollback

Forward-only migration `0005_occurrence_mappings.sql` runs through the existing numbered runner
and commits atomically with its `schema_migrations` row. It creates `occurrence_mappings`,
referencing `event_mappings(id)` with `ON DELETE CASCADE`, unique per series mapping and
Occurrence Start. It stores identities, the Occurrence Start, state, revision, and fingerprint
only. The in-memory repositories mirror the cascade on mapping deletion and rule removal.

The same migration deletes all source and destination incremental cursors, so each rule's next
run reads its full Initial Sync Window and backfills recurring series. Cursor deletion is used
instead of `reprojection_required` because backfill needs only the full window, applies to rules
in every state, and must not show the "policy changed" preview notice. Existing single-event
mappings remain valid; they are re-decided, not rewritten. Enabled rules backfill automatically
after upgrade. Administrators who want to preview recurring projections first pause rules before
upgrading, then preview and enable after upgrade. Upgrade notes recommend a database backup.

Rolling back to an earlier release leaves `occurrence_mappings` unused. Earlier releases classify
recurring events as unsupported and write nothing to them, so recurring projections remain
unchanged until the upgrade is reapplied, while single events continue synchronizing. Rule
Removal in an earlier release deletes a series master like any single event, which removes its
instances, so removal remains safe after rollback.

### Preview

Rule Preview includes eligible series and occurrence exceptions. `eligible_events` and
`excluded_events` keep their meaning for single events and series. Each preview item additionally
reports its kind (`single`, `series`, or `occurrence`) and its planned action from the same
decision service used during synchronization, using only provider reads. Preview remains
side-effect-free apart from recording the validated rule state.

### Rule Removal

Rule Removal in delete mode deletes a recurring projection by deleting its destination master
through `delete_projection`, whose ownership check and already-cancelled handling apply to masters
unchanged. It never deletes individual instances. Occurrence Mappings are removed with their
Series Mapping in both delete and detach modes.

### Verification plan

Domain tests cover series, exception, cancellation, split, all-day exclusion, and ownership
failure decisions, each with allowed and blocked paths. Application tests cover mixed batches,
exceptions arriving without their series, destination drift on instances and masters, the stop
check on occurrence writes, and a policy change on a series whose modified exceptions lie outside
the window: the next run rewrites the master and every exception, then clears the flag. Removal
tests cover a series in delete mode (master deleted, no instance writes, Occurrence Mappings gone
in SQLite and in memory) and detach mode (no provider writes, Occurrence Mappings gone, a reverse
rule ignoring the master, modified instances, and metadata-less cancelled instances).
SQLite-backed tests cover migration `0005` from a version-4 database, the cascade, and cursor
reset. Synthetic Google fixtures cover translation of masters, exceptions, cancelled instances,
time zones, and instance resolution.

## Alternatives considered

- Constructing destination instance identifiers from `<seriesId>_<originalStart>` would save one
  read per occurrence but depends on an undocumented format that differs for timed and all-day
  series; a wrong identifier could target an unrelated event.
- Deriving occurrence state from the Series Mapping at run time without Occurrence Mappings would
  forget source cancellations, resurrecting occurrences when a destination series is recreated,
  and would require full expansion to detect instance drift.
- Flattening series into individual destination events would simplify identity but contradicts
  the Event Series definition, requires an arbitrary horizon for unbounded series, and multiplies
  provider writes.
- A per-rule recurring eligibility policy or pausing rules on upgrade would force a preview
  before backfill but adds rule configuration or interrupts single-event synchronization; pausing
  before upgrade provides the same safeguard on demand.
- Triggering backfill through `reprojection_required` would add a redundant sweep of every mapping
  and display a policy-change notice for paused and draft rules whose policy did not change.

## Consequences

Recurring meetings synchronize as series with exact ownership, loop prevention, drift repair,
policy reprojection, and removal. Occurrence writes cost one additional provider read to resolve
the destination instance. Reconciliation checks masters and recorded exceptions rather than every
occurrence. The upgrade performs one full source and destination re-read per rule. The
`occurrence_mappings` schema, the new reason codes, and the `gcs_source_original_start` metadata
become compatibility surfaces. The adapter behavior for restoring cancelled instances and for
`timeMin` filtering of series masters must be verified with synthetic fixtures mirroring
documented Google responses.
