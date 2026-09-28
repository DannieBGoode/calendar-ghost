import { describe, expect, it } from "vitest"

import ruleEndpointSource from "../components/rule-endpoint.tsx?raw"
import dashboardSource from "../features/dashboard.tsx?raw"

describe("Directional Sync Rule recovery presentation", () => {
  it("shows account avatars and stops every rule that uses a disconnected account", () => {
    expect(ruleEndpointSource).toContain("avatarUrl={account?.avatar_url}")
    expect(dashboardSource).toContain(
      'rule.state === "degraded" || disconnectedAccounts.length > 0',
    )
    expect(dashboardSource).toContain("Synchronization stopped.")
    expect(dashboardSource).toContain("Reauthorize in Settings")
  })
})
