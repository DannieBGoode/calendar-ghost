import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"
import type { OwnPlan, PersonPlan, PlanLimits, PlanSummary, RegistrationPolicy, SyncInterval } from "@/lib/api"
import {
  intervalLabel,
  limitedPeople,
  limitsNothing,
  ownPlanShown,
  ownPlanSummary,
  personPlanFact,
  planLimitsSummary,
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

describe("intervalLabel", () => {
  it.each<[SyncInterval, string]>([
    ["instant", "Instant sync, and a check every 5 minutes"],
    ["5_minutes", "Every 5 minutes"],
    ["10_minutes", "Every 10 minutes"],
    ["15_minutes", "Every 15 minutes"],
    ["30_minutes", "Every 30 minutes"],
    ["60_minutes", "Every hour"],
  ])("names %s", (interval, label) => {
    expect(intervalLabel(i18n, interval)).toBe(label)
  })
})

describe("planLimitsSummary", () => {
  it("counts each limit", () => {
    expect(planLimitsSummary(i18n, FAMILY_LIMITS)).toBe("5 rules, 3 calendar accounts, 2 Integration Tokens")
    expect(planLimitsSummary(i18n, { ...FAMILY_LIMITS, rules: 1, connected_accounts: 1, integration_tokens: 1 })).toBe(
      "1 rule, 1 calendar account, 1 Integration Token",
    )
  })

  it("says No limit where a count has none, and names a Plan that offers no tokens", () => {
    expect(planLimitsSummary(i18n, { ...FAMILY_LIMITS, rules: null })).toBe(
      "No limit on rules, 3 calendar accounts, 2 Integration Tokens",
    )
    expect(planLimitsSummary(i18n, { ...FAMILY_LIMITS, connected_accounts: null, integration_tokens: null })).toBe(
      "5 rules, no limit on calendar accounts, no limit on Integration Tokens",
    )
    expect(planLimitsSummary(i18n, FREE_LIMITS)).toBe("1 rule, 1 calendar account, no Integration Tokens")
  })

  it("says once that a Plan has no limit on any count", () => {
    expect(planLimitsSummary(i18n, UNLIMITED)).toBe("No limit on rules, calendar accounts, or Integration Tokens")
    expect(planLimitsSummary(i18n, { ...UNLIMITED, sync_interval: "5_minutes" })).toBe(
      "No limit on rules, calendar accounts, or Integration Tokens",
    )
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
  })

  it("adds the people each Plan limits, leaving out a Plan that limits nothing", () => {
    expect(limitedPeople([plan("family", FAMILY_LIMITS, 3), plan("free", FREE_LIMITS, 2)])).toBe(5)
    expect(limitedPeople([plan("no-limits", UNLIMITED, 4), plan("free", FREE_LIMITS, 1)])).toBe(1)
    expect(limitedPeople([plan("no-limits", UNLIMITED, 4)])).toBe(0)
    expect(limitedPeople([])).toBe(0)
  })
})

describe("ownPlanSummary", () => {
  it("counts what the User has against each limit, with Instant Sync", () => {
    expect(ownPlanSummary(i18n, family)).toBe(
      "Family: 3 of 5 rules counted, 2 of 3 calendar accounts, 1 of 2 tokens, instant sync included",
    )
  })

  it("names the Default Plan and its slower syncs", () => {
    const free: OwnPlan = {
      ...family,
      plan: { key: "free", name: "Free", on_default: true },
      limits: FREE_LIMITS,
      rules_counted: 1,
      connected_accounts: 1,
      integration_tokens: 0,
      instant: false,
      poll_every_minutes: 5,
    }
    expect(ownPlanSummary(i18n, free)).toBe(
      "Free (default): 1 of 1 rule counted, 1 of 1 calendar account, no Integration Tokens, syncs about every 5 minutes",
    )
  })

  it("counts without a limit where the Plan sets none", () => {
    expect(ownPlanSummary(i18n, { ...family, limits: UNLIMITED, rules_counted: 1, connected_accounts: 4, integration_tokens: 0 })).toBe(
      "Family: 1 rule counted, 4 calendar accounts, 0 tokens, instant sync included",
    )
  })

  it("still counts tokens kept from before a Plan that offers none", () => {
    expect(ownPlanSummary(i18n, { ...family, limits: { ...FAMILY_LIMITS, integration_tokens: 0 }, integration_tokens: 2 })).toBe(
      "Family: 3 of 5 rules counted, 2 of 3 calendar accounts, 2 tokens (0 allowed), instant sync included",
    )
  })

  it("counts past a limit by what is in use, and names the limit apart", () => {
    const over: OwnPlan = {
      ...family,
      limits: { ...FAMILY_LIMITS, rules: 1, connected_accounts: 2, integration_tokens: 1 },
      rules_counted: 2,
      connected_accounts: 3,
      integration_tokens: 2,
    }
    expect(ownPlanSummary(i18n, over)).toBe(
      "Family: 2 rules counted (1 allowed), 3 calendar accounts (2 allowed), 2 tokens (1 allowed), instant sync included",
    )
  })

  it("counts at a limit and under it against the limit", () => {
    const at: OwnPlan = {
      ...family,
      limits: { ...FAMILY_LIMITS, rules: 1, connected_accounts: 1, integration_tokens: 1 },
      rules_counted: 1,
      connected_accounts: 0,
      integration_tokens: 1,
    }
    expect(ownPlanSummary(i18n, at)).toBe(
      "Family: 1 of 1 rule counted, 0 of 1 calendar account, 1 of 1 token, instant sync included",
    )
  })

  it("has nothing to say when no Plan limits the User", () => {
    expect(ownPlanSummary(i18n, plansOff)).toBeNull()
    expect(ownPlanSummary(i18n, administering)).toBeNull()
  })
})

describe("personPlanFact", () => {
  const familyName = { key: "family", name: "Family" }

  it.each<[string, PersonPlan, string]>([
    ["their own Plan", { basis: "plan", plan: { ...familyName, on_default: false }, assigned: familyName }, "Family"],
    [
      "the Default Plan",
      { basis: "plan", plan: { key: "free", name: "Free", on_default: true }, assigned: null },
      "Free (default)",
    ],
    ["their own Plan while Plans are off", { basis: "plans_off", plan: null, assigned: familyName }, "Family, once plans are on"],
    [
      "the Default Plan while Plans are off",
      { basis: "plans_off", plan: null, assigned: null },
      "The default plan, once plans are on",
    ],
    ["an administrator", { basis: "administrator", plan: null, assigned: null }, "No plan limits administrators"],
    [
      "an administrator given a Plan",
      { basis: "administrator", plan: null, assigned: familyName },
      "No plan limits administrators (assigned: Family)",
    ],
  ])("names %s", (_case, plan, fact) => {
    expect(personPlanFact(i18n, plan, plan.basis === "administrator")).toBe(fact)
  })

  it.each<[string, PersonPlan, string]>([
    ["no Plan of their own", { basis: "plans_off", plan: null, assigned: null }, "No plan limits administrators"],
    [
      "a Plan of their own",
      { basis: "plans_off", plan: null, assigned: familyName },
      "No plan limits administrators (assigned: Family)",
    ],
  ])("says no plan limits an administrator with %s while Plans are off", (_case, plan, fact) => {
    expect(personPlanFact(i18n, plan, true)).toBe(fact)
  })
})
