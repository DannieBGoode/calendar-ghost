import { describe, expect, it } from "vitest"

import {
  policyChanged,
  policyChangeConsequences,
  removalConfirmLabel,
  removalConsequence,
  removalOutcome,
  replacementConfirmLabel,
  ruleStateLabel,
  runOutcomeSummary,
} from "./rule-change"

const responses = { tentative_events: "mark", unanswered_invitations: "as_tentative" } as const
const busy = { privacy_policy: "busy_only", sync_all_day_events: true, ...responses } as const
const details = { privacy_policy: "copy_details", sync_all_day_events: true, ...responses } as const

describe("policy change consequences", () => {
  it("detects changes", () => {
    expect(policyChanged(busy, busy)).toBe(false)
    expect(policyChanged(busy, details)).toBe(true)
    expect(policyChanged(busy, { ...busy, sync_all_day_events: false })).toBe(true)
    expect(policyChanged(busy, { ...busy, tentative_events: "skip" })).toBe(true)
    expect(policyChanged(busy, { ...busy, unanswered_invitations: "wait" })).toBe(true)
  })

  it("warns before exposing event details", () => {
    const lines = policyChangeConsequences({
      state: "enabled",
      current: busy,
      next: details,
      mappingCount: 37,
      destination: "Family",
    })
    expect(lines[0]).toBe("Synchronization pauses now. Preview the rule, then enable it again.")
    expect(lines).toContain(
      "37 existing projections in Family will show event titles, descriptions, and locations after the next run, to anyone who can see Family.",
    )
    expect(lines.at(-1)).toBe("Nothing changes in Google Calendar until the rule is enabled again.")
  })

  it("explains redaction and all-day exclusion", () => {
    const lines = policyChangeConsequences({
      state: "draft",
      current: details,
      next: { ...busy, sync_all_day_events: false },
      mappingCount: 1,
      destination: "Work",
    })
    expect(lines[0]).toBe("The rule returns to draft. Preview it before enabling it.")
    expect(lines).toContain(
      "1 existing projection in Work will be rewritten as “Busy”, removing titles, descriptions, and locations.",
    )
    expect(lines).toContain("All-day projections in Work will be deleted on the next run.")
  })

  it("describes paused and degraded rules and newly included all-day events", () => {
    const paused = policyChangeConsequences({
      state: "paused",
      current: { ...busy, sync_all_day_events: false },
      next: busy,
      mappingCount: 0,
      destination: "Work",
    })
    expect(paused[0]).toBe("The rule stays paused. Preview it before enabling it again.")
    expect(paused).toContain("All-day source events will be added to Work on the next run.")
    const [degraded] = policyChangeConsequences({
      state: "degraded",
      current: busy,
      next: { ...busy, sync_all_day_events: false },
      mappingCount: 0,
      destination: "Work",
    })
    expect(degraded).toBe(
      "The rule stays stopped until recovery. Its recovery preview also validates the new policy.",
    )
  })

  it("mentions future projections when nothing is mapped yet", () => {
    const lines = policyChangeConsequences({
      state: "draft",
      current: busy,
      next: details,
      mappingCount: 0,
      destination: "Family",
    })
    expect(lines).toContain(
      "New projections in Family will show event titles, descriptions, and locations to anyone who can see it.",
    )
  })
})

describe("rule removal copy", () => {
  it("names the destructive effect", () => {
    expect(removalConfirmLabel("delete", 37)).toBe("Remove rule and delete 37 projections")
    expect(removalConfirmLabel("detach", 1)).toBe("Remove rule and keep 1 event")
    expect(removalConfirmLabel("delete", 0)).toBe("Remove rule")
    expect(removalConsequence("delete", 2, "Family")).toBe(
      "2 projections this rule wrote will be deleted from Family. Source events are not changed. Any event whose ownership cannot be verified is left in place. This cannot be undone.",
    )
    expect(removalConsequence("detach", 2, "Family")).toBe(
      "2 projections stay in Family as ordinary events that are no longer updated or deleted. This cannot be undone.",
    )
  })
})

