import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"

import type { CalendarProvider, Incident } from "@/lib/api"
import {
  incidentClosedAt,
  incidentDetail,
  incidentDuration,
  incidentResolution,
  openIncidentCount,
} from "@/lib/incidents"

const i18n = testI18n()
// A provider as GET /api/v1/providers describes it, with a synthetic section of the guide.
const GOOGLE: CalendarProvider = {
  kind: "google",
  display_name: "Google",
  connect_url: "/api/v1/oauth/google/start",
  redirect_uri: "http://localhost:8000/api/v1/oauth/google/callback",
  cause_anchors: { api_disabled: "the-google-calendar-api-is-turned-off" },
}
const ADMINISTRATOR = { administrator: true, providers: [GOOGLE] }
const USER = { administrator: false, providers: [GOOGLE] }

function incident(overrides: Partial<Incident> = {}): Incident {
  return {
    id: "incident-1",
    rule_id: "rule-1",
    category: "temporary",
    state: "open",
    summary: "Google Calendar is temporarily unavailable",
    opened_at: "2026-09-28T18:00:00Z",
    updated_at: "2026-09-28T18:30:00Z",
    resolved_at: null,
    resolution: null,
    account_id: "failed-account",
    message: null,
    cause: null,
    step: "wait",
    provider: "google",
    cursor: "cursor",
    ...overrides,
  }
}

describe("incident steps", () => {
  // The server decides the step (ADR 0033); the Web UI words it and offers its one button.
  it.each([
    ["reauthorize", "Nothing is written until", { kind: "settings", label: "Reauthorize in Settings", accountId: "failed-account" }],
    ["recover_rule", "Calendar access is renewed", { kind: "rule", ruleId: "rule-1", label: "Recover this rule" }],
    ["review_rule", "The rule is stopped", { kind: "rule", ruleId: "rule-1", label: "Review this rule" }],
    ["see_blocked", "The rest of the rule keeps syncing", { kind: "blocked", ruleId: "rule-1", label: "See blocked events" }],
    ["wait", "Nothing to do now", null],
    ["administrator", "You fix this as the administrator", null],
  ] as const)("words the %s step", (step, detail, action) => {
    const shown = incidentDetail(i18n, incident({ step }), ADMINISTRATOR)
    expect(shown.explanation).toContain(detail)
    expect(shown.step).toEqual(action)
  })

  it("offers a resolved incident's rule history and says how it closed", () => {
    const resolved = incident({ state: "resolved", resolution: "sync_succeeded", step: "see_history" })
    expect(incidentDetail(i18n, resolved, ADMINISTRATOR)).toMatchObject({
      explanation: "Resolved by a successful sync.",
      step: { kind: "history", ruleId: "rule-1", label: "See what the rule did" },
      fixUrl: null,
    })
  })

  it("offers nothing without a step, such as for a rule since removed", () => {
    expect(incidentDetail(i18n, incident({ step: null }), ADMINISTRATOR)).toMatchObject({ explanation: null, step: null })
  })

  it("never tells anyone else which administrator's cause it is, or that an administrator fixes it", () => {
    const disabled = incident({ cause: "api_disabled", step: "administrator", account_id: "account-1" })
    expect(incidentDetail(i18n, disabled, USER)).toEqual({
      explanation: expect.stringContaining("Google Calendar is not available to Calendar Ghost right now") as string,
      cause: null,
      step: { kind: "settings", label: "Check access in Settings", accountId: "account-1" },
      fixUrl: null,
    })
  })

  it("links an administrator's cause to how to fix it while the incident is open", () => {
    const disabled = incident({ cause: "api_disabled", step: "administrator" })
    expect(incidentDetail(i18n, disabled, ADMINISTRATOR).fixUrl).toMatch(/#the-google-calendar-api-is-turned-off$/)
    expect(incidentDetail(i18n, { ...disabled, state: "resolved" }, ADMINISTRATOR).fixUrl).toBeNull()
  })

  it("names the provider whose registration fails, in its own words", () => {
    const expired = incident({ cause: "oauth_client_invalid", step: "administrator", provider: "outlook" })
    expect(incidentDetail(i18n, expired, ADMINISTRATOR).explanation).toBe(
      "You fix this as the administrator, in the Microsoft Entra admin center.",
    )
    expect(incidentDetail(i18n, expired, USER).explanation).toBe(
      "Outlook is not available to Calendar Ghost right now. To try again, choose Check access on your Microsoft account in Settings. Events already synced stay where they are.",
    )
    // Microsoft is not configured here, so there is no section to link.
    expect(incidentDetail(i18n, expired, ADMINISTRATOR).fixUrl).toBeNull()
  })
})

describe("resolved incidents", () => {
  it("says a removal closed an incident rather than claiming it was fixed", () => {
    expect(incidentResolution(i18n, incident({ state: "resolved", resolution: "rule_removed" }))).toBe(
      "Closed when the rule was removed.",
    )
    expect(incidentResolution(i18n, incident({ state: "resolved", resolution: "sync_succeeded" }))).toBe(
      "Resolved by a successful sync.",
    )
    expect(incidentResolution(i18n, incident({ state: "resolved", resolution: "blocks_cleared" }))).toMatch(
      /daily check/,
    )
  })

  it("claims no reason for incidents resolved before reasons were recorded", () => {
    const legacy = incident({ state: "resolved" })
    expect(incidentResolution(i18n, legacy)).toBeNull()
    expect(incidentClosedAt(legacy)).toBe(legacy.updated_at)
    expect(incidentClosedAt(incident({ resolved_at: "2026-09-29T08:00:00Z" }))).toBe("2026-09-29T08:00:00Z")
  })

  it("counts only the incidents still open, as the Incidents tab shows", () => {
    const open = incident({ id: "open" })
    const resolved = incident({ id: "resolved", state: "resolved", resolution: "rule_removed" })
    expect(openIncidentCount([open, resolved])).toBe(1)
  })

  it("says how long a resolved incident stayed open, to the nearest unit", () => {
    const closedAfter = (resolvedAt: string) => incidentDuration(incident({ state: "resolved", resolved_at: resolvedAt }))
    expect(incidentDuration(incident())).toBeNull()
    expect(closedAfter("2026-09-28T18:00:40Z")).toEqual({ unit: "moment", count: 0 })
    expect(closedAfter("2026-09-28T18:45:00Z")).toEqual({ unit: "minute", count: 45 })
    expect(closedAfter("2026-09-28T20:40:00Z")).toEqual({ unit: "hour", count: 3 })
    expect(closedAfter("2026-10-01T06:00:00Z")).toEqual({ unit: "day", count: 3 })
  })

  it("leaves out a cause Calendar Ghost does not recognise", () => {
    const unknown = incident({ cause: "unknown" })
    const limited = incident({ cause: "rate_limited" })
    expect(incidentDetail(i18n, unknown, ADMINISTRATOR).cause).toBeNull()
    expect(incidentDetail(i18n, limited, ADMINISTRATOR).cause).toBe("rate_limited")
  })
})
