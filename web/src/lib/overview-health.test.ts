import { describe, expect, it } from "vitest"

import type { Dashboard } from "./api"
import { overviewHealth, overviewRules, withoutRunningRemovals } from "./overview-health"

const now = Date.parse("2026-09-28T12:00:00Z")
const healthy: Dashboard = {
  health: "healthy",
  connected_accounts: 2,
  disconnected_accounts: 0,
  sync_rules: 3,
  enabled_rules: 2,
  stopped_rules: 0,
  open_incidents: 0,
  last_synced_at: "2026-09-28T11:57:00Z",
  blocked_events: 0,
  blocked_entry_id: null,
  blocked_rule_id: null,
}

describe("overviewHealth", () => {
  it("reports the last successful sync when everything is quiet", () => {
    const health = overviewHealth(healthy, now)
    expect(health.tone).toBe("healthy")
    expect(health.headline).toBe("Synchronization is healthy")
    expect(health.title).toBe("2 rules running normally")
    expect(health.detail).toMatch(/^Last sync 3 minutes ago\./)
    expect(health.action).toBeNull()
  })

  it("stays healthy with a blocked event but says so and links to it", () => {
    const health = overviewHealth({ ...healthy, blocked_events: 1, blocked_entry_id: 42, blocked_rule_id: "rule-1" }, now)
    expect(health.tone).toBe("healthy")
    expect(health.detail).toBe("1 event couldn't be synced. Last sync 3 minutes ago.")
    expect(health.action).toEqual({
      label: "See the blocked event",
      view: "activity",
      search: "?rule=rule-1&show=blocked&entry=42",
    })
  })

  it("never calls an installation with open incidents healthy", () => {
    const health = overviewHealth({ ...healthy, health: "attention", open_incidents: 2 }, now)
    expect(health.tone).toBe("attention")
    expect(health.headline).not.toMatch(/healthy/i)
    expect(health.title).toBe("2 incidents need attention")
    expect(health.action).toEqual({ label: "Open Activity", view: "activity" })
  })

  it("asks for reauthorization instead of setup when the only account lost access", () => {
    const health = overviewHealth(
      { ...healthy, connected_accounts: 0, disconnected_accounts: 1, stopped_rules: 2, enabled_rules: 0 },
      now,
    )
    expect(health.tone).toBe("attention")
    expect(health.title).toBe("1 Google account needs reauthorization")
    expect(health.action?.view).toBe("settings")
  })

  it("asks for reauthorization before setup when only a disconnected account remains", () => {
    const health = overviewHealth(
      { ...healthy, connected_accounts: 0, disconnected_accounts: 1, sync_rules: 0, enabled_rules: 0 },
      now,
    )
    expect(health.tone).toBe("setup")
    expect(health.headline).toBe("Reauthorize your Google account")
    expect(health.action?.view).toBe("settings")
  })

  it("flags stopped rules even without an incident", () => {
    const health = overviewHealth({ ...healthy, stopped_rules: 1 }, now)
    expect(health.tone).toBe("attention")
    expect(health.title).toBe("1 rule stopped")
  })

  it("guides setup until a rule is running", () => {
    expect(overviewHealth({ ...healthy, connected_accounts: 0 }, now).tone).toBe("setup")
    expect(overviewHealth({ ...healthy, sync_rules: 0, enabled_rules: 0 }, now).headline).toBe(
      "Create your first rule",
    )
    expect(overviewHealth({ ...healthy, enabled_rules: 0 }, now).headline).toBe("No rule is synchronizing")
  })

  it("waits for the first run without inventing a time", () => {
    expect(overviewHealth({ ...healthy, last_synced_at: null }, now).detail).toBe(
      "The first sync runs within five minutes.",
    )
  })

  it("names the affected rule and links straight to it", () => {
    const health = overviewHealth({ ...healthy, open_incidents: 1, stopped_rules: 2 }, now, {
      ruleId: "rule-7",
      name: "Family → Work",
      detail: "Stopped 1 hour ago.",
    })
    expect(health.title).toBe("Family → Work needs attention")
    expect(health.detail).toBe("Stopped 1 hour ago. 1 other problem also needs a look.")
    expect(health.action).toEqual({ label: "Review this rule", view: "rules", ruleId: "rule-7" })
  })
})

describe("withoutRunningRemovals", () => {
  const removing = new Set(["rule-a"])

  it("does not count a rule whose removal is running as stopped", () => {
    const dashboard = { ...healthy, health: "attention" as const, stopped_rules: 1 }
    const shown = withoutRunningRemovals(dashboard, [{ id: "rule-a", state: "disabled" }], removing)
    expect(shown).toMatchObject({ stopped_rules: 0, health: "healthy" })
    expect(overviewHealth(shown, now).tone).toBe("healthy")
  })

  it("keeps other stopped rules and interrupted removals", () => {
    const dashboard = { ...healthy, health: "attention" as const, stopped_rules: 2 }
    const rules = [
      { id: "rule-a", state: "disabled" },
      { id: "rule-b", state: "disabled" },
    ]
    expect(withoutRunningRemovals(dashboard, rules, removing)).toMatchObject({ stopped_rules: 1, health: "attention" })
    expect(withoutRunningRemovals(dashboard, rules, new Set())).toBe(dashboard)
  })

  it("leaves a removal the dashboard has not seen start alone", () => {
    const shown = withoutRunningRemovals(healthy, [{ id: "rule-a", state: "enabled" }], removing)
    expect(shown).toBe(healthy)
  })
})

describe("overviewRules", () => {
  const rule = (id: string, state: string, running: "preview" | null = null) => ({
    id,
    state,
    running: running && { kind: running, started_at: "2026-09-28T12:00:00Z", handling: null, total: null, done: 0 },
  })

  it("keeps working rules within the limit ahead of idle enabled ones", () => {
    const rules = [
      rule("a", "enabled"),
      rule("b", "enabled"),
      rule("c", "draft"),
      rule("d", "paused", "preview"),
      rule("e", "disabled"),
    ]
    expect(overviewRules(rules, new Set(["e"]), 3).map((item) => item.id)).toEqual(["d", "e", "a"])
    expect(overviewRules(rules, new Set(), 5).map((item) => item.id)).toEqual(["d", "a", "b", "c", "e"])
  })
})
