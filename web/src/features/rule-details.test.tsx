/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { EndpointFields } from "./calendar-replacement"
import { RuleDetailsView } from "./rule-details"
import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { ConnectedAccount, DiscoveredCalendar, OwnPlan, RuleDetail, RunOutcome } from "@/lib/api"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const account: ConnectedAccount = {
  id: "personal",
  display_name: "Daniel Calatayud",
  email: "daniel@example.com",
  provider: "google",
  avatar_url: null,
  state: "connected",
  rule_count: 1,
  authorized_at: "2026-10-02T00:00:00Z",
  authorization_lapsed_at: null,
}

const partner: ConnectedAccount = {
  id: "partner",
  provider: "google",
  display_name: "Partner Calendar",
  email: "partner@example.test",
  avatar_url: null,
  state: "connected",
  rule_count: 1,
  authorized_at: "2026-10-02T00:00:00Z",
  authorization_lapsed_at: null,
}

const writableCalendar: DiscoveredCalendar = {
  id: "work@example.test",
  summary: "Work",
  access_role: "owner",
  writable: true,
  primary: true,
}

const readOnlyCalendar: DiscoveredCalendar = {
  id: "holidays@example.test",
  summary: "Holidays",
  access_role: "reader",
  writable: false,
  primary: false,
}

const familyCalendar: DiscoveredCalendar = { id: "family", summary: "Family", writable: true, primary: true, access_role: "owner" }
const errandsCalendar: DiscoveredCalendar = { id: "errands", summary: "Errands", writable: true, primary: false, access_role: "owner" }

// Every time below is a few seconds before "now", so `format.relative` resolves to the catalog's
// "just now" instead of a raw Intl.RelativeTimeFormat phrase that bypasses the pseudo locale.
const now = Date.now()
const justNow = new Date(now - 10_000).toISOString()

const succeeded: RunOutcome = {
  completed_at: justNow,
  succeeded: true,
  full_run: false,
  created: 1,
  updated: 2,
  deleted: 0,
  conflicts: 1,
  checked_mappings: 3,
  drift: 2,
  failure_kind: null,
  failure_provider: null,
  last_succeeded_at: null,
}

const enabledRule: RuleDetail = {
  id: "rule-1",
  source: { connected_account_id: account.id, calendar_id: familyCalendar.id, calendar_name: "Family" },
  destination: { connected_account_id: partner.id, calendar_id: writableCalendar.id, calendar_name: "Work" },
  privacy_policy: "busy_only",
  sync_all_day_events: true,
  tentative_events: "mark",
  unanswered_invitations: "wait",
  sync_birthdays: false,
  state: "enabled",
  reprojection_required: false,
  stop_cause: null,
  initial_lookback_days: 30,
  mapping_count: 3,
  last_sync: succeeded,
  last_reconciliation: succeeded,
  latest_preview: null,
  running: null,
  effective_cadence: "instant",
  poll_every_minutes: 5,
  can_start: true,
  held_rules: 0,
  rule_limit: null,
  keeps_place: false,
}

/** Someone whose rules count past their plan's limit, so a rule they stop may not start again. */
const overTheLimit: OwnPlan = {
  basis: "plan",
  plan: { key: "free", name: "Free", on_default: true },
  limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
  rules_counted: 3,
  held_rules: 0,
  grace: null,
  rules: [],
  connected_accounts: 2,
  integration_tokens: 0,
  instant: false,
  poll_every_minutes: 5,
  may_connect_account: false,
  may_issue_token: false,
  over_rule_limit: true,
}

/**
 * Account names, emails, calendar names, avatar initials, the timestamp the run facts show as a
 * tooltip (locale data from `format.dateTime`, not catalog text), and backend-written titles.
 */
const FIXTURE_TEXT = [
  account.display_name,
  account.email,
  partner.display_name,
  partner.email,
  "Work",
  "Holidays",
  "Family",
  "Errands",
  "DC",
  "PC",
  testI18n().format.dateTime(justNow),
  // The literal titles domain/services.py writes to Google Calendar for tentative events; they are
  // data passed as message parameters, never translated.
  "Busy (tentative)",
  "Maybe:",
]

let container: HTMLDivElement
let root: Root | null = null

