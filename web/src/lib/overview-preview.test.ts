import { describe, expect, it } from "vitest"

import { overviewPreview } from "./overview-preview"

describe("overview preview", () => {
  it("provides a healthy dashboard with realistic rules and recent changes", () => {
    const preview = overviewPreview(Date.parse("2026-10-03T10:00:00.000Z"))

    expect(preview.dashboard).toMatchObject({
      health: "healthy",
      connected_accounts: 2,
      sync_rules: 2,
      enabled_rules: 2,
      open_incidents: 0,
    })
    expect(preview.rules).toHaveLength(2)
    expect(preview.rules.every((rule) => rule.state === "enabled" && rule.last_sync?.succeeded)).toBe(true)
    expect(preview.recentChanges).toHaveLength(2)
    expect(preview.recentChanges.every((change) => change.entry.event?.title === "IO R&D seminar")).toBe(true)
  })

  it("resolves synthetic account and calendar presentation data", () => {
    const preview = overviewPreview()
    const endpoints = preview.endpoints(preview.rules[0])

    expect(endpoints.source).toMatchObject({ name: "Daniel IOG Calendar", account: { email: "daniel@example.test" } })
    expect(endpoints.destination.name).toBe("IO Clone")
    expect(endpoints.disconnected).toEqual([])
  })
})
