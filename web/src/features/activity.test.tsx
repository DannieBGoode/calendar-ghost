/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ActivityView } from "./activity"
import { StaticI18nProvider } from "@/i18n/provider"
import { dateWords, pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type {
  api,
  AuditEntry,
  ConnectedAccount,
  DiscoveredCalendar,
  Incident,
  RecordedEvent,
  RuleSummary,
  SourceChange,
} from "@/lib/api"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const today = new Date()
const at = (daysAgo: number, hour: number, minute = 0) =>
  new Date(today.getFullYear(), today.getMonth(), today.getDate() - daysAgo, hour, minute).toISOString()

const accountA: ConnectedAccount = {
  id: "acct-a",
  provider: "google",
  display_name: "Dana Calendar",
  email: "dana@example.test",
  avatar_url: null,
  state: "connected",
  rule_count: 1,
  authorized_at: at(3, 9),
}
const accountB: ConnectedAccount = { ...accountA, id: "acct-b", display_name: "Partner Calendar", email: "partner@example.test" }
const calendars: Record<string, DiscoveredCalendar[]> = {
  "acct-a": [{ id: "family", summary: "Family", writable: true, primary: true, access_role: "owner" }],
  "acct-b": [{ id: "work", summary: "Work", writable: true, primary: true, access_role: "owner" }],
}

const rule: RuleSummary = {
  id: "rule-1",
  source: { connected_account_id: accountA.id, calendar_id: "family", calendar_name: "Family" },
  destination: { connected_account_id: accountB.id, calendar_id: "work", calendar_name: "Work" },
  privacy_policy: "busy_only",
  sync_all_day_events: false,
  tentative_events: "mark",
  unanswered_invitations: "wait",
  state: "enabled",
  reprojection_required: false,
  last_sync: null,
  latest_preview: null,
  running: null,
}

function recorded(title: string, overrides: Partial<RecordedEvent> = {}): RecordedEvent {
  return {
    title,
    all_day: false,
    starts: at(-1, 10),
    ends: at(-1, 11),
    recurring: false,
    cancelled: false,
    renamed_from: null,
    moved_from: null,
    ...overrides,
  }
}

function entry(id: number, overrides: Partial<AuditEntry>): AuditEntry {
  return {
    id,
    run_id: "run-1",
    occurred_at: at(0, 9, id),
    rule_id: rule.id,
    action: "update",
    outcome: "updated",
    category: "changed",
    reason: "source_changed",
    detail: "",
    source_event_id: `source-${id}`,
    destination_event_id: null,
    event: null,
    repeated: false,
    changed_fields: null,
    ...overrides,
  }
}

/** One entry per category, rule management, a removed rule, a move, a repeat, and an unknown reason. */
const ENTRIES: AuditEntry[] = [
  entry(10, { reason: "brand_new_reason", action: "brand_new_action", detail: "internal: raw", event: recorded("Mystery") }),
  entry(9, { action: "create", reason: "projection_missing", repeated: true, event: recorded("Gym") }),
  entry(8, {
    reason: "occurrence_changed",
    event: recorded("Weekly Review", { recurring: true, moved_from: { all_day: false, starts: at(-1, 8), ends: at(-1, 9) } }),
  }),
  entry(7, { changed_fields: ["title", "description"], event: recorded("Team Sync", { renamed_from: "Old Sync" }) }),
  entry(6, { action: "ignore", category: "skipped", reason: "all_day_excluded", event: recorded("Holiday", { all_day: true, starts: "2026-12-24", ends: "2026-12-27" }) }),
  entry(5, { action: "conflict", category: "blocked", reason: "source_unverifiable", event: recorded("Dentist", { recurring: true }) }),
  entry(4, { action: "ignore", category: "unchanged", reason: "projection_current", event: recorded("Lunch", { cancelled: true }) }),
  entry(3, { action: "policy_changed", reason: null, source_event_id: null, run_id: null }),
  entry(2, { action: "update", reason: "source_changed", event: null }),
  entry(1, {
    run_id: "run-0",
    occurred_at: at(1, 18),
    rule_id: "rule-gone",
    action: "detach_projection",
    reason: null,
    event: recorded("Standup"),
  }),
]

function incident(overrides: Partial<Incident>): Incident {
  return {
    id: "incident",
    rule_id: rule.id,
    category: "authorization",
    state: "open",
    summary: "Access to Google Calendar was denied",
    opened_at: at(2, 9),
    updated_at: at(0, 8),
    resolved_at: null,
    resolution: null,
    account_id: accountA.id,
    message: null,
    ...overrides,
  }
}

// Recorded before Incident messages, so the Web UI shows the stored English summary.
const LEGACY_SUMMARY = "Rule synchronization stopped after 3 failures"
// The stored summaries of coded Incidents differ from what their messages say, so a test that
// finds the message's sentence proves it was translated rather than copied.
const INCIDENTS: Incident[] = [
  incident({
    id: "open-auth",
    summary: "Stored summary: access denied",
    message: { code: "provider_failure", params: { kind: "authorization", provider: "google" } },
  }),
  incident({
    id: "open-conflict",
    category: "conflict",
    summary: "Stored summary: 2 events blocked",
    message: { code: "events_still_blocked", params: { count: 2 } },
  }),
  incident({
    id: "open-installation",
    rule_id: null,
    category: "infrastructure",
    summary: "Stored summary: infrastructure",
    message: { code: "provider_failure", params: { kind: "infrastructure", provider: null } },
  }),
  incident({ id: "resolved-legacy", state: "resolved", category: "permanent", summary: LEGACY_SUMMARY }),
  incident({
    id: "resolved-sync",
    state: "resolved",
    category: "temporary",
    resolution: "sync_succeeded",
    resolved_at: at(0, 7),
    summary: "Stored summary: temporary",
    message: { code: "provider_failure", params: { kind: "temporary", provider: "google" } },
  }),
]

const CHANGE: SourceChange = {
  fields: ["title", "description", "guests", "response", "time"],
  values_available: false,
  changes: [
    { field: "title", before: "Old Sync", after: "Team Sync", before_time: null, after_time: null, added: [], removed: [] },
    { field: "guests", before: null, after: null, before_time: null, after_time: null, added: ["cleo@example.test", "ana@example.test"], removed: ["ben@example.test"] },
    { field: "response", before: "needs_action", after: "accepted", before_time: null, after_time: null, added: [], removed: [] },
    {
      field: "time",
      before: null,
      after: null,
      before_time: { all_day: false, starts: at(-1, 9), ends: at(-1, 10) },
      after_time: { all_day: false, starts: at(-1, 10), ends: at(-1, 11) },
      added: [],
      removed: [],
    },
  ],
}

const EVENT: Awaited<ReturnType<typeof api.activityEvent>> = {
  source: { found: true, cancelled: false, title: "Team Sync", all_day: false, starts: at(-1, 10), ends: at(-1, 11), recurring: true, web_link: "https://calendar.example.test/event" },
  destination: { found: false, cancelled: false, title: "", all_day: false, starts: null, ends: null, recurring: false, web_link: null },
}

/** The conjunction `format.list` writes between changed fields comes from Intl locale data, like dates. */
const LIST_WORDS = new Intl.ListFormat("en-US", { style: "long", type: "conjunction" })
  .formatToParts(["a", "b"])
  .filter((part) => part.type === "literal")
  .map((part) => part.value.trim())

/** Account names, emails, calendar names, event titles, stored text, and avatar initials; dates come from Intl. */
const FIXTURE_TEXT = [
  "Dana Calendar",
  "dana@example.test",
  "Partner Calendar",
  "partner@example.test",
  "cleo@example.test",
  "ana@example.test",
  "ben@example.test",
  "Family",
  "Work",
  "Mystery",
  "Gym",
  "Weekly Review",
  "Team Sync",
  "Old Sync",
  "Holiday",
  "Dentist",
  "Lunch",
  "Standup",
  // An Incident without a message shows its English summary as sent.
  LEGACY_SUMMARY,
  "DC",
  "PC",
  ...dateWords(),
  ...LIST_WORDS,
]

type Scenario = { entries?: AuditEntry[]; incidents?: Incident[]; failIncidents?: boolean }

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

/** Responses for paths that carry an identifier, such as an account's calendars. */
function patternResponse(path: string): Response {
  const accountCalendars = /^\/api\/v1\/accounts\/(.+)\/calendars$/.exec(path)
  if (accountCalendars) return jsonResponse(calendars[decodeURIComponent(accountCalendars[1] ?? "")] ?? [])
  if (/^\/api\/v1\/audit-entries\/\d+\/changes$/.test(path)) return jsonResponse(CHANGE)
  if (/^\/api\/v1\/audit-entries\/\d+\/event$/.test(path)) return jsonResponse(EVENT)
  return jsonResponse({ detail: "not found" }, 404)
}

function mockFetch({ entries = ENTRIES, incidents = INCIDENTS, failIncidents = false }: Scenario) {
  const responses: Record<string, Response> = {
    "/api/v1/audit-entries": jsonResponse(entries),
    "/api/v1/incidents": failIncidents ? jsonResponse({ detail: "boom" }, 500) : jsonResponse(incidents),
    "/api/v1/rules": jsonResponse([rule]),
    "/api/v1/accounts": jsonResponse([accountA, accountB]),
  }
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL) => {
      const path = String(input).split("?")[0] ?? ""
      return Promise.resolve(responses[path] ?? patternResponse(path))
    }),
  )
}

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
  window.history.replaceState(null, "", "/")
  vi.restoreAllMocks()
})

