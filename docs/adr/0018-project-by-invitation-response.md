# Project events by the source calendar's invitation response

## Context

Rules projected every confirmed source event the same way, whatever the Source Calendar had
answered to its invitation. Events answered Maybe looked like firm commitments in the destination,
and declined events and invitations nobody had answered yet were still shown as Busy. Google
returns each attendee's `responseStatus`, and marks the entry for the calendar being read with
`self: true`. Google's own tentative styling is drawn from the viewer's attendee entry, so a
projection could only show it by carrying attendees and invitations, which no projection may
carry.

## Decision

- The Google adapter translates the Source Calendar's own attendee entry into an **Invitation
  Response**: accepted, tentative (Maybe), declined, or awaiting a response. An event without such
  an entry, because the calendar organizes it, has no guests, or was not invited, counts as
  accepted. An unknown status also counts as accepted, so the event projects as before.
- Two rule-wide settings join the Transformation Policy. Changing either is a Material Rule
  Change:
  - **Tentative Event Policy**: `mark` (the default) projects a Maybe event with a title saying so,
    "Busy (tentative)" for a Busy-Only Projection and "Maybe: Standup" for a Details Projection;
    `sync` projects it like an accepted event; `skip` projects nothing.
  - **Unanswered Invitation Policy**: `as_tentative` (the default) treats an unanswered invitation
    as answered Maybe; `wait` projects nothing until it is answered.
- Declined events are never projected; no setting changes that.
- A response the rule does not project is an exclusion, decided like the all-day exclusion: an
  unmapped event is skipped (`declined`, `tentative_excluded`, `awaiting_response`) and a mapped
  one has its projection deleted (`declined_removed`, `tentative_excluded_removed`,
  `awaiting_response_removed`). An occurrence answered on its own is an Occurrence Exception: it
  is marked, or cancelled in the destination, without changing the rest of its series. Rule
  Preview and Full Reconciliation apply the same exclusions.
- The tentative mark is part of the projected title, so answering an invitation changes the
  projection only when the rule shows the answer, and is then a `source_changed` update. The
  response becomes a tracked Source Change field, sealed like the others (ADR 0017), so Activity
  can say "Your response: Maybe → Yes". Other guests' responses are still not tracked.
- A reprojection that rewrites a projection still as the rule last wrote it records
  `policy_applied`, not `destination_drift_repaired`, because nobody edited the destination.
- Migration 15 gives existing rules the defaults and sets their reprojection flag, so the next run
  marks their Maybe events and removes their declined ones.

## Alternatives considered

- Showing a Maybe event as Free (`transparency: transparent`) changes availability rather than
  appearance, and Google draws Free events almost like Busy ones. It can be added later as another
  choice.
- An event colour is visible only to the destination calendar's owner.
- Copying the attendee list would reproduce Google's tentative styling, but would send
  invitations and expose guests.
- Keeping existing rules unchanged until edited would leave declined events visible as Busy, which
  is what this change sets out to fix.

## Consequences

Upgrading rewrites the projections of Maybe events on each rule's next run and deletes those of
declined events and, under `wait`, unanswered invitations, without a new preview. Activity records
these as `policy_applied`, `declined_removed`, and `awaiting_response_removed`. A series whose
master is excluded is not projected, so an occurrence of it accepted on its own stays out, as an
occurrence of an excluded all-day series does. Rolling back to an earlier release keeps the
columns but ignores them; that release sees the tentative titles as drift and rewrites them on its
next full pass, and recreates projections of declined events.
