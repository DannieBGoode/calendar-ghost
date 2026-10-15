# Record a decision only when it says something new

Amends [ADR 0013](0013-record-decisions-worth-explaining.md), which records skips on incremental
runs "that saw the event change", and [ADR 0017](0017-record-source-changes.md), which observes an
event whenever its decision is recorded.

## Context

On 2026-10-14 at 17:48 UTC, Google's change feed for one rule's Source Calendar returned 362
seminar events in one ordinary incremental run (`mode=incremental reason=changes`, no cursor
rejected). The runs five minutes before and after returned 0 or 1. Another rule whose Destination
Calendar is the same calendar saw 362 destination events at the same second, which points to a
change made in Google, not by Calendar Ghost. The run wrote nothing
(`created=0 updated=0 deleted=0 ignored=362`) and added about 277 Audit Entries: 83
`occurrence_current`, 47 `series_without_occurrences`, 45 `declined`, 43
`series_not_synchronized`, 42 `projection_current`, and 17 `occurrence_already_cancelled`.

No entry showed a Source Change. No tracked field difference was detected, and cancelled events
have no Source Observation to compare with. A likely cause is a bulk change by the organizer to
fields Calendar Ghost does not track, such as responses, the organizer, or reminders. The data
cannot prove which.

Two things went wrong for the person reading Activity:

1. **Noise.** Each entry repeated the decision Activity already recorded for that event, with
   nothing new to explain. ADR 0013 records these skips on incremental runs that saw the event
   change. The code read "saw the event change" as "the provider reported it", not as "its tracked
   content changed".
2. **No reason given.** An entry did not say what brought the event into the run, or how the
   source compared with what the rule last saw.

## Decision

**A Source Comparison comes before a decision is recorded.** The run compares the source event
with the rule's Source Observation of it. The result is a Source Comparison: `changed` (a Source
Change exists), `untracked` (the revision differs and no tracked field difference was detected),
`same_revision`, `cancelled` (the event has no observation to build, and its last one is kept), or
`no_baseline` (there is no observation, or it cannot be unsealed). A newer revision also says
whether it completes the baseline: the new observation knows a guest list, conferencing link, or
response the stored one did not. That is not a Source Change, but saving it lets later revisions
be compared in full.

Comparing and saving are separate steps. The run saves an observation only for a decision it
records, so ADR 0017's rule that only recorded decisions observe still holds. An unrecorded
decision leaves the stored observation as it was.

**A repeated `ignore` is counted, not recorded.** Outside the daily pass, an `ignore` decision
recorded under the event's own identity is left out when all of these hold:

- The comparison is `untracked` or `same_revision`, or it is `cancelled` and the previous entry's
  recorded event is cancelled too, and it does not complete the baseline.
- The event's previous Audit Entry (the highest id for the rule and source event, which ADR 0019
  always keeps) has the same action, reason, and destination event.
- Both entries have a recorded event, and the two are equal: same title, same time compared as
  instants, same `recurring`, same `cancelled`.

Creates, updates, deletes, and blocks are always recorded. A block ends in a `conflict` entry, so
the next decision differs from it and is recorded, and `open_blocks` still sees the recovery. A
decision that changes for a reason outside the event, such as a series that loses its last live
occurrence, has a different reason and is recorded. The first `projection_current` after a write
is recorded because the previous action differs.

The daily pass is unchanged. It keeps recording its no-change checks as evidence that a run looked
at an event, and `UNRECORDED_ON_DAILY_PASS` stays. `UNRECORDED_REASONS` stays too. An occurrence
without its own source reference is recorded under its series' identity, so the previous entry
under that identity may be about another event. The rule does not apply to it. Today such an
occurrence has no source event to compare, so it is recorded anyway; the guard is for safety.

Cancellation shows how little the `cancelled` branch does for a series. A repeated cancellation of
a series is already left out as `cancelled_without_projection`, and a restored event is a create
or update, which is always recorded. The branch matters for occurrences.

**Each skipped decision is counted.** `run finished` logs `unrecorded=N` after the decision counts
(`created`, `updated`, `deleted`, `ignored`, `conflicts`). It counts only decisions this rule did
not record. It does not count `UNRECORDED_REASONS` or daily-pass skips. The 2026-10-14 run would
read `ignored=362` and a separate `unrecorded=N`, so the log still shows the burst.

