import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"

import commandsSource from "../components/rule-commands.tsx?raw"
import ruleEndpointSource from "../components/rule-endpoint.tsx?raw"
import rulesSource from "../features/rules.tsx?raw"

describe("Directional Sync Rule recovery presentation", () => {
  it("shows account avatars and stops every rule that uses an account to reauthorize", () => {
    expect(ruleEndpointSource).toContain("avatarUrl={account?.avatar_url}")
    expect(rulesSource).toContain("<RuleEndpoint")
    expect(rulesSource).toContain('rule.state === "degraded" || unauthorized.length > 0')
    expect(rulesSource).toContain("rules.list.stoppedDisconnected")
    expect(commandsSource).toContain("ruleDetails.commands.reauthorize")
    const { t } = testI18n()
    expect(t("rules.list.stoppedDisconnected", { accounts: "dana@example.test" })).toContain("Synchronization stopped")
    expect(t("ruleDetails.commands.reauthorize")).toBe("Reauthorize account")
  })
})
