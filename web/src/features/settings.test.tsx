/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { dateWords, pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import {
  type CalendarProvider,
  api,
  type ConnectedAccount,
  type IntegrationToken,
  type IssuedIntegrationToken,
  type OwnPlan,
} from "@/lib/api"
import { integrationExamples } from "@/lib/integrations"
import type { OpenSettingsTab, SettingsTab } from "@/lib/navigation"

import { IntegrationsSection, SettingsPage } from "./settings"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const REDIRECT_URI = "http://localhost:18000/api/v1/oauth/google/callback"

const connected: ConnectedAccount = {
  id: "acct-a",
  provider: "google",
  display_name: "Dana Calendar",
  email: "dana@example.test",
  avatar_url: null,
  state: "connected",
  rule_count: 2,
  authorized_at: "2026-09-30T10:00:00+00:00",
  authorization_lapsed_at: null,
}
const disconnected: ConnectedAccount = {
  id: "acct-b",
  provider: "google",
  display_name: "Robin Archive",
  email: "robin@example.test",
  avatar_url: null,
  state: "disconnected",
  rule_count: 1,
  authorized_at: null,
  authorization_lapsed_at: null,
}

type StorageUsage = Awaited<ReturnType<typeof api.storage>>

const usage: StorageUsage = {
  database: {
    bytes: 48.2 * 1024 * 1024,
    reclaimable_bytes: 1.2 * 1024 * 1024,
    activity_entries: 61204,
    oldest_activity_at: "2026-06-12T09:00:00+00:00",
  },
  logs: { bytes: 7.9 * 1024 * 1024, files: 2, oldest_at: "2026-09-12T08:00:00+00:00", newest_at: "2026-10-01T18:04:12+00:00" },
  activity_ages: [30, 90, 180, 365],
}

const sourceOnlyAccess: Awaited<ReturnType<typeof api.verifyAccountAccess>> = {
  calendar_api: true,
  calendar_list_access: true,
  event_access: true,
  calendars_visible: 3,
  writable_calendars: 0,
  rules_resumed: 0,
}

const kuma: IntegrationToken = {
  id: "token-kuma",
  name: "Uptime Kuma",
  scopes: ["status:read"],
  created_at: "2026-10-01T09:00:00Z",
  last_used_at: null,
  revoked_at: null,
}
const homepage: IntegrationToken = { ...kuma, id: "token-homepage", name: "Homepage" }
const issued: IssuedIntegrationToken = {
  ...kuma,
  id: "token-agent",
  name: "Claude Code",
  token: "cgs_synthetic-token-shown-once",
}

/** Plans are off: Your plan stays hidden and nothing is limited. */
const plansOff: OwnPlan = {
  basis: "plans_off",
  plan: null,
  limits: null,
  rules_counted: 2,
  connected_accounts: 2,
  integration_tokens: 2,
  instant: true,
  poll_every_minutes: 5,
  may_connect_account: true,
  may_issue_token: true,
  over_rule_limit: false,
}

/** Someone on their own Family plan, with room left everywhere. */
const familyPlan: OwnPlan = {
  basis: "plan",
  plan: { key: "family", name: "Family", on_default: false },
  limits: { rules: 5, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" },
  rules_counted: 3,
  connected_accounts: 2,
  integration_tokens: 0,
  instant: true,
  poll_every_minutes: 5,
  may_connect_account: true,
  may_issue_token: true,
  over_rule_limit: false,
}

/** Someone at every limit of their plan, with more rules counting than it allows. */
const atEveryLimit: OwnPlan = {
  basis: "plan",
  plan: { key: "free", name: "Free", on_default: true },
  limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
  rules_counted: 2,
  connected_accounts: 2,
  integration_tokens: 0,
  instant: false,
  poll_every_minutes: 5,
  may_connect_account: false,
  may_issue_token: false,
  over_rule_limit: true,
}

/** The own-plan answer when Plans cannot be read. */
const UNREADABLE_PLAN = { detail: "database is locked", code: null, params: {} }

// A few seconds before "now", so `format.relative` resolves to the catalog's "just now" rather
// than Intl wording such as "3 days ago", which bypasses the pseudo locale.
const justNow = new Date(Date.now() - 10_000).toISOString()
const PUBLIC_ORIGIN = "http://ghost.example.com"
/** Integration Tokens in every state the section shows: never used, used, and revoked. */
const pseudoTokens: IntegrationToken[] = [
  { ...kuma, created_at: justNow },
  { ...homepage, created_at: justNow, last_used_at: justNow },
  { ...kuma, id: "token-old", name: "Old monitor", created_at: justNow, revoked_at: justNow },
]

const ADMIN_EMAIL = "admin@example.test"
const adminSession = {
  authenticated: true,
  installation_sends_email: false,
  user: { id: "user-admin", email: ADMIN_EMAIL, role: "installation_administrator", notify_by_email: true, instant_sync: true, instant_sync_availability: "on", instant_sync_help: null, language: null },
}

/** Account names, emails, avatar initials, and the Google return address the fixtures introduce. */
const FIXTURE_TEXT = [
  "Dana Calendar",
  "dana@example.test",
  "Robin Archive",
  "robin@example.test",
  "DC",
  "RA",
  ADMIN_EMAIL,
  REDIRECT_URI,
  "http://localhost:18000",
  ...dateWords(),
  // Integration Token names and the issued token are administrator data and a server secret.
  ...pseudoTokens.map((token) => token.name),
  issued.name,
  issued.token,
  // Each example's code block is configuration for another tool, shown as is, never translated.
  ...integrationExamples(testI18n(), PUBLIC_ORIGIN, true).map((example) => example.code),
]

type Scenario = {
  tab?: SettingsTab
  configured?: boolean
  redirectUri?: string | null
  providers?: CalendarProvider[]
  accounts?: ConnectedAccount[]
  storage?: StorageUsage
  clearable?: Response
  cleared?: Response
  tokens?: IntegrationToken[]
  /** GET /api/v1/account/plan; Plans are off unless a test says otherwise. */
  ownPlan?: Response
  /** GET /api/v1/registration; Only Me unless a test says otherwise. */
  registration?: Response
}

/** Google as GET /api/v1/providers describes it once configured. */
function googleProvider(redirectUri: string | null): CalendarProvider {
  return {
    kind: "google",
    display_name: "Google",
    connect_url: "/api/v1/oauth/google/start",
    redirect_uri: redirectUri ?? REDIRECT_URI,
    cause_anchors: {},
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

/** What the Plans and Registration routes answer: Plans off and Only Me unless a test says otherwise. */
function planRoutes({
  ownPlan = jsonResponse(plansOff),
  registration = jsonResponse({ policy: "only_me", only_me_available: true }),
}: Scenario): Record<string, Response> {
  return { "/api/v1/registration": registration, "/api/v1/account/plan": ownPlan, "/api/v1/identity-email": jsonResponse({ configured: false, unavailable_reason: "smtp_missing", test_state: "idle", tested_at: null }) }
}

function mockFetch({
  providers,
  configured = true,
  redirectUri = REDIRECT_URI,
  accounts = [connected, disconnected],
  storage = usage,
  clearable,
  cleared,
  tokens = [kuma, homepage],
  ...rest
}: Scenario) {
  const responses: Record<string, Response> = {
    "/api/v1/account/sign-in-methods": jsonResponse({ has_password: true, identities: [] }),
    "/api/v1/sign-in/providers": jsonResponse({ providers: [] }),
    "/api/v1/settings/sign-in-providers": jsonResponse([]),
    "/api/v1/providers": jsonResponse(providers ?? (configured ? [googleProvider(redirectUri)] : [])),
    "/api/v1/accounts": jsonResponse(accounts),
    "/api/v1/storage": jsonResponse(storage),
    "/api/v1/storage/activity": clearable ?? jsonResponse({ older_than_days: 90, entries: 41880 }),
    "/api/v1/storage/activity/clear": cleared ?? jsonResponse({ removed: 41880, database: usage.database }),
    "/api/v1/integration-tokens": jsonResponse(tokens),
    "/api/v1/session": jsonResponse(adminSession),
    ...planRoutes(rest),
  }
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL) => {
      const path = String(input).split("?")[0] ?? ""
      const verify = /^\/api\/v1\/accounts\/.+\/verify$/.test(path)
      return Promise.resolve(responses[path] ?? jsonResponse(verify ? sourceOnlyAccess : {}))
    }),
  )
}

let container: HTMLDivElement
let root: Root | null = null
let clipboard: PropertyDescriptor | undefined
let address: string
let openTab: ReturnType<typeof vi.fn<OpenSettingsTab>>

function page() {
  return window as typeof window & { happyDOM: { setURL: (url: string) => void } }
}

beforeEach(() => {
  container = document.createElement("div")
  document.body.append(container)
  clipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard")
  address = window.location.href
})

afterEach(() => {
  if (root) {
    act(() => root?.unmount())
    root = null
  }
  container.remove()
  localStorage.clear()
  if (clipboard) Object.defineProperty(navigator, "clipboard", clipboard)
  else Reflect.deleteProperty(navigator, "clipboard")
  page().happyDOM.setURL(address)
  window.history.replaceState(null, "", "/")
  vi.restoreAllMocks()
})

async function settle(times = 6) {
  for (let i = 0; i < times; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

async function renderSettings(i18n: I18n, scenario: Scenario = {}) {
  mockFetch(scenario)
  openTab = vi.fn<OpenSettingsTab>()
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <SettingsPage tab={scenario.tab ?? "connections"} onOpenTab={openTab} onOpenPeople={() => undefined} />
          </QueryClientProvider>
        </ThemeProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
  return container
}

function button(name: string): HTMLButtonElement {
  const found = [...container.querySelectorAll("button")].find((candidate) => candidate.textContent.includes(name))
  if (!found) throw new Error(`no button "${name}"`)
  return found
}

async function click(target: HTMLElement) {
  act(() => target.click())
  await settle()
}

/** Opens the Connect menu and returns its providers' links. */
async function connectMenuItems(): Promise<HTMLAnchorElement[]> {
  await click(button("Connect an account"))
  return [...container.querySelectorAll<HTMLAnchorElement>("[role='menu'] a[role='menuitem']")]
}

describe("SettingsPage", () => {
  it("has no untranslated text with a connected and a disconnected account", async () => {
    // A public plain-HTTP address, so the Integrations transport note shows too.
    page().happyDOM.setURL(`${PUBLIC_ORIGIN}/settings`)
    vi.spyOn(api, "issueIntegrationToken").mockResolvedValue(issued)
    await renderSettings(pseudoI18n(), { tokens: pseudoTokens })
    expect(container.querySelector(".account-list")).not.toBeNull()
    expect(container.querySelector("details.inline-help")).not.toBeNull()

    // Integrations, opened, with a token just issued and a revoke waiting for confirmation.
    await click(container.querySelector<HTMLButtonElement>("[aria-labelledby='integrations-title'] .group-summary")!)
    const input = container.querySelector<HTMLInputElement>("#integration-name")!
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, issued.name)
      input.dispatchEvent(new Event("input", { bubbles: true }))
    })
    act(() => {
      input.closest("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))
    })
    await settle()
    await click(container.querySelector<HTMLButtonElement>("[aria-controls='revoke-token-homepage']")!)
    expect(container.querySelector(".token-reveal")).not.toBeNull()
    expect(container.querySelector("#revoke-token-homepage")).not.toBeNull()
    expect(container.querySelector(".revoked-tokens")).not.toBeNull()
    expect(container.querySelector(".integration-examples")).not.toBeNull()
    expect(untranslatedText(container, FIXTURE_TEXT)).toEqual([])
  })

  it.each(["account", "administration"] as const)("has no untranslated text on the %s tab", async (tab) => {
    await renderSettings(pseudoI18n(), { tab })
    expect(container.querySelector("section")).not.toBeNull()
    expect(untranslatedText(container, FIXTURE_TEXT)).toEqual([])
  })

  it("offers one Connect action that chooses among the providers the installation configured", async () => {
    // A provider this version has no words for is named by what the server calls it.
    const example: CalendarProvider = {
      ...googleProvider(REDIRECT_URI),
      kind: "example",
      display_name: "Example",
      connect_url: "/api/v1/oauth/example/start",
    }
    await renderSettings(testI18n(), { providers: [googleProvider(REDIRECT_URI), example] })

    // Accounts exist, so Connect is not the next step: one quiet trigger, never a button per provider.
    const trigger = button("Connect an account")
    expect(trigger.className).toContain("border-border")
    expect(container.querySelectorAll(".section-heading a")).toHaveLength(0)
    const items = await connectMenuItems()
    expect(items.map((link) => [link.querySelector(".overflow-menu-label")?.textContent, link.getAttribute("href")])).toEqual([
      ["Google account", "/api/v1/oauth/google/start"],
      ["Example account", "/api/v1/oauth/example/start"],
    ])
    // Both return to localhost:18000, not this address, so each opens consent in a new tab.
    expect(items.map((link) => link.target)).toEqual(["_blank", "_blank"])
    expect(items.map((link) => link.querySelector(".overflow-menu-description")?.textContent)).toEqual([
      "Sign in with Google, then come back here.",
      "Sign in with Example, then come back here.",
    ])
  })

  it("says in the Connect menu that Microsoft work or school accounts are not yet verified", async () => {
    const microsoft: CalendarProvider = {
      ...googleProvider(REDIRECT_URI),
      kind: "outlook",
      display_name: "Microsoft",
      connect_url: "/api/v1/oauth/microsoft/start",
    }
    await renderSettings(testI18n(), { providers: [googleProvider(REDIRECT_URI), microsoft] })

    const items = await connectMenuItems()
    expect(items.map((link) => link.querySelector(".overflow-menu-description")?.textContent)).toEqual([
      "Sign in with Google, then come back here.",
      "Sign in with Microsoft, then come back here. Work or school accounts are not yet verified.",
    ])
  })

  it("connects the only configured provider directly, without a menu", async () => {
    await renderSettings(testI18n())

    const connect = [...container.querySelectorAll<HTMLAnchorElement>(".section-heading a")]
    expect(connect.map((link) => [link.textContent.trim(), link.getAttribute("href")])).toEqual([
      ["Connect Google account", "/api/v1/oauth/google/start"],
    ])
    expect([...container.querySelectorAll("button")].some((item) => item.textContent.includes("Connect an account"))).toBe(false)
  })

  it("keeps Connect in place but unavailable at the plan's account limit, saying why, and keeps Reauthorize", async () => {
    await renderSettings(testI18n(), { ownPlan: jsonResponse(atEveryLimit) })

    const heading = container.querySelector<HTMLElement>("[aria-labelledby='accounts-title'] .section-heading")!
    const connect = heading.querySelector("button")!
    expect(connect.textContent.trim()).toBe("Connect Google account")
    expect(connect.getAttribute("aria-disabled")).toBe("true")
    // Nothing starts a provider's consent: no link, no menu.
    expect(heading.querySelector("a[href^='/api/v1/oauth']")).toBeNull()
    expect(heading.querySelector("[aria-haspopup='menu']")).toBeNull()
    const reason = document.getElementById(connect.getAttribute("aria-describedby") ?? "")
    expect(reason?.textContent).toBe("Your plan allows 1 calendar account, and disconnected accounts count too. See your plan")
    expect(reason?.querySelector("a")?.getAttribute("href")).toBe("/settings/account#your-plan")
    // Reauthorization is never refused, so the disconnected account keeps its way back.
    expect(container.querySelector("#account-acct-b a")?.getAttribute("href")).toBe("/api/v1/oauth/google/start?account=acct-b")
  })

  it("keeps the empty state's Connect unavailable at the plan's account limit, as disconnected accounts count", async () => {
    await renderSettings(testI18n(), { accounts: [], ownPlan: jsonResponse(atEveryLimit) })

    const connect = container.querySelector<HTMLButtonElement>(".account-empty button")!
    expect(connect.textContent.trim()).toBe("Connect Google account")
    expect(connect.getAttribute("aria-disabled")).toBe("true")
    expect(container.querySelector(".account-empty a[href^='/api/v1/oauth']")).toBeNull()
  })

  it("offers Connect as usual when the plan cannot be read, since the server still checks", async () => {
    await renderSettings(testI18n(), { ownPlan: jsonResponse(UNREADABLE_PLAN, 500) })

    const connect = [...container.querySelectorAll<HTMLAnchorElement>(".section-heading a")]
    expect(connect.map((link) => link.getAttribute("href"))).toEqual(["/api/v1/oauth/google/start"])
  })

  it("opens consent in a new tab when Google returns elsewhere, and offers to finish here at once", async () => {
    await renderSettings(testI18n())
    const connect = container.querySelector<HTMLAnchorElement>(".section-heading a")!
    expect([connect.target, connect.rel]).toEqual(["_blank", "noopener"])
    expect(container.querySelector(".oauth-return")).toBeNull()

    // The new tab is the browser's; this one stays on Settings.
    connect.addEventListener("click", (event) => event.preventDefault())
    await click(connect)

    expect(container.querySelector(".oauth-return h3")?.textContent).toBe("Finish connecting your Google account")
    expect(container.querySelector(".oauth-return label")?.textContent).toBe("Address Google returned to")
  })

  it("keeps consent in this tab when Google returns to this address", async () => {
    page().happyDOM.setURL("http://localhost:18000/settings")
    await renderSettings(testI18n())
    const connect = container.querySelector<HTMLAnchorElement>(".section-heading a")!
    expect(connect.hasAttribute("target")).toBe(false)
  })

  it("puts Connect in the empty state, as the next step, until an account exists", async () => {
    await renderSettings(testI18n(), { accounts: [] })

    expect(container.querySelector(".section-heading a, .section-heading [aria-haspopup]")).toBeNull()
    const connect = container.querySelector<HTMLAnchorElement>(".account-empty a")
    expect(connect?.textContent.trim()).toBe("Connect Google account")
    expect(connect?.className).toContain("bg-primary")
  })

  it("names each account's provider in its row and on its avatar, and reauthorizes it with that provider", async () => {
    const work = {
      ...connected,
      id: "acct-m",
      provider: "outlook",
      display_name: "Dana Work",
      email: "dana@contoso.example",
      authorization_lapsed_at: justNow,
    }
    const microsoft: CalendarProvider = {
      ...googleProvider(REDIRECT_URI),
      kind: "outlook",
      display_name: "Microsoft",
      connect_url: "/api/v1/oauth/microsoft/start",
      redirect_uri: "http://localhost:18000/api/v1/oauth/microsoft/callback",
    }
    await renderSettings(testI18n(), { accounts: [connected, work], providers: [googleProvider(REDIRECT_URI), microsoft] })

    const rows = [...container.querySelectorAll<HTMLLIElement>(".account-item")]
    expect(rows.map((row) => row.querySelector(".account-copy p")?.textContent)).toEqual([
      "Microsoft account · dana@contoso.example",
      "Google account · dana@example.test",
    ])
    expect(rows.map((row) => row.querySelector(".account-mark")?.getAttribute("title"))).toEqual([
      "Microsoft account",
      "Google account",
    ])
    // Each avatar wears its provider's mark, so the list scans by provider at a glance.
    expect(rows.map((row) => row.querySelector(".account-mark .provider-mark")?.getAttribute("data-provider"))).toEqual([
      "outlook",
      "google",
    ])
    // The fix says where it goes: the provider's own consent, not another page here.
    const reauthorize = rows[0]?.querySelector("a")
    expect(reauthorize?.textContent.trim()).toBe("Reauthorize with Microsoft")
    expect(reauthorize?.getAttribute("href")).toBe("/api/v1/oauth/microsoft/start?account=acct-m")
    // The collapsed summary groups addresses by provider, and its avatars wear their marks too.
    expect(container.querySelector(".account-summary-emails")?.textContent).toBe(
      "Google: dana@example.test · Microsoft: dana@contoso.example",
    )
    expect(container.querySelectorAll(".account-stack .provider-mark")).toHaveLength(2)
    // Each provider in the Connect menu wears its mark beside its name.
    const connect = await connectMenuItems()
    expect(connect.map((link) => link.querySelector(".overflow-menu-label")?.textContent)).toEqual([
      "Google account",
      "Microsoft account",
    ])
    expect(connect.map((link) => link.querySelector(".provider-mark")?.getAttribute("data-provider"))).toEqual(["google", "outlook"])
  })

  it("names every provider that returns somewhere else, with a way to finish for each", async () => {
    const microsoft: CalendarProvider = {
      ...googleProvider(REDIRECT_URI),
      kind: "outlook",
      display_name: "Microsoft",
      connect_url: "/api/v1/oauth/microsoft/start",
      redirect_uri: "http://localhost:18000/api/v1/oauth/microsoft/callback",
    }
    await renderSettings(testI18n(), { providers: [googleProvider(REDIRECT_URI), microsoft] })

    const notes = [...container.querySelectorAll<HTMLDetailsElement>("details.account-group-footer")]
    expect(notes.map((note) => note.querySelector("summary")?.textContent)).toEqual([
      "Google and Microsoft return to http://localhost:18000, not to this page's address",
    ])
    // One field finishes either: the address it is given names its provider.
    expect([...notes[0]!.querySelectorAll("label")].map((label) => label.textContent)).toEqual([
      "Address the provider returned to",
    ])
    expect(notes[0]!.querySelector("input")?.placeholder).toBe("")
  })

  it("names where each provider returns when they disagree, in one note, and finishes either from one field", async () => {
    const microsoft: CalendarProvider = {
      ...googleProvider(REDIRECT_URI),
      kind: "outlook",
      display_name: "Microsoft",
      connect_url: "/api/v1/oauth/microsoft/start",
      redirect_uri: "http://localhost:8000/api/v1/oauth/microsoft/callback",
    }
    await renderSettings(testI18n(), { providers: [googleProvider(REDIRECT_URI), microsoft] })

    const notes = [...container.querySelectorAll<HTMLDetailsElement>("details.account-group-footer")]
    expect(notes).toHaveLength(1)
    const note = notes[0]!
    expect(note.querySelector("summary")?.textContent).toBe("Google and Microsoft return to addresses other than this page's")
    expect([...note.querySelectorAll(".oauth-return-origins li")].map((item) => item.textContent)).toEqual([
      "Google: http://localhost:18000",
      "Microsoft: http://localhost:8000",
    ])
    expect(note.querySelectorAll("form")).toHaveLength(1)
    expect(note.textContent).toContain("They now return to different addresses, but an installation usually answers at only one.")
    expect(note.textContent).not.toContain("SSH tunnel")

    const field = note.querySelector("input")!
    const form = note.querySelector("form")!
    const enter = (value: string) => {
      act(() => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(field, value)
        field.dispatchEvent(new Event("input", { bubbles: true }))
      })
    }
    enter("http://localhost:8000/settings?state=s&code=c")
    act(() => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))
    })
    expect(note.querySelector('[role="alert"]')?.textContent).toBe(
      "That is not an address one of these providers returned to. Copy the whole address from the address bar.",
    )

    const assign = vi.spyOn(window.location, "assign").mockImplementation(() => undefined)
    enter("http://localhost:8000/api/v1/oauth/microsoft/callback?state=s&code=c")
    act(() => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))
    })
    expect(assign).toHaveBeenCalledWith(`${window.location.origin}/api/v1/oauth/microsoft/callback?state=s&code=c`)
  })

  it("keeps an account's reauthorization unavailable while its provider is not configured", async () => {
    const lapsed = { ...connected, id: "acct-l", provider: "example", authorization_lapsed_at: justNow }
    await renderSettings(testI18n(), { accounts: [lapsed] })

    const reauthorize = [...container.querySelectorAll<HTMLButtonElement>("button")].find(
      (item) => item.textContent.trim() === "Reauthorize account",
    )
    expect(reauthorize?.disabled).toBe(true)
  })

  it("ignores an unknown connection outcome", async () => {
    window.history.replaceState(null, "", "/settings?oauth=surprise&provider=google")
    await renderSettings(testI18n())
    expect(container.querySelector(".oauth-feedback h2")).toBeNull()
  })

  it("leads with an account Google stopped accepting and offers to reauthorize it", async () => {
    const lapsed = { ...connected, id: "acct-l", email: "lapsed@example.test", authorization_lapsed_at: justNow }
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined)
    window.history.replaceState(null, "", "/settings?account=acct-l")
    await renderSettings(testI18n(), { accounts: [connected, lapsed] })

    const rows = [...container.querySelectorAll<HTMLLIElement>(".account-item")]
    expect(rows.map((row) => row.id)).toEqual(["account-acct-l", "account-acct-a"])
    const [first] = rows
    expect(first?.querySelector(".account-actions > span")?.textContent).toContain("Needs reauthorization")
    // The chip and the stopped rules say it; no third sentence repeats it.
    expect(first?.querySelector(".account-lapse-note")).toBeNull()
    // Google is asked to offer this account first.
    expect(first?.querySelector("a")?.getAttribute("href")).toBe("/api/v1/oauth/google/start?account=acct-l")
    // Arriving from a stopped rule shows that account, and does so only once.
    expect(first?.hasAttribute("data-focused")).toBe(true)
    expect(scrolled).toHaveBeenCalledOnce()
    expect(window.location.search).toBe("")
    expect(container.querySelector(".account-summary-status")?.textContent).toBe("2 accounts, 1 needs reauthorization")
  })

  it("says how many rules restarted when Google returns after reauthorization", async () => {
    window.history.replaceState(null, "", "/settings?oauth=connected&provider=google&account=acct-a&resumed=2")
    await renderSettings(testI18n())
    expect(container.querySelector(".oauth-feedback p")?.textContent).toBe(
      "Access is restored. 2 rules restarted and catch up on changes made while they were stopped.",
    )
  })

  it("says a new account met the plan's limit, and links to Your plan in place of Try again", async () => {
    window.history.replaceState(null, "", "/settings?oauth=account_limit_reached&provider=google&limit=1")
    await renderSettings(testI18n())

    const notice = container.querySelector(".oauth-feedback")!
    expect(notice.getAttribute("role")).toBe("alert")
    expect(notice.querySelector("h2")?.textContent).toBe("Your plan's calendar accounts are all in use")
    expect(notice.querySelector("p")?.textContent).toBe(
      "No account was connected. Your plan allows 1 calendar account, and disconnected accounts count too. Delete one you no longer use, or ask your administrator for a larger plan.",
    )
    const links = [...notice.querySelectorAll("a")].map((link) => [link.textContent, link.getAttribute("href")])
    expect(links).toEqual([["See your plan", "/settings/account#your-plan"]])
    // A reload does not announce the refusal again: every arrival parameter, `limit` too, is gone.
    expect(window.location.search).toBe("")
  })

  it("has no untranslated text when a new account met the plan's limit", async () => {
    window.history.replaceState(null, "", "/settings?oauth=account_limit_reached&provider=google&limit=2")
    await renderSettings(pseudoI18n())
    expect(container.querySelector(".oauth-feedback")).not.toBeNull()
    expect(untranslatedText(container, FIXTURE_TEXT)).toEqual([])
  })

  it("still offers to try again when authorization failed", async () => {
    window.history.replaceState(null, "", "/settings?oauth=authorization_failed&provider=google")
    await renderSettings(testI18n())
    const notice = container.querySelector(".oauth-feedback")!
    expect(notice.getAttribute("role")).toBe("alert")
    expect([...notice.querySelectorAll("a")].map((link) => link.textContent)).toEqual(["Try again"])
  })

  it("keeps the English copy", async () => {
    window.history.replaceState(null, "", "/settings?oauth=connected&provider=google")
    await renderSettings(testI18n())
    expect(container.querySelector(".oauth-feedback h2")?.textContent).toBe("Google account connected")
    const rows = [...container.querySelectorAll(".account-copy span")].map((span) => span.textContent)
    // The account to reauthorize leads the list.
    expect(rows).toEqual(["1 rule stopped until it is reauthorized", "Used by 2 rules"])
    // The visible word stands beside one screen reader phrase, rather than a glued " accounts".
    expect(container.querySelector(".account-summary-toggle [aria-hidden='true']")?.textContent).toBe("Hide")
    expect(container.querySelector(".account-summary-toggle .sr-only")?.textContent).toBe("Hide accounts")
    expect(container.querySelector(".account-summary-emails")?.textContent).toBe("Google: dana@example.test, robin@example.test")

    await click(button("Check access"))
    expect(container.querySelector(".account-access-result p")?.textContent).toBe(
      "Calendar-list and event permissions are available. 3 calendars are visible and 0 can be used as a destination. This account can still be used as a source.",
    )
    await click(button("Delete account"))
    expect(container.querySelector("#delete-acct-b p")?.textContent).toBe(
      "This cannot be undone. The account record and 1 affected Directional Sync Rule, including their mappings, cursors, incidents, and audit activity, will be removed. Existing Managed Projections in their calendars will not be deleted and will no longer be managed.",
    )
    // Disconnecting is a rare, disruptive choice, so it waits in the row's menu.
    expect([...container.querySelectorAll("button")].some((item) => item.textContent.trim() === "Disconnect account")).toBe(
      false,
    )
    await click(container.querySelector<HTMLButtonElement>("#account-acct-a [aria-haspopup='menu']")!)
    const disconnect = [...container.querySelectorAll<HTMLButtonElement>("[role='menuitem']")].find(
      (item) => item.querySelector(".overflow-menu-label")?.textContent === "Disconnect account",
    )!
    await click(disconnect)
    expect(container.querySelector("#disconnect-acct-a p")?.textContent).toBe(
      "Its stored credentials will be removed. 2 affected rules will require reauthorization before they can run.",
    )
  })

  it("warns before a disconnect that the plan may not let its rules start again, while more rules count than it allows", async () => {
    await renderSettings(testI18n(), { ownPlan: jsonResponse(atEveryLimit) })
    await click(container.querySelector<HTMLButtonElement>("#account-acct-a [aria-haspopup='menu']")!)
    const disconnect = [...container.querySelectorAll<HTMLButtonElement>("[role='menuitem']")].find(
      (item) => item.querySelector(".overflow-menu-label")?.textContent === "Disconnect account",
    )!
    await click(disconnect)
    expect(container.querySelector("#disconnect-acct-a p")?.textContent).toBe(
      "Its stored credentials will be removed. 2 affected rules will require reauthorization before they can run. Your plan may not let these rules start again.",
    )
  })

  it("warns before a disconnect that the plan may not let its one rule start again", async () => {
    await renderSettings(testI18n(), { accounts: [{ ...connected, rule_count: 1 }, disconnected], ownPlan: jsonResponse(atEveryLimit) })
    await click(container.querySelector<HTMLButtonElement>("#account-acct-a [aria-haspopup='menu']")!)
    const disconnect = [...container.querySelectorAll<HTMLButtonElement>("[role='menuitem']")].find(
      (item) => item.querySelector(".overflow-menu-label")?.textContent === "Disconnect account",
    )!
    await click(disconnect)
    expect(container.querySelector("#disconnect-acct-a p")?.textContent).toBe(
      "Its stored credentials will be removed. 1 affected rule will require reauthorization before it can run. Your plan may not let this rule start again.",
    )
  })

  const NO_DISCONNECT_NOTE: [string, Scenario][] = [
    ["an account no rule uses", { accounts: [{ ...connected, rule_count: 0 }, disconnected], ownPlan: jsonResponse(atEveryLimit) }],
    ["a plan that cannot be read", { ownPlan: jsonResponse(UNREADABLE_PLAN, 500) }],
  ]

  it.each(NO_DISCONNECT_NOTE)("says nothing about the plan before disconnecting %s", async (_case, scenario) => {
    await renderSettings(testI18n(), scenario)
    await click(container.querySelector<HTMLButtonElement>("#account-acct-a [aria-haspopup='menu']")!)
    const disconnect = [...container.querySelectorAll<HTMLButtonElement>("[role='menuitem']")].find(
      (item) => item.querySelector(".overflow-menu-label")?.textContent === "Disconnect account",
    )!
    await click(disconnect)
    expect(container.querySelector("#disconnect-acct-a p")?.textContent).not.toContain("Your plan")
  })

  it("has no untranslated text at every limit of a plan", async () => {
    // The page's own address, so the Integrations examples match the fixture text.
    page().happyDOM.setURL(`${PUBLIC_ORIGIN}/settings`)
    await renderSettings(pseudoI18n(), { ownPlan: jsonResponse(atEveryLimit) })
    await click(container.querySelector<HTMLButtonElement>("[aria-labelledby='integrations-title'] .group-summary")!)
    await click(container.querySelector<HTMLButtonElement>("#account-acct-a [aria-haspopup='menu']")!)
    // The item's description id ends with its id, "disconnect"; its label is pseudo-translated.
    const disconnect = [...container.querySelectorAll<HTMLButtonElement>("#account-acct-a [role='menuitem']")].find((item) =>
      item.getAttribute("aria-describedby")?.endsWith("-disconnect"),
    )!
    await click(disconnect)

    expect(container.querySelector(".action-hint a")).not.toBeNull()
    expect(container.querySelector("#integration-limit")).not.toBeNull()
    expect(container.querySelector("#disconnect-acct-a")).not.toBeNull()
    expect(untranslatedText(container, FIXTURE_TEXT)).toEqual([])
  })

  it("summarizes storage on Administration", async () => {
    await renderSettings(testI18n(), { tab: "administration" })
    const summaries = [...container.querySelectorAll(".setting-row p")].map((paragraph) => paragraph.textContent)
    expect(summaries).toContain("48.2 MB · 61,204 Activity entries since Jun 12, 2026 · 1.2 MB can be reclaimed")
    expect(summaries).toContain("7.9 MB · Sep 12 – Oct 1, 2026")
  })

  it("explains a failed count with the server's detail", async () => {
    await renderSettings(testI18n(), {
      tab: "administration",
      clearable: jsonResponse({ detail: "older_than_days must be one of 30, 90." }, 422),
    })
    await click(container.querySelector<HTMLButtonElement>("[aria-controls='clear-activity-confirmation']")!)
    expect(container.querySelector("#clear-activity-confirmation p")?.textContent).toBe(
      "The entries to remove could not be counted: older_than_days must be one of 30, 90.",
    )
  })

  it("explains a failed count from the error code, not the server's English", async () => {
    await renderSettings(testI18n(), {
      tab: "administration",
      clearable: jsonResponse({ detail: "older_than_days must be one of 30, 90.", code: "invalid_activity_age", params: {} }, 422),
    })
    await click(container.querySelector<HTMLButtonElement>("[aria-controls='clear-activity-confirmation']")!)
    expect(container.querySelector("#clear-activity-confirmation p")?.textContent).toBe(
      "The entries to remove could not be counted: Choose one of the offered ages for clearing Activity.",
    )
  })

  it("says the old Activity was cleared when its space could not be reclaimed", async () => {
    await renderSettings(testI18n(), {
      tab: "administration",
      cleared: jsonResponse({ detail: "Database is locked.", code: "storage_busy", params: {} }, 409),
    })
    await click(container.querySelector<HTMLButtonElement>("[aria-controls='clear-activity-confirmation']")!)
    await click(container.querySelector<HTMLButtonElement>("#clear-activity-confirmation .confirmation-actions button:last-child")!)
    expect(container.querySelector("#clear-activity-confirmation")).toBeNull()
    expect(container.querySelector("[aria-labelledby='storage-title'] [role='alert']")?.textContent).toBe(
      "Old Activity was cleared, but its space could not be reclaimed while a rule is synchronizing. Try again when it finishes.",
    )
  })
})

