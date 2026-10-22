/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import App from "./App"
import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n } from "@/i18n/testing"
import { untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { Dashboard, UserOverview } from "@/lib/api"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const dashboard: Dashboard = {
  status: "setup",
  needs_attention: false,
  problems: [],
  connected_accounts: 0,
  disconnected_accounts: 0,
  lapsed_accounts: 0,
  sync_rules: 0,
  enabled_rules: 0,
  running_rules: 0,
  stopped_rules: 0,
  held_rules: 0,
  open_incidents: 0,
  last_synced_at: null,
  blocked_events: 0,
  blocked_entry_id: null,
  blocked_rule_id: null,
  next_pass_at: null,
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
    scheduler: { configured: true, last_pass_completed_at: null, current_pass_started_at: null, next_pass_at: null },
    counts: { rules: 0, running: 0, stopped: 0, paused: 0, held: 0, overdue: 0, open_incidents: 0, blocked_events: 0, disconnected_accounts: 0, lapsed_accounts: 0 },
    problems: [],
    rules: [],
    incidents: [],
  },
  resources: { rules: 0, connected_accounts: 0, activity_entries: 0, provider_calls: [], since: "2026-09-01" },
  plan: null,
}

const RESPONSES: Record<string, unknown> = {
  "/api/v1/account/sign-in-methods": { has_password: true, identities: [] },
  "/api/v1/sign-in/providers": { providers: [] },
  "/api/v1/setup": { administrator_configured: true },
  "/api/v1/session": { authenticated: true },
  "/api/v1/dashboard": dashboard,
  "/api/v1/rules": [],
  "/api/v1/accounts": [],
  "/api/v1/providers": [],
  "/api/v1/recent-changes": [],
  "/api/v1/integration-tokens": [],
}

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: () => Promise.resolve(body) } as Response
}

let container: HTMLDivElement
let root: Root | null = null

beforeEach(() => {
  container = document.createElement("div")
  document.body.append(container)
  vi.stubGlobal("fetch", vi.fn((input: string | URL) => Promise.resolve(respond(String(input)))))
  function respond(url: string): Response {
    const path = url.split("?")[0] ?? ""
    if (path in RESPONSES) return jsonResponse(RESPONSES[path])
    return jsonResponse({})
  }
})

afterEach(() => {
  if (root) {
    act(() => root?.unmount())
    root = null
  }
  container.remove()
  localStorage.clear()
  vi.restoreAllMocks()
})

