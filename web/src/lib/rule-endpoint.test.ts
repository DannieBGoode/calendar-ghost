import { describe, expect, it } from "vitest"

import ruleEndpointSource from "../components/rule-endpoint.tsx?raw"
import { ruleEndpointLabel } from "./rule-endpoint"

const account = { email: "person@example.test" }

describe("ruleEndpointLabel", () => {
  it("names a secondary calendar and identifies its account by email", () => {
    const calendars = [{ id: "7cf2710909@group.calendar.google.com", summary: "Family" }]
    expect(ruleEndpointLabel("7cf2710909@group.calendar.google.com", account, calendars)).toEqual({
      calendar: "Family",
      account: "person@example.test",
    })
  })

  it("does not repeat the email for a primary calendar named after it", () => {
    const calendars = [{ id: "person@example.test", summary: "person@example.test" }]
    expect(ruleEndpointLabel("person@example.test", account, calendars)).toEqual({
      calendar: "person@example.test",
      account: "Primary calendar",
    })
  })

  it("never shows an opaque calendar identifier when the name is unavailable", () => {
    expect(ruleEndpointLabel("7cf2710909@group.calendar.google.com", account, undefined)).toEqual({
      calendar: "Secondary calendar",
      account: "person@example.test",
    })
    expect(ruleEndpointLabel("person@example.test", account, undefined)).toEqual({
      calendar: "person@example.test",
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
    expect(ruleEndpointSource).toContain("ruleEndpointLabel(")
    expect(ruleEndpointSource).not.toContain("<span>{calendarId}</span>")
  })
})
