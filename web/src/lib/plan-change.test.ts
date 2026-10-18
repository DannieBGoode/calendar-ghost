import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"
import type { OverLimit, PersonRow, PlanAssignments, PlanSummary } from "@/lib/api"
import {
  NO_PLAN,
  changeMove,
  changeOptions,
  changeTitle,
  changedResult,
  choiceVerdict,
  chosenPlan,
  sharedChoice,
} from "@/lib/plan-change"

const i18n = testI18n()

type Held = { key: string; name: string; on_default: boolean } | null

function person(email: string, has: Held): PersonRow {
  return {
    id: `user-${email.split("@")[0]}`,
    email,
    role: "user",
    state: "active",
    created_at: "2026-10-01T09:00:00Z",
    last_sign_in_at: null,
    verdict: "healthy",
    problems: 0,
    last_synced_at: null,
    resources: { rules: 0, connected_accounts: 0, activity_entries: 0, provider_calls: [], since: "2026-09-10" },
    plan: has && { basis: "plan", plan: has, assigned: null, has, over: [], assigned_by: null, assigned_at: null, use: null },
  }
}

function plan(key: string, name: string, limits: PlanSummary["limits"], isDefault = false): PlanSummary {
  return {
    key,
    name,
    limits,
    is_default: isDefault,
    people: 0,
    limited_people: 0,
    over_people: 0,
    use: { rules: [], connected_accounts: [], integration_tokens: [] },
  }
}

