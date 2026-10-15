import { describe, expect, it } from "vitest"

import { checkedBecauseKey, comparisonKey } from "./activity-provenance"
import type { AuditEntry } from "./api"

function entry(overrides: Partial<AuditEntry>): AuditEntry {
  return {
    id: 1,
    run_id: "run-1",
    occurred_at: "2026-09-28T15:18:46+00:00",
    rule_id: "rule-1",
    action: "ignore",
    outcome: "skipped",
    category: "unchanged",
    reason: "projection_current",
    detail: "",
    source_event_id: "source-event",
    destination_event_id: null,
    event: null,
    repeated: false,
    changed_fields: null,
    run_reason: null,
    found_by: null,
    source_comparison: null,
    ...overrides,
  }
}

describe("checkedBecauseKey", () => {
  it.each([
    [{ run_reason: "changes", found_by: "source_feed" }, "activity.detail.why.sourceReported"],
    [{ run_reason: "changes", found_by: "destination_feed" }, "activity.detail.why.destinationReported"],
    [{ run_reason: "changes", found_by: "pending_replay" }, "activity.detail.why.pendingReplay"],
    [{ run_reason: "daily_pass", found_by: "source_feed" }, "activity.detail.why.dailyPass"],
    [{ run_reason: "first_run", found_by: "source_feed" }, "activity.detail.why.firstRun"],
    [{ run_reason: "reconcile_now", found_by: "source_feed" }, "activity.detail.why.reconcileNow"],
    [{ run_reason: "reprojection", found_by: "reprojection" }, "activity.detail.why.reprojection"],
    [{ run_reason: "relisted", found_by: "source_feed" }, "activity.detail.why.relisted"],
    [{ run_reason: null, found_by: "reconciliation" }, "activity.detail.why.reconciliation"],
    [{ run_reason: null, found_by: null }, null],
  ] as const)("%o -> %s", (fields, key) => {
    expect(checkedBecauseKey(entry(fields))).toBe(key)
  })
})

describe("comparisonKey", () => {
  it.each([
    ["untracked", "activity.detail.comparison.untracked"],
    ["same_revision", "activity.detail.comparison.sameRevision"],
    ["no_baseline", "activity.detail.comparison.noBaseline"],
    ["changed", null],
    ["cancelled", null],
    [null, null],
  ] as const)("%s -> %s", (kind, key) => {
    expect(comparisonKey(entry({ source_comparison: kind }))).toBe(key)
  })
})