beforeEach(() => {
  container = document.createElement("div")
  document.body.append(container)
})

afterEach(() => {
  if (root) {
    act(() => root?.unmount())
    root = null
  }
  container.remove()
  vi.restoreAllMocks()
})

function renderFields(i18n: I18n, writableOnly: boolean) {
  return renderToStaticMarkup(
    <StaticI18nProvider i18n={i18n}>
      <EndpointFields
        legend={writableOnly ? "Destination calendar" : "Source calendar"}
        idPrefix={writableOnly ? "replace-destination" : "replace-source"}
        accounts={[account]}
        account={account.id}
        calendar={writableCalendar.id}
        calendars={[writableCalendar, readOnlyCalendar]}
        writableOnly={writableOnly}
        onAccount={() => undefined}
        onCalendar={() => undefined}
      />
    </StaticI18nProvider>,
  )
}

describe("EndpointFields", () => {
  it("keeps a read-only calendar selectable as a Source Calendar", () => {
    const markup = renderFields(testI18n(), false)

    expect(markup).toContain(`value="${writableCalendar.id}"`)
    expect(markup).toContain(`value="${readOnlyCalendar.id}"`)
    expect(markup).toContain(readOnlyCalendar.summary)
  })

  it("excludes a read-only calendar from the Destination Calendar options", () => {
    const markup = renderFields(testI18n(), true)

    expect(markup).toContain(`value="${writableCalendar.id}"`)
    expect(markup).not.toContain(`value="${readOnlyCalendar.id}"`)
    expect(markup).not.toContain(readOnlyCalendar.summary)
  })
})

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

function mockFetch(rule: RuleDetail | null, ownPlan: Response = jsonResponse({})) {
  const calendars: Record<string, DiscoveredCalendar[]> = {
    [account.id]: [familyCalendar, errandsCalendar],
    [partner.id]: [writableCalendar, readOnlyCalendar],
  }
  vi.stubGlobal("fetch", vi.fn((input: string | URL) => Promise.resolve(respond(String(input)))))
  function respond(url: string): Response {
    const path = url.split("?")[0] ?? ""
    if (path === "/api/v1/accounts") return jsonResponse([account, partner])
    if (path === "/api/v1/account/plan") return ownPlan
    const calendarMatch = /^\/api\/v1\/accounts\/(.+)\/calendars$/.exec(path)
    if (calendarMatch) return jsonResponse(calendars[decodeURIComponent(calendarMatch[1] ?? "")] ?? [])
    if (path.startsWith("/api/v1/rules/")) {
      return rule ? jsonResponse(rule) : jsonResponse({ detail: "sync rule does not exist", code: "rule_not_found", params: {} }, 404)
    }
    return jsonResponse({})
  }
}