describe("Settings tabs", () => {
  function sections(): (string | null)[] {
    return [...container.querySelectorAll(".settings-page > section")].map((item) => item.getAttribute("aria-labelledby"))
  }

  function tabs(): HTMLAnchorElement[] {
    return [...container.querySelectorAll<HTMLAnchorElement>("nav.page-tabs a")]
  }

  it.each([
    ["connections", ["accounts-title", "integrations-title"]],
    ["account", ["own-account-title", "appearance-title"]],
    ["administration", ["registration-title", "identity-email-title", "sign-in-providers-title", "storage-title"]],
  ] as const)("shows the %s tab's sections", async (tab, shown) => {
    await renderSettings(testI18n(), { tab })
    expect(sections()).toEqual(shown)
  })

  it("shows Your plan between the account section and Appearance once a plan limits you", async () => {
    await renderSettings(testI18n(), { tab: "account", ownPlan: jsonResponse(familyPlan) })
    expect(sections()).toEqual(["own-account-title", "your-plan-title", "appearance-title"])
    expect(container.querySelector("#your-plan h3")?.textContent).toBe("Family")
  })

  it("opens Connections from Your plan's sentence about calendar accounts past the limit", async () => {
    await renderSettings(testI18n(), { tab: "account", ownPlan: jsonResponse(atEveryLimit) })
    const link = [...container.querySelectorAll<HTMLAnchorElement>("#your-plan .plan-usage-note a")].find(
      (anchor) => anchor.textContent === "Connections",
    )
    expect(link?.getAttribute("href")).toBe("/settings/connections")
    await click(link!)
    expect(openTab).toHaveBeenCalledWith("connections")
    // The sentence goes with Your account, so focus moves to the tab it opened, not to the page.
    expect(document.activeElement).toBe(tabs().find((tab) => tab.textContent === "Connections"))
  })

  it("keeps the rest of Your account working when Your plan cannot load", async () => {
    await renderSettings(testI18n(), {
      tab: "account",
      ownPlan: jsonResponse({ detail: "database is locked" }, 500),
      registration: jsonResponse({ policy: "invitation_only", only_me_available: false }),
    })
    expect(sections()).toEqual(["own-account-title", "your-plan-title", "appearance-title"])
    expect(container.querySelector("#your-plan [role='alert']")?.textContent).toContain("Your plan could not load.")
    expect(container.querySelector("#own-account-title")?.textContent).toBe("Sign-in, email, and sync")
    expect(container.querySelector("#appearance-title")).not.toBeNull()
  })

  it("links each tab to its own address and marks the one shown", async () => {
    await renderSettings(testI18n(), { tab: "account" })
    expect(container.querySelector("nav.page-tabs")?.getAttribute("aria-label")).toBe("Settings sections")
    expect(tabs().map((tab) => [tab.textContent, tab.getAttribute("href"), tab.getAttribute("aria-current")])).toEqual([
      ["Your account", "/settings/account", "page"],
      ["Connections", "/settings/connections", null],
      ["Administration", "/settings/administration", null],
    ])
  })

  it("opens a tab in place on a plain click", async () => {
    await renderSettings(testI18n())
    const click = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 })
    act(() => {
      tabs()[2]!.dispatchEvent(click)
    })
    expect(click.defaultPrevented).toBe(true)
    expect(openTab).toHaveBeenCalledWith("administration")
  })

  it("shows a connection outcome only on Connections", async () => {
    window.history.replaceState(null, "", "/settings?oauth=connected&provider=google")
    await renderSettings(testI18n(), { tab: "account" })
    expect(container.querySelector(".oauth-feedback")).toBeNull()
  })
})

