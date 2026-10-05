/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, createElement } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { RuleBuilder, RulesView } from "./rules"
import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { ConnectedAccount, DiscoveredCalendar, RuleSummary, RunOutcome } from "@/lib/api"
import type { ViewChange } from "@/lib/navigation"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function account(id: string): ConnectedAccount {
  return {
    id,
    display_name: `Account ${id}`,
    email: `${id}@example.test`,
    provider: "google",
    avatar_url: null,
    state: "connected",
    rule_count: 0,
    authorized_at: "2026-10-02T00:00:00Z",
    authorization_lapsed_at: null,
  }
}

// Source account: one writable calendar, one read-only.
const accountA = account("a")
const workA: DiscoveredCalendar = { id: "work-a", summary: "Work A", access_role: "owner", writable: true, primary: true }
const holidaysA: DiscoveredCalendar = { id: "holidays-a", summary: "Holidays A", access_role: "reader", writable: false, primary: false }

// Initial destination account: two writable calendars, one read-only.
const accountB = account("b")
const workB1: DiscoveredCalendar = { id: "work-b1", summary: "Work B1", access_role: "owner", writable: true, primary: true }
const holidaysB: DiscoveredCalendar = { id: "holidays-b", summary: "Holidays B", access_role: "reader", writable: false, primary: false }
const workB2: DiscoveredCalendar = { id: "work-b2", summary: "Work B2", access_role: "owner", writable: true, primary: false }

// A switch target with its own single writable calendar.
const accountD = account("d")
const workD1: DiscoveredCalendar = { id: "work-d1", summary: "Work D1", access_role: "owner", writable: true, primary: true }

// A switch target with no writable calendars at all.
const accountC = account("c")
const holidaysC: DiscoveredCalendar = { id: "holidays-c", summary: "Holidays C", access_role: "reader", writable: false, primary: true }

const calendarsByAccount: Record<string, DiscoveredCalendar[]> = {
  a: [workA, holidaysA],
  b: [workB1, holidaysB, workB2],
  c: [holidaysC],
  d: [workD1],
}

/** Account names, emails, calendar names, and the avatar initials derived from them. */
const FIXTURE_TEXT = [
  "Account a",
  "a@example.test",
  "Account b",
  "b@example.test",
  "Account c",
  "c@example.test",
  "Account d",
  "d@example.test",
  "Work A",
  "Holidays A",
  "Work B1",
  "Holidays B",
  "Work B2",
  "Work D1",
  "Holidays C",
  "AA",
  "AB",
  "AC",
  "AD",
  // The literal title domain/services.py writes to Google Calendar for a Busy-Only tentative
  // event; it is data passed as a message parameter, never translated.
  "Busy (tentative)",
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

function renderBuilder(
  i18n: I18n,
  accounts: ConnectedAccount[] = [accountA, accountB, accountC, accountD],
  onCreated = vi.fn(),
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  for (const [id, calendars] of Object.entries(calendarsByAccount)) {
    queryClient.setQueryData(["calendars", id], calendars)
  }
  root = createRoot(container)
  act(() => {
    root?.render(
      createElement(StaticI18nProvider, {
        i18n,
        children: createElement(
          QueryClientProvider,
          { client: queryClient },
          createElement(RuleBuilder, { accounts, onCreated }),
        ),
      }),
    )
  })
  return container
}

function click(element: Element) {
  act(() => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
  })
}

function selectOptions(id: string): HTMLOptionElement[] {
  return Array.from(container.querySelectorAll<HTMLOptionElement>(`#${id} option`))
}

function selectElement(id: string): HTMLSelectElement {
  return container.querySelector<HTMLSelectElement>(`#${id}`)!
}

/** Switches an AccountSelect combobox (scoped to its own wrapper) to the account at `targetId`. */
function switchAccount(triggerId: string, targetId: string) {
  const trigger = container.querySelector<HTMLButtonElement>(`#${triggerId}`)!
  const wrapper = trigger.closest<HTMLElement>(".account-select")!
  click(trigger)
  const options = Array.from(wrapper.querySelectorAll('[role="option"]'))
  const target = options.find((option) => option.textContent.includes(`Account ${targetId}`))
  if (!target) throw new Error(`No account option for ${targetId}`)
  click(target)
}

