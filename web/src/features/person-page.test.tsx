/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { dateWords, pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { SessionStatus, UserOverview } from "@/lib/api"

import { PersonView } from "./person-page"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const justNow = new Date(Date.now() - 10_000).toISOString()
const RULE_NAME = "Calendar 1 → Calendar 2"

const robin: UserOverview = {
  user: {
    id: "user-robin",
    email: "robin@example.test",
    role: "user",
    state: "active",
    created_at: justNow,
    last_sign_in_at: null,
  },
  status: {
    status: "review",
    needs_attention: true,
    summary: "3 events couldn't be synced.",
    version: "0.1.1",
    checked_at: justNow,
    last_synced_at: justNow,
    scheduler: { configured: true, last_pass_completed_at: justNow, current_pass_started_at: null },
    counts: {
      rules: 1,
      running: 1,
      stopped: 0,
      paused: 0,
      overdue: 0,
      open_incidents: 0,
      blocked_events: 3,
      disconnected_accounts: 0,
      lapsed_accounts: 0,
    },
    problems: [{ kind: "blocked", rule_id: "rule-1", summary: "3 events couldn't be synced", since: null, message: null }],
    rules: [
      {
        id: "rule-1",
        name: RULE_NAME,
        state: "enabled",
        source: { calendar: "Calendar 1", provider: "google" },
        destination: { calendar: "Calendar 2", provider: "google" },
        projection: "busy_only",
        last_succeeded_at: justNow,
        running: null,
        problem: null,
      },
    ],
    incidents: [],
  },
  resources: {
    rules: 1,
    connected_accounts: 2,
    activity_entries: 40,
    provider_calls: [{ provider: "google", calls: 75, rate_limited: 1, failed: 0 }],
    since: "2026-09-10",
  },
}

const session: SessionStatus = {
  authenticated: true,
  installation_sends_email: false,
  user: { id: "user-dana", email: "dana@example.test", role: "installation_administrator", notify_by_email: true, language: null },
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

type Call = { method: string; path: string; body: unknown }
let calls: Call[] = []
let container: HTMLDivElement
let root: Root | null = null
let back: ReturnType<typeof vi.fn<() => void>>
let deleted: ReturnType<typeof vi.fn<(notice: string) => void>>

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

async function settle(times = 8) {
  for (let i = 0; i < times; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

async function renderPerson(i18n: I18n, personId = "user-robin", answers: Record<string, Response> = {}) {
  const routes: Record<string, Response> = {
    "GET /api/v1/session": jsonResponse(session),
    "GET /api/v1/users/user-robin/overview": jsonResponse(robin),
    "GET /api/v1/users/user-dana/overview": jsonResponse({
      ...robin,
      user: { ...robin.user, id: "user-dana", email: "dana@example.test", role: "installation_administrator" },
    }),
    "PUT /api/v1/users/user-robin/state": jsonResponse({ ...robin.user, state: "disabled" }),
    "DELETE /api/v1/users/user-robin": jsonResponse({ rules: 1, deleted: 4, detached: 0, left: 0 }),
    ...answers,
  }
  calls = []
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET"
      const path = String(input).split("?")[0] ?? ""
      const body: unknown = init?.body ? JSON.parse(init.body as string) : undefined
      calls.push({ method, path, body })
      const notFound = { detail: "user nobody does not exist", code: "user_not_found", params: {} }
      return Promise.resolve(routes[`${method} ${path}`] ?? jsonResponse(notFound, 404))
    }),
  )
  back = vi.fn<() => void>()
  deleted = vi.fn<(notice: string) => void>()
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <PersonView personId={personId} onBack={back} onDeleted={deleted} />
          </QueryClientProvider>
        </ThemeProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
}

async function click(target: HTMLElement) {
  act(() => target.click())
  await settle()
}

function button(label: string): HTMLButtonElement {
  const found = [...container.querySelectorAll("button")].find((item) => item.textContent.trim() === label)
  if (!found) throw new Error(`No button labelled ${label}`)
  return found
}

async function choose(action: string) {
  await click(container.querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
  const item = [...container.querySelectorAll<HTMLButtonElement>("[role='menuitem']")].find(
    (candidate) => candidate.querySelector(".overflow-menu-label")?.textContent === action,
  )
  if (!item) throw new Error(`No action ${action}`)
  await click(item)
}

describe("A person's page", () => {
  it("shows who they are and exactly what the Operator Overview shows about them", async () => {
    await renderPerson(testI18n())

    expect(container.querySelector("h1")?.textContent).toBe("robin@example.test")
    const text = container.textContent
    expect(text).toContain("Never signed in")
    expect(text).toContain("Needs a look")
    expect(text).toContain("3 events couldn't be synced")
    expect(text).toContain(RULE_NAME)
    expect(text).toContain("40 Activity entries")
    expect(text).toContain("Google Calendar: 75 calls, 1 refused for its rate limit, 0 failed")
    expect([...container.querySelectorAll("h2")].map((heading) => heading.textContent)).toEqual([
      "Problems",
      "Rules",
      "Resource use",
    ])
  })

  it("has no untranslated text with its actions open", async () => {
    await renderPerson(pseudoI18n())
    await click(container.querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
    expect(untranslatedText(container, ["robin@example.test", RULE_NAME, ...dateWords()])).toEqual([])
  })

  it("returns to People from its link", async () => {
    await renderPerson(testI18n())
    const link = container.querySelector<HTMLAnchorElement>("a.person-back")!
    expect(link.getAttribute("href")).toBe("/people")
    await click(link)
    expect(back).toHaveBeenCalledOnce()
  })

  it("offers the actions People offers, and refreshes what it shows after one", async () => {
    await renderPerson(testI18n())
    const before = calls.filter((call) => call.path === "/api/v1/users/user-robin/overview").length
    await choose("Disable")
    expect(calls.find((call) => call.method === "PUT")?.body).toEqual({ state: "disabled" })
    expect(container.querySelector("[role='status']")?.textContent).toBe(
      "robin@example.test can no longer sign in. Their rules wait until you enable them again.",
    )
    expect(calls.filter((call) => call.path === "/api/v1/users/user-robin/overview").length).toBeGreaterThan(before)
  })

  it("returns to People, saying what was deleted, once they are deleted", async () => {
    await renderPerson(testI18n())
    await choose("Delete")
    await click(button("Delete permanently"))
    expect(calls.some((call) => call.method === "DELETE")).toBe(true)
    expect(deleted).toHaveBeenCalledWith("robin@example.test was deleted. 4 events their rules wrote were deleted.")
  })

  it("offers no actions on your own page", async () => {
    await renderPerson(testI18n(), "user-dana")
    expect(container.querySelector("h1")?.textContent).toBe("dana@example.testYou")
    expect(container.querySelector("[aria-haspopup='menu']")).toBeNull()
  })

  it("says when nobody here has the address", async () => {
    await renderPerson(testI18n(), "nobody")
    expect(container.querySelector(".empty-panel h1")?.textContent).toBe("Nobody here has this address")
    await click(button("Back to People"))
    expect(back).toHaveBeenCalledOnce()
  })
})
