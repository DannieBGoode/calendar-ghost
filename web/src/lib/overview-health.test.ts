import { describe, expect, it } from "vitest"

import { testI18n } from "../i18n/testing"
import type { Dashboard, ServerProblem } from "./api"
import { overviewHealth, overviewRules } from "./overview-health"

const i18n = testI18n()
const now = Date.parse("2026-09-28T12:00:00Z")
const healthy: Dashboard = {
  status: "healthy",
  needs_attention: false,
  problems: [],
  connected_accounts: 2,
  disconnected_accounts: 0,
  lapsed_accounts: 0,
  sync_rules: 3,
  enabled_rules: 2,
  stopped_rules: 0,
  open_incidents: 0,
  last_synced_at: "2026-09-28T11:57:00Z",
  blocked_events: 0,
  blocked_entry_id: null,
  blocked_rule_id: null,
  next_pass_at: null,
}

const names: Record<string, string> = {
  "rule-7": "Family → Work",
  "rule-8": "Work → Family",
  "rule-9": "Work → Family",
}
const ruleName = (ruleId: string) => names[ruleId] ?? null
const problem = (
  kind: ServerProblem["kind"],
  rule_id: string | null,
  summary: string,
  since: string | null = "2026-09-28T11:00:00Z",
): ServerProblem => ({ kind, rule_id, summary, since, message: null, cause: null, last_tried_at: null, provider: null })

