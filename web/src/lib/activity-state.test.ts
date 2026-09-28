import { describe, expect, it } from "vitest"

import dashboardSource from "../features/dashboard.tsx?raw"
import apiSource from "./api.ts?raw"

describe("Activity view states", () => {
  it("keeps successful empty activity distinct from a recoverable request failure", () => {
    expect(dashboardSource).toContain("No activity yet")
    expect(dashboardSource).toContain("Activity is temporarily unavailable")
    expect(dashboardSource).toContain("activity.refetch()")
    expect(dashboardSource).toContain("incidents.refetch()")
  })

  it("loads audit entries from a path that content blockers do not treat as tracking", () => {
    expect(apiSource).toContain('"/api/v1/audit-entries"')
    expect(apiSource).not.toContain("/api/v1/activity")
  })
})