async function settle(times = 8) {
  for (let i = 0; i < times; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

async function renderActivity(i18n: I18n, scenario: Scenario = {}, search = "") {
  window.history.replaceState(null, "", `/activity${search}`)
  mockFetch(scenario)
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <ActivityView onViewChange={() => undefined} onOpenRule={() => undefined} />
        </QueryClientProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
  return container
}

async function click(element: Element | null) {
  expect(element).not.toBeNull()
  act(() => {
    ;(element as HTMLElement).click()
  })
  await settle(2)
}

describe("ActivityView", () => {
  it("shows what each Incident says and what each entry did", async () => {
    await renderActivity(testI18n())
    await click(container.querySelector(".resolved-incidents-toggle"))
    const text = container.textContent
    expect(container.querySelector("h1")?.textContent).toBe("What your rules did")
    expect(text).toContain("Access to Google Calendar was denied")
    expect(text).toContain("2 events could not be synced and were still blocked at the daily check.")
    expect(text).toContain("Local synchronization infrastructure failed")
    expect(text).toContain("Google Calendar is temporarily unavailable")
    expect(text).toContain(LEGACY_SUMMARY)
    expect(text).not.toContain("Stored summary")
    expect(text).toContain("Hide resolved incidents")
    expect(text).toContain("Resolved by a successful sync.")
    expect(text).toContain("Title and description changed in Family, so updated in Work")
    expect(text).toContain("Missing from Work, so put back again")
    expect(text).toContain("Something happened")
    expect(container.querySelector('[aria-label="Show only Family to Work"]')).not.toBeNull()
  })

  it("announces how many entries a search found", async () => {
    await renderActivity(testI18n(), { entries: ENTRIES.slice(0, 1) }, "?q=Mystery")
    expect(container.querySelector('p[role="status"]')?.textContent).toBe("1 entry found for “Mystery”.")
  })

  it("says what to do about a block", async () => {
    await renderActivity(testI18n(), {}, "?entry=5")
    const next = container.querySelector(".activity-next")
    expect(next?.textContent).toBe(
      "What to do: If this repeats, check in Settings that the Google account for Family is still connected.",
    )
    expect(next?.querySelector("strong")?.textContent).toBe("What to do:")
  })

  it("explains an unknown reason in a sentence and keeps the recorded detail as a diagnostic", async () => {
    await renderActivity(testI18n(), {}, "?entry=10")
    const detail = container.querySelector(".activity-detail")
    expect(detail?.querySelector(".activity-explanation")?.textContent).toBe(
      "This version of Calendar Ghost cannot describe this entry yet. Its recorded detail is below.",
    )
    expect(detail?.querySelector(".activity-next")).toBeNull()
    const facts = [...(detail?.querySelectorAll(".activity-diagnostics dt") ?? [])]
    const recorded = facts.find((term) => term.textContent === "Recorded detail")
    expect(recorded?.nextElementSibling?.textContent).toBe("internal: raw")
  })

  it("has no untranslated text in Incidents, the history table, and the rule picker", async () => {
    await renderActivity(pseudoI18n())
    await click(container.querySelector(".resolved-incidents-toggle"))
    await click(container.querySelector('[role="combobox"]'))
    expect(container.querySelectorAll('[role="option"]').length).toBeGreaterThan(2)
    expect(untranslatedText(container, FIXTURE_TEXT)).toEqual([])
  })

  it("lists what a guest list gained and lost", async () => {
    await renderActivity(testI18n(), {}, "?entry=7")
    const values = [...container.querySelectorAll(".activity-change-value")].map((value) => value.textContent)
    expect(values).toContain("Added cleo@example.test, ana@example.test")
    expect(values).toContain("Removed ben@example.test")
  })
})
