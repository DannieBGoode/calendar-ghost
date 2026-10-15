/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { RulePreviewView } from "./rule-preview"
import { StaticI18nProvider } from "@/i18n/provider"
import { dateWords, pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { ConnectedAccount, RuleDetail, RulePreview } from "@/lib/api"
import type { OpenRule } from "@/lib/navigation"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const account: ConnectedAccount = {
  id: "personal",
  display_name: "Dana",
  email: "dana@example.test",
  provider: "google",
  avatar_url: null,
  state: "connected",
  rule_count: 1,
  authorized_at: "2026-10-02T00:00:00Z",
  authorization_lapsed_at: null,
}

const previewedRule: RuleDetail = {
  id: "rule-1",
  source: { connected_account_id: account.id, calendar_id: "family", calendar_name: "Family" },
  destination: { connected_account_id: account.id, calendar_id: "work", calendar_name: "Work" },
  privacy_policy: "busy_only",
  sync_all_day_events: true,
  tentative_events: "mark",
  unanswered_invitations: "wait",
  sync_birthdays: false,
  state: "dry_run_validated",
  reprojection_required: false,
  effective_cadence: "instant",
  poll_every_minutes: 5,
  initial_lookback_days: 30,
  mapping_count: 0,
  last_sync: null,
  last_reconciliation: null,
  latest_preview: null,
  running: null,
}

const today = new Date()
const at = (hour: number) => new Date(today.getFullYear(), today.getMonth(), today.getDate(), hour).toISOString()
const isoDay = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`

const preview: RulePreview = {
  rule_id: "rule-1",
  eligible_events: 1,
  excluded_events: 1,
  recurring_series: 0,
  occurrence_changes: 0,
  items: [
    {
      source_event_id: "dentist",
      kind: "single",
      title: "Dentist",
      starts_at: at(9),
      ends_at: at(10),
      time_zone: null,
      starts_on: null,
      ends_before: null,
      recurrence: null,
      series_event_id: null,
      original_start: null,
      cancelled: false,
      response: "accepted",
      birthday: false,
      planned_action: "create",
      reason: "source_created",
      projection: { title: "Busy", carries_details: false, recurrence: null },
    },
    {
      source_event_id: "birthday",
      kind: "single",
      title: "Mum",
      starts_at: null,
      ends_at: null,
      time_zone: null,
      starts_on: isoDay(today),
      ends_before: isoDay(new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1)),
      recurrence: null,
      series_event_id: null,
      original_start: null,
      cancelled: false,
      response: "accepted",
      birthday: true,
      planned_action: "ignore",
      reason: "birthday",
      projection: null,
    },
  ],
}

/**
 * A weekly series with one moved date, one cancelled, and one changed back to its regular time:
 * created by the run when `series` is "create", already in the destination when it is "ignore".
 */
function seriesItems(series: "create" | "ignore"): RulePreview["items"] {
  const [dentist] = preview.items
  if (!dentist) throw new Error("no fixture")
  const base = { ...dentist, title: "Swim", series_event_id: "swim", kind: "occurrence" as const }
  return [
    { ...dentist, source_event_id: "swim", kind: "series", title: "Swim", recurrence: ["RRULE:FREQ=WEEKLY"], planned_action: series, reason: series === "create" ? "source_created" : "projection_current", projection: { title: "Busy", carries_details: false, recurrence: ["RRULE:FREQ=WEEKLY"] } },
    { ...base, source_event_id: "swim_1", starts_at: at(11), ends_at: at(12), original_start: at(9), planned_action: "update", reason: "occurrence_changed" },
    { ...base, source_event_id: "swim_2", starts_at: null, ends_at: null, original_start: at(13), cancelled: true, planned_action: "delete", reason: "occurrence_cancelled", projection: null },
    { ...base, source_event_id: "swim_3", starts_at: at(15), ends_at: at(16), original_start: at(15), planned_action: "ignore", reason: "occurrence_current" },
  ]
}

/** Calendar and event names come from the server; dates, times, and the time zone from locale data. */
const zone = new Intl.DateTimeFormat("en-US", { timeZoneName: "shortGeneric" }).formatToParts(today).find((part) => part.type === "timeZoneName")?.value ?? ""
// An address may break after its "@", so each half is server text too.
const FIXTURE_TEXT = ["Family", "Work", "Dentist", "Mum", "Busy (tentative)", "Busy", account.email, ...account.email.replace("@", "@ ").split(" "), "DA", zone, ...dateWords()]

type Answer = { status: number; body: unknown }

function jsonResponse({ status, body }: Answer): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

let container: HTMLDivElement
let root: Root | null = null
let calls: string[] = []

function mockFetch(previewAnswer: Answer, rule: RuleDetail = previewedRule) {
  calls = []
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL, init?: RequestInit) => {
      const path = String(input).split("?")[0] ?? ""
      calls.push(`${init?.method ?? "GET"} ${path}`)
      if (path === "/api/v1/accounts") return Promise.resolve(jsonResponse({ status: 200, body: [account] }))
      if (path.endsWith("/calendars")) return Promise.resolve(jsonResponse({ status: 200, body: [] }))
      if (path === "/api/v1/rules/rule-1/preview") return Promise.resolve(jsonResponse(previewAnswer))
      if (path === "/api/v1/rules/rule-1/enable") return Promise.resolve(jsonResponse({ status: 200, body: { ...rule, state: "enabled" } }))
      if (path === "/api/v1/rules/rule-1") return Promise.resolve(jsonResponse({ status: 200, body: rule }))
      return Promise.resolve(jsonResponse({ status: 200, body: [] }))
    }),
  )
}

async function settle(times = 8) {
  for (let i = 0; i < times; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

async function renderPreview(i18n: I18n, onOpenRule: OpenRule = () => undefined) {
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <RulePreviewView ruleId="rule-1" onViewChange={() => undefined} onOpenRule={onOpenRule} />
        </QueryClientProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
}

function button(name: string): HTMLButtonElement {
  const found = [...container.querySelectorAll("button")].find(
    (each) => (each.getAttribute("aria-label") ?? each.textContent.trim()) === name,
  )
  if (!found) throw new Error(`no button named ${name}`)
  return found
}

beforeEach(() => {
  container = document.createElement("div")
  document.body.append(container)
})

afterEach(() => {
  act(() => root?.unmount())
  root = null
  container.remove()
  vi.unstubAllGlobals()
})

describe("RulePreviewView", () => {
  it("shows each source event beside what the destination will hold", async () => {
    mockFetch({ status: 200, body: preview })
    await renderPreview(testI18n())

    const text = container.textContent
    expect(text).toMatch(/Previewed at .+\. Nothing is written until you start syncing\./)
    expect(text).toContain("1 to add")
    expect(text).toContain("1 not synced")
    expect(text).toContain("Busy only: titles, descriptions, and locations stay private.")
    // The accounts name their provider, and the rule's choices are on the page, folded.
    expect([...container.querySelectorAll(".rule-preview-account")].map((each) => each.textContent)).toEqual(["Google accountdana@example.test"])
    expect(container.querySelector(".rule-preview-facts")?.getAttribute("aria-label")).toBe("What this rule syncs:")
    // The title names the calendars; the header does not name them again.
    const underTitle = [...container.querySelectorAll(".rule-preview-header > :not(h1)")].map((node) => node.textContent)
    expect(underTitle.join(" ")).not.toMatch(/Family|Work/)
    // Each choice is its own list item with an icon; those that leave events out read quieter.
    const facts = [...container.querySelectorAll(".rule-preview-fact")]
    expect(facts.map((fact) => [fact.textContent, fact.getAttribute("data-tone"), fact.querySelectorAll("svg[aria-hidden=true]").length])).toEqual([
      ["From the past 30 days", "on", 1],
      ["All-day events", "on", 1],
      ["No birthdays", "off", 1],
      ["Maybe events as “Busy (tentative)”", "on", 1],
      ["Invitations sync once answered", "on", 1],
      ["No declined events", "off", 1],
    ])
    expect(container.querySelector(".rule-preview-settings > a")?.textContent).toBe("Change")
    expect(text).toContain("new or changed events sync on their own")
    const rows = [...container.querySelectorAll(".rule-preview-row")].map((row) => row.textContent)
    expect(rows).toEqual([
      "All dayMum Nothing is writtenNot synced: birthday",
      expect.stringMatching(/^9:00 AM–10:00 AMDentist Busy Add$/),
    ])
    expect(calls.filter((call) => call.startsWith("POST"))).toEqual(["POST /api/v1/rules/rule-1/preview"])
  })

  it("names the year on days outside the current one", async () => {
    const later = new Date(today.getFullYear() + 4, 6, 3, 9)
    const [dentist] = preview.items
    if (!dentist) throw new Error("no fixture")
    const items = [{ ...dentist, starts_at: later.toISOString(), ends_at: new Date(later.getTime() + 3_600_000).toISOString() }]
    mockFetch({ status: 200, body: { ...preview, items } })
    await renderPreview(testI18n())

    const headings = [...container.querySelectorAll(".rule-preview-day th")].map((each) => each.textContent)
    expect(headings).toEqual([testI18n().format.date(later, { weekday: "short", day: "numeric", month: "short", year: "numeric" })])
    expect(headings[0]).toContain(String(later.getFullYear()))
  })

  it("combines Show with kinds in one row that keeps its shape", async () => {
    mockFetch({ status: 200, body: preview })
    await renderPreview(testI18n())
    const options = () => [...container.querySelectorAll(".rule-preview-filters button")].length
    const before = options()

    act(() => button("Not synced 1").click())
    expect(button("Not synced 1").getAttribute("aria-checked")).toBe("true")
    act(() => button("Birthdays 1").click())

    expect(button("Birthdays 1").getAttribute("aria-pressed")).toBe("true")
    // Counts follow the other choices, so the chosen Show count is the rows shown.
    expect(button("Will sync 0").getAttribute("aria-disabled")).toBe("true")
    expect(container.querySelectorAll(".rule-preview-row")).toHaveLength(1)
    // Nothing comes or goes beside the filters, so the table below does not move.
    expect(options()).toBe(before)
    const results = container.querySelector(".rule-preview-results")
    expect([...(results?.children ?? [])].map((child) => child.className)).toEqual(["rule-preview-filters", "rule-preview-table-wrap"])
    // A filtered table is not every event, so it does not close by saying so.
    expect(container.querySelector(".rule-preview-later")).toBeNull()
  })

  it("moves the Show choice with the arrow keys, as one tab stop", async () => {
    mockFetch({ status: 200, body: preview })
    await renderPreview(testI18n())

    const all = button("All 2")
    expect(button("Will sync 1").tabIndex).toBe(-1)
    act(() => {
      all.focus()
      all.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }))
    })
    expect(button("Will sync 1").getAttribute("aria-checked")).toBe("true")
    expect(document.activeElement).toBe(button("Will sync 1"))
  })

  it("puts Refresh in Start's place when the rule changed since the preview", async () => {
    mockFetch({ status: 200, body: preview })
    const answer = vi.mocked(fetch).getMockImplementation()
    vi.mocked(fetch).mockImplementation((input, init) =>
      (input instanceof Request ? input.url : input.toString()).endsWith("/enable")
        ? Promise.resolve(jsonResponse({ status: 409, body: { detail: "changed", code: "rule_not_executable", params: {} } }))
        : (answer?.(input, init) ?? Promise.reject(new Error("no answer"))),
    )
    await renderPreview(testI18n())

    act(() => button("Start syncing to Work").click())
    await settle()

    expect(container.querySelector(".rule-preview-footer")?.textContent).toContain("This rule changed since the preview.")
    expect(container.querySelector(".rule-preview-start-button")?.textContent).toBe("Refresh")
    expect(document.activeElement).toBe(container.querySelector(".rule-preview-start-button"))
  })

  it("names the decision's effect when the rule copies details", async () => {
    mockFetch({ status: 200, body: preview }, { ...previewedRule, privacy_policy: "copy_details" })
    await renderPreview(testI18n())

    expect(button("Start syncing and share details with Work")).toBeTruthy()
    expect(container.querySelector(".rule-preview-privacy")?.getAttribute("data-tone")).toBe("attention")
  })

  it("keeps the filters through a refresh, and drops the old numbers when one fails", async () => {
    mockFetch({ status: 200, body: preview })
    await renderPreview(testI18n())
    act(() => button("Not synced 1").click())

    act(() => button("Refresh").click())
    await settle()
    expect(button("Not synced 1").getAttribute("aria-checked")).toBe("true")

    mockFetch({ status: 503, body: { detail: "down", code: "provider_failed", params: { kind: "unavailable", provider: "google" } } })
    act(() => button("Refresh").click())
    await settle()
    const footer = container.querySelector(".rule-preview-footer")?.textContent ?? ""
    expect(footer).not.toContain("to add")
    // The panel says what to do; Start waits without promising it will come back by itself.
    expect(footer).not.toContain("Available when the preview finishes")
    expect(button("Start syncing to Work").getAttribute("aria-disabled")).toBe("true")
    expect(container.querySelector(".rule-preview-lead")?.textContent).not.toContain("Previewed at")
  })

  it("starts syncing and returns to the rule", async () => {
    mockFetch({ status: 200, body: preview })
    const onOpenRule = vi.fn()
    await renderPreview(testI18n(), onOpenRule)

    act(() => button("Start syncing to Work").click())
    await settle()

    expect(calls).toContain("POST /api/v1/rules/rule-1/enable")
    expect(onOpenRule).toHaveBeenCalledWith("rule-1", { notice: "Enabled. The first sync to Work runs within five minutes, or choose Sync now." })
  })

  it("points at the account to reauthorize when the preview could not read it", async () => {
    mockFetch({ status: 424, body: { detail: "denied", code: "provider_failed", params: { kind: "authentication", provider: "google" } } })
    await renderPreview(testI18n())

    expect(container.querySelector("[role=alert]")?.textContent).toContain("Reauthorize account")
    expect(button("Start syncing to Work").getAttribute("aria-disabled")).toBe("true")
    // Regression: ISSUE-002, a failed preview still said it was reading the calendar.
    // Found by /qa on 2026-10-13
    expect(container.textContent).not.toContain("Reading Family")
  })

  it("names the Earlier group in separate phrases for screen readers", async () => {
    // Regression: ISSUE-005, the toggle's name ran its parts together ("Oct 7 1 event 1 to add").
    // Found by /qa on 2026-10-13
    const lastWeek = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 6, 19)
    const past = { ...preview.items[0], source_event_id: "book-club", title: "Book club", starts_at: lastWeek.toISOString(), ends_at: lastWeek.toISOString() }
    mockFetch({ status: 200, body: { ...preview, items: [past, ...preview.items] } })
    await renderPreview(testI18n())

    const toggle = container.querySelector(".rule-preview-earlier-toggle")
    expect(toggle?.getAttribute("aria-label")).toMatch(/^Earlier, from .+: 1 event, 1 to add$/)
  })

  it("shows that it is reading, in the results, with a line that moves on as seconds pass", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] })
    mockFetch({ status: 200, body: preview })
    const answer = vi.mocked(fetch).getMockImplementation()
    let finish: (response: Response) => void = () => undefined
    vi.mocked(fetch).mockImplementation((input, init) =>
      (input instanceof Request ? input.url : input.toString()).endsWith("/preview")
        ? new Promise<Response>((resolve) => (finish = resolve))
        : (answer?.(input, init) ?? Promise.reject(new Error("no answer"))),
    )
    await renderPreview(testI18n())

    const status = () => container.querySelector(".rule-preview-reading")
    expect(status()?.textContent).toBe("Reading Family…Checking each event against this rule.")
    // Not a live region: the seconds would be read out one by one.
    expect(status()?.closest("[aria-live], [role=status]")).toBeNull()
    expect(container.querySelector(".rule-preview-skeleton")).not.toBeNull()
    expect(container.querySelector(".rule-preview-lead")?.textContent).toBe("A preview: nothing is written until you start syncing.Refresh")
    expect(button("Refresh").getAttribute("aria-disabled")).toBe("true")

    act(() => {
      vi.advanceTimersByTime(5_000)
    })
    expect(status()?.textContent).toBe("Reading Family…5 seconds so far.")
    act(() => {
      vi.advanceTimersByTime(10_000)
    })
    expect(status()?.textContent).toBe("Reading Family…15 seconds so far. Large calendars can take up to a minute.")

    finish(jsonResponse({ status: 200, body: preview }))
    await settle()
    expect(status()).toBeNull()
    vi.useRealTimers()
  })

  // Regression: a retry of a failed first read hid its panel behind the placeholder rows, and a
  // press of the panel's waiting Refresh left focus on a button that then went away.
  // Found by /qa on 2026-10-15
  it("keeps a failed first read's panel while Refresh retries it", async () => {
    mockFetch({ status: 503, body: { detail: "down", code: "provider_failed", params: { kind: "unavailable", provider: "google" } } })
    await renderPreview(testI18n())
    const answer = vi.mocked(fetch).getMockImplementation()
    vi.mocked(fetch).mockImplementation((input, init) =>
      (input instanceof Request ? input.url : input.toString()).endsWith("/preview") ? new Promise<Response>(() => undefined) : (answer?.(input, init) ?? Promise.reject(new Error("no answer"))),
    )
    const panelRefresh = () => container.querySelector<HTMLButtonElement>("[role=alert] button")

    act(() => panelRefresh()?.click())
    await settle()

    expect(container.querySelector(".rule-preview-reading")?.textContent).toContain("Reading Family…")
    expect(panelRefresh()?.getAttribute("aria-disabled")).toBe("true")
    expect(container.querySelector(".rule-preview-skeleton")).toBeNull()

    act(() => panelRefresh()?.focus())
    act(() => panelRefresh()?.click())
    expect(document.activeElement).toBe(button("Refresh"))
  })

  it("says it is reading above the last results while Refresh reads", async () => {
    mockFetch({ status: 200, body: preview })
    await renderPreview(testI18n())
    const answer = vi.mocked(fetch).getMockImplementation()
    vi.mocked(fetch).mockImplementation((input, init) =>
      (input instanceof Request ? input.url : input.toString()).endsWith("/preview") ? new Promise<Response>(() => undefined) : (answer?.(input, init) ?? Promise.reject(new Error("no answer"))),
    )

    act(() => button("Refresh").click())
    await settle()

    const status = container.querySelector(".rule-preview-reading")
    expect(status?.textContent).toContain("Reading Family…")
    // Beside the dimmed results, not inside them, so it is not dimmed or made inert with them.
    expect(status?.nextElementSibling?.className).toBe("rule-preview-results")
    expect(container.querySelector(".rule-preview-results")?.getAttribute("aria-busy")).toBe("true")
    expect(document.activeElement).toBe(button("Refresh"))
  })

  it("counts every date of a series a new rule adds as added or not synced", async () => {
    // Regression: a new rule's preview said it would update, remove, and leave up to date events
    // it had never written, because a run fixes a new series' changed dates after writing it.
    mockFetch({ status: 200, body: { ...preview, items: [...preview.items, ...seriesItems("create")] } })
    await renderPreview(testI18n())

    const footer = container.querySelector(".rule-preview-counts")?.textContent ?? ""
    expect(footer).toBe("What starting this rule writes to Work:4 to add2 not synced")
    const outcomes = [...container.querySelectorAll(".rule-preview-row .activity-effect")].map((each) => each.textContent)
    expect(outcomes).toEqual(expect.arrayContaining(["Add", "Not synced: cancelled"]))
    expect(outcomes).not.toEqual(expect.arrayContaining(["Update", "Already up to date"]))
    expect(outcomes.some((each) => each.startsWith("Remove"))).toBe(false)
    expect(container.textContent).toContain("This date only: moved from")
  })

  it("keeps updates, removals, and current dates for a series the destination already has", async () => {
    mockFetch({ status: 200, body: { ...preview, items: [...preview.items, ...seriesItems("ignore")] } })
    await renderPreview(testI18n())

    const footer = container.querySelector(".rule-preview-counts")?.textContent ?? ""
    expect(footer).toBe("What starting this rule writes to Work:1 to add1 to update1 to remove2 already up to date1 not synced")
  })

  it("leaves no text untranslated", async () => {
    mockFetch({ status: 200, body: preview })
    await renderPreview(pseudoI18n())

    expect(untranslatedText(container, FIXTURE_TEXT)).toEqual([])
  })
})
