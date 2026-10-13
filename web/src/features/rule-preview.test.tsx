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

/** Calendar and event names come from the server; dates, times, and the time zone from locale data. */
const zone = new Intl.DateTimeFormat("en-US", { timeZoneName: "short" }).formatToParts(today).find((part) => part.type === "timeZoneName")?.value ?? ""
const FIXTURE_TEXT = ["Family", "Work", "Dentist", "Mum", "Busy (tentative)", "Busy", account.email, "DA", zone, ...dateWords()]

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
    expect(text).toMatch(/A preview from .+: nothing is written until you start syncing\./)
    expect(text).toContain("1 to add")
    expect(text).toContain("1 not synced")
    expect(text).toContain("Busy only: titles, descriptions, and locations stay private.")
    // The accounts name their provider, and the rule's choices are on the page, folded.
    expect(text).toContain("Google account · dana@example.test")
    expect(text).toContain("What this rule syncs")
    // The title names the calendars; the header does not name them again.
    const underTitle = [...container.querySelectorAll(".rule-preview-header > :not(h1)")].map((node) => node.textContent)
    expect(underTitle.join(" ")).not.toMatch(/Family|Work/)
    expect(container.querySelector(".rule-preview-settings")?.textContent).toBe(
      "What this rule syncs: From the past 30 days · All-day events · No birthdays · Maybe events as “Busy (tentative)” · Invitations sync once answered · No declined eventsChange",
    )
    expect(text).toContain("new or changed events sync on their own")
    const rows = [...container.querySelectorAll(".rule-preview-row")].map((row) => row.textContent)
    expect(rows).toEqual([
      "All dayMumNothing is writtenNot synced: birthday",
      expect.stringMatching(/^9:00 AM–10:00 AMDentistBusyAdd$/),
    ])
    expect(calls.filter((call) => call.startsWith("POST"))).toEqual(["POST /api/v1/rules/rule-1/preview"])
  })

  it("narrows the table to what will not sync", async () => {
    mockFetch({ status: 200, body: preview })
    await renderPreview(testI18n())

    act(() => button("Not synced 1").click())

    expect(button("Not synced 1").getAttribute("aria-pressed")).toBe("true")
    // Counts follow the other choices, so a kind with nothing to show can't lead to an empty table.
    act(() => button("Will sync 1").click())
    act(() => button("Kind").click())
    expect(button("Birthdays 0").getAttribute("aria-disabled")).toBe("true")
    expect(button("All 2").getAttribute("aria-disabled")).toBeNull()
    expect(container.querySelectorAll(".rule-preview-row")).toHaveLength(1)
    expect(container.textContent).toContain("Showing 1 of 2")
    // A filtered table is not every event, so it does not close by saying so.
    expect(container.querySelector(".rule-preview-later")).toBeNull()
  })

  it("keeps the filters through a refresh, and drops the old numbers when one fails", async () => {
    mockFetch({ status: 200, body: preview })
    await renderPreview(testI18n())
    act(() => button("Not synced 1").click())

    act(() => button("Refresh").click())
    await settle()
    expect(button("Not synced 1").getAttribute("aria-pressed")).toBe("true")

    mockFetch({ status: 503, body: { detail: "down", code: "provider_failed", params: { kind: "unavailable", provider: "google" } } })
    act(() => button("Refresh").click())
    await settle()
    const footer = container.querySelector(".rule-preview-footer")?.textContent ?? ""
    expect(footer).not.toContain("to add")
    expect(footer).toContain("Available when the preview finishes")
    expect(container.querySelector(".rule-preview-lead")?.textContent).not.toContain("A preview from")
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

  it("leaves no text untranslated", async () => {
    mockFetch({ status: 200, body: preview })
    await renderPreview(pseudoI18n())

    expect(untranslatedText(container, FIXTURE_TEXT)).toEqual([])
  })
})
