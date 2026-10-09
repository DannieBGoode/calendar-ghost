/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { dateWords, pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { PendingInvitation, Person, Registration, SessionStatus } from "@/lib/api"
import { integrationExamples } from "@/lib/integrations"

import { SettingsPage } from "./settings"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const ORIGIN = "http://localhost:8000"
// A few seconds ago, so relative times read "just now" from the catalog rather than from Intl.
const justNow = new Date(Date.now() - 10_000).toISOString()
const nextWeek = new Date(Date.now() + 7 * 86_400_000).toISOString()

const me: Person = {
  id: "user-dana",
  email: "dana@example.test",
  role: "installation_administrator",
  state: "active",
  created_at: justNow,
  last_sign_in_at: justNow,
}
const robin: Person = { ...me, id: "user-robin", email: "robin@example.test", role: "user", last_sign_in_at: null }
const sam: Person = { ...me, id: "user-sam", email: "sam@example.test", role: "user", state: "disabled" }
const invitation: PendingInvitation = { id: "inv-1", created_at: justNow, expires_at: nextWeek }

function session(role: "installation_administrator" | "user"): SessionStatus {
  return {
    authenticated: true,
    installation_sends_email: true,
    user: { id: me.id, email: me.email, role, notify_by_email: true, language: null },
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

type Call = { method: string; path: string; body: unknown }
type Scenario = {
  role?: "installation_administrator" | "user"
  registration?: Registration
  people?: Person[]
  /** Answers by "METHOD /path", overriding the defaults. */
  answers?: Record<string, Response>
}

let calls: Call[] = []

function serve({ role = "installation_administrator", registration, people = [me, robin, sam], answers = {} }: Scenario) {
  const defaults: Record<string, Response> = {
    "GET /api/v1/session": jsonResponse(session(role)),
    "GET /api/v1/google/configuration": jsonResponse({ configured: true, redirect_uri: null }),
    "GET /api/v1/accounts": jsonResponse([]),
    "GET /api/v1/integration-tokens": jsonResponse([]),
    "GET /api/v1/storage": jsonResponse({
      database: { bytes: 1024 * 1024, reclaimable_bytes: 0, activity_entries: 0, oldest_activity_at: null },
      logs: { bytes: 0, files: 0, oldest_at: null, newest_at: null },
      activity_ages: [30, 90, 180, 365],
    }),
    "GET /api/v1/registration": jsonResponse(registration ?? { policy: "invitation_only", only_me_available: false }),
    "GET /api/v1/users": jsonResponse(people),
    "GET /api/v1/invitations": jsonResponse([invitation]),
    "POST /api/v1/invitations": jsonResponse({ id: "inv-2", token: "inv_synthetic", expires_at: nextWeek }, 201),
    "DELETE /api/v1/invitations/inv-1": { ok: true, status: 204, json: () => Promise.resolve(null) } as Response,
    "POST /api/v1/users/user-robin/password-reset-links": jsonResponse(
      { id: "reset-1", token: "reset_synthetic", expires_at: nextWeek },
      201,
    ),
    "DELETE /api/v1/users/user-robin": jsonResponse({ rules: 2, deleted: 5, detached: 0, left: 0 }),
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
            <SettingsPage />
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

function button(label: string, scope: ParentNode = container): HTMLButtonElement {
  const found = [...scope.querySelectorAll("button")].find((item) => item.textContent.trim() === label)
  if (!found) throw new Error(`No button labelled ${label}`)
  return found
}

function personRow(email: string): HTMLElement {
  const heading = [...container.querySelectorAll(".person-row h3")].find((item) => item.textContent === email)
  if (!heading) throw new Error(`No person ${email}`)
  return heading.closest<HTMLElement>(".person-row")!
}

async function click(target: HTMLElement) {
  act(() => target.click())
  await settle()
}

async function choose(email: string, action: string) {
  await click(personRow(email).querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
  const items = [...personRow(email).querySelectorAll<HTMLButtonElement>("[role='menuitem']")]
  const item = items.find((candidate) => candidate.querySelector(".overflow-menu-label")?.textContent === action)
  if (!item) throw new Error(`No action ${action} for ${email}`)
  await click(item)
}

function sent(method: string, path: string): Call | undefined {
  return calls.find((call) => call.method === method && call.path === path)
}

function requested(path: string): boolean {
  return calls.some((call) => call.path === path)
}

describe("Settings for an administrator", () => {
  it("has no untranslated text with people, invitations, and links to pass on", async () => {
    await renderSettings(pseudoI18n())
    await click(container.querySelector<HTMLButtonElement>("#invite-someone")!)
    await click(personRow("robin@example.test").querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
    expect(container.querySelector("[role='menu']")).not.toBeNull()
    const fixtures = [
      me.email!,
      robin.email!,
      sam.email!,
      `${ORIGIN}/invitation#inv_synthetic`,
      ...dateWords(),
      ...integrationExamples(testI18n(), ORIGIN, true).map((example) => example.code),
    ]
    expect(container.querySelector(".link-reveal")).not.toBeNull()
    expect(untranslatedText(container, fixtures)).toEqual([])
  })

  it("shows who can join, and the people and invitations only while invitations are on", async () => {
    await renderSettings(testI18n(), { registration: { policy: "only_me", only_me_available: true } })
    expect(section("registration-title")).not.toBeNull()
    expect(section("people-title")).toBeNull()
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

  it("lists people with their role, state, and sign-ins, and no actions on yourself", async () => {
    await renderSettings(testI18n())
    const rows = [...container.querySelectorAll(".person-row h3")].map((heading) => heading.textContent)
    expect(rows).toEqual(["dana@example.test", "robin@example.test", "sam@example.test"])
    expect(personRow("dana@example.test").textContent).toContain("You")
    expect(personRow("dana@example.test").textContent).toContain("Administrator")
    expect(personRow("dana@example.test").querySelector("[aria-haspopup='menu']")).toBeNull()
    expect(personRow("robin@example.test").textContent).toContain("Joined just now · never signed in")
    expect(personRow("sam@example.test").textContent).toContain("Disabled")
  })

  it("makes someone an administrator", async () => {
    await renderSettings(testI18n(), {
      answers: { "PUT /api/v1/users/user-robin/role": jsonResponse({ ...robin, role: "installation_administrator" }) },
    })
    await choose("robin@example.test", "Make administrator")
    expect(sent("PUT", "/api/v1/users/user-robin/role")?.body).toEqual({ role: "installation_administrator" })
    expect(section("people-title")?.querySelector("[role='status']")?.textContent).toBe(
      "robin@example.test is now an administrator.",
    )
  })

  it("disables and enables a person", async () => {
    await renderSettings(testI18n(), {
      answers: {
        "PUT /api/v1/users/user-robin/state": jsonResponse({ ...robin, state: "disabled" }),
        "PUT /api/v1/users/user-sam/state": jsonResponse({ ...sam, state: "active" }),
      },
    })
    await choose("robin@example.test", "Disable")
    expect(sent("PUT", "/api/v1/users/user-robin/state")?.body).toEqual({ state: "disabled" })
    await choose("sam@example.test", "Enable")
    expect(sent("PUT", "/api/v1/users/user-sam/state")?.body).toEqual({ state: "active" })
  })

  it("explains the server's refusal to remove the last administrator", async () => {
    const refusal = { detail: "last", code: "last_administrator", params: {} }
    await renderSettings(testI18n(), {
      people: [me, { ...robin, role: "installation_administrator" }],
      answers: { "PUT /api/v1/users/user-robin/role": jsonResponse(refusal, 409) },
    })
    await choose("robin@example.test", "Remove administrator")
    expect(sent("PUT", "/api/v1/users/user-robin/role")?.body).toEqual({ role: "user" })
    expect(personRow("robin@example.test").parentElement?.querySelector("[role='alert']")?.textContent).toBe(
      "Someone else must be an administrator first. Calendar Ghost always keeps one who can sign in.",
    )
  })

  it("creates a password reset link to pass on, shown once", async () => {
    await renderSettings(testI18n())
    await choose("robin@example.test", "Create password reset link")
    expect(sent("POST", "/api/v1/users/user-robin/password-reset-links")).toBeDefined()
    const reveal = container.querySelector(".link-reveal")!
    expect(reveal.querySelector("h3")?.textContent).toBe("Copy the password reset link for robin@example.test now")
    expect(reveal.querySelector<HTMLInputElement>("input")!.value).toBe(`${ORIGIN}/password-reset#reset_synthetic`)

    await click(button("Done", reveal))
    expect(container.querySelector(".link-reveal")).toBeNull()
  })

  it("deletes a person only after confirming what is removed", async () => {
    await renderSettings(testI18n())
    await choose("robin@example.test", "Delete")
    const confirmation = container.querySelector<HTMLElement>("#delete-person-user-robin")!
    expect(confirmation.querySelector("h3")?.textContent).toBe("Delete robin@example.test permanently?")
    expect(confirmation.textContent).toContain("Backups taken before now keep their records")
    expect(sent("DELETE", "/api/v1/users/user-robin")).toBeUndefined()

    await click(button("Delete permanently", confirmation))
    expect(sent("DELETE", "/api/v1/users/user-robin")).toBeDefined()
    expect(section("people-title")?.querySelector("[role='status']")?.textContent).toBe(
      "robin@example.test was deleted. 5 events their rules wrote were deleted.",
    )
  })

  it("invites someone with a link shown once, and revokes a waiting invitation", async () => {
    await renderSettings(testI18n())
    await click(button("Invite someone"))
    expect(sent("POST", "/api/v1/invitations")).toBeDefined()
    const reveal = container.querySelector(".link-reveal")!
    expect(reveal.querySelector<HTMLInputElement>("input")!.value).toBe(`${ORIGIN}/invitation#inv_synthetic`)
    expect(reveal.textContent).toContain("It works once, until")

    await click(button("Revoke"))
    expect(sent("DELETE", "/api/v1/invitations/inv-1")).toBeDefined()
  })
})

describe("Settings for someone who is not an administrator", () => {
  it("hides who can join, people, and storage, and never asks for them", async () => {
    await renderSettings(testI18n(), { role: "user" })
    expect(section("accounts-title") ?? container.querySelector("h1")).not.toBeNull()
    expect(section("registration-title")).toBeNull()
    expect(section("people-title")).toBeNull()
    expect(section("storage-title")).toBeNull()
    expect(requested("/api/v1/registration")).toBe(false)
    expect(requested("/api/v1/users")).toBe(false)
    expect(requested("/api/v1/storage")).toBe(false)
    expect(section("own-account-title")).not.toBeNull()
  })
})
