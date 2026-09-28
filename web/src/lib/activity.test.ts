import { describe, expect, it } from "vitest"

import { ApiError } from "./api"
import { describeEntry, entryInspection, eventLookupFailure, formatRunTime, groupRuns, outcomeLabel, summarizeRun } from "./activity"
import type { AuditEntry } from "./api"

function entry(overrides: Partial<AuditEntry>): AuditEntry {
  return {
    id: 1,
    run_id: "run-1",
    occurred_at: "2026-09-28T15:18:46+00:00",
    rule_id: "rule-1",
    action: "ignore",
    outcome: "skipped",
    category: "skipped",
    reason: "recurring_unsupported",
    detail: "",
    source_event_id: "source-event",
    destination_event_id: null,
    ...overrides,
  }
}

describe("activity presentation", () => {
  it("explains skipped recurring events in calendar language", () => {
    const copy = describeEntry(entry({}))
    expect(copy.summary).toBe("Skipped a recurring event")
    expect(copy.explanation).toContain("not synced yet")
  })

  it("falls back to the recorded detail for entries without a reason code", () => {
    const copy = describeEntry(entry({ reason: null, detail: "excluded event has no managed projection" }))
    expect(copy.summary).toBe("Skipped an event")
    expect(copy.explanation).toBe("excluded event has no managed projection")
  })

  it("explains rule management entries in domain language", () => {
    expect(describeEntry(entry({ action: "policy_changed", reason: null, detail: "privacy=copy_details, all_day=include" })).summary).toBe(
      "Changed the projection policy",
    )
    expect(describeEntry(entry({ action: "remove_projection", reason: null })).summary).toBe(
      "Deleted a projection during Rule Removal",
    )
    expect(describeEntry(entry({ action: "detach_projection", reason: null })).summary).toBe(
      "Kept a projection as a Detached Event",
    )
    expect(describeEntry(entry({ action: "rule_removed", reason: null })).summary).toBe("Removed the rule")
    expect(outcomeLabel(entry({ action: "remove_projection", category: "changed" }))).toBe("Removed")
    expect(outcomeLabel(entry({ action: "rule_removed", category: "changed" }))).toBe("Removed")
    expect(outcomeLabel(entry({ action: "detach_projection", category: "changed" }))).toBe("Kept")
  })

  it("only looks up events for rules that still exist", () => {
    expect(entryInspection(entry({}), true)).toBe("event")
    expect(entryInspection(entry({ action: "detach_projection", reason: null }), false)).toBe("details")
    expect(entryInspection(entry({ action: "policy_changed", reason: null, source_event_id: null }), true)).toBe(
      "details",
    )
    expect(
      entryInspection(entry({ action: "create", reason: null, detail: "", source_event_id: null }), true),
    ).toBeNull()
  })

  it("explains why an event lookup failed", () => {
    expect(eventLookupFailure(new ApiError("gone", 410))).toBe(
      "This rule was removed, so its events can no longer be looked up.",
    )
    expect(eventLookupFailure(new ApiError("unavailable", 503))).toBe(
      "Google is not configured, so the event cannot be looked up.",
    )
    expect(eventLookupFailure(new ApiError("provider", 424))).toBe(
      "Google could not return this event right now. The account may need reauthorization in Settings.",
    )
  })

  it("labels outcomes by category before action", () => {
    expect(outcomeLabel(entry({ action: "conflict", category: "skipped" }))).toBe("Skipped")
    expect(outcomeLabel(entry({ action: "conflict", category: "blocked" }))).toBe("Blocked")
    expect(outcomeLabel(entry({ action: "delete", category: "changed" }))).toBe("Removed")
  })

  it("groups consecutive entries by run and keeps legacy entries together by minute", () => {
    const runs = groupRuns([
      entry({ id: 5, run_id: "run-2" }),
      entry({ id: 4, run_id: "run-2", action: "create", category: "changed" }),
      entry({ id: 3, run_id: null, occurred_at: "2026-09-27T09:00:10+00:00" }),
      entry({ id: 2, run_id: null, occurred_at: "2026-09-27T09:00:50+00:00" }),
      entry({ id: 1, run_id: null, occurred_at: "2026-09-27T09:00:50+00:00", rule_id: "rule-2" }),
    ])

    expect(runs.map((run) => run.entries.map((item) => item.id))).toEqual([[5, 4], [3, 2], [1]])
    expect(summarizeRun(runs[0].entries)).toBe("1 created · 1 skipped")
  })

  it("keeps one group per run when concurrent rules interleave their entries", () => {
    const runs = groupRuns([
      entry({ id: 4, run_id: "work-run", rule_id: "rule-1" }),
      entry({ id: 3, run_id: "home-run", rule_id: "rule-2" }),
      entry({ id: 2, run_id: "work-run", rule_id: "rule-1", action: "create", category: "changed" }),
      entry({ id: 1, run_id: "home-run", rule_id: "rule-2" }),
    ])

    expect(runs.map((run) => [run.key, run.entries.map((item) => item.id)])).toEqual([
      ["work-run", [4, 2]],
      ["home-run", [3, 1]],
    ])
    expect(summarizeRun(runs[0].entries)).toBe("1 created · 1 skipped")
  })

  it("describes decisions with Event Projection terminology", () => {
    expect(describeEntry(entry({ reason: "source_created" })).summary).toBe("Created a projection")
    expect(describeEntry(entry({ reason: "managed_projection_source" })).summary).toBe(
      "Skipped a managed projection",
    )
  })

  it("uses relative day names for recent runs", () => {
    const now = new Date(2026, 8, 28, 18, 0)
    expect(formatRunTime(new Date(2026, 8, 28, 15, 18).toISOString(), now)).toMatch(/^Today at /)
    expect(formatRunTime(new Date(2026, 8, 27, 15, 18).toISOString(), now)).toMatch(/^Yesterday at /)
  })
})
