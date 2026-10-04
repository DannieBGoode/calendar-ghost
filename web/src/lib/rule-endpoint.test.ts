import { describe, expect, it } from "vitest"

import ruleEndpointSource from "../components/rule-endpoint.tsx?raw"
import { testI18n } from "@/i18n/testing"
import { ruleEndpointLabel } from "./rule-endpoint"

const account = { email: "person@example.test" }
const i18n = testI18n()

describe("ruleEndpointLabel", () => {
  it("names a secondary calendar and identifies its account by email", () => {
    const calendars = [{ id: "7cf2710909@group.calendar.google.com", summary: "Family" }]
    expect(ruleEndpointLabel(i18n, { calendar_id: "7cf2710909@group.calendar.google.com" }, account, calendars)).toEqual({
      calendar: "Family",
      account: "person@example.test",
    })
  })

  it("does not repeat the email for a primary calendar named after it", () => {
    const calendars = [{ id: "person@example.test", summary: "person@example.test" }]
    expect(ruleEndpointLabel(i18n, { calendar_id: "person@example.test" }, account, calendars)).toEqual({
      calendar: "person@example.test",
      account: "Primary calendar",
    })
  })

  it("never shows an opaque calendar identifier when the name is unavailable", () => {
    expect(ruleEndpointLabel(i18n, { calendar_id: "7cf2710909@group.calendar.google.com" }, account, undefined)).toEqual({
      calendar: "Secondary calendar",
      account: "person@example.test",
    })
    expect(ruleEndpointLabel(i18n, { calendar_id: "person@example.test" }, account, undefined)).toEqual({
      calendar: "person@example.test",
      account: "Primary calendar",
    })
  })

  it("shows the name recorded when Google last listed the calendar until it lists them again", () => {
    const endpoint = { calendar_id: "7cf2710909@group.calendar.google.com", calendar_name: "Family" }
    expect(ruleEndpointLabel(i18n, endpoint, account, undefined)).toEqual({
      calendar: "Family",
      account: "person@example.test",
    })
    const renamed = [{ id: "7cf2710909@group.calendar.google.com", summary: "Household" }]
    expect(ruleEndpointLabel(i18n, endpoint, account, renamed).calendar).toBe("Household")
  })

  it("falls back safely when the account is unknown", () => {
    expect(ruleEndpointLabel(i18n, { calendar_id: "abc@group.calendar.google.com" }, undefined, undefined)).toEqual({
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
