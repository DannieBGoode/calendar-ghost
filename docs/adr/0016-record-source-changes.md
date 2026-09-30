# Record what changed in a source event, and write only when the projection changes

## Context

Activity said "Changed in Personal → updated in Work" whenever Google reported a new revision of a
source event, but not what changed. Google's revision (etag) changes on any edit: a guest added, a
response to the invitation, a reminder, a colour, or the description. The decision service updated
the Managed Projection on every new revision, even when the projection it derived was identical to
the destination. A Busy-Only rule therefore rewrote "Busy" with "Busy" when someone accepted an
invitation, and Activity recorded it as a change. Occurrences of a series behaved the same way.

Google's Calendar API does not say who changed an event. It does return the event's current
details, so a run can compare them with what an earlier run saw. Showing what changed, and the
values before and after, requires keeping those details between runs. AGENTS.md and ADR 0014 ruled
out persisting descriptions, locations, attendees, and conferencing data.

## Decision

- A decision writes to the destination only when the projection derived from the source differs
  from the destination's actual content. A new source revision alone is evidence to check, not a
  reason to write. When they match, the decision is `projection_current` (or
  `occurrence_current`), and the Event Mapping or Occurrence Mapping records the new revision
  without a provider write. An update's reason is `source_changed` only when the projection the
  source now calls for differs from the one last written; otherwise it repairs Drift.
- A series whose source revision changed re-verifies its Occurrence Mappings even when the series
  itself needed no write. Its Series Mapping records the new revision only after that
  re-verification completes, so a retry after a failure re-verifies again.
- Each rule keeps a **Source Observation** of every source event it decides: its revision, title,
  time, description, location, guests, recurrence, and conferencing entry points. When a later run
  sees a new revision, it compares the two and records the **Source Change** on that decision's
  Audit Entry: which fields changed, and their values before and after. The first observation of an
  event records no change. Observations are updated only by recorded decisions, so a change is
  never absorbed by a decision Activity does not show.
- Responses to invitations, reminders, colours, and other fields are not tracked. A revision that
  changed none of the tracked fields records no Source Change, and its decision reads as
  "already up to date".
- Guests are compared as the set of attendee email addresses; a response or display-name change is
  not a guest change. When Google omits part of the guest list (`attendeesOmitted`), guests are
  unknown and not compared, so a partial list never reads as guests removed. Cancelled events are
  not observed; their last observation stays, so a restored event is compared with how it was.
- Titles stay in plain text, as ADR 0014 decided, including a change's previous title. The other
  values are sealed with AES-256-GCM under a key derived with HKDF-SHA256 from the Installation
  Master Key for this purpose only, bound to the rule and source event as associated data. Values
  are stored as Google returned them, without redaction, so descriptions keep any meeting links,
  dial-in codes, or passwords they contain.
- Sealed change values are kept for 90 days. Every scheduler pass clears older values from the
  Audit Entries of every rule, including paused and removed rules, keeping the names of the fields
  that changed and the titles. A rule's full listing deletes its observations of single events that
  ended more than 90 days ago and of calendars it no longer uses. Observations are deleted with
  their rule.
- Activity lists which fields changed. Opening an entry shows the values before and after, read and
  unsealed on request. Values that expired or cannot be unsealed, for example after the master key
  was replaced, are reported as no longer available.

## Alternatives considered

- Keyed digests of each field would say which fields changed without persisting values, but cannot
  show what changed to.
- Reading the event from Google when an entry is opened shows its current values, not the values
  the change produced, and nothing about the values before.
- Inferring changes from the previous Audit Entry works only for what entries already record, and
  the previous entry is a synchronization decision, not necessarily an earlier source revision.
- Redacting links and codes from descriptions cannot be made reliable, and the operator chose to
  see descriptions as they were.

## Consequences

The database now holds sealed descriptions, locations, guest email addresses, recurrence rules, and
conferencing links of every observed event, plus 90 days of their earlier values. Anyone with both
the database and the master key, including a backup that contains both, can read them. Losing the
master key makes the history unreadable as well as the credentials. Backups keep values beyond 90
days until they rotate.

Busy-Only rules no longer rewrite projections for changes they do not show, so responses to
invitations and detail edits cause no provider writes. Entries recorded before this change have no
Source Change. ADR 0014 still governs titles, times, and naming events in Activity.
