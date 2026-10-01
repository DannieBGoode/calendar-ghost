# Record the decisions worth explaining

Amended by [ADR 0019](0019-administrator-chosen-activity-retention.md), which lets the
administrator clear Activity older than a chosen age.

## Context

`docs/sync-model.md` required every synchronization decision to append an Audit Entry, including
every skip. In practice most entries explained nothing. With rules in both directions, each
projection a rule wrote came back on the next run twice: the reverse rule logged it as
"Skipped: a managed projection", and the writing rule's destination feed logged it as "Already up
to date" after reading its source again. The daily full pass then recorded a skip or check for
every event in the window again, every day, with no retention limit. Activity filled up with loop
prevention and bookkeeping, and each echo cost a provider read.

## Decision

- An Audit Entry records a write, a block, a no-change check, or a skip that explains why an
  expected projection is absent. Runs still count every decision.
- `managed_projection_source`, `outside_source_calendar`, `cancelled_without_projection`,
  `before_sync_window`, and `occurrence_retired` are not recorded. They are loop prevention, events
  that were never in the rule's scope, or bookkeeping with no provider write.
- `all_day_excluded`, `series_not_synchronized`, and `series_without_occurrences` are recorded on
  the first run and on incremental runs that saw the event change, and not on the daily full pass.
- Earlier entries with the unrecorded reasons stay in SQLite and are hidden from Activity.
- A series check made only to repair one missing occurrence is not recorded when it finds the
  series current. Listed beside the occurrence's block it read as a contradiction ("already up to
  date" and "blocked" for the same event); the block's detail records the check instead.
- A destination projection or occurrence reported back unchanged by an incremental feed, still
  carrying this rule's Managed Origin and the fingerprint recorded when it was written, is counted
  as ignored without reading its source or recording a check. When either feed is a full listing,
  because of a missing or rejected cursor, every reported projection is verified as before.

## Alternatives considered

- Keeping every decision and hiding the noise in the Web UI would still grow the database without
  bound and spend a provider read on every echo.
- Dropping no-change checks too would leave no way to confirm in Activity that a run looked at an
  event and found it already matching. With echoes skipped, those checks come mainly from the daily
  pass, once per mapped event.
- Deleting earlier noisy entries in a migration would reclaim space but destroy recorded evidence;
  hiding them is reversible.

## Consequences

Activity shows fewer, more meaningful entries, and runs with no changes record nothing. An
unrecorded skip can no longer be looked up by event, so "why is this event missing?" is answered
only for all-day exclusions, unsynchronized series, and series whose every occurrence is
cancelled. The trust in the echo check rests on the
same fingerprint comparison the decision service already uses to confirm a projection is current.
Retention is now the administrator's choice; see [ADR 0019](0019-administrator-chosen-activity-retention.md).