async function tick() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
}

async function renderSection(administrator = false) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  root = createRoot(container)
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={testI18n()}>
        <QueryClientProvider client={queryClient}>
          <IntegrationsSection administrator={administrator} />
        </QueryClientProvider>
      </StaticI18nProvider>,
    )
  })
  // Wait for the token list to load or fail, however long a busy test run takes.
  for (let attempt = 0; attempt < 50; attempt++) {
    await tick()
    if (container.querySelector(".group-summary, .integration-load-error")) return
  }
  throw new Error("The Integrations section never finished loading")
}

function press(element: Element) {
  act(() => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
  })
}

function labelledButton(label: string, scope: ParentNode = container): HTMLButtonElement {
  const found = Array.from(scope.querySelectorAll("button")).find((item) => item.textContent.trim() === label)
  if (!found) throw new Error(`No button labelled ${label}`)
  return found
}

function rowOf(name: string): HTMLElement {
  const heading = Array.from(container.querySelectorAll(".group-body h3")).find((item) => item.textContent === name)
  if (!heading) throw new Error(`No token named ${name}`)
  return heading.closest<HTMLElement>(".setting-row")!
}

function summary(): HTMLButtonElement {
  return container.querySelector<HTMLButtonElement>(".group-summary")!
}

async function openGroup() {
  press(summary())
  await tick()
}