async function settle(times = 6) {
  for (let i = 0; i < times; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

async function renderDetails(
  i18n: I18n,
  rule: RuleDetail | null,
  notice: string | null = null,
  ownPlan: Response = jsonResponse({}),
) {
  mockFetch(rule, ownPlan)
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <RuleDetailsView ruleId="rule-1" notice={notice} onViewChange={() => undefined} onOpenRule={() => undefined} onOpenRulePreview={() => undefined} />
        </QueryClientProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
  return container
}

function click(element: Element | null) {
  if (!element) throw new Error("missing element")
  act(() => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
  })
}

function choose(selector: string, value: string) {
  const select = container.querySelector<HTMLSelectElement>(selector)!
  act(() => {
    select.value = value
    select.dispatchEvent(new Event("change", { bubbles: true }))
  })
}

describe("RuleDetailsView", () => {
  it.each(["plans_off", "administrator", "unlimited"])("shows pending release without a keep step with %s", async (basis) => {
    await renderDetails(testI18n(), { ...enabledRule, state: "degraded", stop_cause: "plan_hold" }, null, jsonResponse({ ...overTheLimit, basis: basis === "unlimited" ? "plan" : basis, limits: basis === "unlimited" ? { ...overTheLimit.limits, rules: null } : null, held_rules: 1 }))
    expect(container.textContent).toContain("Resumes at the next scheduled check.")
    expect(container.querySelector('a[href="/settings/account#your-plan"]')).toBeNull()
    expect(container.textContent).not.toContain("Preview to restart")
  })

  it("offers Your plan Retry when its read fails without replacing the hold by recovery", async () => {
    await renderDetails(testI18n(), { ...enabledRule, state: "degraded", stop_cause: "plan_hold" }, null, jsonResponse({}, 500))
    expect(container.querySelector('a[href="/settings/account#your-plan"]')?.textContent).toBe("See your plan")
    expect(container.textContent).toContain("Held by your plan")
    expect(container.textContent).not.toContain("Preview to restart")
  })

  it("warns before a policy edit while held rules wait within the limit", async () => {
    await renderDetails(testI18n(), enabledRule, null, jsonResponse({ ...overTheLimit, rules_counted: 1, held_rules: 1, over_rule_limit: false }))
    click(container.querySelector('[aria-controls="policy-form"]'))
    expect(container.querySelector("#policy-form")?.textContent).toContain("Your plan may not let this rule start again.")
  })

  it("shows the hold and ordinary Preview and Pause without recovery commands", async () => {
    await renderDetails(testI18n(), { ...enabledRule, state: "degraded", stop_cause: "plan_hold" }, null, jsonResponse(overTheLimit))
    expect(container.textContent).toContain("Held by your plan")
    expect(container.textContent).toContain("Resumes by itself when your plan has room.")
    expect([...container.querySelectorAll("a")].filter((a) => a.textContent === "Choose which rules sync")).toHaveLength(1)
    expect(container.textContent).not.toContain("Preview to restart")
    click(container.querySelector("button[aria-haspopup=menu]"))
    expect(container.querySelector("[role=menu]")?.textContent).toContain("Preview")
    expect(container.querySelector("[role=menu]")?.textContent).toContain("Pause rule")
    expect(container.querySelector("[role=menu]")?.textContent).not.toMatch(/Sync now|Reconcile now/)
  })

  it("test_policy_edit_ends_automatic_plan_release", async () => {
    await renderDetails(testI18n(), { ...enabledRule, state: "degraded", stop_cause: "plan_hold" })
    click([...container.querySelectorAll("button")].find((button) => button.textContent === "Change policy") ?? null)
    choose("#edit-privacy-policy", "copy_details")
    expect(container.textContent).toContain("The plan hold ends. This rule will no longer resume by itself. Preview it, then start it within your plan's rule limit.")
  })

  it("renders the rule's facts, runs, and commands in English", async () => {
    await renderDetails(testI18n(), enabledRule)

    expect(container.querySelector("h1")?.textContent).toContain("Family")
    const runs = container.querySelector("[aria-labelledby='rule-runs-title']")
    expect(runs?.textContent).toContain("Projections3 in WorkThe events this rule wrote to Work, each kept matching its source in Family.")
    expect(container.textContent).toContain("Includes events from the past 30 days onward")
    expect(container.querySelector(".rule-facts-groups")?.textContent).toContain("Birthdays from contactsNot synced")
    expect(container.textContent).toContain("Succeeded: 1 created, 2 updated, 0 deleted, 1 conflict")
    expect(container.textContent).toContain(
      "Checked 3 projections: 2 differences found; none were changed. 1 conflict blocked",
    )
    expect(container.querySelector('[aria-label="More actions for Family to Work"]')).not.toBeNull()
  })

  it("groups the rule's choices as its policy form does, each with the icon Rule Preview shows", async () => {
    await renderDetails(testI18n(), enabledRule)

    const groups = [...container.querySelectorAll(".rule-facts-groups > dl")]
    const labels = groups.map((group) =>
      [...group.querySelectorAll("dt")].map((label) => [label.textContent, label.querySelector("svg[aria-hidden=true]")?.classList[1]]),
    )
    expect(labels).toEqual([
      [
        ["Event information", "lucide-file-text"],
        ["Events you answered Maybe", "lucide-circle-question-mark"],
        ["Invitations you haven't answered", "lucide-mail-question-mark"],
        ["Declined events", "lucide-circle-x"],
      ],
      [
        ["All-day events", "lucide-calendar-days"],
        ["Birthdays from contacts", "lucide-cake"],
        ["Starting point", "lucide-rotate-ccw-clock"],
      ],
    ])
  })

  it("says when the rule keeps no projections, whether or not it wrote any before", async () => {
    await renderDetails(testI18n(), { ...enabledRule, mapping_count: 0 })

    expect(container.querySelector("[aria-labelledby='rule-runs-title']")?.textContent).toContain("ProjectionsNone in Work")
  })

  it("says how soon the rule syncs, and why it waits for its schedule", async () => {
    await renderDetails(testI18n(), enabledRule)
    const runs = () => container.querySelector<HTMLElement>("[aria-labelledby='rule-runs-title']")!
    expect(runs().textContent).toContain(
      "When it syncsSyncs instantlyRuns soon after a change in Family, and checks every 5 minutes as well.",
    )
    expect(runs().querySelector("a[href*='instant-sync']")).toBeNull()

    act(() => root?.unmount())
    root = null
    await renderDetails(testI18n(), { ...enabledRule, effective_cadence: "waiting_for_provider" })
    expect(runs().textContent).toContain(
      "When it syncsSyncs every 5 minutesInstant sync starts once the calendar provider confirms it will report changes in Family.",
    )
    const help = runs().querySelector("a[href*='instant-sync']")
    expect(help?.textContent).toBe("Learn why (opens in a new tab)")
    expect(help?.getAttribute("href")).toBe("https://calendarghost.com/docs/instant-sync#waiting-for-the-provider")

    act(() => root?.unmount())
    root = null
    await renderDetails(testI18n(), { ...enabledRule, effective_cadence: "off_by_user" })
    expect(runs().textContent).toContain("Syncs every 5 minutesYou turned instant sync off in Settings.")
    expect(runs().querySelector("a[href*='instant-sync']")).toBeNull()

    act(() => root?.unmount())
    root = null
    await renderDetails(testI18n(), { ...enabledRule, effective_cadence: "not_in_plan", poll_every_minutes: 15 })
    expect(runs().textContent).toContain("Syncs every 15 minutesYour plan does not include instant sync.")

    act(() => root?.unmount())
    root = null
    await renderDetails(testI18n(), { ...enabledRule, effective_cadence: "not_in_plan", poll_every_minutes: 60 })
    expect(runs().textContent).toContain("Syncs every hourYour plan does not include instant sync.")
  })

  it("says nothing about how soon a rule syncs until it is enabled", async () => {
    await renderDetails(testI18n(), { ...enabledRule, state: "paused" })
    expect(container.textContent).not.toContain("When it syncs")
  })

  it("warns before a privacy edit that the plan may not let the rule start again, while more rules count than it allows", async () => {
    await renderDetails(testI18n(), enabledRule, null, jsonResponse(overTheLimit))
    click(container.querySelector('[aria-controls="policy-form"]'))

    const note = container.querySelector("#policy-form .field-hint[data-tone='attention']")
    expect(note?.textContent).toBe("Your plan may not let this rule start again.")
    // Beside Save: the note comes right before the form's actions.
    expect(note?.nextElementSibling?.classList.contains("form-actions")).toBe(true)
  })

  it("warns before editing a stopped rule too, which may still count", async () => {
    await renderDetails(testI18n(), { ...enabledRule, state: "degraded" }, null, jsonResponse(overTheLimit))
    click(container.querySelector('[aria-controls="policy-form"]'))
    expect(container.querySelector("#policy-form")?.textContent).toContain("Your plan may not let this rule start again.")
  })

  it("says nothing about the plan before editing a paused rule, which no longer counts", async () => {
    await renderDetails(testI18n(), { ...enabledRule, state: "paused" }, null, jsonResponse(overTheLimit))
    click(container.querySelector('[aria-controls="policy-form"]'))
    expect(container.querySelector("#policy-form")).not.toBeNull()
    expect(container.querySelector("#policy-form")?.textContent).not.toContain("Your plan")
  })

  it.each([
    ["names no plan", jsonResponse({})],
    ["cannot be read", jsonResponse({ detail: "database is locked" }, 500)],
  ])("says nothing about the plan before a privacy edit when the own plan %s", async (_case, ownPlan) => {
    await renderDetails(testI18n(), enabledRule, null, ownPlan)
    click(container.querySelector('[aria-controls="policy-form"]'))
    expect(container.querySelector("#policy-form")).not.toBeNull()
    expect(container.querySelector("#policy-form")?.textContent).not.toContain("Your plan")
  })

  describe("a previewed rule the plan will not let start", () => {
    const previewed: RuleDetail = {
      ...enabledRule,
      state: "dry_run_validated",
      latest_preview: { completed_at: justNow, eligible_events: 3, excluded_events: 0, recurring_series: 0, occurrence_changes: 0 },
    }
    /** At the rule limit, but not past it: one more rule may not start. */
    const atTheLimit: OwnPlan = { ...overTheLimit, rules_counted: 1, over_rule_limit: false }

    it("says why it cannot start, with a link to Your plan, instead of Ready to start", async () => {
      await renderDetails(testI18n(), previewed, null, jsonResponse(atTheLimit))
      expect(container.querySelector(".rule-actions")?.textContent).toContain("PreviewedReview and start")
      expect(container.textContent).not.toContain("Ready to start")
      const note = container.querySelector<HTMLElement>("#rule-preview-ready")!
      expect(note.textContent).toBe("Your plan lets 1 rule sync. Pause or remove it to start this rule. See your plan")
      expect(note.querySelector("a")?.getAttribute("href")).toBe("/settings/account#your-plan")
    })

    it.each([
      ["keeps a replaced rule's place", { ...previewed, keeps_place: true }, jsonResponse(atTheLimit)],
      ["has room under the plan", previewed, jsonResponse({ ...atTheLimit, rules_counted: 0 })],
      ["cannot read the plan", previewed, jsonResponse({ detail: "database is locked" }, 500)],
    ])("reads Ready to start when it %s", async (_case, rule, ownPlan) => {
      await renderDetails(testI18n(), rule, null, ownPlan)
      expect(container.querySelector(".rule-actions")?.textContent).toContain("Ready to startReview and start")
      expect(container.querySelector("#rule-preview-ready")?.textContent).toContain("3 events will appear in Work")
    })
  })

  it("has no untranslated text with the plan's note before a privacy edit", async () => {
    await renderDetails(pseudoI18n(), enabledRule, null, jsonResponse(overTheLimit))
    click(container.querySelector('[aria-controls="policy-form"]'))
    // As the test with every form open does: the busy-only title it would show is data, not copy.
    choose("#edit-privacy-policy", "copy_details")
    click(container.querySelector('[aria-haspopup="menu"]'))
    // The form's own hint, not the privacy or invitation hints nested in its fields.
    expect(container.querySelector("#policy-form > .field-hint")).not.toBeNull()
    expect(untranslatedText(container, FIXTURE_TEXT)).toEqual([])
  })

  it("has no untranslated text for each reason a rule waits for its schedule", async () => {
    for (const reason of ["not_watchable", "waiting_for_provider", "off_by_user", "not_in_plan", "no_public_address", "not_reaching"]) {
      await renderDetails(pseudoI18n(), { ...enabledRule, effective_cadence: reason as RuleDetail["effective_cadence"] })
      expect(untranslatedText(container, FIXTURE_TEXT)).toEqual([])
      act(() => root?.unmount())
      root = null
    }
  })

  it("has no untranslated text with every form open", async () => {
    await renderDetails(pseudoI18n(), enabledRule, "A notice the previous page already translated")
    // The notice is translated where it is created; only the page around it is checked here.
    container.querySelector(".page-notice")?.remove()

    click(container.querySelector('[aria-controls="policy-form"]'))
    choose("#edit-privacy-policy", "copy_details")
    click(container.querySelector('[aria-controls="replace-form"]'))
    choose("#replace-source-calendar", errandsCalendar.id)
    click(container.querySelector('[aria-controls="replace-confirmation"]'))
    click(container.querySelector('[aria-controls="removal-form"]'))
    click(container.querySelector('[aria-haspopup="menu"]'))

    expect(container.querySelector("#policy-form")).not.toBeNull()
    expect(container.querySelector("#replace-confirmation")).not.toBeNull()
    expect(container.querySelector("#removal-form")).not.toBeNull()
    expect(container.querySelector('[role="menu"]')).not.toBeNull()
    expect(untranslatedText(container, FIXTURE_TEXT)).toEqual([])
  })
})
