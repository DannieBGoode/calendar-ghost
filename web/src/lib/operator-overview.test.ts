import { describe, expect, it } from "vitest"

import { testI18n } from "../i18n/testing"
import type { ResourceUse, ServerProblem } from "./api"
import { problemText, resourceFacts, verdictTone, VERDICTS } from "./operator-overview"

const i18n = testI18n()

const problem = (kind: ServerProblem["kind"], summary: string): ServerProblem => ({
  kind,
  rule_id: "rule-1",
  summary,
  since: null,
  message: null,
})

describe("verdictTone", () => {
  it("colors a verdict by how much it needs someone", () => {
    expect(VERDICTS.map((verdict) => [verdict, verdictTone(verdict)])).toEqual([
      ["stalled", "stopped"],
      ["stopped", "stopped"],
      ["review", "attention"],
      ["waiting", "attention"],
      ["paused", "neutral"],
      ["setup", "neutral"],
      ["healthy", "healthy"],
    ])
  })
})

describe("problemText", () => {
  it("names a problem no Incident explains by its kind, in the catalog's words", () => {
    expect(problemText(i18n, problem("stalled", "Scheduled synchronization stopped running"), 0)).toBe(
      "Scheduled synchronization stopped running",
    )
    expect(problemText(i18n, problem("stopped", "Stopped syncing"), 0)).toBe("Stopped syncing")
    expect(problemText(i18n, problem("overdue", "Not synced in over a day"), 0)).toBe("Not synced in over a day")
    expect(problemText(i18n, problem("blocked", "3 events couldn't be synced"), 3)).toBe(
      "3 events couldn't be synced",
    )
  })

  it("translates a problem an Incident explains from its message", () => {
    const lapsed: ServerProblem = {
      ...problem("stopped", "A calendar account needs reauthorization"),
      message: { code: "authorization_lapsed", params: { provider: "google" } },
    }

    expect(problemText(i18n, lapsed, 0)).toBe("A Google Calendar account needs reauthorization")
  })
})

describe("resourceFacts", () => {
  const quiet: ResourceUse = {
    rules: 1,
    connected_accounts: 2,
    activity_entries: 1,
    provider_calls: [],
    since: "2026-09-10",
  }

  it("counts what a User keeps here and the calls their rules made", () => {
    const busy: ResourceUse = {
      ...quiet,
      rules: 3,
      activity_entries: 1204,
      provider_calls: [{ provider: "google", calls: 1530, rate_limited: 2, failed: 1 }],
    }

    expect(resourceFacts(i18n, busy)).toEqual({
      kept: ["3 rules", "2 Google accounts", "1,204 Activity entries"],
      calls: ["Google Calendar: 1,530 calls, 2 refused for its rate limit, 1 failed"],
    })
  })

  it("says when no rule called a calendar provider", () => {
    expect(resourceFacts(i18n, quiet)).toEqual({
      kept: ["1 rule", "2 Google accounts", "1 Activity entry"],
      calls: [],
    })
  })
})
