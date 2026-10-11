import { describe, expect, it } from "vitest"

import { testI18n } from "../i18n/testing"
import type { CalendarProvider, InstallationHint, ServerProblem } from "./api"
import { causeOf, causeText, hintText, howToFixUrl, isAdministratorCause, retryTiming } from "./causes"

const i18n = testI18n()
const NOW = Date.parse("2026-10-10T12:00:00Z")

const problem = (cause: ServerProblem["cause"], last_tried_at: string | null = null): ServerProblem => ({
  kind: "stopped",
  rule_id: "rule-1",
  summary: "Stopped syncing",
  since: null,
  message: null,
  cause,
  last_tried_at,
  provider: "google",
})

// A provider as GET /api/v1/providers describes it, with synthetic sections of the guide.
const provider: CalendarProvider = {
  kind: "google",
  display_name: "Example",
  connect_url: "/api/v1/oauth/example/start",
  redirect_uri: "http://localhost:8000/api/v1/oauth/example/callback",
  cause_anchors: { api_disabled: "the-api-is-off", access_revoked: "the-grant-is-refused" },
}

describe("causeOf", () => {
  it("reads a problem's Cause, and one this version does not know as unknown", () => {
    expect(causeOf(problem("api_disabled"))).toBe("api_disabled")
    expect(causeOf(problem(null))).toBeNull()
    expect(causeOf(problem("a_cause_from_a_later_server" as ServerProblem["cause"]))).toBe("unknown")
  })
})

describe("isAdministratorCause", () => {
  it("is true only for what the installation's registration with its provider fixes", () => {
    expect(isAdministratorCause("api_disabled")).toBe(true)
    expect(isAdministratorCause("quota_exceeded")).toBe(true)
    expect(isAdministratorCause("oauth_client_invalid")).toBe(true)
    for (const cause of ["access_revoked", "calendar_forbidden", "calendar_not_found", "rate_limited", "temporary", "unknown"] as const) {
      expect(isAdministratorCause(cause)).toBe(false)
    }
    expect(isAdministratorCause(null)).toBe(false)
  })
})

describe("causeText", () => {
  it("says the likely cause in plain words", () => {
    expect(causeText(i18n, "api_disabled")).toBe(
      "Likely cause: the Google Calendar API is turned off for this installation.",
    )
    expect(causeText(i18n, "unknown")).toBe(
      "Likely cause: Google refused for a reason Calendar Ghost does not recognize.",
    )
  })
})

describe("howToFixUrl", () => {
  it("links an administrator's Cause to its provider's section of the troubleshooting guide, and nothing else", () => {
    expect(howToFixUrl("api_disabled", provider)).toBe("https://calendarghost.com/docs/troubleshooting#the-api-is-off")
    // A User's own Cause has a section, but the administrator is never sent to fix it.
    expect(howToFixUrl("access_revoked", provider)).toBeNull()
    expect(howToFixUrl("quota_exceeded", provider)).toBeNull()
    expect(howToFixUrl("api_disabled", null)).toBeNull()
    expect(howToFixUrl(null, provider)).toBeNull()
  })
})

describe("retryTiming", () => {
  it("says when a cause that fixes itself was last tried and is tried again", () => {
    const waiting = problem("rate_limited", "2026-10-10T11:56:00Z")

    expect(retryTiming(i18n, waiting, "2026-10-10T12:03:00Z", NOW)).toBe("Last tried 4 minutes ago. Tries again in 3 minutes.")
    expect(retryTiming(i18n, waiting, null, NOW)).toBe("Last tried 4 minutes ago.")
    expect(retryTiming(i18n, problem("temporary"), null, NOW)).toBeNull()
    expect(retryTiming(i18n, problem("api_disabled", "2026-10-10T11:56:00Z"), null, NOW)).toBeNull()
  })
})

describe("hintText", () => {
  const hint = (kind: InstallationHint["kind"], cause: InstallationHint["cause"]): InstallationHint => ({
    kind,
    cause,
    users: 3,
    anchor: "anchor",
    provider: "google",
  })

  it("says each pattern in one sentence with how many people it affects", () => {
    expect(hintText(i18n, hint("shared_cause", "api_disabled"))).toBe(
      "3 people are affected because the Google Calendar API is turned off for this installation.",
    )
    expect(hintText(i18n, { ...hint("shared_cause", "api_disabled"), users: 1 })).toBe(
      "1 person is affected because the Google Calendar API is turned off for this installation.",
    )
    expect(hintText(i18n, hint("testing_mode", "access_revoked"))).toBe(
      "3 people lost Google about 7 days after connecting, which usually means the Google OAuth app is in Testing mode.",
    )
    expect(hintText(i18n, hint("unrecognized", "unknown"))).toBe(
      "3 people failed for a reason Calendar Ghost does not recognize. The service logs name Google's reason.",
    )
  })
})
