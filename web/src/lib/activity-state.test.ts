import { describe, expect, it } from "vitest"

import dashboardSource from "../features/dashboard.tsx?raw"

describe("Activity view states", () => {
  it("keeps successful empty activity distinct from a recoverable request failure", () => {
    expect(dashboardSource).toContain("No activity yet")
    expect(dashboardSource).toContain("Activity is temporarily unavailable")
    expect(dashboardSource).toContain("activity.refetch()")
    expect(dashboardSource).toContain("incidents.refetch()")
  })

  it("names browser extensions as a cause when the request never reaches the service", () => {
    expect(dashboardSource).toContain("a browser extension such as a content blocker")
    expect(dashboardSource).not.toContain("The local service did not answer.")
  })

  it("keeps expired-session, server-error, and connectivity guidance on separate branches", () => {
    expect(dashboardSource).toMatch(
      /authenticationExpired\s*\?\s*"Your administrator session has expired\.[^"]*"\s*:\s*serviceFailed\s*\?\s*"The local service returned an error; try the request again\."\s*:\s*"The request did not reach the local service\./,
    )
  })
})
