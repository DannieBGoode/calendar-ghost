import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"
import type { RulePolicyPayload } from "./api"
import { responseConsequences, tentativeFact, tentativeHint, unansweredFact, unansweredHint } from "./invitation-responses"

const i18n = testI18n()

const marked: RulePolicyPayload = {
  privacy_policy: "busy_only",
  sync_all_day_events: true,
  tentative_events: "mark",
  unanswered_invitations: "as_tentative",
}

describe("invitation responses", () => {
  it("shows the tentative title each privacy policy writes", () => {
    expect(tentativeHint(i18n, marked)).toBe("Shown as “Busy (tentative)”.")
    expect(tentativeHint(i18n, { ...marked, privacy_policy: "copy_details" })).toBe(
      "Shown as “Maybe: ” and the event title, like “Maybe: Standup”.",
    )
    expect(tentativeHint(i18n, { ...marked, tentative_events: "sync" })).toBe("Shown the same as events you accepted.")
    expect(tentativeFact(i18n, { ...marked, tentative_events: "skip" })).toBe("Not synced")
    expect(tentativeFact(i18n, marked)).toBe("Synced as “Busy (tentative)”")
    expect(unansweredFact(i18n, { ...marked, unanswered_invitations: "wait" })).toBe("Not synced until answered")
    expect(unansweredFact(i18n, marked)).toBe("Synced as Maybe")
  })

  it("says unanswered invitations treated as Maybe are not synced when Maybe events are not", () => {
    const skipping = { ...marked, tentative_events: "skip" } as const
    expect(unansweredFact(i18n, skipping)).toBe("Not synced, like events you answered Maybe")
    expect(unansweredHint(i18n, skipping)).toBe(
      "Treated as Maybe, so they stay out of the destination too. Declined events are never synced.",
    )
    expect(unansweredHint(i18n, marked)).toBe("Declined events are never synced.")
  })

  it("says what changing the Maybe choice does", () => {
    expect(responseConsequences(i18n, marked, marked, "Work")).toEqual([])
    expect(responseConsequences(i18n, marked, { ...marked, tentative_events: "sync" }, "Work")).toEqual([
      "Events you answered Maybe will lose their tentative mark in Work on the next run.",
    ])
    expect(responseConsequences(i18n, { ...marked, tentative_events: "sync" }, marked, "Work")).toEqual([
      "Events you answered Maybe will be marked as tentative in Work on the next run.",
    ])
  })

  it("counts unanswered invitations as Maybe events when they are synced as Maybe", () => {
    expect(responseConsequences(i18n, marked, { ...marked, tentative_events: "skip" }, "Work")).toEqual([
      "Events you answered Maybe will be deleted from Work on the next run.",
      "Invitations you haven't answered will be deleted from Work on the next run.",
    ])
    const waiting = { ...marked, unanswered_invitations: "wait" } as const
    expect(responseConsequences(i18n, { ...waiting, tentative_events: "skip" }, waiting, "Work")).toEqual([
      "Events you answered Maybe will be added to Work on the next run.",
    ])
    expect(responseConsequences(i18n, waiting, marked, "Work")).toEqual([
      "Invitations you haven't answered will be added to Work as Maybe events on the next run.",
    ])
    expect(
      responseConsequences(i18n, { ...marked, tentative_events: "skip" }, { ...waiting, tentative_events: "skip" }, "Work"),
    ).toEqual([])
  })
})
