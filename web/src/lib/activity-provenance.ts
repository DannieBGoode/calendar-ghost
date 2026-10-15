import type { MessageKey } from "@/i18n/types"
import type { AuditEntry } from "@/lib/api"

type RunReason = NonNullable<AuditEntry["run_reason"]>
type SourceComparison = NonNullable<AuditEntry["source_comparison"]>

// Every run reason but `changes` explains itself; a changes run names the calendar that reported.
const BY_RUN_REASON: Partial<Record<RunReason, MessageKey>> = {
  daily_pass: "activity.detail.why.dailyPass",
  first_run: "activity.detail.why.firstRun",
  reconcile_now: "activity.detail.why.reconcileNow",
  reprojection: "activity.detail.why.reprojection",
  relisted: "activity.detail.why.relisted",
}

/** The catalog key of the line that says why the run looked at this event, if it recorded one. */
export function checkedBecauseKey(entry: AuditEntry): MessageKey | null {
  if (entry.found_by === "reconciliation") return "activity.detail.why.reconciliation"
  if (entry.found_by === "pending_replay") return "activity.detail.why.pendingReplay"
  if (entry.run_reason === "changes") {
    if (entry.found_by === "source_feed") return "activity.detail.why.sourceReported"
    if (entry.found_by === "destination_feed") return "activity.detail.why.destinationReported"
    return null
  }
  return entry.run_reason ? (BY_RUN_REASON[entry.run_reason] ?? null) : null
}

// A change or a cancellation is already said by the Source Change section and the row.
const BY_COMPARISON: Partial<Record<SourceComparison, MessageKey>> = {
  untracked: "activity.detail.comparison.untracked",
  same_revision: "activity.detail.comparison.sameRevision",
  no_baseline: "activity.detail.comparison.noBaseline",
}

/** The catalog key of the comparison line, only when it adds to the Source Change section. */
export function comparisonKey(entry: AuditEntry): MessageKey | null {
  return entry.source_comparison ? (BY_COMPARISON[entry.source_comparison] ?? null) : null
}
