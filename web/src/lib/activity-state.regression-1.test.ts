// Regression: ISSUE-001 — Activity blamed a restarting service when a content blocker stopped the request
// Found by /qa on 2026-09-28
import { describe, expect, it } from "vitest"

import dashboardSource from "../features/dashboard.tsx?raw"

describe("Activity request failure guidance", () => {
  it("names browser extensions as a cause when the request never reaches the service", () => {
    expect(dashboardSource).toContain("The request did not reach the local service.")
    expect(dashboardSource).toContain("a browser extension such as a content blocker")
    expect(dashboardSource).not.toContain("The local service did not answer.")
  })

  it("keeps the expired-session guidance separate from connectivity failures", () => {
    expect(dashboardSource).toContain(
      "Your administrator session has expired. Sign in again to view operational activity.",
    )
  })
})
