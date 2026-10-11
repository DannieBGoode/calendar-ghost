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
  user: { id: "user-admin", email: ADMIN_EMAIL, role: "installation_administrator", notify_by_email: true, language: null },
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

function mockFetch({
  providers,
  configured = true,
  redirectUri = REDIRECT_URI,
  accounts = [connected, disconnected],
  storage = usage,
  clearable,
  cleared,
  tokens = [kuma, homepage],
}: Scenario) {
  const responses: Record<string, Response> = {
    "/api/v1/providers": jsonResponse(providers ?? (configured ? [googleProvider(redirectUri)] : [])),
    "/api/v1/accounts": jsonResponse(accounts),
    "/api/v1/storage": jsonResponse(storage),
    "/api/v1/storage/activity": clearable ?? jsonResponse({ older_than_days: 90, entries: 41880 }),
    "/api/v1/storage/activity/clear": cleared ?? jsonResponse({ removed: 41880, database: usage.database }),
    "/api/v1/integration-tokens": jsonResponse(tokens),
    "/api/v1/session": jsonResponse(adminSession),
    "/api/v1/registration": jsonResponse({ policy: "only_me", only_me_available: true }),
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

  it("offers to connect an account of each provider the installation configured", async () => {
    // A provider this version has no words for is named by what the server calls it.
    const example: CalendarProvider = {
      ...googleProvider(REDIRECT_URI),
      kind: "example",
      display_name: "Example",
      connect_url: "/api/v1/oauth/example/start",
    }
    await renderSettings(testI18n(), { providers: [googleProvider(REDIRECT_URI), example] })

    const connect = [...container.querySelectorAll<HTMLAnchorElement>(".connect-actions a")]
    expect(connect.map((link) => [link.textContent.trim(), link.getAttribute("href")])).toEqual([
      ["Connect Google account", "/api/v1/oauth/google/start"],
      ["Connect Example account", "/api/v1/oauth/example/start"],
    ])
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
    expect(rows[0]?.querySelector("a")?.getAttribute("href")).toBe("/api/v1/oauth/microsoft/start?account=acct-m")
    const connect = [...container.querySelectorAll<HTMLAnchorElement>(".connect-actions a")]
    expect(connect.map((link) => link.textContent.trim())).toEqual(["Connect Google account", "Connect Microsoft account"])
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
    expect(container.querySelector(".account-summary-emails")?.textContent).toBe("dana@example.test, robin@example.test")

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
    ["administration", ["registration-title", "storage-title"]],
  ] as const)("shows the %s tab's sections", async (tab, shown) => {
    await renderSettings(testI18n(), { tab })
    expect(sections()).toEqual(shown)
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
