# Domain model

The canonical glossary is [CONTEXT.md](../CONTEXT.md). This document explains aggregate boundaries and invariants.

## Directional Sync Rule aggregate

A Directional Sync Rule identifies one source Calendar Endpoint and one destination Calendar Endpoint. Each endpoint combines a Connected Account identity with a provider calendar identity, so a rule may cross Google identities. Rules may form one-to-many or many-to-one topologies, but an exact directional relationship is unique.

The rule owns its Transformation Policy, all-day eligibility, initial lookback, and lifecycle. A new or materially changed rule must pass Rule Preview before enabling. Editing the transformation policy or all-day eligibility sets a persisted reprojection flag that the next successful Sync Run clears after rewriting every mapped projection. Source and destination are fixed for the life of a rule; changing either is a Rule Replacement.

Invariants:

- Source and destination endpoints cannot be identical.
- Busy-only is the default transformation policy.
- All-day events are included by default and may be excluded per rule.
- Destination content is never authoritative.
- Managed projections are never eligible sources.

## Event Mapping aggregate

An Event Mapping is the durable ownership link between one source Event Reference and one destination Event Reference under one rule. It stores identities, source revision, and a non-reversible Projection Fingerprint, not event content.

Invariants:

- A mapping belongs to exactly one directional rule.
- One source maps to at most one destination under a rule.
- One managed destination maps to at most one source under a rule.
- Update or deletion requires a valid mapping and matching origin metadata.
- Identity ambiguity is a Conflict; content difference is Drift.

An Event Mapping whose source is an Event Series is a Series Mapping. It may own Occurrence Mappings:
one per destination occurrence the application wrote, keyed by the occurrence's original start and
recording whether the occurrence is `modified` or `cancelled`, its source revision, and (for
modified occurrences) a Projection Fingerprint.

- At most one Occurrence Mapping exists per Series Mapping and original start.
- Occurrence Mappings are removed with their Series Mapping, including on Rule Removal.
- Occurrence Mappings are not counted as managed projections; a series counts once.
- Writing an occurrence requires the Series Mapping, a destination series carrying this rule's
  Managed Origin, and an occurrence whose parent is exactly that series.
- When no occurrence of the source series remains that the rule would project, the Series Mapping
  stays dormant without a destination series and keeps its `cancelled` Occurrence Mappings, so
  restoring one occurrence cannot bring back the others.
- A Series Mapping created by an incremental run carries a pending exception replay until every
  source Occurrence Exception has been applied; the replay is removed with its Series Mapping.

## Reconciliation report

A Full Reconciliation produces a `ReconciliationReport` for one rule: the number of mappings it
checked, the Drift it found, and the Conflicts it found. Drift is a content difference between a
mapped projection and what its source calls for (`missing`, `unexpected`, `incorrect_projection`).
A Conflict carries a `SyncReason`: `mapping_inconsistent` for a mapping outside the rule's
relationship or whose source is itself a managed projection, `source_unverifiable` for a mapping
whose source cannot be read, and `projection_unmapped` for a managed event with no mapping. A report
is consistent only when both are empty, so a Conflict leaves the rule inconsistent without counting
as Drift. It covers only mappings whose source or projection reaches the rule's sync window ([ADR 0016](adr/0016-reconcile-within-the-sync-window.md)), and `checked_mappings` counts those. The report never implies a repair; see [ADR 0015](adr/0015-reconciliation-reports-conflicts-apart-from-drift.md).

## Calendar Event values

A Calendar Event is a transient provider-neutral representation. Its time is either a timezone-aware Timed Interval or an All-Day Range with an exclusive end date. Recurring events retain Event Series, Occurrence, and Occurrence Exception identity. An occurrence's original start is normalized to a UTC instant (timed series) or a date (all-day series) so both calendars identify it identically, and a timed series keeps its IANA time zone so its recurrence expands at the same local times across daylight-saving changes.

Attendees, organizer identity, conferencing links, and attachments do not enter an Event Projection. Event content is processed in memory and excluded from operational persistence, except the source event's title and time recorded on each Audit Entry (ADR 0014).

## State machines

```text
Draft -> Previewed ----> Enabled -> Paused
             |              |
             -> Degraded <--|

any state -> Removing (Rule Removal incomplete) -> removed
```

Only a successfully previewed configuration can become Enabled. An Enabled Rule can be Paused from
the Web UI. A Material Rule Change returns Enabled and Paused rules to Paused, Draft and
Previewed rules to Draft, and keeps Degraded rules Degraded, so the rule must pass a new
preview. Rule Removal first moves the rule to Removing, which cannot synchronize, preview, change
policy, or enable; the rule is deleted once every mapping is deleted, detached, or left in place
because its ownership could not be verified, and a failed removal can be retried in either mode. Disconnecting an account moves affected Enabled and Previewed rules to Degraded,
preventing a previously validated rule from being enabled without authorization. A Degraded Rule
performs no writes until the account is reauthorized and the rule passes a new recovery preview;
re-enabling starts with both preserved incremental positions.

Permanent deletion is available only after a Connected Account is disconnected. Deletion removes
the account and every Directional Sync Rule that references it, including those rules' Event
Mappings, cursors, incidents, and audit activity. It does not issue provider writes: existing
Managed Projections remain in Google Calendar but are no longer managed.
Deletion first waits for any run, provider write, or lifecycle change of each affected rule to
finish, as Rule Removal does, so no in-flight work outlives the records it depends on. The account
and its rules are then deleted in one transaction that also rechecks the account is disconnected,
so a reauthorization or a new rule for the account cannot interleave with it.
