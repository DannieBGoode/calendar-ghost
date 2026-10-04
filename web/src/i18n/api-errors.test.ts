import { describe, expect, it } from "vitest"

import { ApiError, UnreadableResponseError } from "@/lib/api"

import { apiErrorMessage } from "./api-errors"
import { testI18n } from "./testing"

const i18n = testI18n()

describe("apiErrorMessage", () => {
  it("shows the server's detail, or a generic message when it sent none", () => {
    expect(apiErrorMessage(i18n, new ApiError("custom detail", 500, "custom detail"))).toBe("custom detail")
    expect(apiErrorMessage(i18n, new ApiError("x", 422, null))).toBe("The request could not be completed.")
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
