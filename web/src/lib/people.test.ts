import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"
import type { Person } from "@/lib/api"

import { deletionMessage, isAdministrator, personFacts, personName } from "./people"

const NOW = Date.parse("2026-10-09T12:00:00Z")

const robin: Person = {
  id: "user-robin",
  email: "robin@example.test",
  role: "user",
  state: "active",
  created_at: "2026-10-09T09:00:00Z",
  last_sign_in_at: null,
}

describe("people", () => {
  it("says when a person joined and last signed in, and never anything they own", () => {
    const i18n = testI18n()
    expect(personFacts(i18n, robin, NOW)).toBe("Joined 3 hours ago · never signed in")
    expect(personFacts(i18n, { ...robin, last_sign_in_at: "2026-10-09T11:00:00Z" }, NOW)).toBe(
      "Joined 3 hours ago · last signed in 1 hour ago",
    )
  })

  it("names a person by email, or says they have none yet", () => {
    const i18n = testI18n()
    expect(personName(i18n, robin)).toBe("robin@example.test")
    expect(personName(i18n, { ...robin, email: null })).toBe("No email yet")
  })

  it("tells an administrator apart", () => {
    expect(isAdministrator({ role: "installation_administrator" })).toBe(true)
    expect(isAdministrator({ role: "user" })).toBe(false)
    expect(isAdministrator(null)).toBe(false)
  })

  it("reports a deletion with what happened to the events their rules wrote", () => {
    const i18n = testI18n()
    expect(deletionMessage(i18n, "robin@example.test", { rules: 0, deleted: 0, detached: 0, left: 0 })).toBe(
      "robin@example.test was deleted.",
    )
    expect(deletionMessage(i18n, "robin@example.test", { rules: 3, deleted: 12, detached: 0, left: 1 })).toBe(
      "robin@example.test was deleted. 12 events their rules wrote were deleted. 1 rule could not reach its calendar, so its events stay there, no longer managed.",
    )
  })
})
