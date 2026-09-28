import { describe, expect, it } from "vitest"

import dashboardSource from "../features/dashboard.tsx?raw"
import { ruleEndpointLabel } from "./rule-endpoint"

const account = { email: "daniel@example.com" }

describe("ruleEndpointLabel", () => {
  it("names a secondary calendar and identifies its account by email", () => {
    const calendars = [{ id: "7cf2710909@group.calendar.google.com", summary: "Family" }]
    expect(ruleEndpointLabel("7cf2710909@group.calendar.google.com", account, calendars)).toEqual({
      calendar: "Family",
      account: "daniel@example.com",
    })
  })

  it("does not repeat the email for a primary calendar named after it", () => {
    const calendars = [{ id: "daniel@example.com", summary: "daniel@example.com" }]
    expect(ruleEndpointLabel("daniel@example.com", account, calendars)).toEqual({
      calendar: "daniel@example.com",
      account: "Primary calendar",
    })
  })

  it("never shows an opaque calendar identifier when the name is unavailable", () => {
    expect(ruleEndpointLabel("7cf2710909@group.calendar.google.com", account, undefined)).toEqual({
      calendar: "Secondary calendar",
      account: "daniel@example.com",
    })
    expect(ruleEndpointLabel("daniel@example.com", account, undefined)).toEqual({
      calendar: "daniel@example.com",
      account: "Primary calendar",
    })
  })

  it("falls back safely when the account is unknown", () => {
    expect(ruleEndpointLabel("abc@group.calendar.google.com", undefined, undefined)).toEqual({
      calendar: "Secondary calendar",
      account: "Unknown account",
    })
  })
})

describe("rule endpoint presentation", () => {
  it("renders calendar names rather than raw calendar identifiers", () => {
    expect(dashboardSource).toContain("ruleEndpointLabel(")
    expect(dashboardSource).not.toContain("<span>{calendarId}</span>")
  })
})
