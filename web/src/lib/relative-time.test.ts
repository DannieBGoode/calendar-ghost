import { describe, expect, it } from "vitest"

import { relativeTime } from "./relative-time"

const now = Date.parse("2026-09-28T12:00:00Z")

describe("relativeTime", () => {
  it("rounds very recent runs to just now", () => {
    expect(relativeTime("2026-09-28T11:59:30Z", now)).toBe("just now")
  })

  it("uses minutes, hours, and days", () => {
    expect(relativeTime("2026-09-28T11:55:00Z", now)).toBe("5 minutes ago")
    expect(relativeTime("2026-09-28T09:00:00Z", now)).toBe("3 hours ago")
    expect(relativeTime("2026-09-27T09:00:00Z", now)).toBe("yesterday")
  })

  it("falls back to a date after a week", () => {
    expect(relativeTime("2026-09-01T12:00:00Z", now)).toMatch(/^on /)
  })

  it("does not throw on an unreadable timestamp", () => {
    expect(relativeTime("not a date", now)).toBe("at an unknown time")
  })
})
