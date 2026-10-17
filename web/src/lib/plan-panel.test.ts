import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"
import type { PlanLimits } from "@/lib/api"
import { planAllowsSentence, planPanelMeta } from "@/lib/plan-panel"

const i18n = testI18n()

const FREE: PlanLimits = { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" }
const UNLIMITED: PlanLimits = { rules: null, connected_accounts: null, integration_tokens: null, sync_interval: "instant" }

describe("A plan's panel", () => {
  it.each([
    [FREE, "1 active rule, 1 calendar account, no Integration Tokens, every 5 minutes."],
    [{ ...FREE, rules: 5, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" }, "5 active rules, 3 calendar accounts, 2 Integration Tokens, with Instant sync."],
    [UNLIMITED, "Unlimited, with Instant sync."],
    [{ ...UNLIMITED, sync_interval: "60_minutes" }, "Unlimited, every hour."],
    // A sentence never starts in lower case, whichever count has no limit.
    [{ ...FREE, rules: null }, "Unlimited active rules, 1 calendar account, no Integration Tokens, every 5 minutes."],
    [{ ...FREE, connected_accounts: null, integration_tokens: null }, "1 active rule, unlimited calendar accounts, unlimited Integration Tokens, every 5 minutes."],
  ] as const)("says what a plan allows in one sentence: %j", (limits, sentence) => {
    expect(planAllowsSentence(i18n, limits)).toBe(sentence)
  })

  it("says who has the plan before what it allows", () => {
    expect(planPanelMeta(i18n, { name: "Free", people: 2, limits: FREE })).toBe(
      "2 people have Free. 1 active rule, 1 calendar account, no Integration Tokens, every 5 minutes.",
    )
    expect(planPanelMeta(i18n, { name: "Pro", people: 1, limits: UNLIMITED })).toBe("1 person has Pro. Unlimited, with Instant sync.")
    expect(planPanelMeta(i18n, { name: "Spare", people: 0, limits: UNLIMITED })).toBe("Nobody has Spare yet. Unlimited, with Instant sync.")
  })
})
