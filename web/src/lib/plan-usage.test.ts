import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"
import type { OwnPlan, PersonPlanOverview } from "@/lib/api"
import { ownPlanCard, planCardSummary, planUsageRows } from "@/lib/plan-usage"

const i18n = testI18n()
const NOW = Date.parse("2026-10-17T12:00:00Z")
const FREE = { key: "free", name: "Free", on_default: false }
const DEFAULT_FREE = { ...FREE, on_default: true }

/** Robin's Free, which Dana gave: at the rule limit, over on calendar accounts, no tokens included. */
const robin: PersonPlanOverview = {
  basis: "plan",
  plan: FREE,
  assigned: { key: "free", name: "Free" },
  has: FREE,
  over: [{ limit: "connected_accounts", in_use: 2, allowed: 1 }],
  assigned_by: "dana@example.test",
  // 9:00 on Oct 12 where the test runs, so the day reads the same in every time zone.
  assigned_at: new Date(2026, 9, 12, 9).toISOString(),
  use: {
    rules: { in_use: 1, allowed: 1 },
    connected_accounts: { in_use: 2, allowed: 1 },
    integration_tokens: { in_use: 0, allowed: 0 },
    sync_interval: "5_minutes",
  },
}

const who = { name: "robin@example.test", administrator: false, now: NOW }

function rows(plan: PersonPlanOverview) {
  return planUsageRows(i18n, plan, "robin@example.test")
}

describe("planCardSummary", () => {
  it.each<[string, PersonPlanOverview, string]>([
    ["a plan an administrator gave, while plans are on", robin, "Given by dana@example.test on Oct 12. Plans are on, so it limits robin@example.test now."],
    [
      "the default plan while plans are off",
      { ...robin, basis: "plans_off", plan: null, assigned: null, has: DEFAULT_FREE, assigned_by: null, assigned_at: null },
      "The default plan. Plans are off, so it limits nobody yet.",
    ],
    [
      "the default plan while plans are on",
      { ...robin, plan: DEFAULT_FREE, assigned: null, has: DEFAULT_FREE, assigned_by: null, assigned_at: null },
      "The default plan. Plans are on, so it limits robin@example.test now.",
    ],
    ["a plan given by someone since deleted", { ...robin, assigned_by: null }, "Given on Oct 12. Plans are on, so it limits robin@example.test now."],
    [
      "a plan of their own nothing recorded giving",
      { ...robin, assigned_by: null, assigned_at: null },
      "Their own plan, not the default. Plans are on, so it limits robin@example.test now.",
    ],
    ["a plan given in another year", { ...robin, assigned_at: new Date(2025, 11, 30, 9).toISOString() }, "Given by dana@example.test on Dec 30, 2025. Plans are on, so it limits robin@example.test now."],
    [
      "no plan yet",
      { ...robin, basis: "plans_off", plan: null, assigned: null, has: null, assigned_by: null, assigned_at: null, use: null },
      "They have no plan until one is the default.",
    ],
  ])("says who gave %s and whether it limits them now", (_case, plan, words) => {
    expect(planCardSummary(i18n, plan, who)).toBe(words)
  })

  it("says only that no plan limits administrators", () => {
    expect(planCardSummary(i18n, { ...robin, basis: "administrator", plan: null }, { ...who, administrator: true })).toBe(
      "No plan limits administrators.",
    )
    expect(planCardSummary(i18n, { ...robin, basis: "plans_off", plan: null }, { ...who, administrator: true })).toBe(
      "No plan limits administrators.",
    )
  })
})

