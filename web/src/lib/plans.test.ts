import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"
import type {
  OverLimit,
  OwnPlan,
  PersonPlanOverview,
  PlanLimits,
  PlanSummary,
  RegistrationPolicy,
} from "@/lib/api"
import {
  heldPlanChips,
  limitedPeople,
  limitsNothing,
  ownPlanShown,
  planWarning,
  previewedStartRefusal,
  startRefusal,
} from "@/lib/plans"

const i18n = testI18n()

const FAMILY_LIMITS: PlanLimits = { rules: 5, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" }
const FREE_LIMITS: PlanLimits = { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" }
const UNLIMITED: PlanLimits = { rules: null, connected_accounts: null, integration_tokens: null, sync_interval: "instant" }

/** A User the Family Plan limits, their own Plan, with room left for everything. */
const family: OwnPlan = {
  basis: "plan",
  plan: { key: "family", name: "Family", on_default: false },
  limits: FAMILY_LIMITS,
  rules_counted: 3,
  connected_accounts: 2,
  integration_tokens: 1,
  instant: true,
  poll_every_minutes: 5,
  may_connect_account: true,
  may_issue_token: true,
  over_rule_limit: false,
}

const plansOff: OwnPlan = {
  ...family,
  basis: "plans_off",
  plan: null,
  limits: null,
}

const administering: OwnPlan = { ...plansOff, basis: "administrator" }

describe("ownPlanShown", () => {
  it.each<[string, OwnPlan | undefined, RegistrationPolicy | undefined, boolean]>([
    ["a User a Plan limits", family, undefined, true],
    ["a User a Plan limits, under Invitation only", family, "invitation_only", true],
    ["anyone while Plans are off", plansOff, "invitation_only", false],
    ["an administrator under Only me", administering, "only_me", false],
    ["an administrator under Invitation only", administering, "invitation_only", true],
    ["an administrator while the Registration Policy loads", administering, undefined, false],
    ["a read that has not answered", undefined, "invitation_only", false],
    ["an empty answer", {} as OwnPlan, "invitation_only", false],
  ])("for %s", (_case, plan, policy, shown) => {
    expect(ownPlanShown(plan, policy)).toBe(shown)
  })
})

describe("planWarning", () => {
  it("warns only while more rules count than the Plan allows", () => {
    expect(planWarning({ ...family, rules_counted: 6, over_rule_limit: true })).toBe(true)
    expect(planWarning({ ...family, rules_counted: 5 })).toBe(false)
    expect(planWarning(plansOff)).toBe(false)
  })

  it("never warns without an answer", () => {
    expect(planWarning(undefined)).toBe(false)
    expect(planWarning({} as OwnPlan)).toBe(false)
  })
})

describe("startRefusal", () => {
  it("says nothing when the rule may start", () => {
    expect(startRefusal(i18n, { can_start: true, rule_limit: 3 })).toBeNull()
    expect(startRefusal(i18n, { can_start: true, rule_limit: null })).toBeNull()
  })

  it("gives the rule limit's message, in the plural its limit needs", () => {
    expect(startRefusal(i18n, { can_start: false, rule_limit: 1 })).toBe(
      "Your plan lets 1 rule sync. Pause or remove it to start this rule.",
    )
    expect(startRefusal(i18n, { can_start: false, rule_limit: 3 })).toBe(
      "Your plan lets 3 rules sync. Pause or remove one to start this rule.",
    )
  })

  it("falls back to the general limit message without a limit", () => {
    expect(startRefusal(i18n, { can_start: false, rule_limit: null })).toBe(
      "Your plan's limit is reached. Settings, Your account, Your plan shows what it allows.",
    )
  })
})

describe("previewedStartRefusal", () => {
  const previewed = { state: "dry_run_validated", keeps_place: false }
  const atFamilyLimit: OwnPlan = { ...family, rules_counted: 5 }
  const refusal = "Your plan lets 5 rules sync. Pause or remove one to start this rule."

  it.each<[string, OwnPlan, string | null]>([
    ["room under the limit", family, null],
    ["the limit reached", atFamilyLimit, refusal],
    ["more counted than the limit", { ...atFamilyLimit, rules_counted: 6, over_rule_limit: true }, refusal],
    ["no rule limit", { ...atFamilyLimit, limits: UNLIMITED }, null],
    ["Plans off", plansOff, null],
  ])("answers for a previewed rule with %s", (_case, plan, expected) => {
    expect(previewedStartRefusal(i18n, plan, previewed)).toBe(expected)
  })

  it("lets a rule that keeps a replaced rule's place start whatever the limit", () => {
    expect(previewedStartRefusal(i18n, atFamilyLimit, { ...previewed, keeps_place: true })).toBeNull()
  })

  it("says nothing of a rule that is not waiting to start, or while the Plan is unknown", () => {
    expect(previewedStartRefusal(i18n, atFamilyLimit, { ...previewed, state: "draft" })).toBeNull()
    expect(previewedStartRefusal(i18n, undefined, previewed)).toBeNull()
  })
})

describe("limitsNothing", () => {
  it("holds for a Plan with no limit on any count that syncs instantly, such as No limits", () => {
    expect(limitsNothing(UNLIMITED)).toBe(true)
  })

  it.each([
    ["a rule limit", { ...UNLIMITED, rules: 3 }],
    ["a calendar account limit", { ...UNLIMITED, connected_accounts: 1 }],
    ["no Integration Tokens", { ...UNLIMITED, integration_tokens: 0 }],
    ["a slower sync", { ...UNLIMITED, sync_interval: "5_minutes" as const }],
  ])("fails for a Plan with %s", (_name, limits) => {
    expect(limitsNothing(limits)).toBe(false)
  })
})

describe("limitedPeople", () => {
  const plan = (key: string, limits: PlanLimits, limited: number): PlanSummary => ({
    key,
    name: key,
    limits,
    is_default: false,
    people: limited + 1,
    limited_people: limited,
    over_people: 0,
    use: { rules: [], connected_accounts: [], integration_tokens: [] },
  })

  it("adds the people each Plan limits, leaving out a Plan that limits nothing", () => {
    expect(limitedPeople([plan("family", FAMILY_LIMITS, 3), plan("free", FREE_LIMITS, 2)])).toBe(5)
    expect(limitedPeople([plan("no-limits", UNLIMITED, 4), plan("free", FREE_LIMITS, 1)])).toBe(1)
    expect(limitedPeople([plan("no-limits", UNLIMITED, 4)])).toBe(0)
    expect(limitedPeople([])).toBe(0)
  })
})

describe("heldPlanChips", () => {
  const familyName = { key: "family", name: "Family" }
  const hasFamily = { ...familyName, on_default: false }
  const hasFree = { key: "free", name: "Free", on_default: true }
  /** A person's Plan as their page and their row of People show it, within every limit. */
  const person = (plan: Partial<PersonPlanOverview>): PersonPlanOverview => ({
    basis: "plan",
    plan: null,
    assigned: null,
    has: null,
    over: [],
    assigned_by: null,
    assigned_at: null,
    use: null,
    ...plan,
  })
  const chips = (plan: PersonPlanOverview, administrator = false) =>
    heldPlanChips(i18n, plan, administrator).map(({ text, tone, detail }) => [text, tone, detail ?? null])

  it("marks the default plan, and nothing for a plan of their own within every limit", () => {
    expect(chips(person({ plan: hasFree, has: hasFree }))).toEqual([["Default", "neutral", null]])
    expect(chips(person({ plan: hasFamily, assigned: familyName, has: hasFamily }))).toEqual([])
    expect(chips(person({ basis: "plans_off" }))).toEqual([])
  })

  it("marks a limit they are over in Attention Ochre, with each limit in words, while plans are on", () => {
    const over: OverLimit[] = [
      { limit: "rules", in_use: 3, allowed: 2 },
      { limit: "connected_accounts", in_use: 2, allowed: 1 },
    ]
    expect(chips(person({ plan: hasFamily, has: hasFamily, over }))).toEqual([
      ["Over a limit", "attention", "3 active rules, 2 allowed and 2 calendar accounts, 1 allowed"],
    ])
  })

  it("says what they would be over, neutral, while plans are off", () => {
    const over: OverLimit[] = [{ limit: "integration_tokens", in_use: 1, allowed: 0 }]
    expect(chips(person({ basis: "plans_off", has: hasFree, over }))).toEqual([
      ["Default", "neutral", null],
      ["Would be over", "neutral", "1 integration token, none allowed"],
    ])
  })

  it("marks an administrator not limited, whatever they have, on or off", () => {
    expect(chips(person({ basis: "administrator", has: hasFree }), true)).toEqual([
      ["Default", "neutral", null],
      ["Not limited", "neutral", null],
    ])
    expect(chips(person({ basis: "plans_off", has: hasFamily }), true)).toEqual([["Not limited", "neutral", null]])
  })
})
