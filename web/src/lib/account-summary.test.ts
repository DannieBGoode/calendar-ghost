import { describe, expect, it } from "vitest"

import { accountSummary } from "./account-summary"

const connected = { state: "connected" }
const disconnected = { state: "disconnected" }

describe("accountSummary", () => {
  it("counts connected accounts quietly", () => {
    expect(accountSummary([connected])).toEqual({ text: "1 account connected", needsAttention: false })
    expect(accountSummary([connected, connected])).toEqual({
      text: "2 accounts connected",
      needsAttention: false,
    })
  })

  it("names the accounts that need reauthorization", () => {
    expect(accountSummary([connected, connected, disconnected])).toEqual({
      text: "2 accounts connected, 1 needs reauthorization",
      needsAttention: true,
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
})