const NO_LIMITS = plan("no-limits", "No limits", { rules: null, connected_accounts: null, integration_tokens: null, sync_interval: "instant" }, true)
const FREE = plan("free", "Free", { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" })
const FAMILY = plan("family", "Family", { rules: 5, connected_accounts: 3, integration_tokens: null, sync_interval: "instant" })
/** As the server lists them, by name; Change plan puts the default first. */
const PLANS = [FAMILY, FREE, NO_LIMITS]

const FOLLOWS = { key: "no-limits", name: "No limits", on_default: true }
const GIVEN_DEFAULT = { key: "no-limits", name: "No limits", on_default: false }
const HAS_FREE = { key: "free", name: "Free", on_default: false }
const HAS_FAMILY = { key: "family", name: "Family", on_default: false }

/** What a dry run answers for these people: what each would be over. */
function dryRun(people: [PersonRow, OverLimit[]][]): PlanAssignments {
  return {
    dry_run: true,
    people: people.map(([who, over]) => ({ user_id: who.id, email: who.email, had: who.plan?.has ?? null, has: HAS_FREE, over })),
  }
}

const ACCOUNTS_OVER: OverLimit[] = [{ limit: "connected_accounts", in_use: 2, allowed: 1 }]

describe("Change plan's options", () => {
  it("offers each plan once, the default first with its badge, what they have now marked Current, each with its limits in short", () => {
    const robin = person("robin@example.test", HAS_FREE)
    expect(changeOptions(i18n, PLANS, [robin])).toEqual([
      { value: "no-limits", title: "No limits", summary: "Unlimited, Instant", badges: [{ text: "Default", kind: "default" }] },
      { value: "family", title: "Family", summary: "5 rules, 3 accounts, unlimited tokens, Instant", badges: [] },
      { value: "free", title: "Free", summary: "1 rule, 1 account, no tokens, every 5 min", badges: [{ text: "Current", kind: "current" }] },
    ])
    expect(sharedChoice(PLANS, [robin])).toBe("free")
  })

  it("marks the default Current both for someone who follows it and for someone given it as their own", () => {
    const alex = person("alex@example.test", FOLLOWS)
    const lee = person("lee@example.test", GIVEN_DEFAULT)
    for (const people of [[alex], [lee], [alex, lee]]) {
      expect(changeOptions(i18n, PLANS, people)[0]?.badges).toEqual([
        { text: "Default", kind: "default" },
        { text: "Current", kind: "current" },
      ])
      expect(sharedChoice(PLANS, people)).toBe("no-limits")
    }
  })

  it("for several people with different plans, counts who has each, and has no choice they all share", () => {
    const people = [
      person("robin@example.test", HAS_FREE),
      person("jordan@example.test", HAS_FREE),
      person("sam@example.test", HAS_FAMILY),
      person("alex@example.test", FOLLOWS),
    ]
    expect(changeOptions(i18n, PLANS, people).map((option) => [option.title, option.badges.map((badge) => badge.text)])).toEqual([
      ["No limits", ["Default", "1 has it"]],
      ["Family", ["1 has it"]],
      ["Free", ["2 have it"]],
    ])
    expect(sharedChoice(PLANS, people)).toBeNull()
  })

  it("offers No plan last only while no plan is the default, Current for someone with none", () => {
    const lee = person("lee@example.test", null)
    const robin = person("robin@example.test", HAS_FREE)
    const noDefault = [FAMILY, FREE]
    expect(changeOptions(i18n, noDefault, [lee]).at(-1)).toEqual({
      value: NO_PLAN,
      title: "No plan",
      summary: "Nothing limits them until a plan is the default.",
      badges: [{ text: "Current", kind: "current" }],
    })
    expect(sharedChoice(noDefault, [lee])).toBe(NO_PLAN)
    expect(changeOptions(i18n, noDefault, [robin]).at(-1)?.badges).toEqual([])
    expect(changeOptions(i18n, PLANS, [robin]).some((option) => option.value === NO_PLAN)).toBe(false)
  })

  it("sends a plan's key, or null for the default, which they then follow, or for no plan", () => {
    expect(changeMove(PLANS, "free")).toBe("free")
    expect(changeMove(PLANS, "no-limits")).toBeNull()
    expect(changeMove([FAMILY, FREE], NO_PLAN)).toBeNull()
    expect(chosenPlan(PLANS, "family")).toBe(FAMILY)
    expect(chosenPlan(PLANS, "no-limits")).toBe(NO_LIMITS)
    expect(chosenPlan([FAMILY, FREE], NO_PLAN)).toBeNull()
  })
})

describe("What a choice in Change plan would do", () => {
  it("for one person, names each limit they would be over, or says they fit, and nothing before the dry run answers", () => {
    const robin = person("robin@example.test", HAS_FAMILY)
    expect(choiceVerdict(i18n, [robin], undefined)).toBeNull()
    expect(choiceVerdict(i18n, [robin], dryRun([[robin, []]]))).toEqual({ text: "Within every limit", over: false })
    expect(choiceVerdict(i18n, [robin], dryRun([[robin, ACCOUNTS_OVER]]))).toEqual({
      text: "Would be over: 2 calendar accounts, 1 allowed",
      over: true,
    })
  })

  it("for several, names the one who would be over and their limits, or counts them", () => {
    const robin = person("robin@example.test", HAS_FAMILY)
    const jordan = person("jordan@example.test", HAS_FAMILY)
    const both = [robin, jordan]
    expect(choiceVerdict(i18n, both, dryRun([[robin, []], [jordan, []]]))).toEqual({ text: "Nobody would be over a limit", over: false })
    expect(choiceVerdict(i18n, both, dryRun([[robin, []], [jordan, ACCOUNTS_OVER]]))).toEqual({
      text: "jordan@example.test would be over: 2 calendar accounts, 1 allowed",
      over: true,
    })
    expect(choiceVerdict(i18n, both, dryRun([[robin, ACCOUNTS_OVER], [jordan, ACCOUNTS_OVER]]))).toEqual({
      text: "2 people would be over a limit",
      over: true,
    })
  })
})

describe("Change plan's words", () => {
  it("titles the choice by the one person, or by how many", () => {
    const robin = person("robin@example.test", HAS_FREE)
    expect(changeTitle(i18n, [robin])).toBe("Change plan for robin@example.test")
    expect(changeTitle(i18n, [robin, person("jordan@example.test", HAS_FREE)])).toBe("Change plan for 2 people")
  })

  it("says what a change did, naming the plan, or that they have none", () => {
    const robin = person("robin@example.test", HAS_FREE)
    const two = [robin, person("jordan@example.test", HAS_FREE)]
    expect(changedResult(i18n, [robin], FREE)).toBe("robin@example.test now has Free.")
    expect(changedResult(i18n, [robin], NO_LIMITS)).toBe("robin@example.test now has No limits.")
    expect(changedResult(i18n, [robin], null)).toBe("robin@example.test has no plan now.")
    expect(changedResult(i18n, two, FREE)).toBe("2 people now have Free.")
    expect(changedResult(i18n, two, null)).toBe("2 people have no plan now.")
  })
})
