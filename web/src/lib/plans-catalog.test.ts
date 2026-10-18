import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"
import type { PeoplePage, PersonRow, PlanSummary, PlansOverview } from "@/lib/api"
import {
  compactStatusSentence,
  countCell,
  makeDefaultHint,
  overPeople,
  removeRefusal,
  settingResult,
  speedLabel,
  statusFacts,
  statusSentence,
  switchedBy,
  undoOf,
} from "@/lib/plans-catalog"

const i18n = testI18n()

const NO_USE: PlanSummary["use"] = { rules: [], connected_accounts: [], integration_tokens: [] }

const free: PlanSummary = {
  key: "free",
  name: "Free",
  limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
  is_default: false,
  people: 2,
  limited_people: 2,
  over_people: 1,
  use: NO_USE,
}
const pro: PlanSummary = {
  key: "pro",
  name: "Pro",
  limits: { rules: null, connected_accounts: null, integration_tokens: null, sync_interval: "instant" },
  is_default: false,
  people: 1,
  limited_people: 1,
  over_people: 0,
  use: NO_USE,
}
/** The Plan the server makes the default when Plans turn on with none: it limits nothing. */
const noLimits: PlanSummary = { ...pro, key: "no-limits", name: "No limits", people: 2, limited_people: 1 }

function overview({
  enabled = true,
  defaultPlan = "no-limits",
  plans = [noLimits, free, pro],
  followers = 2,
}: {
  enabled?: boolean
  defaultPlan?: string | null
  plans?: PlanSummary[]
  followers?: number
} = {}): PlansOverview {
  return {
    enabled,
    default_plan: defaultPlan,
    sync_intervals: ["instant", "5_minutes"],
    followers,
    plans: plans.map((plan) => ({ ...plan, is_default: plan.key === defaultPlan })),
  }
}

function person(email: string): PersonRow {
  return {
    id: `user-${email}`,
    email,
    role: "user",
    state: "active",
    created_at: "2026-10-01T09:00:00Z",
    last_sign_in_at: null,
    verdict: "healthy",
    problems: 0,
    last_synced_at: null,
    resources: { rules: 0, connected_accounts: 0, activity_entries: 0, provider_calls: [], since: "2026-09-10" },
    plan: null,
  }
}

function holders(emails: string[], total = emails.length): PeoplePage {
  return { users: emails.map(person), total, page: 1, page_size: 3 }
}

describe("countCell", () => {
  it("says a count as a number, no limit as Unlimited, muted, and zero as None, a limit in ink as numbers are", () => {
    expect(countCell(i18n, 1200)).toEqual({ text: "1,200", muted: false })
    expect(countCell(i18n, null)).toEqual({ text: "Unlimited", muted: true })
    expect(countCell(i18n, 0)).toEqual({ text: "None", muted: false })
  })
})

describe("speedLabel", () => {
  it.each([
    ["instant", "Instant"],
    ["5_minutes", "Every 5 min"],
    ["10_minutes", "Every 10 min"],
    ["15_minutes", "Every 15 min"],
    ["30_minutes", "Every 30 min"],
    ["60_minutes", "Every hour"],
  ] as const)("says %s in a table cell's words", (interval, words) => {
    expect(speedLabel(i18n, interval)).toBe(words)
  })
})

describe("overPeople", () => {
  it("adds up the people each Plan limits who have more than it allows", () => {
    expect(overPeople([free, { ...pro, over_people: 2 }])).toBe(3)
    expect(overPeople([])).toBe(0)
  })
})