describe("planUsageRows", () => {
  it("names each limit and what counts toward it, in order", () => {
    expect(rows(robin).map((row) => [row.limit, row.title, row.hint])).toEqual([
      ["rules", "Active rules", "Running, or waiting for reauthorization"],
      ["accounts", "Calendar accounts", "Disconnected accounts count"],
      ["tokens", "Integration tokens", "Revoked tokens don't count"],
      ["speed", "Sync speed", "How soon changes reach other calendars"],
    ])
  })

  it("shows a count at its limit as full and neutral, with Limit reached", () => {
    const [rules] = rows(robin)
    expect(rules).toMatchObject({
      meter: { value: 1, max: 1, valueText: "1 of 1, limit reached", tone: "neutral" },
      value: "1 of 1",
      chip: { text: "Limit reached", tone: "neutral" },
      note: null,
    })
  })

  it("shows a count past its limit in Attention Ochre, with Over and what keeps working", () => {
    const accounts = rows(robin)[1]
    expect(accounts).toMatchObject({
      meter: { value: 2, max: 1, valueText: "2 of 1, over the limit", tone: "over" },
      value: "2 of 1",
      chip: { text: "Over", tone: "attention" },
      note: {
        text: "robin@example.test has 2 calendar accounts and Free allows 1. Their accounts keep syncing, but they can't connect another until one is removed. They see the same on Your plan.",
        tone: "attention",
      },
    })
  })

  it("keeps a count past its limit neutral while plans are off, as Would be over, with no sentence", () => {
    const accounts = rows({ ...robin, basis: "plans_off", plan: null })[1]
    expect(accounts).toMatchObject({
      meter: { value: 2, max: 1, valueText: "2 of 1, would be over the limit", tone: "neutral" },
      chip: { text: "Would be over", tone: "neutral" },
      note: null,
    })
  })

  it("says a plan includes no tokens with no meter, and Over for tokens kept from before", () => {
    expect(rows(robin)[2]).toMatchObject({ meter: null, detail: "Free includes none.", value: "Not included", quiet: true, chip: null })
    const kept = rows({ ...robin, use: { ...robin.use!, integration_tokens: { in_use: 1, allowed: 0 } } })[2]
    expect(kept).toMatchObject({
      meter: null,
      detail: "Free includes none.",
      value: "1 in use",
      chip: { text: "Over", tone: "attention" },
      note: {
        text: "robin@example.test has 1 integration token and Free includes none. Their tokens keep working, but they can't issue another. They see the same on Your plan.",
        tone: "attention",
      },
    })
  })

  it("shows a count with no limit in words, with no meter", () => {
    const unlimited = rows({ ...robin, use: { ...robin.use!, rules: { in_use: 4, allowed: null } } })[0]
    expect(unlimited).toMatchObject({ meter: null, detail: "No limit", value: "4 in use", chip: null })
  })

  it("shows a count within its limit with no chip", () => {
    const within = rows({ ...robin, use: { ...robin.use!, rules: { in_use: 2, allowed: 5 } } })[0]
    expect(within).toMatchObject({ meter: { value: 2, max: 5, valueText: "2 of 5", tone: "neutral" }, value: "2 of 5", chip: null })
  })

  it("says rules and tokens past their limits in their own words", () => {
    const over = rows({
      ...robin,
      use: { ...robin.use!, rules: { in_use: 3, allowed: 1 }, integration_tokens: { in_use: 2, allowed: 1 } },
    })
    expect(over[0]?.note?.text).toBe(
      "robin@example.test has 3 active rules and Free allows 1. Their rules keep syncing, but they can't start another until fewer are active. They see the same on Your plan.",
    )
    expect(over[2]?.note?.text).toBe(
      "robin@example.test has 2 integration tokens and Free allows 1. Their tokens keep working, but they can't issue another until one is revoked. They see the same on Your plan.",
    )
  })

  it("says how soon their calendars sync, and when Instant sync is not part of the plan", () => {
    expect(rows(robin)[3]).toMatchObject({ detail: "Instant sync is not part of Free.", value: "Every 5 minutes", speed: "5_minutes", meter: null })
    const instant = rows({ ...robin, use: { ...robin.use!, sync_interval: "instant" } })[3]
    expect(instant).toMatchObject({ detail: null, value: "Instant", speed: "instant" })
  })

  it("has no rows without a plan's use", () => {
    expect(rows({ ...robin, use: null })).toEqual([])
    expect(rows({ ...robin, has: null })).toEqual([])
  })
})

describe("ownPlanCard", () => {
  /** Robin's own Free, as Your plan reads it: at the rule limit, over on calendar accounts, no tokens. */
  const own: OwnPlan = {
    basis: "plan",
    plan: FREE,
    limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
    rules_counted: 1,
    held_rules: 0,
    grace: null,
    rules: [],
    connected_accounts: 2,
    integration_tokens: 0,
    instant: false,
    poll_every_minutes: 5,
    may_connect_account: false,
    may_issue_token: false,
    over_rule_limit: false,
  }

  it("gives the person page's rows in the reader's own words", () => {
    const rows = ownPlanCard(i18n, own)?.rows ?? []
    expect(rows.map((row) => [row.title, row.hint])).toEqual([
      ["Active rules", "Running rules, and rules waiting for you to reauthorize an account. Paused rules and drafts don't count."],
      ["Calendar accounts", "Every account you connected counts, disconnected ones too."],
      ["Integration tokens", "Revoked tokens don't count."],
      ["Sync speed", "How soon changes reach your other calendars."],
    ])
  })

  it("shows Over a limit when only calendar accounts are past their limit", () => {
    expect(ownPlanCard(i18n, own)?.chips).toEqual([{ id: "over", text: "Over a limit", tone: "attention" }])
  })

  it("says rules and tokens past their limits to the reader", () => {
    const rows =
      ownPlanCard(i18n, {
        ...own,
        limits: { ...own.limits!, integration_tokens: 1 },
        rules_counted: 3,
        connected_accounts: 1,
        integration_tokens: 2,
      })?.rows ?? []
    expect(rows.map((row) => row.note)).toEqual([
      {
        text: "You have 3 active rules and your plan allows 1. They keep syncing, but you can't start another until fewer are active.",
        tone: "attention",
      },
      null,
      {
        text: "You have 2 integration tokens and your plan allows 1. They keep working, but you can't issue another until you revoke one in <link>Connections</link>.",
        tone: "attention",
      },
      null,
    ])
    const kept = ownPlanCard(i18n, { ...own, integration_tokens: 1 })?.rows[2]
    expect(kept).toMatchObject({
      value: "1 in use",
      chip: { text: "Over", tone: "attention" },
      note: { text: "You have 1 integration token and your plan includes none. It keeps working, but you can't issue another.", tone: "attention" },
    })
  })

  it("has no card when no plan limits the reader", () => {
    expect(ownPlanCard(i18n, { ...own, basis: "plans_off", plan: null, limits: null })).toBeNull()
    expect(ownPlanCard(i18n, { ...own, basis: "administrator", plan: null, limits: null })).toBeNull()
  })
})
