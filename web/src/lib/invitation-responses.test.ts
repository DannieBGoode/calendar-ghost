import { describe, expect, it } from "vitest"

import type { RulePolicyPayload } from "./api"
import { responseConsequences, tentativeFact, tentativeHint, unansweredFact } from "./invitation-responses"

const marked: RulePolicyPayload = {
  privacy_policy: "busy_only",
  sync_all_day_events: true,
  tentative_events: "mark",
  unanswered_invitations: "as_tentative",
}

describe("invitation responses", () => {
  it("shows the tentative title each privacy policy writes", () => {
    expect(tentativeHint(marked)).toBe("Shown as “Busy (tentative)”.")
    expect(tentativeHint({ ...marked, privacy_policy: "copy_details" })).toBe(
      "Shown as “Maybe: ” and the event title, like “Maybe: Standup”.",
    )
    expect(tentativeHint({ ...marked, tentative_events: "sync" })).toBe("Shown the same as events you accepted.")
    expect(tentativeFact({ ...marked, tentative_events: "skip" })).toBe("Not synced")
    expect(tentativeFact(marked)).toBe("Synced as “Busy (tentative)”")
    expect(unansweredFact("wait")).toBe("Not synced until answered")
  })

  it("says what changing the Maybe choice does", () => {
    expect(responseConsequences(marked, marked, "Work")).toEqual([])
    expect(responseConsequences(marked, { ...marked, tentative_events: "sync" }, "Work")).toEqual([
      "Events you answered Maybe will lose their tentative mark in Work on the next run.",
    ])
    expect(responseConsequences({ ...marked, tentative_events: "sync" }, marked, "Work")).toEqual([
      "Events you answered Maybe will be marked as tentative in Work on the next run.",
    ])
  })

  it("counts unanswered invitations as Maybe events when they are synced as Maybe", () => {
    expect(responseConsequences(marked, { ...marked, tentative_events: "skip" }, "Work")).toEqual([
      "Events you answered Maybe will be deleted from Work on the next run.",
      "Invitations you haven't answered will be deleted from Work on the next run.",
    ])
    const waiting = { ...marked, unanswered_invitations: "wait" } as const
    expect(responseConsequences({ ...waiting, tentative_events: "skip" }, waiting, "Work")).toEqual([
      "Events you answered Maybe will be added to Work on the next run.",
    ])
    expect(responseConsequences(waiting, marked, "Work")).toEqual([
      "Invitations you haven't answered will be added to Work as Maybe events on the next run.",
    ])
    expect(responseConsequences({ ...marked, tentative_events: "skip" }, { ...waiting, tentative_events: "skip" }, "Work")).toEqual([])
  })
})
