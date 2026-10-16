import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"
import type {
  OverLimit,
  OwnPlan,
  PersonPlanOverview,
  PlanLimits,
  PlanSummary,
  RegistrationPolicy,
  SyncInterval,
} from "@/lib/api"
import {
  defaultPlanChoice,
  intervalLabel,
  limitedPeople,
  limitsNothing,
  ownPlanRows,
  ownPlanShown,
  personPlanFact,
  planChoiceLabel,
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

describe("planChoiceLabel", () => {
  const choice = (name: string, limits: PlanLimits) => ({ name, limits })

  it("names a Plan with each limit and how soon calendars sync", () => {
    expect(planChoiceLabel(i18n, choice("Family", FAMILY_LIMITS))).toBe(
      "Family: 5 rules, 3 calendar accounts, 2 Integration Tokens, instant sync",
    )
    expect(planChoiceLabel(i18n, choice("Free", FREE_LIMITS))).toBe(
      "Free: 1 rule, 1 calendar account, no Integration Tokens, every 5 minutes",
    )
  })

  it("says No limit in the same words as the Plan's row, after the name", () => {
    expect(planChoiceLabel(i18n, choice("Family", { ...FAMILY_LIMITS, rules: null, integration_tokens: null }))).toBe(
      "Family: no limit on rules, 3 calendar accounts, no limit on Integration Tokens, instant sync",
    )
    expect(planChoiceLabel(i18n, choice("No limits", UNLIMITED))).toBe(
      "No limits: no limit on rules, calendar accounts, or Integration Tokens, instant sync",
    )
  })

  it.each<[SyncInterval, string]>([
    ["instant", "instant sync"],
    ["5_minutes", "every 5 minutes"],
    ["10_minutes", "every 10 minutes"],
    ["15_minutes", "every 15 minutes"],
    ["30_minutes", "every 30 minutes"],
    ["60_minutes", "every hour"],
  ])("names the %s interval", (interval, words) => {
    expect(planChoiceLabel(i18n, choice("Free", { ...FREE_LIMITS, sync_interval: interval }))).toBe(
      `Free: 1 rule, 1 calendar account, no Integration Tokens, ${words}`,
    )
  })
})

describe("defaultPlanChoice", () => {
  const plan = (name: string, isDefault: boolean): PlanSummary => ({
    key: name.toLowerCase(),
    name,
    limits: FREE_LIMITS,
    is_default: isDefault,
    people: 0,
    limited_people: 0,
    over_people: 0,
    use: { rules: [], connected_accounts: [], integration_tokens: [] },
  })

  it("names the Plan that is the default now", () => {
    expect(defaultPlanChoice(i18n, [plan("Family", false), plan("Free", true)])).toBe("Default plan (Free)")
  })

  it("names no Plan while none is the default", () => {
    expect(defaultPlanChoice(i18n, [plan("Family", false)])).toBe("Default plan")
    expect(defaultPlanChoice(i18n, [])).toBe("Default plan")
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

describe("ownPlanRows", () => {
  const RULES_HINT = "Paused rules and drafts don't count."
  const ACCOUNTS_HINT = "Disconnected accounts count. Reconnecting an account is never refused."
  const TOKENS_HINT = "Revoked tokens don't count."

  it("gives one row per limit, each with how much of it is in use, then how soon calendars sync", () => {
    expect(ownPlanRows(i18n, family)).toEqual([
      { limit: "rules", title: "Rules that can sync", value: "3 of 5 in use", hint: RULES_HINT, over: null },
      { limit: "accounts", title: "Calendar accounts you can connect", value: "2 of 3 in use", hint: ACCOUNTS_HINT, over: null },
      { limit: "tokens", title: "Integration Tokens you can have", value: "1 of 2 in use", hint: TOKENS_HINT, over: null },
      { limit: "sync", title: "How soon calendars sync", value: "Instant sync, and a check every 5 minutes", hint: null, over: null },
    ])
  })

  it("says No limit where the Plan sets none, with how many are in use", () => {
    const rows = ownPlanRows(i18n, { ...family, limits: UNLIMITED, rules_counted: 1, connected_accounts: 4, integration_tokens: 0 })
    expect(rows.map((row) => row.value)).toEqual([
      "No limit, 1 in use",
      "No limit, 4 in use",
      "No limit, 0 in use",
      "Instant sync, and a check every 5 minutes",
    ])
    expect(rows.every((row) => row.over === null)).toBe(true)
  })

  it("says a Plan with no tokens does not include them, and how soon its calendars sync", () => {
    const free: OwnPlan = { ...family, limits: FREE_LIMITS, rules_counted: 1, connected_accounts: 1, integration_tokens: 0 }
    expect(ownPlanRows(i18n, free).map((row) => row.value)).toEqual([
      "1 of 1 in use",
      "1 of 1 in use",
      "Not included",
      "Every 5 minutes",
    ])
  })

  it("counts at a limit against it, which is not past it", () => {
    const at: OwnPlan = { ...family, limits: { ...FAMILY_LIMITS, rules: 1, connected_accounts: 1, integration_tokens: 1 }, rules_counted: 1, connected_accounts: 0, integration_tokens: 1 }
    const rows = ownPlanRows(i18n, at)
    expect(rows.map((row) => row.value).slice(0, 3)).toEqual(["1 of 1 in use", "0 of 1 in use", "1 of 1 in use"])
    expect(rows.every((row) => row.over === null)).toBe(true)
  })

  it("counts past a lowered limit by what is in use, and says what keeps working and how to make room", () => {
    const over: OwnPlan = {
      ...family,
      limits: { ...FAMILY_LIMITS, rules: 1, connected_accounts: 2, integration_tokens: 1 },
      rules_counted: 2,
      connected_accounts: 3,
      integration_tokens: 2,
    }
    expect(ownPlanRows(i18n, over).slice(0, 3)).toEqual([
      {
        limit: "rules",
        title: "Rules that can sync",
        value: "2 in use, 1 allowed",
        hint: RULES_HINT,
        over: "You have more rules in use than your plan allows. They keep syncing, but you cannot start another until you pause or remove one.",
      },
      {
        limit: "accounts",
        title: "Calendar accounts you can connect",
        value: "3 in use, 2 allowed",
        hint: ACCOUNTS_HINT,
        over: "You have more calendar accounts than your plan allows. They keep working, but you cannot connect another until you delete one.",
      },
      {
        limit: "tokens",
        title: "Integration Tokens you can have",
        value: "2 in use, 1 allowed",
        hint: TOKENS_HINT,
        over: "You have more Integration Tokens than your plan allows. They keep working, but you cannot issue another until you revoke one.",
      },
    ])
  })

  it("still counts tokens kept from before a Plan that includes none, as past its limit", () => {
    const kept = ownPlanRows(i18n, { ...family, limits: { ...FAMILY_LIMITS, integration_tokens: 0 }, integration_tokens: 2 })[2]
    expect(kept?.value).toBe("Not included, 2 in use")
    expect(kept?.over).toBe(
      "You have more Integration Tokens than your plan allows. They keep working, but you cannot issue another until you revoke one.",
    )
  })

  it.each<[SyncInterval, string]>([
    ["10_minutes", "Every 10 minutes"],
    ["60_minutes", "Every hour"],
  ])("words a sync interval of %s as the Plan's editor does", (interval, label) => {
    expect(ownPlanRows(i18n, { ...family, limits: { ...FAMILY_LIMITS, sync_interval: interval } })[3]?.value).toBe(label)
  })

  it("has no rows when no Plan limits the User", () => {
    expect(ownPlanRows(i18n, plansOff)).toEqual([])
    expect(ownPlanRows(i18n, administering)).toEqual([])
  })
})

describe("personPlanFact", () => {
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
    ...plan,
  })

  it.each<[string, PersonPlanOverview, string]>([
    ["their own Plan", person({ plan: hasFamily, assigned: familyName, has: hasFamily }), "Plan: Family"],
    ["the Default Plan", person({ plan: hasFree, has: hasFree }), "Plan: Free (default)"],
    [
      "their own Plan while Plans are off",
      person({ basis: "plans_off", assigned: familyName, has: hasFamily }),
      "Plan: Family, once plans are on",
    ],
    [
      "the Default Plan while Plans are off",
      person({ basis: "plans_off", has: hasFree }),
      "Plan: Free (default), once plans are on",
    ],
    ["no Plan yet while Plans are off", person({ basis: "plans_off" }), "Plan: the default, once plans are on"],
    ["an administrator who has no Plan", person({ basis: "administrator" }), "No plan limits administrators"],
    [
      "an administrator who has the Default Plan",
      person({ basis: "administrator", has: hasFree }),
      "Plan: Free (default). No plan limits administrators",
    ],
    [
      "an administrator given a Plan",
      person({ basis: "administrator", assigned: familyName, has: hasFamily }),
      "Plan: Family. No plan limits administrators",
    ],
  ])("names %s, as the Plans tab counts who has it", (_case, plan, fact) => {
    expect(personPlanFact(i18n, plan, plan.basis === "administrator")).toBe(fact)
  })

  it.each<[string, PersonPlanOverview, string]>([
    ["no Plan", person({ basis: "plans_off" }), "No plan limits administrators"],
    ["the Default Plan", person({ basis: "plans_off", has: hasFree }), "Plan: Free (default). No plan limits administrators"],
    [
      "a Plan of their own",
      person({ basis: "plans_off", assigned: familyName, has: hasFamily }),
      "Plan: Family. No plan limits administrators",
    ],
  ])("says no plan limits an administrator with %s while Plans are off", (_case, plan, fact) => {
    expect(personPlanFact(i18n, plan, true)).toBe(fact)
  })

  it.each<[string, OverLimit[], string]>([
    [
      "one limit",
      [{ limit: "connected_accounts", in_use: 2, allowed: 1 }],
      "Plan: Family. 2 calendar accounts, 1 allowed",
    ],
    [
      "each limit, rules first, and tokens a Plan includes none of",
      [
        { limit: "rules", in_use: 3, allowed: 2 },
        { limit: "connected_accounts", in_use: 2, allowed: 1 },
        { limit: "integration_tokens", in_use: 2, allowed: 0 },
      ],
      "Plan: Family. 3 rules, 2 allowed. 2 calendar accounts, 1 allowed. 2 Integration Tokens, none allowed",
    ],
    [
      "one of a count",
      [{ limit: "integration_tokens", in_use: 1, allowed: 0 }],
      "Plan: Family. 1 Integration Token, none allowed",
    ],
  ])("says how much they have and how much is allowed past %s", (_case, over, fact) => {
    const plan = person({ plan: hasFamily, assigned: familyName, has: hasFamily, over })
    expect(personPlanFact(i18n, plan, false)).toBe(fact)
  })

  it("says what a person has past a limit while Plans are off, as turning them on would find it", () => {
    const plan = person({ basis: "plans_off", has: hasFree, over: [{ limit: "rules", in_use: 2, allowed: 1 }] })
    expect(personPlanFact(i18n, plan, false)).toBe("Plan: Free (default), once plans are on. 2 rules, 1 allowed")
  })
})
