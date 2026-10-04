import { describe, expect, it } from "vitest"

import { incidentText } from "./incident-text"
import { testI18n } from "./testing"

const i18n = testI18n()
const legacy = { summary: "Stored English summary", message: null }

describe("incidentText", () => {
  it("renders provider failures", () => {
    expect(incidentText(i18n, { summary: "", message: { code: "provider_failure", params: { kind: "rate_limit", provider: "google" } } }))
      .toBe("Google Calendar is limiting requests")
    expect(incidentText(i18n, { summary: "", message: { code: "provider_failure", params: { kind: "temporary", provider: null } } }))
      .toBe("The calendar provider is temporarily unavailable")
    expect(incidentText(i18n, { summary: "", message: { code: "provider_failure", params: { kind: "authentication", provider: "google" } } }))
      .toBe("Authorization for Google Calendar expired")
  })

  it("renders blocked events with plural rules", () => {
    expect(incidentText(i18n, { summary: "", message: { code: "events_still_blocked", params: { count: 1 } } }))
      .toBe("1 event could not be synced and was still blocked at the daily check.")
    expect(incidentText(i18n, { summary: "", message: { code: "events_still_blocked", params: { count: 3 } } }))
      .toBe("3 events could not be synced and were still blocked at the daily check.")
  })

  it("renders removal failures", () => {
    expect(incidentText(i18n, { summary: "", message: { code: "removal_stopped", params: { kind: "authorization", provider: "google" } } }))
      .toBe("Rule Removal stopped: Access to Google Calendar was denied")
  })

  it("uses the stored summary for legacy, unknown, or malformed messages", () => {
    expect(incidentText(i18n, legacy)).toBe("Stored English summary")
    expect(incidentText(i18n, { ...legacy, message: { code: "new_code", params: {} } })).toBe("Stored English summary")
    expect(incidentText(i18n, { ...legacy, message: { code: "provider_failure", params: { kind: "odd" } } })).toBe("Stored English summary")
    expect(incidentText(i18n, { ...legacy, message: { code: "removal_stopped", params: {} } })).toBe("Stored English summary")
    expect(incidentText(i18n, { ...legacy, message: { code: "events_still_blocked", params: {} } })).toBe("Stored English summary")
  })
})
