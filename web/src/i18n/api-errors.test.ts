import { describe, expect, it, vi } from "vitest"

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

  it("words a plan's refusals with the numbers the server sends", () => {
    const rules = (limit: number) => coded("plan_limit_reached", { reason: "rules", limit, count: limit })
    expect(apiErrorMessage(i18n, rules(1))).toBe("Your plan lets 1 rule sync. Pause or remove it to start this rule.")
    expect(apiErrorMessage(i18n, rules(3))).toBe("Your plan lets 3 rules sync. Pause or remove one to start this rule.")
    const tokens = (limit: number) => coded("plan_limit_reached", { reason: "integration_tokens", limit, count: limit })
    // A Plan that includes no tokens says so, never "0 Integration Tokens".
    expect(apiErrorMessage(i18n, tokens(0))).toBe(
      "Your plan does not include integration tokens. To get one, ask your administrator.",
    )
    expect(apiErrorMessage(i18n, tokens(1))).toBe(
      "Your plan allows 1 integration token, and it is in use. Revoke it to issue another.",
    )
    expect(apiErrorMessage(i18n, tokens(2))).toBe(
      "Your plan allows 2 integration tokens, and all are in use. Revoke one to issue another.",
    )
    // A limit of none with no message of its own reads as any other.
    expect(apiErrorMessage(i18n, rules(0))).toBe("Your plan lets 0 rules sync. Pause or remove one to start this rule.")
    const later = coded("plan_limit_reached", { reason: "a_later_resource", limit: 2, count: 2 })
    expect(apiErrorMessage(i18n, later)).toBe(
      "Your plan's limit is reached. Settings, Your account, Your plan shows what it allows.",
    )
    expect(apiErrorMessage(i18n, coded("plan_in_use", { people: 1, count: 1 }))).toBe(
      "1 person has this plan. Give them another plan before you remove it.",
    )
    expect(apiErrorMessage(i18n, coded("plan_in_use", { people: 2, count: 2 }))).toBe(
      "2 people have this plan. Give them another plan before you remove it.",
    )
    expect(apiErrorMessage(i18n, coded("invalid_plan", { reason: "key" }))).toBe(
      "Use 1 to 32 lower-case letters, digits, and hyphens for the key, starting with a letter or digit.",
    )
    expect(apiErrorMessage(i18n, coded("plans_need_default"))).toBe(
      "Plans can't be on without a default plan. Choose another default instead.",
    )
  })

  it("shows the server's detail for an unknown code or a missing param, then a generic message", () => {
    expect(apiErrorMessage(i18n, coded("brand_new"))).toBe("English detail")
    expect(apiErrorMessage(i18n, coded("removal_interrupted", {}, "removal stopped"))).toBe("removal stopped")
    expect(apiErrorMessage(i18n, coded("brand_new", {}, null))).toBe("The request could not be completed.")
    expect(apiErrorMessage(i18n, new ApiError("custom detail", 500, "custom detail"))).toBe("custom detail")
    expect(apiErrorMessage(i18n, new ApiError("x", 422, null))).toBe("The request could not be completed.")
  })

  it("shows the server's detail in production when the server left out one of a message's params", () => {
    // Production fills a missing param with nothing, so the message must not be used at all.
    vi.stubEnv("MODE", "production")
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined)
    try {
      const production = testI18n()
      expect(apiErrorMessage(production, coded("removal_interrupted", {}, "removal stopped"))).toBe("removal stopped")
      expect(apiErrorMessage(production, coded("plan_name_taken", {}, "That name is taken"))).toBe("That name is taken")
      // Without its length, a too-short value gets the general validation message.
      const tooShort = coded("invalid_request", { field: "password", reason: "string_too_short" })
      expect(apiErrorMessage(production, tooShort)).toBe("Some of the information is not valid. Check it and try again.")
      const rules = coded("plan_limit_reached", { reason: "rules", limit: 2 }, "Limit reached")
      expect(apiErrorMessage(production, rules)).toBe(
        "Your plan's limit is reached. Settings, Your account, Your plan shows what it allows.",
      )
      expect(warn).not.toHaveBeenCalled()
    } finally {
      vi.unstubAllEnvs()
      warn.mockRestore()
    }
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
    expect(providerName(i18n, "outlook")).toBe("Outlook")
    expect(providerName(i18n, "a-later-provider")).toBe("the calendar provider")
  })
})
