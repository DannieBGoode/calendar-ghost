/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { dateWords, pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { Person, Registration, SessionStatus, UserOverview } from "@/lib/api"
import type { SettingsTab } from "@/lib/navigation"

import { SettingsPage } from "./settings"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const ORIGIN = "http://localhost:8000"
// A few seconds ago, so relative times read "just now" from the catalog rather than from Intl.
const justNow = new Date(Date.now() - 10_000).toISOString()

const me: Person = {
  id: "user-dana",
  email: "dana@example.test",
  role: "installation_administrator",
  state: "active",
  created_at: justNow,
  last_sign_in_at: justNow,
}

function session(role: "installation_administrator" | "user"): SessionStatus {
  return {
    authenticated: true,
    installation_sends_email: true,
    user: { id: me.id, email: me.email, role, notify_by_email: true, language: null },
  }
}

/** What the Operator Overview shows about someone with nothing set up yet. */
const NOTHING_SET_UP: UserOverview = {
  user: { id: "user-dana", email: "dana@example.test", role: "user", state: "active", created_at: "2026-09-01T00:00:00Z", last_sign_in_at: null },
  status: {
    status: "setup",
    needs_attention: false,
    summary: "Setup is not finished.",
    version: "0.1.1",
    checked_at: "2026-09-01T00:00:00Z",
    last_synced_at: null,
    scheduler: { configured: true, last_pass_completed_at: null, current_pass_started_at: null },
    counts: { rules: 0, running: 0, stopped: 0, paused: 0, overdue: 0, open_incidents: 0, blocked_events: 0, disconnected_accounts: 0, lapsed_accounts: 0 },
    problems: [],
    rules: [],
    incidents: [],
  },
  resources: { rules: 0, connected_accounts: 0, activity_entries: 0, provider_calls: [], since: "2026-09-01" },
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

type Call = { method: string; path: string; body: unknown }
type Scenario = {
  tab?: SettingsTab
  role?: "installation_administrator" | "user"
  registration?: Registration
  /** Answers by "METHOD /path", overriding the defaults. */
  answers?: Record<string, Response>
}

let calls: Call[] = []

function serve({ role = "installation_administrator", registration, answers = {} }: Scenario) {
  const defaults: Record<string, Response> = {
    "GET /api/v1/session": jsonResponse(session(role)),
    "GET /api/v1/google/configuration": jsonResponse({ configured: true, redirect_uri: null }),
    "GET /api/v1/accounts": jsonResponse([]),
    "GET /api/v1/integration-tokens": jsonResponse([]),
    "GET /api/v1/account/overview": jsonResponse(NOTHING_SET_UP),
    "GET /api/v1/storage": jsonResponse({
      database: { bytes: 1024 * 1024, reclaimable_bytes: 0, activity_entries: 0, oldest_activity_at: null },
      logs: { bytes: 0, files: 0, oldest_at: null, newest_at: null },
      activity_ages: [30, 90, 180, 365],
    }),
    "GET /api/v1/registration": jsonResponse(registration ?? { policy: "invitation_only", only_me_available: false }),
  }
  const routes = { ...defaults, ...answers }
  calls = []
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET"
      const path = String(input).split("?")[0] ?? ""
      const body: unknown = init?.body ? JSON.parse(init.body as string) : undefined
      calls.push({ method, path, body })
      return Promise.resolve(routes[`${method} ${path}`] ?? jsonResponse({}))
    }),
  )
}

let container: HTMLDivElement
let root: Root | null = null
let address: string

function page() {
  return window as typeof window & { happyDOM: { setURL: (url: string) => void } }
}

beforeEach(() => {
  container = document.createElement("div")
  document.body.append(container)
  address = window.location.href
  page().happyDOM.setURL(`${ORIGIN}/settings`)
})

afterEach(() => {
  if (root) {
    act(() => root?.unmount())
    root = null
  }
  container.remove()
  page().happyDOM.setURL(address)
  vi.restoreAllMocks()
})

async function settle(times = 8) {
  for (let i = 0; i < times; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

async function renderSettings(i18n: I18n, scenario: Scenario = {}) {
  serve(scenario)
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <SettingsPage tab={scenario.tab ?? "administration"} onOpenTab={() => undefined} onOpenPeople={() => undefined} />
          </QueryClientProvider>
        </ThemeProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
}

function section(titleId: string): HTMLElement | null {
  return container.querySelector<HTMLElement>(`[aria-labelledby='${titleId}']`)
}

async function click(target: HTMLElement) {
  act(() => target.click())
  await settle()
}

function sent(method: string, path: string): Call | undefined {
  return calls.find((call) => call.method === method && call.path === path)
}

function requested(path: string): boolean {
  return calls.some((call) => call.path === path)
}

describe("Administration", () => {
  it("has no untranslated text", async () => {
    await renderSettings(pseudoI18n())
    expect(untranslatedText(container, dateWords())).toEqual([])
  })

  it("holds who can join and storage, and leaves people and invitations to the People page", async () => {
    await renderSettings(testI18n(), { registration: { policy: "invitation_only", only_me_available: false } })
    expect(section("registration-title")).not.toBeNull()
    expect(section("storage-title")).not.toBeNull()
    expect(section("people-list-title")).toBeNull()
    expect(section("invitations-title")).toBeNull()
    expect(requested("/api/v1/users")).toBe(false)
    expect(requested("/api/v1/invitations")).toBe(false)
  })

  it("switches to Invitation only", async () => {
    await renderSettings(testI18n(), {
      registration: { policy: "only_me", only_me_available: true },
      answers: { "PUT /api/v1/registration": jsonResponse({ policy: "invitation_only", only_me_available: true }) },
    })
    await click(container.querySelector<HTMLInputElement>("input[value='invitation_only']")!)
    expect(sent("PUT", "/api/v1/registration")?.body).toEqual({ policy: "invitation_only" })
    expect(section("registration-title")?.querySelector("[role='status']")?.textContent).toBe(
      "People can now join with an invitation link.",
    )
  })

  it("keeps Only me unavailable while other people are here, and says why", async () => {
    await renderSettings(testI18n(), { registration: { policy: "invitation_only", only_me_available: false } })
    const onlyMe = container.querySelector<HTMLInputElement>("input[value='only_me']")!
    expect(onlyMe.disabled).toBe(true)
    expect(container.querySelector<HTMLInputElement>("input[value='invitation_only']")!.checked).toBe(true)
    expect(onlyMe.closest("label")?.textContent).toContain(
      "Available again once you are the only person here. Delete the other people first.",
    )
  })
})

describe("Settings for someone who is not an administrator", () => {
  it("offers no Administration tab, shows Your account at its address, and never asks for what it holds", async () => {
    await renderSettings(testI18n(), { role: "user", tab: "administration" })
    const tabs = [...container.querySelectorAll("nav.page-tabs a")].map((tab) => tab.textContent)
    expect(tabs).toEqual(["Your account", "Connections"])
    expect(container.querySelector("nav.page-tabs [aria-current='page']")?.textContent).toBe("Your account")
    expect(section("own-account-title")).not.toBeNull()
    expect(section("registration-title")).toBeNull()
    expect(section("storage-title")).toBeNull()
    expect(requested("/api/v1/registration")).toBe(false)
    expect(requested("/api/v1/users")).toBe(false)
    expect(requested("/api/v1/storage")).toBe(false)
  })

  it("keeps their own account under Your account", async () => {
    await renderSettings(testI18n(), { role: "user", tab: "account" })
    expect(section("own-account-title")).not.toBeNull()
  })
})
