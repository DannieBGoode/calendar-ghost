# Synchronize recurring series through series and occurrence mappings

## Context

Recurring series and occurrence exceptions were excluded from synchronization because projecting
only a series, or only its exceptions, can duplicate or resurrect occurrences. Recurring meetings
are often the majority of a work calendar, so the exclusion leaves most availability unprojected.
Recurring events must follow the same Directional Sync Rule guarantees as single events: source
authority, exact ownership before update or deletion, loop prevention, drift repair, and rule-wide
transformation.

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

- the normalized original start (a UTC instant for timed series, a date for all-day series);
- the source instance and destination instance identities;
- the state, `modified` or `cancelled`;
- the source revision and, for `modified`, the Projection Fingerprint.

An Occurrence Mapping is created when a source Occurrence Exception is applied, or when a direct
destination edit to an otherwise unmodified occurrence is repaired. Occurrences unmodified on both
sides need no row. `cancelled` rows are retained so a recreated destination series cannot
resurrect occurrences the source cancelled. Deleting a Series Mapping deletes its Occurrence
Mappings.

`OccurrenceIdentity.original_start` becomes a typed Occurrence Start (UTC `datetime` or `date`)
so source and destination representations of the same occurrence compare equal regardless of
provider formatting.

### Resolving destination occurrences

The destination occurrence is resolved through the provider by destination series identity and
Occurrence Start. The Google adapter uses `events.instances(eventId, originalStart, showDeleted)`
and never constructs instance identifiers. "No such occurrence" is distinct from "cancelled
occurrence".

### Ownership and loop prevention

Before writing an occurrence, the domain requires all of:

1. a Series Mapping for this rule and the occurrence's source series;
2. a destination master whose Managed Origin names this rule and source series;
3. a destination instance whose parent series is exactly the mapped destination series;
4. when present on the instance, a Managed Origin naming this rule and source series.

Any mismatch is a Conflict and nothing is written. Occurrence writes carry the series Managed
Origin plus the private properties `gcs_source_original_start` and `gcs_operation_key`, so every
destination instance identifies its source series.

A source exception is processed only through its parent series. An exception whose parent is a
Managed Projection, is ineligible under rule policy, or is unmapped and cannot be created is
ignored. Metadata-less cancelled instances of a managed series therefore never become sources of
a reverse rule.

Operation Keys for series reuse the single-event formula. Occurrence Operation Keys hash rule,
source series, Occurrence Start, source revision, and action. Every write uses
`sendUpdates=none`.

### Ordering within a batch

Within each source batch, series masters and single events are processed before occurrence
exceptions. When an exception's series has no Series Mapping, the application loads the source
series and decides it first; if the series is eligible it is created, then the exception is
applied. If the series is ineligible the exception is ignored. If the series cannot be loaded the
run fails before any occurrence write and the cursors do not advance.

### Source updates

| Source change | Destination behavior |
| --- | --- |
| Series content, time, RRULE, EXDATE, or RDATE change | Update the destination master, then re-verify every Occurrence Mapping of the series in the same run |
| "This and following" split | The truncated master (`UNTIL`) updates the destination master; the new native series creates a new destination series; Occurrence Mappings beyond `UNTIL` whose occurrences no longer exist on either side are removed without provider writes |
| Moved or edited occurrence | Update the matching destination instance |
| Cancelled occurrence | Cancel the matching destination instance and retain a `cancelled` Occurrence Mapping |
| Cancelled series | Delete the destination master, removing its instances, and delete the Series Mapping and its Occurrence Mappings |

A destination occurrence is cancelled only when the source proves the occurrence is cancelled or
no longer part of an existing source series. When the source series cannot be verified, the
decision is a Conflict and no deletion occurs. When the destination series has no occurrence at
the required Occurrence Start, the application repairs the destination master from the source
and resolves again once; a remaining mismatch is a Conflict.

### Transformations and eligibility

The rule's Transformation Policy applies to the series and to every occurrence it writes.
Busy-Only Projection copies timing, recurrence, and the busy title; Details Projection
additionally copies title, description, and location per series and per exception. Attendees,
organizer identity, conferencing data, attachments, and invitations are never copied.

An all-day series follows the rule's All-Day Sync Policy; when excluded, the series and its
exceptions are ignored. An exception whose own time becomes all-day under an excluding rule
cancels its destination occurrence, matching single-event exclusion.

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
recorded exceptions are sufficient evidence.

If the provider cannot restore a single cancelled instance, the application recreates the destination
series under the existing Series Mapping identity and re-applies its Occurrence Mappings.

### Persistence, upgrade, and rollback

A new `occurrence_mappings` table references `event_mappings(id)` with `ON DELETE CASCADE` and
is unique per series mapping and Occurrence Start. It stores identities, the Occurrence Start,
state, revision, and fingerprint only.

Migrations become ordered, numbered SQL files applied by a small runner that records each version
in `schema_migrations`; `0001_initial.sql` is unchanged. Migration `0002` creates the table and
clears source and destination incremental cursors so each rule's next run re-reads its source
within the Initial Sync Window and backfills recurring series. Existing single-event mappings
remain valid; they are re-verified, not rewritten.

Enabled rules backfill automatically after upgrade. Administrators who want to preview recurring
projections first pause rules before upgrading, then preview and enable after upgrade. Upgrade
notes recommend a database backup.

Rolling back to an earlier release leaves `occurrence_mappings` unused. Earlier releases classify
recurring events as unsupported and write nothing to them, so recurring projections remain
unchanged until the upgrade is reapplied, while single events continue synchronizing.

### Preview

Rule Preview includes eligible series and occurrence exceptions. Each preview item reports its
kind (`single`, `series`, or `occurrence`) and its planned action from the same decision service
used during synchronization, using only provider reads. Preview remains side-effect-free apart
from recording the validated rule state.

### Rule Removal compatibility

Rule Removal deletes a recurring projection by deleting its destination master after the normal
mapping and Managed Origin ownership checks, never by deleting individual instances. Occurrence
Mappings are removed with their Series Mapping.

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

## Consequences

Recurring meetings synchronize as series with exact ownership, loop prevention, and drift repair.
Occurrence writes cost one additional provider read to resolve the destination instance.
Reconciliation checks masters and recorded exceptions rather than every occurrence. The upgrade
performs one full source and destination re-read per rule. The `occurrence_mappings` schema and
the `gcs_source_original_start` metadata become compatibility surfaces. The adapter behavior for
restoring cancelled instances and for `timeMin` filtering of series masters must be verified with
synthetic fixtures mirroring documented Google responses.
