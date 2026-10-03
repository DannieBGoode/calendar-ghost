import { describe, expect, it } from "vitest"

import { accountSummary } from "./account-summary"

const connected = { state: "connected", rule_count: 1 }
const disconnected = { state: "disconnected", rule_count: 0 }

describe("accountSummary", () => {
  it("counts connected accounts quietly", () => {
    expect(accountSummary([connected])).toEqual({ text: "1 account connected", needsAttention: false, stopsRules: false })
    expect(accountSummary([connected, connected])).toEqual({
      text: "2 accounts connected",
      needsAttention: false,
      stopsRules: false,
    })
  })

  it("names the accounts that need reauthorization", () => {
    expect(accountSummary([connected, connected, disconnected])).toEqual({
      text: "2 accounts connected, 1 needs reauthorization",
      needsAttention: true,
      stopsRules: false,
    })
    expect(accountSummary([connected, disconnected, disconnected]).text).toBe(
      "1 account connected, 2 need reauthorization",
    )
  })

  it("says so when no account is connected", () => {
    expect(accountSummary([disconnected]).text).toBe("1 account disconnected, it needs reauthorization")
    expect(accountSummary([disconnected, disconnected]).text).toBe(
      "2 accounts disconnected, they need reauthorization",
    )
  })

  it("flags a disconnected account that stopped rules as urgent", () => {
    expect(accountSummary([connected, { state: "disconnected", rule_count: 2 }]).stopsRules).toBe(true)
  })
})
