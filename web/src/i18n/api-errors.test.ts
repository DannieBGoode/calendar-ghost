import { describe, expect, it } from "vitest"

import { ApiError, UnreadableResponseError } from "@/lib/api"

import { apiErrorMessage, providerName } from "./api-errors"
import { testI18n } from "./testing"

const i18n = testI18n()
const coded = (code: string, params: ApiError["params"] = {}, detail: string | null = "English detail") =>
  new ApiError(detail ?? "x", 409, detail, { code, params })

describe("apiErrorMessage", () => {
  it("translates a server code", () => {
    expect(apiErrorMessage(i18n, coded("storage_busy"))).toBe(
      "Old Activity was cleared, but its space could not be reclaimed while a rule is synchronizing. Try again when it finishes.",
    )
    expect(apiErrorMessage(i18n, coded("rule_execution_unavailable"))).toBe(
      "Running rules needs a configured calendar provider and the installation master key.",
    )
    expect(apiErrorMessage(i18n, coded("invalid_state_transition"))).toBe(
      "This rule cannot change to that state right now. Reload and try again.",
    )
  })

  it("fills server params and names the provider", () => {
    const error = coded("removal_interrupted", { processed: 2, remaining: 3, total: 5, provider: "google", kind: "rate_limit" })
    expect(apiErrorMessage(i18n, error)).toBe(
      "Removal stopped after 2 of 5 projections because Google Calendar reported a problem. Retry to continue.",
    )
    expect(apiErrorMessage(i18n, coded("provider_failed", { provider: null, kind: "temporary" }))).toBe(
      "The calendar provider reported a problem. Try again shortly.",
    )
  })

  it("uses the specific validation message when the reason is known, the general one otherwise", () => {
    const tooShort = coded("invalid_request", { field: "password", reason: "string_too_short", min_length: 12 })
    expect(apiErrorMessage(i18n, tooShort)).toBe("Use at least 12 characters.")
    const oneCharacter = coded("invalid_request", { field: "name", reason: "string_too_short", min_length: 1 })
    expect(apiErrorMessage(i18n, oneCharacter)).toBe("Use at least 1 character.")
    const tooLong = coded("invalid_request", { field: "name", reason: "string_too_long", max_length: 80 })
    expect(apiErrorMessage(i18n, tooLong)).toBe("Use at most 80 characters.")
    const oneAtMost = coded("invalid_request", { field: "name", reason: "string_too_long", max_length: 1 })
    expect(apiErrorMessage(i18n, oneAtMost)).toBe("Use at most 1 character.")
    const other = coded("invalid_request", { field: "privacy_policy", reason: "literal_error" })
    expect(apiErrorMessage(i18n, other)).toBe("Some of the information is not valid. Check it and try again.")
  })

  it("shows the server's detail for an unknown code or a missing param, then a generic message", () => {
    expect(apiErrorMessage(i18n, coded("brand_new"))).toBe("English detail")
    expect(apiErrorMessage(i18n, coded("removal_interrupted", {}, "removal stopped"))).toBe("removal stopped")
    expect(apiErrorMessage(i18n, coded("brand_new", {}, null))).toBe("The request could not be completed.")
    expect(apiErrorMessage(i18n, new ApiError("custom detail", 500, "custom detail"))).toBe("custom detail")
    expect(apiErrorMessage(i18n, new ApiError("x", 422, null))).toBe("The request could not be completed.")
  })

  it("never shows an unfilled placeholder outside tests", () => {
    // Production leaves a missing `{name}` in place instead of throwing; the detail reads better.
    const production = { ...i18n, t: ((key, params) => (key === "common.apiError.removal_interrupted" ? "{processed} of {total}" : i18n.t(key, params))) as typeof i18n.t }
    expect(apiErrorMessage(production, coded("removal_interrupted", {}, "removal stopped"))).toBe("removal stopped")
  })

  it("describes an unreadable response", () => {
    expect(apiErrorMessage(i18n, new UnreadableResponseError("x", 200))).toBe("The service returned an unreadable response.")
  })

  it("describes a network failure", () => {
    expect(apiErrorMessage(i18n, new TypeError("Failed to fetch"))).toBe("The browser could not reach Calendar Ghost.")
  })

  it("falls back to a generic message for anything else", () => {
    expect(apiErrorMessage(i18n, new Error("boom"))).toBe("The request could not be completed.")
  })
})

describe("providerName", () => {
  it("names known providers and falls back neutrally", () => {
    expect(providerName(i18n, "google")).toBe("Google Calendar")
    expect(providerName(i18n, null)).toBe("the calendar provider")
    expect(providerName(i18n, "outlook")).toBe("the calendar provider")
  })
})
