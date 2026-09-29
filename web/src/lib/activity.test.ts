import { describe, expect, it } from "vitest"

import { ApiError } from "./api"
import { describeEntry, entryInspection, eventLookupFailure, formatRunTime, groupRuns, whatHappened } from "./activity"
import { activityStateFromSearch } from "./activity-location"
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
    expect(copy.happened).toBe("Skipped: recurring event")
    expect(copy.explanation).toContain("Earlier versions")
  })

  it("explains cancelled occurrences in calendar language", () => {
    const copy = describeEntry(entry({ action: "delete", reason: "occurrence_cancelled" }))
    expect(copy.happened).toBe("One occurrence removed from {destination}")
  })

  it("falls back to the recorded detail for entries without a reason code", () => {
    const copy = describeEntry(entry({ reason: null, detail: "excluded event has no managed projection" }))
    expect(copy.happened).toBe("Skipped")
    expect(copy.explanation).toBe("excluded event has no managed projection")
  })

  it("says what happened to rule management entries without calling them event changes", () => {
    const changed = (action: string) => whatHappened(entry({ action, reason: null, category: "changed" }), "Work")

    expect(changed("policy_changed")).toEqual({ text: "Privacy setting changed", icon: "rule", tone: "change" })
    expect(changed("rule_removed")).toEqual({ text: "Rule removed", icon: "rule", tone: "change" })
    expect(changed("remove_projection")).toMatchObject({ text: "Removed from Work with the rule", icon: "removed" })
    expect(changed("detach_projection")).toMatchObject({ text: "Kept in Work, no longer synced", icon: "kept" })
    expect(whatHappened(entry({ action: "removal_conflict", reason: null, category: "blocked" }), "Work")).toEqual({
      text: "Blocked: left in Work during Rule Removal",
      icon: "blocked",
      tone: "blocked",
    })
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

  it("says what happened in calendar terms, reserving colour for blocked changes", () => {
    expect(whatHappened(entry({ action: "conflict", category: "skipped" }), "Work")).toMatchObject({
      icon: "skipped",
      tone: "quiet",
    })
    expect(
      whatHappened(entry({ action: "conflict", reason: "destination_ownership_inconsistent", category: "blocked" }), "Work"),
    ).toEqual({ text: "Blocked: not owned by this rule", icon: "blocked", tone: "blocked" })
    expect(whatHappened(entry({ action: "delete", reason: "source_cancelled", category: "changed" }), "Work")).toEqual({
      text: "Removed from Work",
      icon: "removed",
      tone: "change",
    })
    expect(
      whatHappened(entry({ action: "update", reason: "destination_drift_repaired", category: "changed" }), null),
    ).toMatchObject({ text: "Edit in the destination undone", icon: "repaired" })
    expect(whatHappened(entry({ reason: "projection_current", category: "unchanged" }), "Work")).toMatchObject({
      text: "Already up to date",
      tone: "quiet",
    })
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
  })

  it("describes decisions with Event Projection terminology", () => {
    expect(whatHappened(entry({ action: "create", reason: "source_created", category: "changed" }), "Work").text).toBe(
      "Added to Work",
    )
    expect(describeEntry(entry({ reason: "managed_projection_source" })).explanation).toContain("never synced again")
  })

  it("explains series whose every occurrence is cancelled", () => {
    const skipped = entry({ reason: "series_without_occurrences" })
    expect(describeEntry(skipped).happened).toBe("Skipped: every occurrence is cancelled")
    expect(describeEntry(skipped).explanation).toContain("synced again if an occurrence is restored")
    const removed = entry({ action: "delete", reason: "series_without_occurrences_removed", category: "changed" })
    expect(whatHappened(removed, "Work").text).toBe("Removed from Work: every occurrence is cancelled")
  })

  it("uses relative day names for recent runs", () => {
    const now = new Date(2026, 8, 28, 18, 0)
    expect(formatRunTime(new Date(2026, 8, 28, 15, 18).toISOString(), now)).toMatch(/^Today at /)
    expect(formatRunTime(new Date(2026, 8, 27, 15, 18).toISOString(), now)).toMatch(/^Yesterday at /)
  })
})

describe("activity address", () => {
  it("reads links that name the outcome with the earlier category parameter", () => {
    expect(activityStateFromSearch("?rule=rule-7&category=blocked")).toEqual({ ruleId: "rule-7", show: "blocked", entryId: null })
    expect(activityStateFromSearch("?category=everything").show).toBe("")
    expect(activityStateFromSearch("?show=skipped&category=blocked").show).toBe("skipped")
  })
})
