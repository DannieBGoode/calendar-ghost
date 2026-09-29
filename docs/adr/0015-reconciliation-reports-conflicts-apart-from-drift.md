# Report reconciliation conflicts apart from drift, and record them as blocks

## Context

Reconcile Now runs a full Sync Run and then a read-only Full Reconciliation. The reconciliation's
report listed every finding as drift, including mappings it could not prove against the rule or
their source, which CONTEXT.md defines as Conflicts. Those findings reached the Reconcile Now
payload's `drift` list and the stored reconciliation outcome's `drift` count, and the Web UI
described all of them as "repaired from the source", although the reconciliation never writes and
the sync before it had already done every repair it could. None of the conflicts were recorded as
Audit Entries, so "see Activity" could not show them.

After a successful full pass, whatever the reconciliation still finds was not repaired: an event
that ended before the sync window, a change made after the pass, or an identity problem no run may
write through. A managed event carrying this rule's marker but no mapping is never deleted by any
run, so it is an identity question, not a content difference.

## Decision

- `ReconciliationReport` keeps `drift` for content differences (`missing`, `unexpected`,
  `incorrect_projection`) and gains `conflicts`, each with a `SyncReason`. `is_consistent` requires
  both to be empty. The `mapping_inconsistency` drift kind is gone.
- A mapping outside the rule's relationship, or whose source is itself a managed projection, is a
  `mapping_inconsistent` Conflict. A mapping whose source cannot be read is `source_unverifiable`.
  A managed event with no mapping is the new `projection_unmapped` reason. A source that was read and
  is cancelled or excluded while its projection remains is `unexpected` drift, because a verified
  source authorizes the deletion a Sync Run would make.
- Each reconciliation Conflict appends one Audit Entry with action `conflict`, outcome `blocked`,
  and its reason, under the full pass's run identifier, so Activity lists it as Blocked beside the
  pass's own decisions. Findings about a source the pass already blocked are left out.
- The Reconcile Now response keeps `conflicts` as the pass's blocked count, lists remaining drift
  in `drift`, and adds `reconciliation_conflicts` as `{reason, detail}` items. The stored
  reconciliation outcome uses the existing `drift` and `conflicts` columns (migration 0004) for the
  two counts. No schema change is needed.

## Alternatives considered

- Keeping every finding in `drift` and fixing only the wording would leave `consistent` and the
  stored count mixing identity problems with content differences.
- Changing `conflicts` in the payload to the combined total would silently change an existing
  field's meaning for any client reading it.
- New reason codes specific to reconciliation would duplicate `mapping_inconsistent` and
  `source_unverifiable`, which already name these conditions; their Activity copy was reworded so
  it is true whichever run recorded them.

## Consequences

- `projection_unmapped` is a stored reason code and a compatibility surface.
- Reconciliation outcomes recorded before this change counted mapping conflicts in `drift` and
  record `0` conflicts; they still read, and the Web UI describes them as differences left
  unchanged. Rolling back leaves the new rows readable: earlier releases ignore `conflicts` on
  reconciliation rows, and the `projection_unmapped` entries fall back to generic "blocked" copy.
- A reconciliation block counts as an open block until the next daily pass and as earlier evidence
  for that pass's `blocked:{rule}` check. It does not open an Incident by itself.
- Drift in events that ended before the sync window is reported but still not repaired by any run
  except a reprojection.
