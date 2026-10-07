import { describe, expect, it } from "vitest"

import { testI18n } from "../i18n/testing"
import { accountSummary } from "./account-summary"

const connected = { state: "connected", rule_count: 1 }
const disconnected = { state: "disconnected", rule_count: 0 }

describe("accountSummary", () => {
  it("counts connected accounts quietly", () => {
    const i18n = testI18n()
    expect(accountSummary(i18n, [connected])).toEqual({
      text: "1 account connected",
      needsAttention: false,
      stopsRules: false,
    })
    expect(accountSummary(i18n, [connected, connected])).toEqual({
      text: "2 accounts connected",
      needsAttention: false,
      stopsRules: false,
    })
  })

  it("groups a large connected count by the locale", () => {
    const accounts = Array.from({ length: 1234 }, () => connected)
    expect(accountSummary(testI18n(), accounts).text).toBe("1,234 accounts connected")
  })

  it("names the accounts that need reauthorization", () => {
    const i18n = testI18n()
    expect(accountSummary(i18n, [connected, connected, disconnected])).toEqual({
      text: "2 accounts connected, 1 needs reauthorization",
      needsAttention: true,
      stopsRules: false,
    })
    expect(accountSummary(i18n, [connected, disconnected, disconnected]).text).toBe(
      "1 account connected, 2 need reauthorization",
    )
  })

  it("says so when no account is connected", () => {
    const i18n = testI18n()
    expect(accountSummary(i18n, [disconnected]).text).toBe("1 account needs reauthorization")
    expect(accountSummary(i18n, [disconnected, disconnected]).text).toBe("2 accounts need reauthorization")
  })

  it("flags a disconnected account that stopped rules as urgent", () => {
    expect(accountSummary(testI18n(), [connected, { state: "disconnected", rule_count: 2 }]).stopsRules).toBe(true)
  })

  it("counts a connected account Google stopped accepting as needing reauthorization", () => {
    const lapsed = { state: "connected", rule_count: 2, authorization_lapsed_at: "2026-10-05T09:00:00Z" }
    expect(accountSummary(testI18n(), [connected, connected, lapsed])).toEqual({
      text: "2 accounts connected, 1 needs reauthorization",
      needsAttention: true,
      stopsRules: true,
    })
  })
})