describe("RuleBuilder", () => {
  it("keeps read-only calendars selectable as Source Calendars", () => {
    renderBuilder(testI18n(), [accountA, accountB])

    const options = selectOptions("source-calendar")
    expect(options.map((option) => option.value)).toEqual([workA.id, holidaysA.id])
    expect(selectElement("source-calendar").disabled).toBe(false)
  })

  it("excludes read-only calendars from Destination options and never defaults to one", () => {
    renderBuilder(testI18n(), [accountA, accountB])

    const options = selectOptions("destination-calendar")
    expect(options.map((option) => option.value)).toEqual([workB1.id, workB2.id])
    expect(options.some((option) => option.value === holidaysB.id)).toBe(false)
    // The default destination (no explicit choice made yet) must be a writable calendar.
    expect(selectElement("destination-calendar").value).toBe(workB1.id)
  })

  it("refreshes destination options to the newly selected account's writable calendars", () => {
    renderBuilder(testI18n(), [accountA, accountB, accountD, accountC])

    expect(selectOptions("destination-calendar").map((option) => option.value)).toEqual([workB1.id, workB2.id])

    switchAccount("destination-account", "d")

    const options = selectOptions("destination-calendar")
    expect(options.map((option) => option.value)).toEqual([workD1.id])
    expect(selectElement("destination-calendar").value).toBe(workD1.id)
  })

  it("offers no destination and blocks submission for an account with no writable calendars", () => {
    renderBuilder(testI18n(), [accountA, accountB, accountD, accountC])

    switchAccount("destination-account", "c")

    const destinationSelect = selectElement("destination-calendar")
    expect(selectOptions("destination-calendar")).toHaveLength(0)
    expect(destinationSelect.disabled).toBe(true)
    expect(destinationSelect.value).toBe("")
    expect(container.textContent).toContain("This account has no writable calendars to choose.")

    const submit = container.querySelector<HTMLButtonElement>('button[type="submit"]')!
    expect(submit.disabled).toBe(true)
  })
})

// A few seconds before "now", so `format.relative` resolves to the catalog's "just now".
const justNow = new Date(Date.now() - 10_000).toISOString()

const lastSync: RunOutcome = {
  completed_at: justNow,
  succeeded: true,
  full_run: false,
  created: 0,
  updated: 1,
  deleted: 0,
  conflicts: 0,
  checked_mappings: 1,
  drift: 0,
  failure_kind: null,
  last_succeeded_at: null,
}

function ruleSummary(id: string, overrides: Partial<RuleSummary>): RuleSummary {
  return {
    id,
    source: { connected_account_id: accountA.id, calendar_id: workA.id, calendar_name: workA.summary },
    destination: { connected_account_id: accountB.id, calendar_id: workB1.id, calendar_name: workB1.summary },
    privacy_policy: "busy_only",
    sync_all_day_events: true,
    tentative_events: "mark",
    unanswered_invitations: "wait",
    state: "enabled",
    reprojection_required: false,
    last_sync: lastSync,
    latest_preview: null,
    running: null,
    ...overrides,
  }
}

const RULE_ROWS: RuleSummary[] = [
  ruleSummary("enabled", {}),
  ruleSummary("stopped", {
    state: "degraded",
    destination: { connected_account_id: accountB.id, calendar_id: workB2.id, calendar_name: workB2.summary },
    last_sync: { ...lastSync, succeeded: false, failure_kind: "temporary" },
  }),
  ruleSummary("previewed", {
    state: "dry_run_validated",
    destination: { connected_account_id: accountD.id, calendar_id: workD1.id, calendar_name: workD1.summary },
    latest_preview: { completed_at: justNow, eligible_events: 3, excluded_events: 1, recurring_series: 0, occurrence_changes: 0 },
  }),
  ruleSummary("syncing", {
    source: { connected_account_id: accountB.id, calendar_id: workB1.id, calendar_name: workB1.summary },
    destination: { connected_account_id: accountA.id, calendar_id: workA.id, calendar_name: workA.summary },
    running: { kind: "sync", started_at: justNow, handling: null, total: 8, done: 2, stage: null },
  }),
  ruleSummary("draft", {
    state: "draft",
    source: { connected_account_id: accountD.id, calendar_id: workD1.id, calendar_name: workD1.summary },
    last_sync: null,
  }),
]

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: () => Promise.resolve(body) } as Response
}

