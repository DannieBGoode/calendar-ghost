/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { StaticI18nProvider } from "@/i18n/provider"
import { dateWords, pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { SessionStatus, UserOverview } from "@/lib/api"

import { AdministratorViewSection } from "./settings-administrator-view"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const justNow = new Date(Date.now() - 10_000).toISOString()
const RULE_NAMES = ["Calendar 1 → Calendar 2", "Calendar 2 → Calendar 3"]

const overview: UserOverview = {
  user: {
    id: "user-robin",
    email: "robin@example.test",
    role: "user",
    state: "active",
    created_at: justNow,
    last_sign_in_at: justNow,
  },
  status: {
    status: "stopped",
    needs_attention: true,
    summary: "Calendar 1 → Calendar 2: Stopped syncing.",
    version: "0.1.1",
    checked_at: justNow,
    last_synced_at: justNow,
    scheduler: { configured: true, last_pass_completed_at: justNow, current_pass_started_at: null },
    counts: {
      rules: 2,
      running: 1,
      stopped: 1,
      paused: 0,
      overdue: 0,
      open_incidents: 0,
      blocked_events: 0,
      disconnected_accounts: 0,
      lapsed_accounts: 0,
    },
    problems: [{ kind: "stopped", rule_id: "rule-1", summary: "Stopped syncing", since: null, message: null }],
    rules: [
      {
        id: "rule-1",
        name: RULE_NAMES[0]!,
        state: "degraded",
        source: { calendar: "Calendar 1", provider: "google", number: 1 },
        destination: { calendar: "Calendar 2", provider: "google", number: 2 },
        projection: "busy_only",
        last_succeeded_at: justNow,
        running: null,
        problem: { kind: "stopped", rule_id: "rule-1", summary: "Stopped syncing", since: null, message: null },
      },
      {
        id: "rule-2",
        name: RULE_NAMES[1]!,
        state: "enabled",
        source: { calendar: "Calendar 2", provider: "google", number: 2 },
        destination: { calendar: "Calendar 3", provider: "google", number: 3 },
        projection: "busy_only",
        last_succeeded_at: null,
        running: null,
        problem: null,
      },
    ],
    incidents: [],
  },
  resources: {
    rules: 2,
    connected_accounts: 2,
    activity_entries: 14,
    provider_calls: [{ provider: "google", calls: 120, rate_limited: 0, failed: 1 }],
    since: "2026-09-10",
  },
}

const member: SessionStatus = {
  authenticated: true,
  installation_sends_email: false,
  user: { id: "user-robin", email: "robin@example.test", role: "user", notify_by_email: true, language: null },
}
const administrator: SessionStatus = {
  ...member,
  user: { ...member.user!, role: "installation_administrator" },
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

let requested: string[] = []
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

async function render(i18n: I18n, session: SessionStatus, policy = "invitation_only") {
  const answers: Record<string, Response> = {
    "/api/v1/session": jsonResponse(session),
    "/api/v1/registration": jsonResponse({ policy, only_me_available: policy === "only_me" }),
    "/api/v1/account/overview": jsonResponse(overview),
  }
  requested = []
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL) => {
      requested.push(String(input))
      return Promise.resolve(answers[String(input)] ?? jsonResponse({}, 404))
    }),
  )
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <AdministratorViewSection />
        </QueryClientProvider>
      </StaticI18nProvider>,
    )
  })
  for (let i = 0; i < 6; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

describe("AdministratorViewSection", () => {
  it("shows exactly what administrators see, and what they never see", async () => {
    await render(testI18n(), member)

    const text = container.textContent
    expect(container.querySelector("h2")?.textContent).toBe("What your administrator can see")
    expect(text).toContain("They never see your calendar names, Google account emails, or events.")
    expect(text).toContain("Stopped")
    expect(text).toContain("A rule stopped syncing and writes nothing until it is fixed.")
    expect(text).toContain("Stopped syncing")
    for (const name of RULE_NAMES) expect(text).toContain(name)
    expect(text).toContain("2 rules")
    expect(text).toContain("14 Activity entries")
    expect(text).toContain("Google Calendar: 120 calls, 0 refused for its rate limit, 1 failed")
    expect(requested).toContain("/api/v1/account/overview")
  })

  it("is shown to an administrator while other people can join", async () => {
    await render(testI18n(), administrator)

    expect(container.querySelector("h2")?.textContent).toBe("What your administrator can see")
  })

  it("is not shown under Only me, where nobody else is here", async () => {
    await render(testI18n(), administrator, "only_me")

    expect(container.textContent).toBe("")
    expect(requested).not.toContain("/api/v1/account/overview")
  })

  it("has no untranslated text", async () => {
    await render(pseudoI18n(), member)

    expect(untranslatedText(container, [...RULE_NAMES, ...dateWords()])).toEqual([])
  })
})
