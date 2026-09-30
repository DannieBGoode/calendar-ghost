import { describe, expect, it } from "vitest"

import type { ConnectedAccount, Incident } from "@/lib/api"
import {
  accessRenewedSince,
  incidentClosedAt,
  incidentGuidance,
  incidentResolution,
  splitIncidents,
} from "@/lib/incidents"

const NOT_RENEWED = { accessRenewed: false }
const RENEWED = { accessRenewed: true }

function account(state: string, authorizedAt: string | null, id = "failed-account"): ConnectedAccount {
  return {
    id,
    display_name: "Personal",
    email: "person@example.test",
    avatar_url: null,
    state,
    rule_count: 1,
    authorized_at: authorizedAt,
  }
}

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
    ...overrides,
  }
}

describe("incident guidance", () => {
  it("sends authorization incidents to Settings while access is lost, even once the rule is gone", () => {
    for (const category of ["authentication", "authorization"]) {
      for (const rule of [NOT_RENEWED, null]) {
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
      const guidance = incidentGuidance(incident({ category }), RENEWED)
      expect(guidance.action).toEqual({ kind: "rule", ruleId: "rule-1", label: "Recover this rule" })
      expect(guidance.detail).not.toMatch(/reauthorize/i)
    }
  })

  it("opens a stopped rule so it can be recovered, but only while the rule exists", () => {
    for (const category of ["permanent", "infrastructure"]) {
      expect(incidentGuidance(incident({ category }), RENEWED).action).toEqual({
        kind: "rule",
        ruleId: "rule-1",
        label: "Review this rule",
      })
      expect(incidentGuidance(incident({ category }), null).action).toBeNull()
    }
  })

  it("asks nothing of the administrator while transient failures are retried", () => {
    for (const category of ["rate_limit", "temporary"]) {
      const guidance = incidentGuidance(incident({ category }), RENEWED)
      expect(guidance.action).toBeNull()
      expect(guidance.detail).toMatch(/^Nothing to do now/)
    }
  })

  it("filters Activity to the rule's blocked events for a persisting block", () => {
    expect(incidentGuidance(incident({ category: "conflict" }), RENEWED).action).toEqual({
      kind: "blocked",
      ruleId: "rule-1",
      label: "See blocked events",
    })
  })

  it("offers the rule without explaining a category it does not know", () => {
    expect(incidentGuidance(incident({ category: "ownership" }), RENEWED)).toEqual({
      detail: null,
      action: { kind: "rule", ruleId: "rule-1", label: "Review this rule" },
    })
    expect(incidentGuidance(incident({ category: "ownership", rule_id: null }), null).action).toBeNull()
  })
})

describe("renewed access", () => {
  // The incident last recorded a failure at 18:30, from "failed-account".
  const before = "2026-09-28T18:00:00Z"
  const after = "2026-09-28T19:00:00Z"

  it("is not claimed for accounts that stayed connected through the failure", () => {
    // Google rejecting credentials leaves the account connected; nothing was renewed.
    expect(accessRenewedSince(incident(), [account("connected", before), account("connected", before, "other")])).toBe(
      false,
    )
  })

  it("is claimed once the account that failed was reauthorized after the failure", () => {
    expect(accessRenewedSince(incident(), [account("connected", after), account("connected", before, "other")])).toBe(
      true,
    )
  })

  it("is not claimed when only another account of the rule was reauthorized", () => {
    expect(accessRenewedSince(incident(), [account("connected", before), account("connected", after, "other")])).toBe(
      false,
    )
  })

  it("needs every account of the rule reauthorized when the failing one was not recorded", () => {
    const unknown = incident({ account_id: null })
    expect(accessRenewedSince(unknown, [account("connected", after), account("connected", before, "other")])).toBe(false)
    expect(accessRenewedSince(unknown, [account("connected", after), account("connected", after, "other")])).toBe(true)
  })

  it("is not claimed while any account of the rule is disconnected or unknown", () => {
    expect(accessRenewedSince(incident(), [account("connected", after), account("disconnected", null, "other")])).toBe(
      false,
    )
    expect(accessRenewedSince(incident(), [account("connected", after), undefined])).toBe(false)
  })

  it("is withdrawn when the incident records another failure after reauthorizing", () => {
    const failedAgain = incident({ updated_at: "2026-09-28T19:30:00Z" })
    expect(accessRenewedSince(failedAgain, [account("connected", after), account("connected", after, "other")])).toBe(
      false,
    )
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
