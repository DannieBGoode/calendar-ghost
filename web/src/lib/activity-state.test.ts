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

describe("activity for removed rules", () => {
  it("explains why events of a removed rule cannot be looked up", () => {
    expect(activitySource).toContain("entryInspection(entry, ruleExists)")
    expect(activitySource).toContain("This rule was removed, so its events can no longer be looked up.")
  })
})