async function renderRulesList(
  i18n: I18n,
  {
    rows = RULE_ROWS,
    accounts = [accountA, accountB, accountC, accountD],
    onViewChange = () => undefined,
  }: { rows?: RuleSummary[]; accounts?: ConnectedAccount[]; onViewChange?: ViewChange } = {},
) {
  vi.stubGlobal("fetch", vi.fn((input: string | URL) => Promise.resolve(respond(String(input)))))
  function respond(url: string): Response {
    const path = url.split("?")[0] ?? ""
    if (path === "/api/v1/rules") return jsonResponse(rows)
    if (path === "/api/v1/accounts") return jsonResponse(accounts)
    const calendars = /^\/api\/v1\/accounts\/(.+)\/calendars$/.exec(path)
    if (calendars) return jsonResponse(calendarsByAccount[decodeURIComponent(calendars[1] ?? "")] ?? [])
    return jsonResponse({})
  }
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      createElement(StaticI18nProvider, {
        i18n,
        children: createElement(
          QueryClientProvider,
          { client: queryClient },
          createElement(RulesView, { notice: null, createRule: false, onViewChange, onOpenRule: () => undefined }),
        ),
      }),
    )
  })
  for (let i = 0; i < 6; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
  return container
}

describe("RulesView", () => {
  it("shows each rule row's run, status, and next step", async () => {
    await renderRulesList(testI18n())
    const text = container.textContent
    expect(text).toContain("Last synced just now")
    expect(text).toContain("Last sync failed just now: Google Calendar was temporarily unavailable")
    expect(text).toContain("Previewed just now: 3 events will appear in Work D1, 1 excluded.")
    expect(text).toMatch(/2 of 8 checked · Running for \d+ s · It keeps running if you leave this page\./)
    expect(text).toContain("Preview to restart")
    expect(container.querySelector('[aria-label="More actions for Work A to Work B1"]')).not.toBeNull()
  })

  it("sends a rule an expired Google account stopped to that account in Settings", async () => {
    const lapsed = { ...accountB, authorization_lapsed_at: justNow }
    const stopped = ruleSummary("stopped", {
      state: "degraded",
      last_sync: { ...lastSync, succeeded: false, failure_kind: "authentication" },
    })
    const onViewChange = vi.fn()
    await renderRulesList(testI18n(), { rows: [stopped], accounts: [accountA, lapsed], onViewChange })

    expect(container.textContent).not.toContain("Preview to restart")
    expect(container.querySelector(".rule-note")?.textContent).toBe(
      `Synchronization stopped: ${lapsed.email} must be reauthorized before this rule can run.`,
    )
    const link = [...container.querySelectorAll("a")].find((anchor) => anchor.textContent === "Reauthorize account")
    expect(link?.getAttribute("href")).toBe("/settings?account=b")
    click(link!)
    expect(onViewChange).toHaveBeenCalledWith("settings", { search: "?account=b" })
  })

  it("has no untranslated text in rule rows, their status, and their commands", async () => {
    await renderRulesList(pseudoI18n())
    const menus = container.querySelectorAll('[aria-haspopup="menu"]')
    expect(menus.length).toBeGreaterThan(0)
    for (const menu of menus) click(menu)
    expect(container.querySelectorAll('[role="menuitem"]').length).toBeGreaterThan(0)
    expect(untranslatedText(container, FIXTURE_TEXT)).toEqual([])
  })
})