**Each entry says what brought its event into the run.** Every entry a Sync Run records carries
two codes and the comparison:

- `run_reason` says why the run read the calendars the way it did. The first that applies wins:
  `reprojection`, `reconcile_now`, `daily_pass`, `first_run`, `relisted` (an incremental run in
  which a feed was listed in full because its cursor was missing or rejected), or `changes`.
- `found_by` names the work that started the chain of decisions: `source_feed`,
  `destination_feed`, `reprojection`, or `pending_replay` (an earlier run left a series replay
  unfinished). Work nested inside it, such as a series repair or an immediate exception replay,
  inherits the value.
- `source_comparison` is the comparison above, when the decision had a source event to compare.

Full Reconciliation entries carry `found_by=reconciliation`. A Full Reconciliation is not a Sync
Run, so its `run_reason` and comparison stay `NULL`. Rule removal and rule edits are not Sync Run
decisions, so all three values stay `NULL`. Entries recorded before this release keep `NULL`. An
unknown stored code reads as null in the API, so a rollback and a later upgrade cannot break
Activity.

Migration 32 adds the three nullable `TEXT` columns. The values are codes and hold no event
content, so ADR 0014's limits are unchanged.

## Alternatives considered

**Rejected: field digests.** Storing a keyed digest (HMAC) of each untracked field, such as the
organizer, responses, reminders, and color, plus one digest of the rest of the payload, would name
which untracked field changed without keeping its value. It is not part of this design:

- It explains entries that are no longer shown. A digest-only difference must not create an
  entry, or the 2026-10-14 run would record its entries again, each saying "responses changed".
  Under the repeated-decision rule those entries are not recorded, so the digests would explain
  almost nothing a person sees.
- The "rest of the payload" digest is not stable. Leaving out volatile fields such as `etag`,
  `updated`, `sequence`, and `htmlLink` still leaves differences from missing fields, defaults, key
  order, and adapter versions. Graph reads selected fields only. A mismatch proves that the input
  differed, not that the organizer did something.
- It weakens ADR 0017's privacy position. ADR 0017 considered keyed digests and rejected them.
  Responses have four possible values, so with the installation key they can be guessed, and equal
  digests show when a value went back to an earlier one. Digests would also need their own key
  derivation, canonical form, version, retention, and key-reset behavior.
- The revision already says what the data supports. `untracked` says that the provider sent a new
  version and no tracked change was detected. The data supports nothing stronger.

If a later need, such as acting on other people's responses, requires a new field, it becomes a
tracked field under ADR 0017's rules, with its value sealed.

**Rejected: a run summary entry.** One Audit Entry that summarized the burst ("Google sent 362
events again...") would break the meaning of an Audit Entry as one decision about one event.
Activity's categories, counts, search, block queries, and retention all depend on that meaning.
`rule_run_outcomes` keeps only the latest outcome per rule and run kind, so a summary there would
disappear five minutes later. A retained per-run record, shown as a run heading in Activity, would
work, but it is a separate feature. The `unrecorded=N` log field covers investigations for now.

**Rejected: comparing more fields to catch the change.** Tracking the organizer, responses, or
reminders would turn the burst into Source Changes. It changes what Calendar Ghost stores about
other people, and ADR 0017 settled that limit.

## Consequences

A provider that re-sends many events with no tracked change no longer fills Activity. Each such
event keeps its last entry, and the log's `unrecorded=N` still shows the size of the burst. An
unrecorded skip cannot be looked up by event, but the event's previous entry says the same thing
with the same title and time.

Each repeated-decision check costs one indexed read of `audit_entries_source_event`, only for an
`ignore` outside the daily pass with its own identity and a comparison. The stored observation of
an unrecorded decision keeps its old revision, so the next new revision is compared with it
again. A newer revision that completes the baseline is recorded and saved.

Activity can say why each new entry was made and how its source compared with what the rule last
saw. Earlier entries show neither line. Rolling back to an earlier release ignores the new
columns.
