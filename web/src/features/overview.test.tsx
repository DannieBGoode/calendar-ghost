/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { OverviewView } from "./overview"
import { StaticI18nProvider } from "@/i18n/provider"
import { dateWords, pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { CalendarProvider, ConnectedAccount, Dashboard, OwnPlan, RecentChange, RuleSummary, ServerProblem } from "@/lib/api"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

// Every relative time below is a few seconds before "now", so `format.relative` always resolves to
// the catalog's "just now" message instead of a raw Intl.RelativeTimeFormat string such as
// "3 hours ago" (which bypasses the catalog, and the pseudo locale, entirely).
const now = Date.now()
const justNow = (offsetMs = 10_000) => new Date(now - offsetMs).toISOString()

const accountA: ConnectedAccount = {
  id: "acct-a",
  provider: "google",
  display_name: "Dana Calendar",
  email: "dana@example.test",
  avatar_url: null,
  state: "connected",
  rule_count: 1,
  authorized_at: justNow(90_000),
  authorization_lapsed_at: null,
}
const accountB: ConnectedAccount = {
  id: "acct-b",
  provider: "google",
  display_name: "Partner Calendar",
  email: "partner@example.test",
  avatar_url: null,
  state: "connected",
  rule_count: 1,
  authorized_at: justNow(90_000),
  authorization_lapsed_at: null,
}

const rule: RuleSummary = {
  id: "rule-1",
  source: { connected_account_id: accountA.id, calendar_id: "family", calendar_name: "Family" },
  destination: { connected_account_id: accountB.id, calendar_id: "work", calendar_name: "Work" },
  privacy_policy: "busy_only",
  sync_all_day_events: true,
  tentative_events: "mark",
  unanswered_invitations: "wait",
  sync_birthdays: false,
  state: "enabled",
  reprojection_required: false,
  effective_cadence: "instant",
  poll_every_minutes: 5,
  last_sync: {
    completed_at: justNow(),
    succeeded: true,
    full_run: true,
    created: 0,
    updated: 1,
    deleted: 0,
    conflicts: 0,
    checked_mappings: 1,
    drift: 0,
    failure_kind: null,
    failure_provider: null,
    last_succeeded_at: null,
  },
  latest_preview: null,
  running: null,
  keeps_place: false,
}

// A problem an Incident explains carries its message, which the Overview translates; its stored
// summary differs so a test that finds the message's sentence proves it was translated.
const providerFailure: ServerProblem = {
  kind: "review",
  rule_id: "rule-1",
  summary: "Stored summary: access denied",
  since: justNow(),
  message: { code: "provider_failure", params: { kind: "authorization", provider: "google" } },
  cause: null,
  last_tried_at: null,
  provider: null,
}
// Other problems have no code yet, so their English summaries are data.
const overdue: ServerProblem = {
  kind: "overdue",
  rule_id: "rule-1",
  summary: "This rule has not synced in over a day",
  since: justNow(),
  message: null,
  cause: null,
  last_tried_at: null,
  provider: null,
}
const stalled: ServerProblem = {
  kind: "stalled",
  rule_id: null,
  summary: "The scheduler has not run recently",
  since: justNow(),
  message: null,
  cause: null,
  last_tried_at: null,
  provider: null,
}
const SERVER_TEXT = [overdue.summary, stalled.summary]

const repeatedChange: RecentChange = {
  entry: {
    id: 501,
    run_id: "run-1",
    occurred_at: justNow(),
    rule_id: "rule-1",
    action: "update",
    outcome: "updated",
    category: "changed",
    reason: "source_changed",
    detail: "",
    source_event_id: "evt-1",
    destination_event_id: "evt-1-dest",
    event: {
      title: "Team Sync",
      all_day: false,
      starts: new Date(now + 1_800_000).toISOString(),
      ends: new Date(now + 3_600_000).toISOString(),
      recurring: false,
      cancelled: false,
      renamed_from: null,
      moved_from: null,
    },
    repeated: false,
    changed_fields: null,
    run_reason: null,
    found_by: null,
    source_comparison: null,
  },
  repeats: 3,
  first_occurred_at: justNow(),
}

const attentionDashboard: Dashboard = {
  status: "review",
  needs_attention: true,
  problems: [providerFailure],
  connected_accounts: 2,
  disconnected_accounts: 0,
  lapsed_accounts: 0,
  sync_rules: 1,
  enabled_rules: 1,
  running_rules: 1,
  stopped_rules: 0,
  open_incidents: 1,
  last_synced_at: justNow(),
  blocked_events: 0,
  blocked_entry_id: null,
  blocked_rule_id: null,
  next_pass_at: null,
}

/** Account names, emails, calendar names, event titles, and avatar initials the fixtures introduce. */
const FIXTURE_TEXT = [
  "Dana Calendar",
  "dana@example.test",
  "Partner Calendar",
  "partner@example.test",
  "Family",
  "Work",
  "Team Sync",
  "DC",
  "PC",
]

type Scenario = {
  dashboard: Dashboard
  rules: RuleSummary[]
  recentChanges: RecentChange[]
  providers?: CalendarProvider[]
  /** GET /api/v1/account/plan; `{}`, which names no plan, unless a test says otherwise. */
  ownPlan?: OwnPlan
}

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: () => Promise.resolve(body) } as Response
}