async function settle(times = 6) {
  for (let i = 0; i < times; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

async function renderApp(i18n: I18n) {
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <App />
          </QueryClientProvider>
        </ThemeProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
  return { container, queryClient }
}

describe("App", () => {
  it.each([["/sign-up", "Create account"], ["/verify-email#proof", "Finish creating your account"]])("opens %s before the session gate", async (path, heading) => {
    const page = window as typeof window & { happyDOM: { setURL: (url: string) => void } }
    const address = window.location.href
    page.happyDOM.setURL(`http://localhost:8000${path}`)
    try {
      RESPONSES["/api/v1/setup"] = { administrator_configured: true, public_registration_available: true }
      RESPONSES["/api/v1/registrations/check"] = { usable: true, email: "robin@example.test" }
      await renderApp(testI18n())
      expect(container.querySelector("h1")?.textContent).toBe(heading)
      expect(vi.mocked(fetch).mock.calls.some(([url]) => url === "/api/v1/session")).toBe(false)
    } finally {
      RESPONSES["/api/v1/setup"] = { administrator_configured: true }
      delete RESPONSES["/api/v1/registrations/check"]
      page.happyDOM.setURL(address)
    }
  })

  it("translates the whole page", async () => {
    const { container } = await renderApp(pseudoI18n())
    const header = container.querySelector("header")
    const footer = container.querySelector("footer")
    expect(header).not.toBeNull()
    expect(footer).not.toBeNull()
    expect(untranslatedText(container)).toEqual([])
  })

  it("links the footer to the troubleshooting guide in a new tab", async () => {
    const { container } = await renderApp(testI18n())
    const help = [...container.querySelectorAll("footer a")].find((link) => link.textContent === "Get help")
    expect(help?.getAttribute("href")).toBe("https://calendarghost.com/docs/troubleshooting")
    expect(help?.getAttribute("target")).toBe("_blank")
  })

  it("opens an invitation before any session, and the signed-in app once it is accepted", async () => {
    const page = window as typeof window & { happyDOM: { setURL: (url: string) => void } }
    const address = window.location.href
    page.happyDOM.setURL("http://localhost:8000/invitation#inv_synthetic")
    try {
      RESPONSES["/api/v1/invitations/check"] = { usable: true }
      const { container } = await renderApp(testI18n())
      expect(container.querySelector("h1")?.textContent).toBe("Join Calendar Ghost")
      expect(container.querySelector("header")).toBeNull()
    } finally {
      delete RESPONSES["/api/v1/invitations/check"]
      page.happyDOM.setURL(address)
    }
  })

  it("opens email recovery before any session, even when already signed in", async () => {
    const page = window as typeof window & { happyDOM: { setURL: (url: string) => void } }
    const address = window.location.href
    page.happyDOM.setURL("http://localhost:8000/forgot-password")
    try {
      RESPONSES["/api/v1/setup"] = { administrator_configured: true, password_reset_available: true }
      await renderApp(testI18n())
      expect(container.querySelector("h1")?.textContent).toBe("Forgot your password?")
      expect(vi.mocked(fetch).mock.calls.some(([url]) => url === "/api/v1/session")).toBe(false)
      expect(container.querySelector("input[type=email]")).not.toBeNull()
    } finally {
      RESPONSES["/api/v1/setup"] = { administrator_configured: true }
      page.happyDOM.setURL(address)
    }
  })

  it("opens a password reset link before any session", async () => {
    const page = window as typeof window & { happyDOM: { setURL: (url: string) => void } }
    const address = window.location.href
    page.happyDOM.setURL("http://localhost:8000/password-reset#reset_synthetic")
    try {
      RESPONSES["/api/v1/password-resets/check"] = { usable: true }
      const { container } = await renderApp(testI18n())
      expect(container.querySelector("h1")?.textContent).toBe("Choose a new password")
    } finally {
      delete RESPONSES["/api/v1/password-resets/check"]
      page.happyDOM.setURL(address)
    }
  })

  it.each([
    ["/settings/connections?oauth=connected&provider=google&account=acct-a", "/settings/connections"],
    // Google's return from before Settings had tabs still opens Connections.
    ["/settings?oauth=connected&provider=google&account=acct-a", "/settings"],
  ])("lands on Connections with the connection outcome when Google returns to %s", async (arrival, settled) => {
    const page = window as typeof window & { happyDOM: { setURL: (url: string) => void } }
    const address = window.location.href
    page.happyDOM.setURL(`http://localhost:8000${arrival}`)
    try {
      const { container } = await renderApp(testI18n())
      expect(container.querySelector(".oauth-feedback h2")?.textContent).toBe("Google account connected")
      expect(container.querySelector("nav.page-tabs [aria-current='page']")?.textContent).toBe("Connections")
      expect(container.querySelector("[aria-labelledby='accounts-title']")).not.toBeNull()
      expect(container.querySelector("#primary-nav [aria-current='page']")?.textContent).toBe("Settings")
      // The address stays at Settings; only the outcome is dropped so a reload does not repeat it.
      expect(`${window.location.pathname}${window.location.search}`).toBe(settled)
      // Dropping the outcome does not move Settings to another tab.
      expect(container.querySelector("nav.page-tabs [aria-current='page']")?.textContent).toBe("Connections")
    } finally {
      page.happyDOM.setURL(address)
    }
  })

  it("opens Settings at Your account, and a tab at its own address without reloading, following back and forward", async () => {
    const page = window as typeof window & { happyDOM: { setURL: (url: string) => void } }
    const address = window.location.href
    page.happyDOM.setURL("http://localhost:8000/settings")
    try {
      const { container } = await renderApp(testI18n())
      expect([...container.querySelectorAll("nav.page-tabs a")].map((tab) => tab.textContent)).toEqual([
        "Your account",
        "Connections",
      ])
      expect(container.querySelector("nav.page-tabs [aria-current='page']")?.textContent).toBe("Your account")
      expect(container.querySelector("[aria-labelledby='appearance-title']")).not.toBeNull()

      const header = container.querySelector("header")
      const tab = [...container.querySelectorAll<HTMLAnchorElement>("nav.page-tabs a")].find(
        (link) => link.textContent === "Connections",
      )!
      const click = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 })
      act(() => {
        tab.dispatchEvent(click)
      })
      await settle()

      expect(click.defaultPrevented).toBe(true)
      expect(window.location.pathname).toBe("/settings/connections")
      expect(container.querySelector("header")).toBe(header)
      expect(container.querySelector("nav.page-tabs [aria-current='page']")?.textContent).toBe("Connections")
      expect(container.querySelector("[aria-labelledby='accounts-title']")).not.toBeNull()
      expect(container.querySelector("[aria-labelledby='appearance-title']")).toBeNull()

      act(() => {
        window.history.replaceState(null, "", "/settings/account")
        window.dispatchEvent(new PopStateEvent("popstate"))
      })
      await settle()
      expect(container.querySelector("nav.page-tabs [aria-current='page']")?.textContent).toBe("Your account")
    } finally {
      page.happyDOM.setURL(address)
    }
  })

  it("returns to the sign-in screen after you delete your own account", async () => {
    const page = window as typeof window & { happyDOM: { setURL: (url: string) => void } }
    const address = window.location.href
    page.happyDOM.setURL("http://localhost:8000/settings/account")
    let signedIn = true
    const user = { id: "user-robin", email: "robin@example.test", role: "user", notify_by_email: true, instant_sync: true, instant_sync_availability: "on", instant_sync_help: null, language: null }
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL, init?: RequestInit) => {
        const path = String(input).split("?")[0] ?? ""
        if (init?.method === "DELETE" && path === "/api/v1/account") {
          signedIn = false
          return Promise.resolve(jsonResponse({ rules: 0, deleted: 0, detached: 0, left: 0 }))
        }
        if (path === "/api/v1/session") {
          return Promise.resolve(
            jsonResponse({ authenticated: signedIn, user: signedIn ? user : null, installation_sends_email: false }),
          )
        }
        if (path === "/api/v1/integration-tokens") return Promise.resolve(jsonResponse([]))
        return Promise.resolve(jsonResponse(RESPONSES[path] ?? {}))
      }),
    )
    try {
      const { container } = await renderApp(testI18n())
      act(() => container.querySelector<HTMLButtonElement>("#own-delete-toggle")!.click())
      const password = container.querySelector<HTMLInputElement>("#own-delete-password")!
      act(() => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(password, "a very long password")
        password.dispatchEvent(new Event("input", { bubbles: true }))
      })
      const confirm = container.querySelector<HTMLButtonElement>("#own-delete-confirmation .confirmation-actions button:last-child")!
      act(() => confirm.click())
      await settle(12)

      expect(container.querySelector("header")).toBeNull()
      expect(container.querySelector(".auth-shell")).not.toBeNull()
    } finally {
      page.happyDOM.setURL(address)
    }
  })

  it("returns to setup after the last person here deletes their own account", async () => {
    const page = window as typeof window & { happyDOM: { setURL: (url: string) => void } }
    const address = window.location.href
    page.happyDOM.setURL("http://localhost:8000/settings/account")
    let remaining = true
    const user = { id: "user-dana", email: "dana@example.test", role: "installation_administrator", notify_by_email: true, instant_sync: true, instant_sync_availability: "on", instant_sync_help: null, language: null }
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL, init?: RequestInit) => {
        const path = String(input).split("?")[0] ?? ""
        if (init?.method === "DELETE" && path === "/api/v1/account") {
          remaining = false
          return Promise.resolve(jsonResponse({ rules: 0, deleted: 0, detached: 0, left: 0 }))
        }
        if (path === "/api/v1/setup") return Promise.resolve(jsonResponse({ administrator_configured: remaining }))
        if (path === "/api/v1/account/deletion") {
          return Promise.resolve(jsonResponse({ needs_another_administrator: false, last_user: true }))
        }
        if (path === "/api/v1/session") {
          return Promise.resolve(
            jsonResponse({ authenticated: remaining, user: remaining ? user : null, installation_sends_email: false }),
          )
        }
        return Promise.resolve(jsonResponse(RESPONSES[path] ?? {}))
      }),
    )
    try {
      const { container } = await renderApp(testI18n())
      act(() => container.querySelector<HTMLButtonElement>("#own-delete-toggle")!.click())
      expect(container.querySelector("#own-delete-confirmation p")?.textContent).toContain("You are the last person here.")
      const password = container.querySelector<HTMLInputElement>("#own-delete-password")!
      act(() => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(password, "a very long password")
        password.dispatchEvent(new Event("input", { bubbles: true }))
      })
      const confirm = container.querySelector<HTMLButtonElement>("#own-delete-confirmation .confirmation-actions button:last-child")!
      act(() => confirm.click())
      await settle(12)

      expect(container.querySelector("header")).toBeNull()
      expect(container.querySelector(".auth-shell h1")?.textContent).toBe("Your calendars, under your control.")
    } finally {
      page.happyDOM.setURL(address)
    }
  })

  it("returns to the sign-in screen after you sign out", async () => {
    const page = window as typeof window & { happyDOM: { setURL: (url: string) => void } }
    const address = window.location.href
    page.happyDOM.setURL("http://localhost:8000/settings")
    const user = { id: "user-robin", email: "robin@example.test", role: "user", notify_by_email: true, instant_sync: true, instant_sync_availability: "on", instant_sync_help: null, language: null }
    const signedIn = { authenticated: true, user, installation_sends_email: false }
    const signedOut = { authenticated: false, user: null, installation_sends_email: false }
    let session: object = signedIn
    const refused = { ok: false, status: 401, json: () => Promise.resolve({}) } as Response
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL, init?: RequestInit) => {
        const path = String(input).split("?")[0] ?? ""
        if (path === "/api/v1/session") {
          if (init?.method === "DELETE") session = signedOut
          return Promise.resolve(jsonResponse(session))
        }
        if (session === signedOut && path !== "/api/v1/setup") return Promise.resolve(refused)
        return Promise.resolve(jsonResponse(path === "/api/v1/integration-tokens" ? [] : (RESPONSES[path] ?? {})))
      }),
    )
    try {
      const { container } = await renderApp(testI18n())
      act(() => container.querySelector<HTMLButtonElement>("header button[aria-label='Sign out']")!.click())
      await settle(12)

      expect(container.querySelector("header")).toBeNull()
      expect(container.querySelector(".auth-shell input[type=email]")).not.toBeNull()
    } finally {
      page.happyDOM.setURL(address)
    }
  })

  it("drops the previous User's records and revealed token when another User signs in", async () => {
    const page = window as typeof window & { happyDOM: { setURL: (url: string) => void } }
    const address = window.location.href
    page.happyDOM.setURL("http://localhost:8000/settings/connections")
    const people = {
      a: { id: "user-a", email: "alex@example.test", role: "user", notify_by_email: true, instant_sync: true, instant_sync_availability: "on", instant_sync_help: null, language: null },
      b: { id: "user-b", email: "blake@example.test", role: "user", notify_by_email: true, instant_sync: true, instant_sync_availability: "on", instant_sync_help: null, language: null },
    }
    const accountOf = (who: "a" | "b") => ({
      id: `acct-${who}`,
      provider: "google",
      display_name: who === "a" ? "Alex Calendar" : "Blake Calendar",
      email: who === "a" ? "alex.calendar@example.test" : "blake.calendar@example.test",
      avatar_url: null,
      state: "connected",
      rule_count: 0,
      authorized_at: "2026-09-30T10:00:00+00:00",
      authorization_lapsed_at: null,
    })
    const token = { id: "token-alex", name: "Alex agent", scopes: ["status:read"], created_at: "2026-10-01T09:00:00Z", last_used_at: null, revoked_at: null }
    const answers: Record<"a" | "b", Record<string, unknown>> = {
      a: { "/api/v1/accounts": [accountOf("a")], "/api/v1/integration-tokens": [token] },
      b: { "/api/v1/integration-tokens": [] },
    }
    let current: "a" | "b" = "a"
    // Blake's accounts answer only when asked to, so nothing cached may stand in for them.
    let answerBlake: (response: Response) => void = () => undefined
    const blakeAccounts = new Promise<Response>((resolve) => {
      answerBlake = resolve
    })
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL, init?: RequestInit) => {
        const path = String(input).split("?")[0] ?? ""
        if (init?.method === "POST") return Promise.resolve(jsonResponse({ ...token, token: "cgs_alex-secret-shown-once" }))
        if (path === "/api/v1/session") {
          return Promise.resolve(jsonResponse({ authenticated: true, user: people[current], installation_sends_email: false }))
        }
        if (current === "b" && path === "/api/v1/accounts") return blakeAccounts
        return Promise.resolve(jsonResponse(answers[current][path] ?? RESPONSES[path] ?? {}))
      }),
    )
    try {
      const { container, queryClient } = await renderApp(testI18n())
      act(() => container.querySelector<HTMLButtonElement>("[aria-labelledby='integrations-title'] .group-summary")!.click())
      const name = container.querySelector<HTMLInputElement>("#integration-name")!
      act(() => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(name, "Alex agent")
        name.dispatchEvent(new Event("input", { bubbles: true }))
      })
      act(() => {
        name.closest("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))
      })
      await settle()
      expect(container.textContent).toContain("alex.calendar@example.test")
      expect(container.querySelector<HTMLInputElement>(".token-field input")?.value).toBe("cgs_alex-secret-shown-once")

      const alexShell = container.querySelector(".app-shell")

      // Another tab of this browser signs in as someone else; this tab learns it from the session.
      current = "b"
      await act(async () => {
        await queryClient.refetchQueries({ queryKey: ["session"] })
      })
      await settle(12)

      expect(container.textContent).not.toContain("alex.calendar@example.test")
      expect(container.querySelector(".token-reveal")).toBeNull()
      expect(container.innerHTML).not.toContain("cgs_alex-secret-shown-once")
      expect(container.textContent).not.toContain("Alex agent")
      // Nothing held for Alex survives: the signed-in app starts over for Blake.
      expect(container.querySelector(".app-shell")).not.toBe(alexShell)

      act(() => answerBlake(jsonResponse([accountOf("b")])))
      await settle()
      expect(container.textContent).toContain("blake.calendar@example.test")
      expect(container.innerHTML).not.toContain("cgs_alex-secret-shown-once")
    } finally {
      page.happyDOM.setURL(address)
    }
  })

  it("titles the page in the active language", async () => {
    await renderApp(testI18n())
    expect(document.title).toBe("Overview – Calendar Ghost")
  })
})

