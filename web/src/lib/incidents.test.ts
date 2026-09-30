import { describe, expect, it } from "vitest"

import type { Incident } from "@/lib/api"
import { incidentClosedAt, incidentGuidance, incidentResolution, splitIncidents } from "@/lib/incidents"

const DISCONNECTED = { accountsConnected: false }
const CONNECTED = { accountsConnected: true }

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
    ...overrides,
  }
}

describe("incident guidance", () => {
  it("sends authorization incidents to Settings while access is lost, even once the rule is gone", () => {
    for (const category of ["authentication", "authorization"]) {
      for (const rule of [DISCONNECTED, null]) {
        expect(incidentGuidance(incident({ category }), rule).action).toEqual({
          kind: "settings",
          label: "Reauthorize in Settings",
        })
      }
    }
  })

  it("sends authorization incidents to the rule's recovery once access is renewed", () => {
    // Reauthorizing leaves the rule stopped, so no sync could close the incident on its own.
    for (const category of ["authentication", "authorization"]) {
      const guidance = incidentGuidance(incident({ category }), CONNECTED)
      expect(guidance.action).toEqual({ kind: "rule", ruleId: "rule-1", label: "Recover this rule" })
      expect(guidance.detail).not.toMatch(/reauthorize/i)
    }
  })

  it("opens a stopped rule so it can be recovered, but only while the rule exists", () => {
    for (const category of ["permanent", "infrastructure"]) {
      expect(incidentGuidance(incident({ category }), CONNECTED).action).toEqual({
        kind: "rule",
        ruleId: "rule-1",
        label: "Review this rule",
      })
      expect(incidentGuidance(incident({ category }), null).action).toBeNull()
    }
  })

  it("asks nothing of the administrator while transient failures are retried", () => {
    for (const category of ["rate_limit", "temporary"]) {
      const guidance = incidentGuidance(incident({ category }), CONNECTED)
      expect(guidance.action).toBeNull()
      expect(guidance.detail).toMatch(/^Nothing to do now/)
    }
  })

  it("filters Activity to the rule's blocked events for a persisting block", () => {
    expect(incidentGuidance(incident({ category: "conflict" }), CONNECTED).action).toEqual({
      kind: "blocked",
      ruleId: "rule-1",
      label: "See blocked events",
    })
  })

  it("offers the rule without explaining a category it does not know", () => {
    expect(incidentGuidance(incident({ category: "ownership" }), CONNECTED)).toEqual({
      detail: null,
      action: { kind: "rule", ruleId: "rule-1", label: "Review this rule" },
    })
    expect(incidentGuidance(incident({ category: "ownership", rule_id: null }), null).action).toBeNull()
  })
})

describe("resolved incidents", () => {
  it("says a removal closed an incident rather than claiming it was fixed", () => {
    expect(incidentResolution(incident({ state: "resolved", resolution: "rule_removed" }))).toBe(
      "Closed when the rule was removed.",
    )
    expect(incidentResolution(incident({ state: "resolved", resolution: "sync_succeeded" }))).toBe(
      "Resolved by a successful sync.",
    )
    expect(incidentResolution(incident({ state: "resolved", resolution: "blocks_cleared" }))).toMatch(
      /daily check/,
    )
  })

  it("claims no reason for incidents resolved before reasons were recorded", () => {
    const legacy = incident({ state: "resolved" })
    expect(incidentResolution(legacy)).toBeNull()
    expect(incidentClosedAt(legacy)).toBe(legacy.updated_at)
    expect(incidentClosedAt(incident({ resolved_at: "2026-09-29T08:00:00Z" }))).toBe("2026-09-29T08:00:00Z")
  })

  it("keeps resolved incidents apart from the open ones that lead Activity", () => {
    const open = incident({ id: "open" })
    const resolved = incident({ id: "resolved", state: "resolved", resolution: "rule_removed" })
    expect(splitIncidents([open, resolved])).toEqual({ open: [open], resolved: [resolved] })
  })
})
