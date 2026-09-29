# Reconcile only within the sync window

## Context

Reconcile Now repairs what its full pass reaches: events from the rule's Initial Sync Window start
onward, 30 days before the run by default, and every recurring series with an occurrence in that
range. The Full Reconciliation after it read the source of every mapping the rule ever recorded,
one request each, and reported differences in events that ended months or years ago. No run could
repair those, so the report listed differences nobody would act on, and each Reconcile Now spent
more provider requests the longer a rule had existed. Past events no longer affect anyone's
schedule; blocks on them already stop counting once the daily pass no longer lists them.

## Decision

- Full Reconciliation covers the same range as the daily pass. It lists the source calendar with
  cancelled events, and this rule's managed destination events, from the window start, and verifies
  every mapping whose source or projection either listing returned.
- A listed source is compared as listed. A source reached only through its projection's listing,
  such as one moved before the window or deleted, is read directly, so a current projection is
  never left unverified.
- A series reaches the window while any occurrence does. Its Occurrence Mappings are checked when
  their original start is in the window, or when either listing returned that occurrence as an
  exception, so an old occurrence moved into the window is checked and a past one is not.
- A mapping neither listing reaches is not read, checked, counted in `checked_mappings`, or
  reported. An unmapped managed event that ended before the window is not reported either.
- `CalendarReader` gains `list_events`, a windowed listing that reads no incremental position, and
  `managed_events` takes the window start.

## Alternatives considered

- Having Reconcile Now also re-decide and repair every mapping outside the window would make
  "repaired" true for old events, but rewrites events nobody looks at and costs a source read per
  mapping on every run.
- A shorter check window than the sync window would save a little more, but leave recent past
  events that the daily pass keeps correct unverified.

## Consequences

- Reconcile Now costs two paginated listings plus reads only for recorded occurrences in the window
  and for sources moved out of it, instead of one read per mapping ever recorded.
- An edit made directly to a projection of an event that ended before the window is neither
  repaired nor reported. Editing the source event still updates the projection through the
  incremental feed, and a Material Rule Change still reprojects every mapping.
- Reconciliation outcomes recorded earlier counted every mapping in `checked_mappings`; later ones
  count only the window. No stored schema changes.
