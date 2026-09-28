import { describe, expect, it } from "vitest"

import dashboardSource from "../features/dashboard.tsx?raw"

describe("Activity view states", () => {
  it("keeps successful empty activity distinct from a recoverable request failure", () => {
    expect(dashboardSource).toContain("No activity yet")
    expect(dashboardSource).toContain("Activity is temporarily unavailable")
    expect(dashboardSource).toContain("activity.refetch()")
    expect(dashboardSource).toContain("incidents.refetch()")
  })
})