describe("statusSentence", () => {
  it("says what a limit does while on, and who gets the default, never a count or a name the facts show", () => {
    const on = "People can't add more than their plan allows. Anyone without a plan of their own, including people who join later, gets the default plan."
    expect(statusSentence(i18n, overview())).toBe(on)
    expect(statusSentence(i18n, overview({ plans: [noLimits, { ...free, limited_people: 1 }] }))).toBe(on)
    expect(statusSentence(i18n, overview({ plans: [noLimits] }))).toBe(on)
  })

  it("says what the switch does while off, whatever the facts count", () => {
    const off = "Nobody is limited. Turning plans on applies each person's plan at once."
    expect(statusSentence(i18n, overview({ enabled: false }))).toBe(off)
    expect(statusSentence(i18n, overview({ enabled: false, plans: [noLimits, { ...free, over_people: 2 }] }))).toBe(off)
    expect(statusSentence(i18n, overview({ enabled: false, plans: [noLimits] }))).toBe(off)
  })

  it("says turning plans on adds No limits when there is no default", () => {
    expect(statusSentence(i18n, overview({ enabled: false, defaultPlan: null, plans: [{ ...free, over_people: 0 }] }))).toBe(
      "Nobody is limited. Turning plans on applies each person's plan at once, and adds a plan named <strong>No limits</strong> as the default for everyone without a plan of their own.",
    )
    expect(statusSentence(i18n, overview({ enabled: false, defaultPlan: null, plans: [] }))).toBe(
      "Everyone can use everything, with no limits. Turning plans on adds a plan named <strong>No limits</strong> as the default, so nobody is limited until you give someone a smaller plan.",
    )
  })
})

describe("compactStatusSentence", () => {
  it("says in fewer words whom Plans limit, and what everyone else gets, beside an open panel", () => {
    expect(compactStatusSentence(i18n, overview())).toBe(
      "They limit <strong>2 people</strong>. People without a plan get <strong>No limits</strong>.",
    )
    expect(compactStatusSentence(i18n, overview({ plans: [noLimits] }))).toBe(
      "They limit nobody. People without a plan get <strong>No limits</strong>.",
    )
    expect(compactStatusSentence(i18n, overview({ enabled: false }))).toBe(
      "Everyone can use everything. Turning plans on limits <strong>2 people</strong> right away, and 1 of them has more than their plan allows.",
    )
    expect(compactStatusSentence(i18n, overview({ enabled: false, defaultPlan: null, plans: [] }))).toBe(
      "Everyone can use everything, with no limits.",
    )
  })
})

describe("statusFacts", () => {
  it("states whom Plans limit, who is over, and the default, while on", () => {
    expect(statusFacts(i18n, overview())).toEqual([
      { id: "limited", label: "Limited now", value: "2 people", attention: false, over: 0, secondary: false },
      { id: "over", label: "Over a limit", value: "1 person", attention: true, over: 1, secondary: false },
      { id: "default", label: "Default plan", value: "No limits", attention: false, over: 0, secondary: true },
    ])
  })

  it("says what Plans would do while off, all neutral, and when nobody is limited or over", () => {
    expect(statusFacts(i18n, overview({ enabled: false, defaultPlan: null, plans: [noLimits] }))).toEqual([
      { id: "limited", label: "Would limit", value: "Nobody", attention: false, over: 0, secondary: false },
      { id: "over", label: "Would be over a limit", value: "Nobody", attention: false, over: 0, secondary: false },
      { id: "default", label: "Default plan", value: "None yet", attention: false, over: 0, secondary: true },
    ])
    expect(statusFacts(i18n, overview({ enabled: false }))[1]).toEqual({
      id: "over",
      label: "Would be over a limit",
      value: "1 person",
      attention: false,
      over: 1,
      secondary: false,
    })
  })
})

describe("makeDefaultHint", () => {
  /** No limits is the default, which `followers` follow and `given` were given as their own plan. */
  function given(followers: number, given = 0): PlansOverview {
    return overview({ plans: [{ ...noLimits, people: followers + given }, free, pro], followers })
  }

  it("says whom Make default moves, and how many they are now", () => {
    expect(makeDefaultHint(i18n, free, given(2))).toBe("People without a plan of their own (2 now) move to Free.")
    expect(makeDefaultHint(i18n, free, given(1))).toBe("People without a plan of their own (1 now) move to Free.")
    expect(makeDefaultHint(i18n, free, given(0))).toBe("Everyone has a plan of their own now. People who join later get Free.")
  })

  it("names who keeps the default they were given as their own plan, since only those without one move", () => {
    expect(makeDefaultHint(i18n, free, given(2, 1))).toBe(
      "People without a plan of their own (2 now) move to Free. 1 person keeps No limits, which was given to them.",
    )
    expect(makeDefaultHint(i18n, free, given(0, 2))).toBe(
      "Everyone has a plan of their own now. People who join later get Free. 2 people keep No limits, which was given to them.",
    )
  })

  it("says whom it moves without a number, never that nobody is moved, when the server did not count them", () => {
    const older: Partial<PlansOverview> = given(2, 1)
    delete older.followers
    expect(makeDefaultHint(i18n, free, older as PlansOverview)).toBe("People without a plan of their own move to Free.")
  })
})