describe("rule replacement copy", () => {
  it("names what happens to existing projections", () => {
    expect(replacementConfirmLabel("delete", 37)).toBe("Replace rule and delete 37 projections")
    expect(replacementConfirmLabel("detach", 1)).toBe("Replace rule and keep 1 event")
    expect(replacementConfirmLabel("delete", 0)).toBe("Replace rule")
  })
})

describe("state and outcome labels", () => {
  it("labels removal in progress", () => {
    expect(ruleStateLabel("disabled")).toBe("Removal incomplete")
    expect(ruleStateLabel("dry_run_validated")).toBe("Preview passed")
    expect(ruleStateLabel("some_new_state")).toBe("some new state")
  })

  it("summarizes outcomes without provider detail", () => {
    expect(runOutcomeSummary(null, "sync")).toBe("Not run yet")
    const base = {
      completed_at: "2026-09-28T10:00:00+00:00",
      succeeded: true,
      full_run: false,
      created: 2,
      updated: 1,
      deleted: 0,
      conflicts: 0,
      checked_mappings: 42,
      drift: 0,
      failure_kind: null,
    }
    expect(runOutcomeSummary(base, "sync")).toBe("Succeeded: 2 created, 1 updated, 0 deleted")
    expect(runOutcomeSummary({ ...base, conflicts: 1 }, "sync")).toBe(
      "Succeeded: 2 created, 1 updated, 0 deleted, 1 conflict",
    )
    expect(runOutcomeSummary(base, "reconciliation")).toBe("All 42 projections matched their sources")
    expect(runOutcomeSummary({ ...base, drift: 3 }, "reconciliation")).toBe(
      "3 of 42 projections differed from their sources; none were changed",
    )
    expect(runOutcomeSummary({ ...base, drift: 1 }, "reconciliation")).toBe(
      "1 of 42 projections differed from its source; it was not changed",
    )
    // A conflict is not drift: nothing was compared wrongly, one event was blocked.
    expect(runOutcomeSummary({ ...base, conflicts: 1 }, "reconciliation")).toBe(
      "Checked 42 projections: 1 conflict blocked",
    )
    expect(runOutcomeSummary({ ...base, drift: 2, conflicts: 1 }, "reconciliation")).toBe(
      "2 of 42 projections differed from their sources; none were changed. 1 conflict blocked",
    )
    expect(
      runOutcomeSummary({ ...base, succeeded: false, failure_kind: "authentication" }, "sync"),
    ).toBe("Failed: Google authorization expired")
    expect(
      runOutcomeSummary({ ...base, succeeded: false, failure_kind: "infrastructure" }, "sync"),
    ).toBe("Failed: Local synchronization failed")
  })
})

describe("rule removal outcome", () => {
  it("reports deleted and detached events", () => {
    expect(removalOutcome({ deleted: 3, detached: 0, conflicts: 0 }, "Family")).toEqual({
      attention: false,
      message: "The rule was removed. 3 projections were deleted from Family.",
    })
    expect(removalOutcome({ deleted: 0, detached: 1, conflicts: 0 }, "Family")).toEqual({
      attention: false,
      message: "The rule was removed. 1 event stays in Family as a Detached Event.",
    })
    expect(removalOutcome({ deleted: 0, detached: 0, conflicts: 0 }, "Family").message).toBe(
      "The rule was removed.",
    )
  })

  it("calls attention to events left because ownership could not be verified", () => {
    expect(removalOutcome({ deleted: 2, detached: 0, conflicts: 1 }, "Family")).toEqual({
      attention: true,
      message:
        "The rule was removed. 2 projections were deleted from Family. 1 event was left in Family because its ownership could not be verified. Review it in Activity under Blocked.",
    })
    expect(removalOutcome({ deleted: 0, detached: 0, conflicts: 2 }, "Family").message).toContain(
      "2 events were left in Family because their ownership could not be verified. Review them",
    )
  })
})
