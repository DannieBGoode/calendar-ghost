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