async function issueToken(name: string) {
  const input = container.querySelector<HTMLInputElement>("#integration-name")!
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, name)
    input.dispatchEvent(new Event("input", { bubbles: true }))
  })
  const form = input.closest<HTMLFormElement>("form")!
  act(() => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))
  })
  await tick()
}

describe("IntegrationsSection", () => {
  beforeEach(() => {
    vi.spyOn(api, "integrationTokens").mockResolvedValue([kuma, homepage])
    vi.spyOn(api, "issueIntegrationToken").mockResolvedValue(issued)
    vi.spyOn(api, "revokeIntegrationToken").mockResolvedValue(undefined)
    // The form reads the own plan for its token limit; Plans are off unless a test says otherwise.
    vi.spyOn(api, "ownPlan").mockResolvedValue(plansOff)
  })

  it("stays collapsed to a summary of the tokens in use", async () => {
    await renderSection()

    expect(summary().textContent).toContain("2 tokens · never used")
    expect(summary().getAttribute("aria-expanded")).toBe("false")
    expect(container.querySelector("#integration-name")).toBeNull()

    await openGroup()
    expect(summary().getAttribute("aria-expanded")).toBe("true")
    expect(rowOf("Uptime Kuma").textContent).toContain("Never used · issued")
  })

  it("shows an issued token once, announces it without reading it, and moves focus to it", async () => {
    await renderSection()
    await openGroup()

    await issueToken("Claude Code")

    expect(api.issueIntegrationToken).toHaveBeenCalledWith("Claude Code", ["status:read"])
    const heading = container.querySelector(".token-reveal h3")
    expect(heading?.textContent).toBe("Copy the token for Claude Code now")
    expect(document.activeElement).toBe(heading)
    expect(container.querySelector<HTMLInputElement>(".token-field input")!.value).toBe(issued.token)
    const status = container.querySelector('[role="status"]')
    expect(status?.textContent).toBe("Token for Claude Code issued. Copy it now; it is shown only once.")
    expect(container.querySelector(".token-reveal")?.getAttribute("role")).toBeNull()
    expect(container.querySelector<HTMLInputElement>("#integration-name")!.value).toBe("")

    act(() => root?.unmount())
    root = null
    await renderSection()
    expect(container.textContent).not.toContain(issued.token)
  })

  it("says what each token may read", async () => {
    vi.mocked(api.integrationTokens).mockResolvedValue([kuma, { ...homepage, scopes: ["status:read", "installation:read"] }])
    await renderSection(true)
    await openGroup()
    expect(rowOf("Uptime Kuma").textContent).toContain("Reads your synchronization status")
    expect(rowOf("Homepage").textContent).toContain("Reads your synchronization status and Installation Health")
  })

  it("lets only an administrator's token also read Installation Health", async () => {
    await renderSection()
    await openGroup()
    expect(container.querySelector("#integration-installation")).toBeNull()
    expect(container.textContent).not.toContain("/api/v1/installation/health")
    act(() => root?.unmount())
    root = null

    await renderSection(true)
    await openGroup()
    expect(container.textContent).toContain("/api/v1/installation/health")
    act(() => container.querySelector<HTMLInputElement>("#integration-installation")!.click())
    await issueToken("Monitor")
    expect(api.issueIntegrationToken).toHaveBeenCalledWith("Monitor", ["status:read", "installation:read"])
    // The next token reads only the administrator's own status unless asked again.
    expect(container.querySelector<HTMLInputElement>("#integration-installation")!.checked).toBe(false)
  })

  it("issues an administrator's token for their own status unless they ask for more", async () => {
    await renderSection(true)
    await openGroup()
    await issueToken("Claude Code")
    expect(api.issueIntegrationToken).toHaveBeenCalledWith("Claude Code", ["status:read"])
  })

  it("keeps the token form in place but unusable when the plan includes no tokens, saying why without at most 0", async () => {
    vi.mocked(api.ownPlan).mockResolvedValue(atEveryLimit)
    await renderSection()
    await openGroup()
    await tick()
    await tick()

    const input = container.querySelector<HTMLInputElement>("#integration-name")!
    const submit = labelledButton("Issue token")
    // Both stay focusable, so keyboard and screen reader users reach the reason.
    expect(input.getAttribute("aria-disabled")).toBe("true")
    expect(input.readOnly).toBe(true)
    expect(input.disabled).toBe(false)
    expect(submit.getAttribute("aria-disabled")).toBe("true")
    expect(submit.disabled).toBe(false)
    const reason = container.querySelector("#integration-limit")
    expect(reason?.textContent).toBe(
      "Your plan does not include integration tokens. To get one, ask your administrator. See your plan",
    )
    expect(reason?.querySelector("a")?.getAttribute("href")).toBe("/settings/account#your-plan")
    expect(input.getAttribute("aria-describedby")).toBe("integration-name-hint integration-limit")
    expect(submit.getAttribute("aria-describedby")).toBe("integration-limit")
    expect(container.textContent).not.toContain("at most")

    // Pressing Issue token keeps focus there and sends nothing; nor does Enter in the field.
    act(() => submit.focus())
    press(submit)
    await tick()
    expect(document.activeElement).toBe(submit)
    await issueToken("Claude Code")
    expect(api.issueIntegrationToken).not.toHaveBeenCalled()
  })

  it("says a plan's tokens are all in use, and how to make room", async () => {
    vi.mocked(api.ownPlan).mockResolvedValue({
      ...atEveryLimit,
      limits: { rules: 1, connected_accounts: 1, integration_tokens: 2, sync_interval: "5_minutes" },
      integration_tokens: 2,
    })
    await renderSection()
    await openGroup()
    await tick()
    await tick()

    expect(labelledButton("Issue token").getAttribute("aria-disabled")).toBe("true")
    expect(container.querySelector("#integration-limit")?.textContent).toBe(
      "Your plan allows 2 integration tokens, and all are in use. Revoke one to issue another. See your plan",
    )
  })

  it("offers Issue token as usual when the plan cannot be read, since the server still checks", async () => {
    vi.mocked(api.ownPlan).mockRejectedValue(new Error("database is locked"))
    await renderSection()
    await openGroup()
    await tick()
    await tick()

    expect(container.querySelector("#integration-limit")).toBeNull()
    expect(container.querySelector("#integration-name")?.getAttribute("aria-disabled")).toBeNull()
    expect(labelledButton("Issue token").getAttribute("aria-disabled")).toBeNull()
    await issueToken("Claude Code")
    expect(api.issueIntegrationToken).toHaveBeenCalledWith("Claude Code", ["status:read"])
  })

  it("offers Issue token as usual while Plans are off", async () => {
    await renderSection()
    await openGroup()
    await tick()

    expect(container.querySelector("#integration-limit")).toBeNull()
    expect(container.querySelector("#integration-name")?.getAttribute("aria-describedby")).toBe("integration-name-hint")
  })

  it("closes the reveal with Done and returns to the name field", async () => {
    await renderSection()
    await openGroup()
    await issueToken("Claude Code")

    press(labelledButton("Done"))

    expect(container.querySelector(".token-reveal")).toBeNull()
    expect(document.activeElement).toBe(container.querySelector("#integration-name"))
  })

  it("asks to copy the token by hand when the clipboard is unavailable", async () => {
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true })
    await renderSection()
    await openGroup()
    await issueToken("Claude Code")

    press(labelledButton("Copy token"))
    await tick()

    expect(container.textContent).toContain("Select the token and copy it.")
    expect(container.querySelector<HTMLInputElement>(".token-field input")!.value).toBe(issued.token)
  })

  it("says the token was copied, then offers to copy it again", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true })
    await renderSection()
    await openGroup()
    await issueToken("Claude Code")
    vi.useFakeTimers({ shouldAdvanceTime: true })

    try {
      press(labelledButton("Copy token"))
      await tick()
      expect(writeText).toHaveBeenCalledWith(issued.token)
      expect(labelledButton("Copied")).toBeTruthy()

      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000)
      })
      expect(labelledButton("Copy token")).toBeTruthy()
    } finally {
      vi.useRealTimers()
    }
  })

  it("confirms a revoke and returns focus to that token's Revoke button on cancel", async () => {
    await renderSection()
    await openGroup()
    const revoke = labelledButton("Revoke", rowOf("Homepage"))

    press(revoke)
    const confirmation = container.querySelector<HTMLElement>("#revoke-token-homepage")!
    expect(confirmation).not.toBeNull()
    expect(confirmation.textContent).toContain("Revoke Homepage?")
    expect(revoke.getAttribute("aria-expanded")).toBe("true")
    // A revoked token stays listed, so the button does not show a trash can.
    expect(labelledButton("Revoke token", confirmation).querySelector("svg")).toBeNull()

    press(labelledButton("Keep token", confirmation))

    expect(container.querySelector("#revoke-token-homepage")).toBeNull()
    expect(document.activeElement).toBe(revoke)
    expect(api.revokeIntegrationToken).not.toHaveBeenCalled()
  })

  it("announces a revoke and keeps focus in the group", async () => {
    await renderSection()
    await openGroup()
    press(labelledButton("Revoke", rowOf("Homepage")))

    press(labelledButton("Revoke token", container.querySelector<HTMLElement>("#revoke-token-homepage")!))
    await tick()

    expect(api.revokeIntegrationToken).toHaveBeenCalledWith("token-homepage")
    expect(container.querySelector('[role="status"]')?.textContent).toBe(
      "Homepage was revoked. Anything that used it has lost access.",
    )
    expect(document.activeElement).toBe(summary())
  })

  it("gathers revoked tokens under one disclosure", async () => {
    vi.mocked(api.integrationTokens).mockResolvedValue([kuma, { ...homepage, revoked_at: "2026-10-02T09:00:00Z" }])
    await renderSection()
    await openGroup()

    expect(container.querySelector(".revoked-tokens summary")?.textContent).toContain("1 revoked token")
    expect(Array.from(container.querySelectorAll(".group-body > .setting-row h3")).map((h) => h.textContent)).toEqual([
      "Uptime Kuma",
    ])
  })

  it("notes plain HTTP only where a token would cross the internet in the clear", async () => {
    page().happyDOM.setURL("http://calendar-ghost.lan:8000/settings")
    await renderSection()
    await openGroup()
    expect(container.textContent).not.toContain("This address uses plain HTTP")

    act(() => root?.unmount())
    root = null
    page().happyDOM.setURL("http://ghost.example.com/settings")
    await renderSection()
    await openGroup()
    expect(container.textContent).toContain("This address uses plain HTTP")
    expect(container.querySelector('[role="alert"]')).toBeNull()
  })

  it("offers to try again when the tokens cannot load", async () => {
    vi.mocked(api.integrationTokens).mockRejectedValueOnce(new Error("offline")).mockResolvedValue([kuma])
    await renderSection()

    expect(container.textContent).toContain("Integration tokens could not load.")
    press(labelledButton("Try again"))
    await tick()

    expect(summary().textContent).toContain("1 token · never used")
  })
})
