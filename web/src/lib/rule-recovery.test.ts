import { describe, expect, it } from "vitest"

import commandsSource from "../components/rule-commands.tsx?raw"
import ruleEndpointSource from "../components/rule-endpoint.tsx?raw"
import rulesSource from "../features/rules.tsx?raw"

describe("Directional Sync Rule recovery presentation", () => {
  it("shows account avatars and stops every rule that uses a disconnected account", () => {
    expect(ruleEndpointSource).toContain("avatarUrl={account?.avatar_url}")
    expect(rulesSource).toContain("<RuleEndpoint")
    expect(rulesSource).toContain('rule.state === "degraded" || disconnected.length > 0')
    expect(rulesSource).toContain("Synchronization stopped")
    expect(commandsSource).toContain("Reauthorize in Settings")
  })
})