describe("overviewHealth", () => {
  it("reports the last successful sync when everything is quiet", () => {
    const health = overviewHealth(i18n, healthy, now)
    expect(health.tone).toBe("healthy")
    expect(health.headline).toBe("Synchronization is healthy")
    expect(health.title).toBe("")
    expect(health.detail).toBe("Calendar Ghost checks your calendars for changes every five minutes.")
    expect(health.facts).toEqual(["2 rules running", "Last sync 3 minutes ago"])
    expect(health.action).toBeNull()
  })

  it("asks for a look at blocked events while rules keep running", () => {
    const health = overviewHealth(
      i18n,
      { ...healthy, status: "review", blocked_events: 1, blocked_entry_id: 42, blocked_rule_id: "rule-1" },
      now,
    )
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
    const health = overviewHealth(i18n, { ...healthy, status: "review", open_incidents: 2 }, now)
    expect(health.tone).toBe("review")
    expect(health.headline).toBe("Something needs a look")
    expect(health.detail).toBe("2 problems kept happening. Activity explains what happened and what to do.")
    expect(health.action).toEqual({ label: "Open Activity", view: "activity" })
  })

  it("names the running rule an incident is about", () => {
    const health = overviewHealth(
      i18n,
      {
        ...healthy,
        status: "review",
        open_incidents: 2,
        problems: [
          problem("review", "rule-7", "Rule Removal stopped"),
          problem("review", "rule-8", "Rule Removal stopped", "2026-09-28T10:00:00Z"),
        ],
      },
      now,
      { ruleName },
    )
    expect(health.tone).toBe("review")
    expect(health.headline).toBe("A rule needs a look")
    expect(health.title).toBe("Family → Work")
    expect(health.detail).toBe("Rule Removal stopped. First seen 1 hour ago. 1 other problem also needs a look.")
    expect(health.action).toEqual({ label: "Review this rule", view: "rules", ruleId: "rule-7" })
  })

  it("only informs while Google limits requests, because the rule retries by itself", () => {
    const health = overviewHealth(
      i18n,
      {
        ...healthy,
        status: "waiting",
        open_incidents: 1,
        problems: [problem("waiting", "rule-7", "Google Calendar is limiting requests")],
      },
      now,
      { ruleName },
    )
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
      i18n,
      {
        ...healthy,
        status: "stopped",
        open_incidents: 2,
        stopped_rules: 1,
        blocked_events: 2,
        blocked_entry_id: 42,
        blocked_rule_id: "rule-1",
        problems: [
          problem("stopped", "rule-7", "Google authorization expired"),
          problem("waiting", "rule-8", "Google Calendar is limiting requests", "2026-09-28T11:55:00Z"),
        ],
      },
      now,
      { ruleName },
    )
    expect(health.tone).toBe("stopped")
    expect(health.title).toBe("Family → Work")
    expect(health.others).toEqual([
      {
        tone: "review",
        summary: "2 events couldn't be synced",
        action: { label: "See blocked events", view: "activity", search: "?rule=rule-1&show=blocked&entry=42" },
      },
      { tone: "waiting", summary: "Work → Family is waiting for Google", action: null },
    ])
  })

  it("never calls an installation with an open incident healthy, even before it is described", () => {
    const health = overviewHealth(i18n, { ...healthy, status: "review", open_incidents: 1 }, now, { ruleName })
    expect(health.tone).toBe("review")
    expect(health.headline).toBe("Something needs a look")
  })

  it("says rules stopped when an account needs reauthorization", () => {
    const health = overviewHealth(
      i18n,
      {
        ...healthy,
        status: "stopped",
        connected_accounts: 0,
        disconnected_accounts: 1,
        lapsed_accounts: 0,
        stopped_rules: 2,
        enabled_rules: 0,
        problems: [
          problem("stopped", "rule-7", "A calendar account needs reauthorization", null),
          problem("stopped", "rule-8", "A calendar account needs reauthorization", null),
        ],
      },
      now,
      { ruleName },
    )
    expect(health.tone).toBe("stopped")
    expect(health.headline).toBe("2 rules stopped syncing")
    expect(health.title).toBe("1 Google account needs reauthorization")
    expect(health.facts).toEqual(["No rules running", "Last sync 3 minutes ago"])
    expect(health.action).toMatchObject({ view: "settings", settingsTab: "connections" })
  })

  describe("with a Cause", () => {
    const lapsedFor = (cause: ServerProblem["cause"]): Dashboard => ({
      ...healthy,
      status: "stopped",
      lapsed_accounts: 1,
      stopped_rules: 2,
      enabled_rules: 0,
      problems: [
        { ...problem("stopped", "rule-7", "A calendar account needs reauthorization", null), cause },
        { ...problem("stopped", "rule-8", "A calendar account needs reauthorization", null), cause },
      ],
    })

    it("tells the User an administrator's Cause is temporarily unavailable, naming neither it nor the administrator", () => {
      const health = overviewHealth(i18n, lapsedFor("api_disabled"), now, { ruleName })

      expect(health.title).toBe("Temporarily unavailable")
      expect(health.detail).toBe(
        "Google Calendar is not available to Calendar Ghost right now. To try again, choose Check access on your Google account in Settings. Events already synced stay where they are.",
      )
      expect(health.action).toMatchObject({ label: "Check access in Settings", view: "settings", settingsTab: "connections" })
    })

    it("tells an administrator the fix is theirs, and where People explains it", () => {
      const health = overviewHealth(i18n, lapsedFor("oauth_client_invalid"), now, { ruleName, administrator: true })

      expect(health.title).toBe("You fix this as the administrator")
      expect(health.detail).toBe(
        "Likely cause: Google no longer accepts this installation's OAuth client. People shows how to fix it in Google Cloud.",
      )
      expect(health.action).toMatchObject({ label: "Open People", view: "people" })
    })

    it("asks the User to reauthorize for their own Cause", () => {
      const health = overviewHealth(i18n, lapsedFor("access_revoked"), now, { ruleName })

      expect(health.title).toBe("1 Google account needs reauthorization")
      expect(health.action).toMatchObject({ view: "settings", settingsTab: "connections" })
    })

    it("asks for another calendar when the calendar is gone or closed to the account", () => {
      const gone: Dashboard = {
        ...healthy,
        status: "stopped",
        stopped_rules: 1,
        problems: [{ ...problem("stopped", "rule-7", "Google Calendar rejected synchronization"), cause: "calendar_not_found" }],
      }
      const health = overviewHealth(i18n, gone, now, { ruleName })

      expect(health.detail).toContain("Choose another calendar, or remove the rule.")
      expect(health.action).toMatchObject({ view: "rules", ruleId: "rule-7" })
    })

    it("says when a rule waiting on Google was last tried and is tried again", () => {
      const waiting: Dashboard = {
        ...healthy,
        status: "waiting",
        open_incidents: 1,
        next_pass_at: "2026-09-28T12:03:00Z",
        problems: [
          {
            ...problem("waiting", "rule-7", "Google Calendar is limiting requests"),
            cause: "rate_limited",
            last_tried_at: "2026-09-28T11:56:00Z",
          },
        ],
      }
      const health = overviewHealth(i18n, waiting, now, { ruleName })

      expect(health.detail).toMatch(/Last tried 4 minutes ago\. Tries again in 3 minutes\.$/)
      expect(health.action).toBeNull()
    })

    it("tells the User a used-up quota only that Calendar Ghost retries, while the administrator learns the cause", () => {
      const waiting: Dashboard = {
        ...healthy,
        status: "waiting",
        open_incidents: 1,
        problems: [{ ...problem("waiting", "rule-7", "Google Calendar is limiting requests"), cause: "quota_exceeded" }],
      }
      const health = overviewHealth(i18n, waiting, now, { ruleName })
      const administrators = overviewHealth(i18n, waiting, now, { ruleName, administrator: true })

      expect(health.detail).toBe(
        "Google Calendar is limiting requests. First seen 1 hour ago. Wait for Google to respond: Calendar Ghost retries by itself and catches up afterwards. If it lasts more than a day, check the Google Workspace Status Dashboard.",
      )
      expect(administrators.detail).toBe(
        "Likely cause: this installation's daily quota of Google requests is used up. You fix this as the administrator, in Google Cloud; Calendar Ghost tries again by itself.",
      )
    })
  })

  it("asks for reauthorization before setup when only a disconnected account remains", () => {
    const health = overviewHealth(
      i18n,
      { ...healthy, status: "setup", connected_accounts: 0, disconnected_accounts: 1, sync_rules: 0, enabled_rules: 0 },
      now,
    )
    expect(health.tone).toBe("setup")
    expect(health.headline).toBe("Reauthorize your Google account")
    expect(health.action).toMatchObject({ view: "settings", settingsTab: "connections" })
  })

  it("puts a stopped rule ahead of problems on running ones", () => {
    const health = overviewHealth(
      i18n,
      {
        ...healthy,
        status: "stopped",
        open_incidents: 3,
        stopped_rules: 1,
        problems: [
          problem("review", "rule-9", "Rule Removal stopped", null),
          problem("stopped", "rule-7", "Stopped syncing", null),
        ],
      },
      now,
      { ruleName },
    )
    expect(health.tone).toBe("stopped")
    expect(health.headline).toBe("A rule stopped syncing")
    expect(health.title).toBe("Family → Work")
    expect(health.detail).toBe(
      "Stopped syncing. It writes nothing until it is fixed. Events already synced stay where they are.",
    )
    expect(health.action).toEqual({ label: "Review this rule", view: "rules", ruleId: "rule-7" })
    expect(health.others).toEqual([
      { tone: "review", summary: "Work → Family needs a look", action: { label: "Review this rule", view: "rules", ruleId: "rule-9" } },
    ])
  })

  it("flags stopped rules even without naming one", () => {
    const health = overviewHealth(
      i18n,
      { ...healthy, status: "stopped", stopped_rules: 1, problems: [problem("stopped", "rule-gone", "Stopped syncing", null)] },
      now,
      { ruleName },
    )
    expect(health.tone).toBe("stopped")
    expect(health.title).toBe("")
    expect(health.action).toEqual({ label: "Review rules", view: "rules" })
  })

  it("tells a pause apart from unfinished setup", () => {
    const paused = overviewHealth(i18n, { ...healthy, status: "paused", enabled_rules: 0 }, now)
    expect(paused.tone).toBe("paused")
    expect(paused.facts).toEqual(["3 rules not running", "Last sync 3 minutes ago"])
    const neverRun = overviewHealth(i18n, { ...healthy, status: "setup", enabled_rules: 0, last_synced_at: null }, now)
    expect(neverRun.tone).toBe("setup")
    expect(neverRun.headline).toBe("No rule is synchronizing")
  })

  it("guides setup until a rule is running", () => {
    expect(overviewHealth(i18n, { ...healthy, status: "setup", connected_accounts: 0 }, now).tone).toBe("setup")
    expect(overviewHealth(i18n, { ...healthy, status: "setup", sync_rules: 0, enabled_rules: 0 }, now).headline).toBe(
      "Create your first rule",
    )
    // The Getting started steps show setup's progress, so the hero lists no facts.
    expect(overviewHealth(i18n, { ...healthy, status: "setup", connected_accounts: 0 }, now).facts).toEqual([])
  })

  it("waits for the first run without inventing a time", () => {
    expect(overviewHealth(i18n, { ...healthy, last_synced_at: null }, now).facts).toEqual(["2 rules running", "Not synced yet"])
    expect(
      overviewHealth(
        i18n,
        {
          ...healthy,
          status: "stopped",
          last_synced_at: null,
          stopped_rules: 1,
          problems: [problem("stopped", "rule-gone", "Stopped syncing", null)],
        },
        now,
      ).facts,
    ).toEqual(["2 rules still running", "Waiting for recovery"])
  })

  it("never repeats a fact in the copy the hero shows", () => {
    const dashboards: Dashboard[] = [
      healthy,
      { ...healthy, last_synced_at: null },
      { ...healthy, status: "review", blocked_events: 2, blocked_entry_id: 42, blocked_rule_id: null },
      { ...healthy, status: "review", open_incidents: 1 },
      { ...healthy, status: "stopped", stopped_rules: 1, problems: [problem("stopped", "rule-7", "Stopped syncing", null)] },
      {
        ...healthy,
        status: "stopped",
        disconnected_accounts: 1,
        lapsed_accounts: 0,
        stopped_rules: 1,
        problems: [problem("stopped", "rule-7", "A calendar account needs reauthorization", null)],
      },
      { ...healthy, status: "paused", enabled_rules: 0 },
    ]
    for (const dashboard of dashboards) {
      const health = overviewHealth(i18n, dashboard, now)
      const copy = [health.headline, health.title, health.detail].join(" ").toLowerCase()
      for (const fact of health.facts) {
        expect(copy).not.toContain(fact.toLowerCase())
      }
    }
  })

  it("says synchronization stopped running when the scheduler stalls", () => {
    const health = overviewHealth(
      i18n,
      { ...healthy, status: "stalled", needs_attention: true, problems: [problem("stalled", null, "Scheduled synchronization stopped running", null)] },
      now,
      { ruleName },
    )
    expect(health.tone).toBe("stopped")
    expect(health.headline).toBe("Synchronization stopped running")
    expect(health.detail).toBe(
      "Calendar Ghost has not checked your calendars recently. Restart the service to resume. Events already synced stay where they are.",
    )
    expect(health.action).toBeNull()
  })

  it("asks for a look at a rule that has not synced in over a day", () => {
    const health = overviewHealth(
      i18n,
      { ...healthy, status: "review", problems: [problem("overdue", "rule-7", "Not synced in over a day", "2026-09-27T10:00:00Z")] },
      now,
      { ruleName },
    )
    expect(health.tone).toBe("review")
    expect(health.title).toBe("Family → Work")
    expect(health.detail).toBe("Not synced in over a day. Last sync yesterday.")
  })

  it("gives a generic hero for a stalled status with no problem to explain it", () => {
    const health = overviewHealth(i18n, { ...healthy, status: "stalled", problems: [] }, now)
    expect(health.tone).toBe("stopped")
    expect(health.headline).not.toBe("Synchronization is healthy")
    expect(health.headline).toBe("Synchronization needs attention")
    expect(health.detail).toBe(
      "A rule stopped syncing. Rules shows which one and what to do. Events already synced stay where they are.",
    )
    expect(health.action).toEqual({ label: "Review rules", view: "rules" })
    expect(health.facts).toEqual(["2 rules still running", "Last sync 3 minutes ago"])
  })

  it("gives a generic hero for a stopped status with no problem to explain it", () => {
    const health = overviewHealth(i18n, { ...healthy, status: "stopped", problems: [] }, now)
    expect(health.tone).toBe("stopped")
    expect(health.headline).not.toBe("Synchronization is healthy")
    expect(health.headline).toBe("Synchronization needs attention")
    expect(health.detail).toBe(
      "A rule stopped syncing. Rules shows which one and what to do. Events already synced stay where they are.",
    )
    expect(health.action).toEqual({ label: "Review rules", view: "rules" })
    expect(health.facts).toEqual(["2 rules still running", "Last sync 3 minutes ago"])
  })

  it("gives a generic hero for a review status with no problem to explain it", () => {
    const health = overviewHealth(i18n, { ...healthy, status: "review", problems: [] }, now)
    expect(health.tone).toBe("review")
    expect(health.headline).not.toBe("Synchronization is healthy")
    expect(health.headline).toBe("Something needs a look")
    expect(health.detail).toBe("Activity explains what happened and what to do.")
    expect(health.action).toEqual({ label: "Open Activity", view: "activity" })
    expect(health.facts).toEqual(["2 rules running", "Last sync 3 minutes ago"])
  })

  it("gives a generic hero for a waiting status with no problem to explain it", () => {
    const health = overviewHealth(i18n, { ...healthy, status: "waiting", problems: [] }, now)
    expect(health.tone).toBe("waiting")
    expect(health.headline).not.toBe("Synchronization is healthy")
    expect(health.headline).toBe("Waiting for the calendar provider")
    expect(health.detail).toBe("Calendar Ghost retries by itself and catches up afterwards.")
    expect(health.action).toBeNull()
    expect(health.facts).toEqual(["2 rules running", "Last sync 3 minutes ago"])
  })

  it("takes its tone from the server", () => {
    for (const status of ["stopped", "review", "waiting", "paused", "setup", "healthy"] as const) {
      expect(overviewHealth(i18n, { ...healthy, status }, now, { ruleName }).tone).toBe(status)
    }
    expect(overviewHealth(i18n, { ...healthy, status: "stalled" }, now, { ruleName }).tone).toBe("stopped")
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