describe("removeRefusal", () => {
  it("counts who has a Plan until their names arrive, or when they cannot", () => {
    expect(removeRefusal(i18n, free, undefined)).toBe("2 people have Free. Give them another plan first.")
    expect(removeRefusal(i18n, { ...free, people: 1 }, holders([]))).toBe("1 person has Free. Give them another plan first.")
  })

  it.each([
    [["robin@example.test"], 1, "robin@example.test has Free. Give them another plan first."],
    [["robin@example.test", "sam@example.test"], 2, "robin@example.test and sam@example.test have Free. Give them another plan first."],
    [
      ["ada@example.test", "robin@example.test", "sam@example.test"],
      5,
      "ada@example.test, robin@example.test, sam@example.test, and 2 more have Free. Give them another plan first.",
    ],
  ])("names the first three who have a Plan (%j of %i)", (emails, total, reason) => {
    expect(removeRefusal(i18n, { ...free, people: total }, holders(emails, total))).toBe(reason)
  })
})

describe("settingResult", () => {
  it("says whom Plans limit once on", () => {
    expect(settingResult(i18n, overview({ enabled: false }), overview())).toBe("Plans are on. They limit 2 people.")
    expect(settingResult(i18n, overview({ enabled: false, plans: [noLimits] }), overview({ plans: [noLimits] }))).toBe(
      "Plans are on. They limit nobody yet.",
    )
  })

  it("names the No limits plan the server made the default when there was none", () => {
    const before = overview({ enabled: false, defaultPlan: null, plans: [free] })
    expect(settingResult(i18n, before, overview({ plans: [noLimits, free] }))).toBe(
      "Plans are on. No limits is the default plan, and it limits nobody.",
    )
  })

  it("says nobody is limited once off, and names a new default", () => {
    expect(settingResult(i18n, overview(), overview({ enabled: false }))).toBe("Plans are off. Nobody is limited.")
    expect(settingResult(i18n, overview(), overview({ defaultPlan: "free" }))).toBe("Free is the default plan now.")
  })
})

describe("undoOf", () => {
  it("presses the switch again, keeping the default the server has now", () => {
    // Turning on with no default made No limits the default; Undo keeps it rather than make another.
    const before = overview({ enabled: false, defaultPlan: null, plans: [free] })
    expect(undoOf(before, overview({ plans: [noLimits, free] }))).toEqual({ enabled: false, defaultPlan: "no-limits" })
    expect(undoOf(overview(), overview({ enabled: false }))).toEqual({ enabled: true, defaultPlan: "no-limits" })
  })

  it("gives the default back, keeping whether Plans are on", () => {
    expect(undoOf(overview(), overview({ defaultPlan: "free" }))).toEqual({ enabled: true, defaultPlan: "no-limits" })
    expect(undoOf(overview({ enabled: false, defaultPlan: null }), overview({ enabled: false, defaultPlan: "free" }))).toEqual({
      enabled: false,
      defaultPlan: null,
    })
  })
})

describe("switchedBy", () => {
  it("tells the switch's change, which asks for another state, from Make default's", () => {
    expect(switchedBy({ enabled: false, defaultPlan: "no-limits" }, overview())).toBe(true)
    expect(switchedBy({ enabled: true, defaultPlan: "free" }, overview())).toBe(false)
    expect(switchedBy(undefined, overview())).toBe(false)
  })
})