function mockFetch(scenario: Scenario) {
  const responses: Record<string, unknown> = {
    "/api/v1/dashboard": scenario.dashboard,
    "/api/v1/rules": scenario.rules,
    "/api/v1/accounts": [accountA, accountB],
    "/api/v1/providers": scenario.providers ?? [],
    "/api/v1/recent-changes": scenario.recentChanges,
    "/api/v1/account/plan": scenario.ownPlan ?? {},
  }
  vi.stubGlobal("fetch", vi.fn((input: string | URL) => Promise.resolve(respond(String(input)))))
  function respond(url: string): Response {
    const path = url.split("?")[0] ?? ""
    if (path in responses) return jsonResponse(responses[path])
    if (/^\/api\/v1\/accounts\/.+\/calendars$/.test(path)) return jsonResponse([])
    return jsonResponse({})
  }
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
  vi.restoreAllMocks()
})

async function settle(times = 6) {
  for (let i = 0; i < times; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

async function renderOverview(i18n: I18n, scenario: Scenario) {
  mockFetch(scenario)
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <OverviewView onViewChange={() => undefined} onOpenRule={() => undefined} />
        </QueryClientProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
  return { container }
}

/** One rule counts and the plan lets one sync, so no other rule may start. */
const atRuleLimit: OwnPlan = {
  basis: "plan",
  plan: { key: "free", name: "Free", on_default: true },
  limits: { rules: 1, connected_accounts: 2, integration_tokens: 0, sync_interval: "5_minutes" },
  rules_counted: 1,
  connected_accounts: 2,
  integration_tokens: 0,
  instant: false,
  poll_every_minutes: 5,
  may_connect_account: false,
  may_issue_token: false,
  over_rule_limit: false,
}

describe("OverviewView", () => {
  it("puts what an open Incident says in the rule's problem sentence", async () => {
    const { container } = await renderOverview(testI18n(), {
      dashboard: attentionDashboard,
      rules: [rule],
      recentChanges: [repeatedChange],
    })
    expect(container.querySelector("#health-title")?.textContent).toBe("A rule needs a look")
    expect(container.querySelector(".health-hero")?.textContent).toContain("Family → Work")
    const detail = container.querySelector(".health-hero-detail")?.textContent
    expect(detail).toContain("Access to Google Calendar was denied")
    expect(detail).not.toContain("Stored summary")
    expect(container.querySelector(".activity-happened-suffix")?.textContent).toContain("3 times since")
  })

  it("offers one Connect action as the first step, choosing the provider in its menu", async () => {
    const provider = (kind: string, displayName: string): CalendarProvider => ({
      kind,
      display_name: displayName,
      connect_url: `/api/v1/oauth/${kind}/start`,
      redirect_uri: `http://localhost/api/v1/oauth/${kind}/callback`,
      cause_anchors: {},
    })
    const { container } = await renderOverview(testI18n(), {
      dashboard: {
        ...attentionDashboard,
        status: "setup",
        needs_attention: false,
        problems: [],
        connected_accounts: 0,
        sync_rules: 0,
        enabled_rules: 0,
        running_rules: 0,
        open_incidents: 0,
        last_synced_at: null,
      },
      rules: [],
      recentChanges: [],
      providers: [provider("google", "Google"), provider("outlook", "Microsoft")],
    })
    const action = [...container.querySelectorAll<HTMLElement>(".step-action > *")]
    expect(action).toHaveLength(1)
    const trigger = action[0]?.querySelector("button")
    expect(trigger?.textContent).toBe("Connect an account")
    expect(trigger?.className).toContain("bg-primary")
    act(() => trigger?.click())
    expect(
      [...container.querySelectorAll("[role='menu'] a[role='menuitem']")].map((item) => item.getAttribute("href")),
    ).toEqual(["/api/v1/oauth/google/start", "/api/v1/oauth/outlook/start"])
  })

  it("keeps the first step's Connect unavailable at the plan's account limit, saying why", async () => {
    const google: CalendarProvider = {
      kind: "google",
      display_name: "Google",
      connect_url: "/api/v1/oauth/google/start",
      redirect_uri: "http://localhost/api/v1/oauth/google/callback",
      cause_anchors: {},
    }
    // A disconnected account still counts, so even the first step can meet the limit.
    const atAccountLimit: OwnPlan = {
      basis: "plan",
      plan: { key: "free", name: "Free", on_default: true },
      limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
      rules_counted: 0,
      connected_accounts: 1,
      integration_tokens: 0,
      instant: false,
      poll_every_minutes: 5,
      may_connect_account: false,
      may_issue_token: false,
      over_rule_limit: false,
    }
    const { container } = await renderOverview(testI18n(), {
      dashboard: {
        ...attentionDashboard,
        status: "setup",
        needs_attention: false,
        problems: [],
        connected_accounts: 0,
        sync_rules: 0,
        enabled_rules: 0,
        running_rules: 0,
        open_incidents: 0,
        last_synced_at: null,
      },
      rules: [],
      recentChanges: [],
      providers: [google],
      ownPlan: atAccountLimit,
    })

    const step = container.querySelector<HTMLElement>(".step-action")!
    expect(step.children).toHaveLength(1)
    const connect = step.querySelector("button")!
    expect(connect.textContent.trim()).toBe("Connect Google account")
    expect(connect.getAttribute("aria-disabled")).toBe("true")
    expect(step.querySelector("a[href^='/api/v1/oauth']")).toBeNull()
    expect(document.getElementById(connect.getAttribute("aria-describedby") ?? "")?.textContent).toBe(
      "Your plan allows 1 calendar account, and disconnected accounts count too. See your plan",
    )
  })

  it.each<[string, OwnPlan | undefined, string]>([
    ["will not let it start", { ...atRuleLimit }, "Previewed"],
    ["has room for it", { ...atRuleLimit, rules_counted: 0 }, "Ready to start"],
    ["names no plan", undefined, "Ready to start"],
  ])("badges a previewed rule by whether it may start when the plan %s", async (_case, ownPlan, badge) => {
    const previewed: RuleSummary = {
      ...rule,
      id: "rule-2",
      state: "dry_run_validated",
      source: { ...rule.destination },
      destination: { ...rule.source },
      last_sync: null,
    }
    const { container } = await renderOverview(testI18n(), {
      dashboard: attentionDashboard,
      rules: [rule, previewed],
      recentChanges: [],
      ...(ownPlan ? { ownPlan } : {}),
    })
    const row = container.querySelector<HTMLElement>(".overview-rules a[href='/rules/rule-2']")?.closest("li")
    expect(row?.lastElementChild?.textContent.trim()).toBe(badge)
  })

  it("has no untranslated text for a rule with an open incident and a repeated change", async () => {
    // The server decides the health; each verdict below leads the hero with different copy.
    const verdicts: Dashboard[] = [
      attentionDashboard,
      { ...attentionDashboard, problems: [overdue] },
      { ...attentionDashboard, status: "stalled", problems: [stalled, overdue] },
      // Before the per-rule problems arrive, a generic hero for the verdict still tells the truth.
      { ...attentionDashboard, status: "stopped", stopped_rules: 1, open_incidents: 0, problems: [] },
      { ...attentionDashboard, status: "review", open_incidents: 0, problems: [] },
      { ...attentionDashboard, status: "waiting", open_incidents: 0, problems: [] },
    ]
    for (const dashboard of verdicts) {
      const { container } = await renderOverview(pseudoI18n(), {
        dashboard,
        rules: [rule],
        recentChanges: [repeatedChange],
      })
      // The recent change's event time is formatted by Intl, so its month, weekday, and AM/PM are data,
      // and the server sends the summaries of problems without a message in English.
      expect(untranslatedText(container, [...FIXTURE_TEXT, ...dateWords(), ...SERVER_TEXT])).toEqual([])
      act(() => root?.unmount())
      root = null
    }
  })
})
