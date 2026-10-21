/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { dateWords, pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { Person, Registration, SessionStatus } from "@/lib/api"
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
    user: { id: me.id, email: me.email, role, notify_by_email: true, instant_sync: true, instant_sync_availability: "on", instant_sync_help: null, language: null },
  }
}

/** What the Operator Overview shows about someone with nothing set up yet. */
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
    "GET /api/v1/identity-email": jsonResponse({ configured: false, unavailable_reason: "smtp_missing", test_state: "idle", tested_at: null }),
    "GET /api/v1/providers": jsonResponse([]),
    "GET /api/v1/accounts": jsonResponse([]),
    "GET /api/v1/integration-tokens": jsonResponse([]),
    "GET /api/v1/storage": jsonResponse({
      database: { bytes: 1024 * 1024, reclaimable_bytes: 0, activity_entries: 0, oldest_activity_at: null },
      logs: { bytes: 0, files: 0, oldest_at: null, newest_at: null },
      activity_ages: [30, 90, 180, 365],
    }),
    "GET /api/v1/registration": jsonResponse(registration ?? { policy: "invitation_only", only_me_available: false, open_available: false, open_unavailable_reason: "identity_email_not_configured" }),
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
  it.each([
    ["identity_email_not_configured", "Configure Identity email"],
    ["identity_email_not_tested", "successful Identity email test"],
  ] as const)("disables Open with a specific readiness reason: %s", async (reason, explanation) => {
    await renderSettings(testI18n(), { registration: { policy: "invitation_only", only_me_available: false, open_available: false, open_unavailable_reason: reason } })
    expect(container.querySelector<HTMLInputElement>("input[value=open]")!.disabled).toBe(true)
    expect(section("registration-title")?.textContent).toContain(explanation)
    expect(container.querySelector("a[href='#identity-email-title']")).not.toBeNull()
    expect(container.querySelector("a[href$='#trusted-proxy-headers']")).not.toBeNull()
  })

  it("keeps selected Open visible after readiness loss and leaves Plans alone", async () => {
    await renderSettings(testI18n(), { registration: { policy: "open", only_me_available: false, open_available: false, open_unavailable_reason: "identity_email_not_tested" } })
    expect(container.querySelector<HTMLInputElement>("input[value=open]")!.checked).toBe(true)
    expect(container.textContent).toContain("With Plans off, everyone has every feature without limits")
    expect(requested("/api/v1/plan-settings")).toBe(false)
  })

  it("warns before Invitation only cancels unfinished public sign-ups", async () => {
    await renderSettings(testI18n(), { registration: { policy: "open", only_me_available: false, open_available: true, open_unavailable_reason: null }, answers: { "PUT /api/v1/registration": jsonResponse({ policy: "invitation_only", only_me_available: false, open_available: true, open_unavailable_reason: null }) } })
    await click(container.querySelector<HTMLInputElement>("input[value=invitation_only]")!)
    expect(sent("PUT", "/api/v1/registration")).toBeUndefined()
    expect(container.textContent).toContain("cancels unfinished public sign-ups")
    await click([...container.querySelectorAll("button")].find((button) => button.textContent === "Switch to Invitation only")!)
    expect(sent("PUT", "/api/v1/registration")?.body).toEqual({ policy: "invitation_only" })
    expect(sent("PUT", "/api/v1/plan-settings")).toBeUndefined()
  })

  it("has no untranslated text", async () => {
    await renderSettings(pseudoI18n())
    expect(untranslatedText(container, dateWords())).toEqual([])
  })

  it("holds who can join and storage, and leaves people, invitations, and plans to the People page", async () => {
    await renderSettings(testI18n(), { registration: { policy: "invitation_only", only_me_available: false, open_available: false, open_unavailable_reason: "identity_email_not_configured" } })
    expect(section("identity-email-title")).not.toBeNull()
    expect(section("registration-title")).not.toBeNull()
    expect(container.querySelectorAll("input[name=registration-policy]")).toHaveLength(3)
    expect(section("identity-email-title")?.querySelector("input")).toBeNull()
    expect(section("storage-title")).not.toBeNull()
    expect(section("plans-title")).toBeNull()
    expect(section("people-list-title")).toBeNull()
    expect(section("invitations-title")).toBeNull()
    expect(requested("/api/v1/users")).toBe(false)
    expect(requested("/api/v1/invitations")).toBe(false)
    expect(requested("/api/v1/plans")).toBe(false)
  })

  it("switches to Invitation only", async () => {
    await renderSettings(testI18n(), {
      registration: { policy: "only_me", only_me_available: true, open_available: false, open_unavailable_reason: "identity_email_not_configured" },
      answers: { "PUT /api/v1/registration": jsonResponse({ policy: "invitation_only", only_me_available: true, open_available: false, open_unavailable_reason: "identity_email_not_configured" }) },
    })
    await click(container.querySelector<HTMLInputElement>("input[value='invitation_only']")!)
    expect(sent("PUT", "/api/v1/registration")?.body).toEqual({ policy: "invitation_only" })
    expect([...section("registration-title")!.querySelectorAll("[role='status']")].at(-1)?.textContent).toBe(
      "People can now join with an invitation link.",
    )
  })

  it("keeps Only me unavailable while other people are here, and says why", async () => {
    await renderSettings(testI18n(), { registration: { policy: "invitation_only", only_me_available: false, open_available: false, open_unavailable_reason: "identity_email_not_configured" } })
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
    expect(section("identity-email-title")).toBeNull()
    expect(requested("/api/v1/identity-email")).toBe(false)
    expect(requested("/api/v1/registration")).toBe(false)
    expect(requested("/api/v1/users")).toBe(false)
    expect(requested("/api/v1/storage")).toBe(false)
  })

  it("keeps their own account under Your account", async () => {
    await renderSettings(testI18n(), { role: "user", tab: "account" })
    expect(section("own-account-title")).not.toBeNull()
  })
})
