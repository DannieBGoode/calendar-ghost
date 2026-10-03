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
    expect(health.title).toBe("")
    expect(health.detail).toBe("Calendar Ghost checks your calendars for changes every five minutes.")
    expect(health.facts).toEqual(["2 rules running", "Last sync 3 minutes ago"])
    expect(health.action).toBeNull()
  })

  it("asks for a look at blocked events while rules keep running", () => {
    const health = overviewHealth({ ...healthy, blocked_events: 1, blocked_entry_id: 42, blocked_rule_id: "rule-1" }, now)
    expect(health.tone).toBe("review")
    expect(health.headline).toBe("An event needs a look")
    expect(health.detail).toBe("1 event couldn't be synced and was left unchanged. Everything else is up to date.")
    expect(health.facts).toEqual(["2 rules running", "Last sync 3 minutes ago"])
    expect(health.action).toEqual({
      label: "See the blocked event",
      view: "activity",
      search: "?rule=rule-1&show=blocked&entry=42",
    })
  })

  it("asks for a look at open incidents on running rules", () => {
    const health = overviewHealth({ ...healthy, health: "attention", open_incidents: 2 }, now)
    expect(health.tone).toBe("review")
    expect(health.headline).toBe("Something needs a look")
    expect(health.detail).toBe("2 problems kept happening. Activity explains what happened and what to do.")
    expect(health.action).toEqual({ label: "Open Activity", view: "activity" })
  })

  it("names the running rule an incident is about", () => {
    const health = overviewHealth({ ...healthy, open_incidents: 2 }, now, [
      { ruleId: "rule-7", name: "Family → Work", detail: "Rule Removal stopped. First seen 1 hour ago.", kind: "review" },
      { ruleId: "rule-8", name: "Work → Family", detail: "Rule Removal stopped. First seen 2 hours ago.", kind: "review" },
    ])
    expect(health.tone).toBe("review")
    expect(health.headline).toBe("A rule needs a look")
    expect(health.title).toBe("Family → Work")
    expect(health.detail).toBe("Rule Removal stopped. First seen 1 hour ago. 1 other problem also needs a look.")
    expect(health.action).toEqual({ label: "Review this rule", view: "rules", ruleId: "rule-7" })
  })

  it("only informs while Google limits requests, because the rule retries by itself", () => {
    const health = overviewHealth({ ...healthy, open_incidents: 1 }, now, [
      { ruleId: "rule-7", name: "Family → Work", detail: "Google Calendar is limiting requests. First seen 1 hour ago.", kind: "waiting" },
    ])
    expect(health.tone).toBe("waiting")
    expect(health.headline).toBe("Waiting for Google")
    expect(health.title).toBe("Family → Work")
    expect(health.detail).toBe(
      "Google Calendar is limiting requests. First seen 1 hour ago. Wait for Google to respond: Calendar Ghost retries by itself and catches up afterwards. If it lasts more than a day, check the Google Workspace Status Dashboard.",
    )
    expect(health.action).toBeNull()
  })

  it("leads with the most urgent problem and lists every other one", () => {
    const health = overviewHealth(
      { ...healthy, open_incidents: 2, stopped_rules: 1, blocked_events: 2, blocked_entry_id: 42, blocked_rule_id: "rule-1" },
      now,
      [
        { ruleId: "rule-7", name: "Personal → Work", detail: "Google authorization expired. First seen 1 hour ago.", kind: "stopped" },
        { ruleId: "rule-8", name: "Family → Work", detail: "Google Calendar is limiting requests. First seen 5 minutes ago.", kind: "waiting" },
      ],
    )
    expect(health.tone).toBe("stopped")
    expect(health.title).toBe("Personal → Work")
    expect(health.others).toEqual([
      {
        tone: "review",
        summary: "2 events couldn't be synced",
        action: { label: "See blocked events", view: "activity", search: "?rule=rule-1&show=blocked&entry=42" },
      },
      { tone: "waiting", summary: "Family → Work is waiting for Google", action: null },
    ])
  })

  it("never calls an installation with an open incident healthy, even before it is described", () => {
    const health = overviewHealth({ ...healthy, open_incidents: 1 }, now, [])
    expect(health.tone).toBe("review")
    expect(health.headline).toBe("Something needs a look")
  })

  it("says rules stopped when an account needs reauthorization", () => {
    const health = overviewHealth(
      { ...healthy, connected_accounts: 0, disconnected_accounts: 1, stopped_rules: 2, enabled_rules: 0 },
      now,
    )
    expect(health.tone).toBe("stopped")
    expect(health.headline).toBe("2 rules stopped syncing")
    expect(health.title).toBe("1 Google account needs reauthorization")
    expect(health.facts).toEqual(["No rules running", "Last sync 3 minutes ago"])
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

  it("puts a stopped rule ahead of problems on running ones", () => {
    const health = overviewHealth({ ...healthy, open_incidents: 3, stopped_rules: 1 }, now, [
      { ruleId: "rule-9", name: "Work → Family", detail: "Rule Removal stopped.", kind: "review" },
      { ruleId: "rule-7", name: "Family → Work", detail: "Stopped 1 hour ago.", kind: "stopped" },
    ])
    expect(health.tone).toBe("stopped")
    expect(health.headline).toBe("A rule stopped syncing")
    expect(health.title).toBe("Family → Work")
    expect(health.detail).toBe(
      "Stopped 1 hour ago. It writes nothing until it is fixed. Events already synced stay where they are.",
    )
    expect(health.action).toEqual({ label: "Review this rule", view: "rules", ruleId: "rule-7" })
    expect(health.others).toEqual([
      { tone: "review", summary: "Work → Family needs a look", action: { label: "Review this rule", view: "rules", ruleId: "rule-9" } },
    ])
  })

  it("flags stopped rules even without naming one", () => {
    const health = overviewHealth({ ...healthy, stopped_rules: 1 }, now)
    expect(health.tone).toBe("stopped")
    expect(health.title).toBe("")
    expect(health.action).toEqual({ label: "Review rules", view: "rules" })
  })

  it("tells a pause apart from unfinished setup", () => {
    const paused = overviewHealth({ ...healthy, enabled_rules: 0 }, now)
    expect(paused.tone).toBe("paused")
    expect(paused.facts).toEqual(["3 rules not running", "Last sync 3 minutes ago"])
    const neverRun = overviewHealth({ ...healthy, enabled_rules: 0, last_synced_at: null }, now)
    expect(neverRun.tone).toBe("setup")
    expect(neverRun.headline).toBe("No rule is synchronizing")
  })

  it("guides setup until a rule is running", () => {
    expect(overviewHealth({ ...healthy, connected_accounts: 0 }, now).tone).toBe("setup")
    expect(overviewHealth({ ...healthy, sync_rules: 0, enabled_rules: 0 }, now).headline).toBe(
      "Create your first rule",
    )
    // The Getting started steps show setup's progress, so the hero lists no facts.
    expect(overviewHealth({ ...healthy, connected_accounts: 0 }, now).facts).toEqual([])
  })

  it("waits for the first run without inventing a time", () => {
    expect(overviewHealth({ ...healthy, last_synced_at: null }, now).facts).toEqual(["2 rules running", "Not synced yet"])
    expect(
      overviewHealth({ ...healthy, last_synced_at: null, stopped_rules: 1 }, now).facts,
    ).toEqual(["2 rules still running", "Waiting for recovery"])
  })

  it("never repeats a fact in the copy the hero shows", () => {
    const dashboards: Dashboard[] = [
      healthy,
      { ...healthy, last_synced_at: null },
      { ...healthy, blocked_events: 2, blocked_entry_id: 42, blocked_rule_id: null },
      { ...healthy, open_incidents: 1 },
      { ...healthy, stopped_rules: 1 },
      { ...healthy, disconnected_accounts: 1, stopped_rules: 1 },
      { ...healthy, enabled_rules: 0 },
    ]
    for (const dashboard of dashboards) {
      const health = overviewHealth(dashboard, now)
      const copy = [health.headline, health.title, health.detail].join(" ").toLowerCase()
      for (const fact of health.facts) {
        expect(copy).not.toContain(fact.toLowerCase())
      }
    }
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
    running: running && { kind: running, started_at: "2026-09-28T12:00:00Z", handling: null, total: null, done: 0, stage: null },
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
