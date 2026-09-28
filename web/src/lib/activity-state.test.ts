import { describe, expect, it } from "vitest"

import activitySource from "../features/activity.tsx?raw"

describe("Activity view states", () => {
  it("keeps successful empty activity distinct from a recoverable request failure", () => {
    expect(activitySource).toContain("No activity yet")
    expect(activitySource).toContain("Activity is temporarily unavailable")
    expect(activitySource).toContain("activity.refetch()")
    expect(activitySource).toContain("incidents.refetch()")
  })
})

describe("Activity filters", () => {
  it("keeps the page and its filters on screen while another rule or filter loads", () => {
    expect(activitySource).toContain("placeholderData: keepPreviousData")
    expect(activitySource).toContain("aria-busy={updating}")
  })
})

describe("activity for removed rules", () => {
  it("explains why events of a removed rule cannot be looked up", () => {
    expect(activitySource).toContain("entryInspection(entry, exists)")
    expect(activitySource).toContain("REMOVED_RULE_LOOKUP")
    expect(activitySource).toContain("eventLookupFailure(event.error)")
  })
})
