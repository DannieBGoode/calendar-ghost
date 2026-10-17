import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"
import type { PeoplePage, PersonRow, PlanAssignments, PlanMove, PlanSummary } from "@/lib/api"
import {
  FOLLOW_DEFAULT,
  assignCandidates,
  assignedResult,
  changeChoices,
  changeConfirm,
  changeResult,
  changedResult,
  chosenPlan,
  heldPlanLine,
  overNote,
  restoredResult,
  undoMoves,
  wouldBeOver,
} from "@/lib/plan-assignment"

const i18n = testI18n()

type Held = { key: string; name: string; on_default: boolean } | null

function person(email: string | null, has: Held, role: PersonRow["role"] = "user"): PersonRow {
  return {
    id: `user-${(email ?? "first").split("@")[0]}`,
    email,
    role,
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

function page(people: PersonRow[], total = people.length): PeoplePage {
  return { users: people, total, page: 1, page_size: 100 }
}

const NO_LIMITS = { key: "no-limits", name: "No limits", on_default: true }
const PRO = { key: "pro", name: "Pro", on_default: false }
const FREE = { key: "free", name: "Free", on_default: false }

function move(email: string, had: Held, has: Held = FREE): PlanMove {
  return { user_id: `user-${email.split("@")[0]}`, email, had, has, over: [] }
}

function answer(people: PlanMove[], dryRun = false): PlanAssignments {
  return { dry_run: dryRun, people }
}

describe("assignCandidates", () => {
  it("lists who does not have the plan yet, administrators apart, in the order found", () => {
    const found = assignCandidates(
      page([
        person("alex@example.test", NO_LIMITS),
        person("dana@example.test", NO_LIMITS, "installation_administrator"),
        person("jordan@example.test", FREE),
        person("robin@example.test", { ...FREE, on_default: true }),
        person("sam@example.test", PRO),
        person("zoe@example.test", null),
      ]),
      "free",
    )
    expect(found.members.map((member) => member.email)).toEqual(["alex@example.test", "sam@example.test", "zoe@example.test"])
    expect(found.administrators.map((administrator) => administrator.email)).toEqual(["dana@example.test"])
    expect(found.more).toBe(false)
  })

  it("says when more people match than one page lists", () => {
    expect(assignCandidates(page([person("alex@example.test", NO_LIMITS)], 101), "free").more).toBe(true)
  })
})

describe("heldPlanLine", () => {
  it.each([
    [NO_LIMITS, "Has No limits, the default"],
    [PRO, "Has Pro"],
    [null, "Has no plan"],
  ])("says which plan someone has now: %o", (has, words) => {
    expect(heldPlanLine(i18n, person("alex@example.test", has))).toBe(words)
  })
})

describe("wouldBeOver", () => {
  it("names each limit someone would have more of, or nothing", () => {
    expect(wouldBeOver(i18n, [])).toBeNull()
    expect(wouldBeOver(i18n, [{ limit: "rules", in_use: 3, allowed: 1 }])).toBe("Would be over: 3 rules, 1 allowed")
    expect(
      wouldBeOver(i18n, [
        { limit: "rules", in_use: 4, allowed: 1 },
        { limit: "integration_tokens", in_use: 1, allowed: 0 },
      ]),
    ).toBe("Would be over: 4 rules, 1 allowed and 1 Integration Token, none allowed")
  })
})

describe("overNote", () => {
  it("says what having more than the plan allows means, for one person by email or for several", () => {
    expect(overNote(i18n, [], "Free")).toBeNull()
    expect(overNote(i18n, ["alex@example.test"], "Free")).toBe(
      "alex@example.test will have more than Free allows. Everything they have keeps working, but they can't add more until they are within it.",
    )
    expect(overNote(i18n, ["alex@example.test", "sam@example.test"], "Free")).toBe(
      "2 people you chose will have more than Free allows. Everything they have keeps working, but they can't add more until they are within it.",
    )
  })
})

describe("assignedResult", () => {
  it("names one person, and counts several", () => {
    expect(assignedResult(i18n, answer([move("alex@example.test", NO_LIMITS)]), "Free")).toBe("alex@example.test now has Free.")
    expect(
      assignedResult(i18n, answer([move("alex@example.test", NO_LIMITS), move("sam@example.test", PRO)]), "Free"),
    ).toBe("2 people now have Free.")
  })
})

describe("undoMoves", () => {
  it("gives each person back the plan they had: their own, or the default by having none", () => {
    expect(
      undoMoves(
        answer([
          move("alex@example.test", NO_LIMITS),
          move("sam@example.test", PRO),
          move("zoe@example.test", null),
          move("lee@example.test", PRO),
        ]),
      ),
    ).toEqual([
      { plan: null, userIds: ["user-alex", "user-zoe"] },
      { plan: "pro", userIds: ["user-sam", "user-lee"] },
    ])
  })
})

describe("restoredResult", () => {
  it("names one person, and counts several", () => {
    expect(restoredResult(i18n, answer([move("alex@example.test", NO_LIMITS)]))).toBe("alex@example.test has their plan back.")
    expect(restoredResult(i18n, answer([move("alex@example.test", NO_LIMITS), move("sam@example.test", PRO)]))).toBe(
      "2 people have their plans back.",
    )
  })
})

/** Plans as Change plan offers them: the default first, then the others as listed. */
function plan(key: string, name: string, isDefault = false): PlanSummary {
  return {
    key,
    name,
    limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
    is_default: isDefault,
    people: 0,
    limited_people: 0,
    over_people: 0,
    use: { rules: [], connected_accounts: [], integration_tokens: [] },
  }
}

const FREE_PLAN = plan("free", "Free")
const DEFAULT_PLAN = { ...plan("no-limits", "No limits", true), limits: { rules: null, connected_accounts: null, integration_tokens: null, sync_interval: "instant" as const } }

describe("Change plan", () => {
  it("offers following the default first, naming it, then each plan with what it allows, what they have marked Current", () => {
    const robin = person("robin@example.test", { key: "free", name: "Free", on_default: false })
    expect(changeChoices(i18n, [FREE_PLAN, DEFAULT_PLAN], robin)).toEqual([
      {
        value: FOLLOW_DEFAULT,
        title: "Follow the default plan",
        description: "No limits now. If the default changes, so does theirs.",
      },
      { value: "no-limits", title: "No limits", description: "Unlimited, with Instant sync." },
      {
        value: "free",
        title: "Free",
        description: "1 active rule, 1 calendar account, no Integration Tokens, every 5 minutes.",
        unavailable: "Current",
      },
    ])
  })

  it("marks following the default Current for someone with no plan of their own, and says when none is the default", () => {
    const alex = person("alex@example.test", { key: "no-limits", name: "No limits", on_default: true })
    const [follow] = changeChoices(i18n, [FREE_PLAN], alex)
    expect(follow).toEqual({
      value: FOLLOW_DEFAULT,
      title: "Follow the default plan",
      description: "No plan is the default yet.",
      unavailable: "Current",
    })
    expect(changeChoices(i18n, [FREE_PLAN], person("lee@example.test", null))[0]?.unavailable).toBe("Current")
  })

  it("finds the plan a choice gives, the default's for following it", () => {
    expect(chosenPlan([FREE_PLAN, DEFAULT_PLAN], "free")).toBe(FREE_PLAN)
    expect(chosenPlan([FREE_PLAN, DEFAULT_PLAN], FOLLOW_DEFAULT)).toBe(DEFAULT_PLAN)
    expect(chosenPlan([FREE_PLAN], FOLLOW_DEFAULT)).toBeUndefined()
  })

  it("says what the dry run found, and nothing before it answers", () => {
    const robin = person("robin@example.test", null)
    expect(changeResult(i18n, robin, FREE_PLAN, undefined)).toBe("")
    expect(changeResult(i18n, robin, undefined, [])).toBe("")
    expect(changeResult(i18n, robin, FREE_PLAN, [])).toBe("robin@example.test is within every limit of Free.")
    expect(changeResult(i18n, robin, FREE_PLAN, [{ limit: "rules", in_use: 3, allowed: 1 }])).toBe(
      "robin@example.test will have more than Free allows. Everything they have keeps working, but they can't add more until they are within it.",
    )
  })

  it("names what confirming does, and what it did", () => {
    const robin = person("robin@example.test", null)
    expect(changeConfirm(i18n, robin, null, undefined)).toBe("Change plan")
    expect(changeConfirm(i18n, robin, FOLLOW_DEFAULT, DEFAULT_PLAN)).toBe("Move robin@example.test to the default plan")
    expect(changeConfirm(i18n, robin, "free", FREE_PLAN)).toBe("Give Free to robin@example.test")
    expect(changedResult(i18n, robin, FREE_PLAN)).toBe("robin@example.test now has Free.")
    expect(changedResult(i18n, robin, null)).toBe("robin@example.test now follows the default plan.")
  })
})
