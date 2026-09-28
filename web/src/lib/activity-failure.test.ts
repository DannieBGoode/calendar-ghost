import { describe, expect, it } from "vitest"

import { activityFailure, activityFailureMessages, activityFailureRequiresReload } from "./activity-failure"
import { ApiError } from "./api"

const blocked = new TypeError("Failed to fetch")

describe("activityFailure", () => {
  it("blames connectivity or a content blocker only when no HTTP response arrived", () => {
    expect(activityFailure([blocked, null])).toBe("unreachable")
    expect(activityFailureMessages.unreachable).toContain("a browser extension such as a content blocker")
  })

  it("reports server errors without suggesting the request was blocked", () => {
    expect(activityFailure([new ApiError("boom", 500), null])).toBe("service-error")
    expect(activityFailureMessages["service-error"]).not.toContain("content blocker")
  })

  it("asks for a reload when a page from an older release calls a removed API path", () => {
    expect(activityFailure([new ApiError("Not Found", 404), null])).toBe("application-updated")
    expect(activityFailureRequiresReload("application-updated")).toBe(true)
  })

  it("prioritizes an expired session over every other failure", () => {
    expect(activityFailure([new ApiError("Not Found", 404), new ApiError("expired", 401)])).toBe(
      "session-expired",
    )
    expect(activityFailureRequiresReload("session-expired")).toBe(true)
  })

  it("retries in place for failures a reload would not fix", () => {
    expect(activityFailureRequiresReload("service-error")).toBe(false)
    expect(activityFailureRequiresReload("unreachable")).toBe(false)
  })
})