describe("People", () => {
  const administrator = {
    id: "user-dana",
    email: "dana@example.test",
    role: "installation_administrator",
    notify_by_email: true,
    instant_sync: true,
    instant_sync_availability: "on",
    instant_sync_help: null,
    language: null,
  }
  const page = window as typeof window & { happyDOM: { setURL: (url: string) => void } }
  let address: string
  let requested: string[]

  beforeEach(() => {
    address = window.location.href
  })

  afterEach(() => {
    page.happyDOM.setURL(address)
  })

  function serveAs(role: string, policy: "only_me" | "invitation_only", hints: unknown[] = []) {
    requested = []
    const answers: Record<string, unknown> = {
      ...RESPONSES,
      "/api/v1/session": { authenticated: true, installation_sends_email: false, user: { ...administrator, role } },
      "/api/v1/registration": { policy, only_me_available: policy === "only_me" },
      "/api/v1/users": {
        users: [
          {
            ...administrator,
            state: "active",
            created_at: "2026-10-01T09:00:00Z",
            last_sign_in_at: null,
            verdict: "setup",
            problems: 0,
            last_synced_at: null,
            resources: NOTHING_SET_UP.resources,
            plan: null,
          },
        ],
        total: 1,
        page: 1,
        page_size: 50,
      },
      "/api/v1/installation/health": {
        status: "setup",
        needs_attention: false,
        incidents: [],
        users: { setup: 1 },
        disabled_users: 0,
        checked_at: "2026-10-01T09:00:00Z",
        hints,
      },
      [`/api/v1/users/${administrator.id}/overview`]: { ...NOTHING_SET_UP, user: { ...NOTHING_SET_UP.user, id: administrator.id } },
      "/api/v1/invitations": [],
      // Plans off, and none yet, as a new installation has them.
      "/api/v1/plans": {
        enabled: false,
        default_plan: null,
        sync_intervals: ["instant", "5_minutes"],
        followers: 1,
        plans: [],
      },
    }
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL) => {
        const path = String(input).split("?")[0] ?? ""
        requested.push(path)
        return Promise.resolve(jsonResponse(answers[path] ?? {}))
      }),
    )
  }

  function navLabels(): string[] {
    return [...document.querySelectorAll("#primary-nav a")].map((link) => link.textContent)
  }

  it("is offered to an administrator while people can join, and opens at its own address", async () => {
    page.happyDOM.setURL("http://localhost:8000/overview")
    serveAs("installation_administrator", "invitation_only")
    const { container } = await renderApp(testI18n())
    expect(navLabels()).toEqual(["Overview", "Rules", "Activity", "People", "Settings"])

    const link = [...container.querySelectorAll<HTMLAnchorElement>("#primary-nav a")].find((item) => item.textContent === "People")!
    expect(link.getAttribute("href")).toBe("/people")
    act(() => {
      link.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 }))
    })
    await settle()
    expect(window.location.pathname).toBe("/people")
    expect(container.querySelector("main h1")?.textContent).toBe("People")
    expect(container.querySelector("#primary-nav [aria-current='page']")?.textContent).toBe("People")
    expect(document.title).toBe("People – Calendar Ghost")
    expect(requested).toContain("/api/v1/users")
  })

  it("flags People when something only the administrator can fix needs them", async () => {
    page.happyDOM.setURL("http://localhost:8000/overview")
    serveAs("installation_administrator", "invitation_only", [
      { kind: "shared_cause", cause: "api_disabled", users: 1, anchor: "the-google-calendar-api-is-turned-off" },
    ])
    const { container } = await renderApp(testI18n())

    const link = [...container.querySelectorAll<HTMLAnchorElement>("#primary-nav a")].find((item) =>
      item.textContent.startsWith("People"),
    )!
    expect(link.querySelector(".nav-flag")).not.toBeNull()
    expect(link.textContent).toBe("People (needs you)")
  })

  it("does not flag People for what people fix themselves", async () => {
    page.happyDOM.setURL("http://localhost:8000/overview")
    serveAs("installation_administrator", "invitation_only")
    const { container } = await renderApp(testI18n())

    expect(container.querySelector("#primary-nav .nav-flag")).toBeNull()
  })

  it("opens a person's page at its own address, and returns to People", async () => {
    page.happyDOM.setURL(`http://localhost:8000/people/${administrator.id}`)
    serveAs("installation_administrator", "invitation_only")
    const { container } = await renderApp(testI18n())
    expect(container.querySelector("main h1")?.textContent).toBe(`${administrator.email}You`)
    expect(container.querySelector("#primary-nav [aria-current='page']")?.textContent).toBe("People")
    expect(requested).toContain(`/api/v1/users/${administrator.id}/overview`)

    act(() => {
      container
        .querySelector<HTMLAnchorElement>("a.person-back")!
        .dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 }))
    })
    await settle()
    expect(window.location.pathname).toBe("/people")
    expect(container.querySelector("main h1")?.textContent).toBe("People")
  })

  it("returns from a person to the same filtered list and their row (review on PR 68)", async () => {
    page.happyDOM.setURL("http://localhost:8000/people?state=active&sort=email")
    serveAs("installation_administrator", "invitation_only")
    const { container } = await renderApp(testI18n())
    const click = (element: Element) =>
      act(() => {
        element.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 }))
      })
    click(container.querySelector("a.person-email")!)
    await settle()
    expect(window.location.pathname).toBe(`/people/${administrator.id}`)
    expect(container.querySelector("a.person-back")?.getAttribute("href")).toBe("/people?state=active&sort=email")

    click(container.querySelector("a.person-back")!)
    await settle()
    expect(`${window.location.pathname}${window.location.search}`).toBe("/people?state=active&sort=email")
    expect(document.activeElement?.getAttribute("href")).toBe(`/people/${administrator.id}`)
  })

  it("opens Plans at its own address, as a tab of People", async () => {
    page.happyDOM.setURL("http://localhost:8000/people/plans")
    serveAs("installation_administrator", "invitation_only")
    const { container } = await renderApp(testI18n())
    expect(window.location.pathname).toBe("/people/plans")
    expect(container.querySelector("main h1")?.textContent).toBe("People")
    expect(container.querySelector("#primary-nav [aria-current='page']")?.textContent).toBe("People")
    expect(container.querySelector("nav.page-tabs [aria-current='page']")?.textContent).toBe("Plans")
    expect(container.querySelector("#plans-title")?.textContent).toBe("Plans")
    expect(document.title).toBe("Plans – People – Calendar Ghost")
    expect(requested).toContain("/api/v1/plans")
    expect(requested).not.toContain("/api/v1/users/plans/overview")
  })

  it("opens New plan's panel at its own address, and Back closes it", async () => {
    page.happyDOM.setURL("http://localhost:8000/people/plans/new")
    serveAs("installation_administrator", "invitation_only")
    const { container } = await renderApp(testI18n())
    expect(window.location.pathname).toBe("/people/plans/new")
    expect(container.querySelector("nav.page-tabs [aria-current='page']")?.textContent).toBe("Plans")
    expect(container.querySelector("#plan-panel-title")?.textContent).toBe("New plan")

    act(() => {
      window.history.replaceState(null, "", "/people/plans")
      window.dispatchEvent(new PopStateEvent("popstate"))
    })
    await settle()
    expect(container.querySelector("#plan-panel")).toBeNull()
    expect(container.querySelector("#plans-empty")).not.toBeNull()
  })

  it("opens a new plan's People tab from its toast after People's other tab replaced Plans, with focus on the panel's title", async () => {
    page.happyDOM.setURL("http://localhost:8000/people/plans/new")
    serveAs("installation_administrator", "invitation_only")
    const team = {
      key: "team",
      name: "Team",
      limits: { rules: null, connected_accounts: null, integration_tokens: null, sync_interval: "instant" },
      is_default: false,
      people: 0,
      limited_people: 0,
      over_people: 0,
      use: { rules: [], connected_accounts: [], integration_tokens: [] },
    }
    const served = vi.mocked(fetch)
    const answer = served.getMockImplementation()!
    let added = false
    served.mockImplementation((input, init) => {
      // The app calls fetch with a path.
      const path = typeof input === "string" ? input.split("?")[0] : ""
      if (path === "/api/v1/plans" && init?.method === "POST") {
        added = true
        return Promise.resolve(jsonResponse(team))
      }
      if (path === "/api/v1/plans" && added) {
        return Promise.resolve(
          jsonResponse({ enabled: false, default_plan: null, sync_intervals: ["instant", "5_minutes"], followers: 1, plans: [team] }),
        )
      }
      return answer(input, init)
    })
    const { container } = await renderApp(testI18n())
    const name = container.querySelector<HTMLInputElement>("#plan-new-name")!
    act(() => {
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set?.call(name, "Team")
      name.dispatchEvent(new Event("input", { bubbles: true }))
    })
    await act(async () => {
      name.closest("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    await settle()
    expect(window.location.pathname).toBe("/people/plans")
    expect(container.querySelector("#plan-panel")).toBeNull()

    const everyone = [...container.querySelectorAll<HTMLAnchorElement>("nav.page-tabs a")].find((tab) => tab.textContent === "Everyone")!
    act(() => {
      everyone.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 }))
    })
    await settle()
    expect(container.querySelector("#plans-title")).toBeNull()

    const assign = [...container.querySelectorAll<HTMLButtonElement>(".toast-viewport button")].find(
      (button) => button.textContent === "Assign people",
    )!
    act(() => assign.focus())
    act(() => assign.click())
    await settle()
    expect(window.location.pathname).toBe("/people/plans/team/people")
    expect(container.querySelector("nav.page-tabs [aria-current='page']")?.textContent).toBe("Plans")
    expect(container.querySelector("#plan-panel-title")?.textContent).toBe("Team")
    expect(document.activeElement).toBe(container.querySelector("#plan-panel-title"))
  })

  it("asks before Back or another page drops a new plan's changes, and goes there once they are discarded", async () => {
    page.happyDOM.setURL("http://localhost:8000/people/plans/new")
    serveAs("installation_administrator", "invitation_only")
    const { container } = await renderApp(testI18n())
    const name = container.querySelector<HTMLInputElement>("#plan-new-name")!
    act(() => {
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set?.call(name, "Team")
      name.dispatchEvent(new Event("input", { bubbles: true }))
    })
    await settle()
    const question = () => container.querySelector(".plan-panel-question")
    const choice = (label: string) =>
      [...container.querySelectorAll<HTMLButtonElement>(".plan-panel-question button")].find((button) => button.textContent === label)!

    // Back: the browser has left, so the page returns to the plan's address and asks.
    act(() => {
      window.history.replaceState(null, "", "/people/plans")
      window.dispatchEvent(new PopStateEvent("popstate"))
    })
    await settle()
    expect(window.location.pathname).toBe("/people/plans/new")
    expect(container.querySelector<HTMLInputElement>("#plan-new-name")?.value).toBe("Team")
    expect(question()?.querySelector("p")?.textContent).toBe("Discard 1 change?")
    act(() => choice("Keep editing").click())

    // A link to another page asks the same way.
    const overview = [...container.querySelectorAll<HTMLAnchorElement>("#primary-nav a")].find((link) => link.textContent === "Overview")!
    act(() => {
      overview.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 }))
    })
    await settle()
    expect(window.location.pathname).toBe("/people/plans/new")
    expect(question()).not.toBeNull()
    act(() => choice("Keep editing").click())

    // Discard goes where Back went.
    act(() => {
      window.history.replaceState(null, "", "/people/plans")
      window.dispatchEvent(new PopStateEvent("popstate"))
    })
    await settle()
    const back = vi.spyOn(window.history, "back").mockImplementation(() => {
      window.history.replaceState(null, "", "/people/plans")
      window.dispatchEvent(new PopStateEvent("popstate"))
    })
    act(() => choice("Discard").click())
    await settle()
    expect(back).toHaveBeenCalledTimes(1)
    expect(window.location.pathname).toBe("/people/plans")
    expect(container.querySelector("#plan-panel")).toBeNull()
    expect(container.querySelector("#plans-empty")).not.toBeNull()
  })

  it("keeps People reachable after an Invitation admits a new User under Only Me", async () => {
    page.happyDOM.setURL("http://localhost:8000/people")
    serveAs("installation_administrator", "only_me")
    const served = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation((input, init) => input === "/api/v1/registration" ? Promise.resolve(jsonResponse({ policy: "only_me", only_me_available: false })) : served(input, init))
    await renderApp(testI18n())
    expect(navLabels()).toContain("People")
    expect(window.location.pathname).toBe("/people")
  })

  it.each([false, true])("keeps Only Me Invitation controls reachable only with live Invitations: %s", async live => {
    page.happyDOM.setURL("http://localhost:8000/people/invitations")
    serveAs("installation_administrator", "only_me")
    const served = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation((input, init) => input === "/api/v1/invitations" ? Promise.resolve(jsonResponse(live ? [{ id: "live-invitation", created_at: "2026-10-01T00:00:00Z", expires_at: "2099-01-01T00:00:00Z" }] : [])) : served(input, init))
    const { container } = await renderApp(testI18n())
    expect(navLabels().includes("People")).toBe(live)
    expect(window.location.pathname).toBe(live ? "/people/invitations" : "/overview")
    if (live) {
      expect([...container.querySelectorAll("button")].some(button => button.textContent === "Revoke")).toBe(true)
      expect(container.textContent).toContain("Change policy")
    }
  })

  it.each([
    ["someone who is not an administrator", "/people", "user", "invitation_only"],
    ["an administrator under Only me", "/people", "installation_administrator", "only_me"],
    ["someone who is not an administrator", "/people/plans", "user", "invitation_only"],
    ["an administrator under Only me", "/people/plans", "installation_administrator", "only_me"],
  ] as const)("is hidden from %s, and %s falls back to Overview", async (_who, path, role, policy) => {
    page.happyDOM.setURL(`http://localhost:8000${path}`)
    serveAs(role, policy)
    const { container } = await renderApp(testI18n())
    expect(navLabels()).toEqual(["Overview", "Rules", "Activity", "Settings"])
    expect(window.location.pathname).toBe("/overview")
    expect(container.querySelector("#primary-nav [aria-current='page']")?.textContent).toBe("Overview")
    expect(requested).not.toContain("/api/v1/users")
    expect(requested).not.toContain("/api/v1/plans")
  })
})
