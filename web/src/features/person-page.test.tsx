/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { AppToasts } from "@/components/app-toasts"
import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { dateWords, pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { PersonPlanOverview, PlansOverview, SessionStatus, UserOverview } from "@/lib/api"

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
    scheduler: { configured: true, last_pass_completed_at: justNow, current_pass_started_at: null, next_pass_at: null },
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
    problems: [{ kind: "blocked", rule_id: "rule-1", summary: "3 events couldn't be synced", since: null, message: null, cause: null, last_tried_at: null, provider: null }],
    rules: [
      {
        id: "rule-1",
        name: RULE_NAME,
        state: "enabled",
        source: { calendar: "Calendar 1", provider: "google", number: 1 },
        destination: { calendar: "Calendar 2", provider: "google", number: 2 },
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
  plan: null,
}

const session: SessionStatus = {
  authenticated: true,
  installation_sends_email: false,
  user: { id: "user-dana", email: "dana@example.test", role: "installation_administrator", notify_by_email: true, instant_sync: true, instant_sync_availability: "on", instant_sync_help: null, language: null },
}

const hasFamily = { key: "family", name: "Family", on_default: false }
const hasFree = { key: "free", name: "Free", on_default: true }

/** Robin's own Plan, which Dana gave and which limits them while Plans are on, within each of its limits. */
const onFamily: PersonPlanOverview = {
  basis: "plan",
  plan: hasFamily,
  assigned: { key: "family", name: "Family" },
  has: hasFamily,
  over: [],
  assigned_by: "dana@example.test",
  assigned_at: "2026-10-12T09:00:00+00:00",
  use: {
    rules: { in_use: 0, allowed: 5 },
    connected_accounts: { in_use: 0, allowed: 3 },
    integration_tokens: { in_use: 0, allowed: 2 },
    sync_interval: "instant",
  },
}

/** Robin on the Default Plan, as assigning it answers and their page then shows it. */
const onFree: PersonPlanOverview = {
  basis: "plan",
  plan: hasFree,
  assigned: null,
  has: hasFree,
  over: [],
  assigned_by: null,
  assigned_at: null,
  use: {
    rules: { in_use: 0, allowed: 1 },
    connected_accounts: { in_use: 0, allowed: 1 },
    integration_tokens: { in_use: 0, allowed: 0 },
    sync_interval: "5_minutes",
  },
}

/** The Plans an administrator chooses from, by name then key, as the server lists them. */
const plans: PlansOverview = {
  enabled: true,
  default_plan: "free",
  sync_intervals: ["instant", "5_minutes"],
  followers: 1,
  plans: [
    {
      key: "family",
      name: "Family",
      limits: { rules: 5, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" },
      is_default: false,
      people: 1,
      limited_people: 1,
      over_people: 0,
      use: { rules: [], connected_accounts: [], integration_tokens: [] },
    },
    {
      key: "free",
      name: "Free",
      limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
      is_default: true,
      people: 3,
      limited_people: 2,
      over_people: 0,
      use: { rules: [], connected_accounts: [], integration_tokens: [] },
    },
  ],
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
let own: {
  openRule: ReturnType<typeof vi.fn<(ruleId: string) => void>>
  openConnections: ReturnType<typeof vi.fn<() => void>>
}

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

/**
 * An answer, one read at each request, for an answer that changes between requests, or one that
 * arrives only when a test gives it.
 */
type Answer = Response | Promise<Response> | (() => Response | Promise<Response>)

async function renderPerson(i18n: I18n, personId = "user-robin", answers: Record<string, Answer> = {}) {
  const routes: Record<string, Answer> = {
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
      const answer = routes[`${method} ${path}`] ?? jsonResponse(notFound, 404)
      return Promise.resolve(typeof answer === "function" ? answer() : answer)
    }),
  )
  back = vi.fn<() => void>()
  deleted = vi.fn<(notice: string) => void>()
  own = { openRule: vi.fn<(ruleId: string) => void>(), openConnections: vi.fn<() => void>() }
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <AppToasts>
              <PersonView personId={personId} onBack={back} onDeleted={deleted} own={own} />
            </AppToasts>
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

/** The facts under the person's name, in order. */
function facts() {
  return [...container.querySelectorAll(".person-facts li")].map((item) => item.textContent)
}

/** The labels of the open actions menu, in order. */
function menuLabels() {
  return [...container.querySelectorAll("[role='menuitem'] .overflow-menu-label")].map((label) => label.textContent)
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
    expect(text).toContain("Google Calendar: 75 calls, 1 refused for too many requests, 0 failed")
    // Who acts on the problem, and how.
    expect(text).toContain("robin@example.test can fix this from their dashboard.")
    expect([...container.querySelectorAll("h2")].map((heading) => heading.textContent)).toEqual([
      "Synchronization",
      "Accounts, Activity, and calls",
    ])
    // Each rule carries its own problem, and the calls say whether they look normal.
    expect(text).toContain("Google asked Calendar Ghost to slow down a few times, and it tried again later.")
    // Health comes before the rules, and the privacy note closes the page.
    expect(container.querySelector(".user-overview > section")?.textContent).toContain("Needs a look")
    expect(container.querySelector(".page-footnote")?.textContent).toContain("never their calendar names")
  })

  it("starts at the person's name, and names the browser tab after them", async () => {
    await renderPerson(testI18n())
    expect(document.activeElement).toBe(container.querySelector("h1"))
    expect(document.title).toBe("robin@example.test – People – Calendar Ghost")
  })

  it("shows a command's result once, beside the actions", async () => {
    await renderPerson(testI18n())
    await choose("Disable")
    expect(container.querySelectorAll(".command-result")).toHaveLength(1)
  })

  it("shows every problem of one rule, so a reauthorization step is never hidden (review on PR 68)", async () => {
    const lapsed = {
      kind: "stopped" as const,
      rule_id: "rule-1",
      summary: "A calendar account needs reauthorization",
      since: null,
      message: { code: "authorization_lapsed", params: { provider: "google" } },
      provider: "google",
    }
    const blocked = { ...robin.status.problems[0]!, rule_id: "rule-1" }
    const both = { ...robin, status: { ...robin.status, status: "stopped" as const, problems: [lapsed, blocked] } }
    await renderPerson(testI18n(), "user-robin", { "GET /api/v1/users/user-robin/overview": jsonResponse(both) })

    const text = container.textContent
    expect(text).toContain("A Google account needs reauthorization")
    expect(text).toContain("robin@example.test can fix this from their dashboard.")
    expect(text).toContain("3 events couldn't be synced")
  })

  it("says each problem's likely cause, and that an administrator's Cause is the reader's to fix", async () => {
    const lapsed = {
      kind: "stopped" as const,
      rule_id: "rule-1",
      summary: "A calendar account needs reauthorization",
      since: null,
      message: { code: "authorization_lapsed", params: { provider: "google" } },
      cause: "api_disabled" as const,
      last_tried_at: justNow,
      provider: "google",
    }
    const stopped = { ...robin, status: { ...robin.status, status: "stopped" as const, problems: [lapsed] } }
    // Where the guide explains it is the provider's to say.
    const google = {
      kind: "google",
      display_name: "Google",
      connect_url: "/api/v1/oauth/google/start",
      redirect_uri: "http://localhost:8000/api/v1/oauth/google/callback",
      cause_anchors: { api_disabled: "the-google-calendar-api-is-turned-off" },
    }
    await renderPerson(testI18n(), "user-robin", {
      "GET /api/v1/users/user-robin/overview": jsonResponse(stopped),
      "GET /api/v1/providers": jsonResponse([google]),
    })

    const text = container.textContent
    expect(text).toContain("Likely cause: the Google Calendar API is turned off for this installation.")
    expect(text).toContain("You fix this as the administrator, in Google Cloud. robin@example.test has nothing to do.")
    // Only the administrator can fix it, so it stands out.
    expect(container.querySelector(".user-overview-problem")?.getAttribute("data-owner")).toBe("administrator")
    const howToFix = [...container.querySelectorAll<HTMLAnchorElement>("a")].find((link) => link.textContent.startsWith("How to fix"))
    expect(howToFix?.href).toBe("https://calendarghost.com/docs/troubleshooting#the-google-calendar-api-is-turned-off")
    expect(howToFix?.target).toBe("_blank")
  })

  it("says a person fixes their own Cause from their dashboard, and offers the administrator nothing to do", async () => {
    const lapsed = {
      kind: "stopped" as const,
      rule_id: "rule-1",
      summary: "A calendar account needs reauthorization",
      since: null,
      message: { code: "authorization_lapsed", params: { provider: "google" } },
      provider: "google",
      cause: "access_revoked" as const,
      last_tried_at: justNow,
    }
    const stopped = { ...robin, status: { ...robin.status, status: "stopped" as const, problems: [lapsed] } }
    await renderPerson(testI18n(), "user-robin", { "GET /api/v1/users/user-robin/overview": jsonResponse(stopped) })

    const text = container.textContent
    // The problem already says the account needs reauthorization; the cause would only repeat it.
    expect(text).not.toContain("Likely cause")
    expect(text).toContain("robin@example.test can fix this from their dashboard.")
    // Quietly, the answer in case they ask for help.
    expect(text).toContain("If they ask for help: they reauthorize their Google account in Settings, under Connections.")
    expect(container.querySelector(".user-overview-problem")?.getAttribute("data-owner")).toBe("user")
    expect(text).not.toContain("How to fix")
    expect(container.querySelector(".user-overview-problem button, .user-overview-problem a")).toBeNull()
  })

  it("speaks to you on your own page, as the administrator you are", async () => {
    await renderPerson(testI18n(), "user-dana")

    const text = container.textContent
    expect(text).toContain("Activity explains what happened and what to do.")
    expect(text).not.toContain("dana@example.test can fix this")
  })

  it("closes with what administrators never see, and no longer points to Settings", async () => {
    await renderPerson(testI18n())

    const footnote = container.querySelector(".page-footnote")?.textContent ?? ""
    expect(footnote).toContain("never their calendar names, connected account emails, or events")
    expect(footnote).not.toContain("Settings")
  })

  it("says how many rules run, rather than repeating the status badge", async () => {
    await renderPerson(testI18n())

    expect(container.querySelector(".user-overview-verdict p")?.textContent).toBe("1 of 1 rule is running.")
  })

  it("keeps a healthy person to one card", async () => {
    const healthy = {
      ...robin,
      status: { ...robin.status, status: "healthy" as const, problems: [], counts: { ...robin.status.counts, blocked_events: 0 } },
    }
    await renderPerson(testI18n(), "user-robin", { "GET /api/v1/users/user-robin/overview": jsonResponse(healthy) })

    expect([...container.querySelectorAll("h2")].map((heading) => heading.textContent)).toEqual(["Synchronization"])
    expect(container.textContent).toContain("40 Activity entries")
  })

  describe("when an account lapsed for every rule it stops", () => {
    const lapse = (ruleId: string, cause: "access_revoked" | "api_disabled") => ({
      kind: "stopped" as const,
      rule_id: ruleId,
      summary: "A calendar account needs reauthorization",
      since: null,
      message: { code: "authorization_lapsed", params: { provider: "google" } },
      provider: "google",
      cause,
      last_tried_at: null,
    })
    const rule = robin.status.rules[0]!
    const twoRules = (cause: "access_revoked" | "api_disabled", person = robin) => ({
      ...person,
      status: {
        ...robin.status,
        status: "stopped" as const,
        counts: { ...robin.status.counts, rules: 2, running: 0, stopped: 2 },
        problems: [lapse("rule-1", cause), lapse("rule-2", cause)],
        rules: [
          { ...rule, state: "degraded" as const },
          {
            ...rule,
            id: "rule-2",
            name: "Calendar 2 → Calendar 1",
            state: "degraded" as const,
            source: rule.destination,
            destination: rule.source,
          },
        ],
      },
    })

    it("says it once, naming the rules it stops, without a cause line that repeats it", async () => {
      await renderPerson(testI18n(), "user-robin", {
        "GET /api/v1/users/user-robin/overview": jsonResponse(twoRules("access_revoked")),
      })

      const text = container.textContent
      expect(text.split("A Google account needs reauthorization").length - 1).toBe(1)
      expect(text).toContain("Stops Calendar 1 → Calendar 2 and Calendar 2 → Calendar 1.")
      expect(text.split("robin@example.test can fix this from their dashboard.").length - 1).toBe(1)
      expect(text).not.toContain("Likely cause")
    })

    it("on your own page, names your calendars and links to your step", async () => {
      const dana = {
        ...robin.user,
        id: "user-dana",
        email: "dana@example.test",
        role: "installation_administrator" as const,
      }
      const endpoint = (calendar: string, name: string) => ({
        connected_account_id: "account-1",
        calendar_id: `${calendar}@group.example`,
        calendar_name: name,
      })
      await renderPerson(testI18n(), "user-dana", {
        "GET /api/v1/users/user-dana/overview": jsonResponse(twoRules("access_revoked", { ...robin, user: dana })),
        "GET /api/v1/rules": jsonResponse([
          { id: "rule-1", source: endpoint("one", "Family"), destination: endpoint("two", "Work") },
          { id: "rule-2", source: endpoint("two", "Work"), destination: endpoint("one", "Family") },
        ]),
      })

      const text = container.textContent
      expect(text).toContain("Family → Work")
      expect(container.querySelector(".page-footnote")).toBeNull()
      expect(text).toContain("Stops Family → Work and Work → Family.")
      expect(text).toContain("Reauthorize your Google account in Settings, under Connections.")
      const open = [...container.querySelectorAll("button")].find((item) => item.textContent === "Open Connections")!
      await click(open)
      expect(own.openConnections).toHaveBeenCalled()
    })

    it("keeps the cause line when it says something new", async () => {
      await renderPerson(testI18n(), "user-robin", {
        "GET /api/v1/users/user-robin/overview": jsonResponse(twoRules("api_disabled")),
      })

      expect(container.textContent).toContain("Likely cause: the Google Calendar API is turned off for this installation.")
    })
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

  it("stays wherever you went if a deletion finishes after you left the page (review on PR 68)", async () => {
    await renderPerson(testI18n())
    let answer: (response: Response) => void = () => undefined
    const served = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      if (init?.method === "DELETE") return new Promise<Response>((resolve) => (answer = resolve))
      return served(input, init)
    })
    await choose("Delete")
    await click(button("Delete permanently"))

    act(() => root?.unmount())
    root = null
    await act(async () => {
      answer(jsonResponse({ rules: 1, deleted: 4, detached: 0, left: 0 }))
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    expect(deleted).not.toHaveBeenCalled()
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

  describe("their plan", () => {
    const withPlan = (plan: PersonPlanOverview, extra: Record<string, Answer> = {}) => ({
      "GET /api/v1/users/user-robin/overview": jsonResponse({ ...robin, plan }),
      "GET /api/v1/plans": jsonResponse(plans),
      ...extra,
    })
    /** Robin over Family's calendar account limit, at its rule limit, with no tokens. */
    const overFamily: PersonPlanOverview = {
      ...onFamily,
      over: [{ limit: "connected_accounts", in_use: 4, allowed: 3 }],
      use: {
        rules: { in_use: 5, allowed: 5 },
        connected_accounts: { in_use: 4, allowed: 3 },
        integration_tokens: { in_use: 0, allowed: 2 },
        sync_interval: "instant",
      },
    }
    const given = (has: { key: string; name: string; on_default: boolean }) =>
      jsonResponse({ dry_run: true, people: [{ user_id: "user-robin", email: "robin@example.test", had: hasFamily, has, over: [] }] })

    function card(): HTMLElement {
      return container.querySelector<HTMLElement>(".person-plan-card")!
    }

    function summary(): string | undefined {
      return card().querySelector(".person-plan-summary")?.textContent
    }

    /** Each usage row: its name, then what its value and chip say. */
    function usage(): string[][] {
      return [...card().querySelectorAll(".plan-usage-row")].map((row) => [
        row.querySelector(".plan-usage-name")?.textContent ?? "",
        row.querySelector(".plan-usage-value")?.textContent ?? "",
        row.querySelector(".plan-usage-chip")?.textContent ?? "",
      ])
    }

    function chooser(): HTMLElement | null {
      return container.querySelector<HTMLElement>("#plan-change-user-robin")
    }

    function choice(label: string): HTMLInputElement {
      const found = [...chooser()!.querySelectorAll<HTMLInputElement>("input[type='radio']")].find((radio) =>
        [...(radio.labels ?? [])].some((item) => item.textContent.startsWith(label)),
      )
      if (!found) throw new Error(`No choice ${label}`)
      return found
    }

    /** What describes an option: its limits in short, then what choosing it would do, once known. */
    function described(radio: HTMLInputElement): string[] {
      const ids = radio.getAttribute("aria-describedby")?.split(" ") ?? []
      return ids.map((id) => document.getElementById(id)?.textContent ?? "")
    }

    /** Each option: its name with its badges, its limits in short, and whether it is chosen. */
    function options(): [string, string, boolean][] {
      return [...chooser()!.querySelectorAll<HTMLInputElement>("input[type='radio']")].map((radio) => [
        [...(radio.labels ?? [])].map((item) => item.textContent).join(" "),
        described(radio)[0] ?? "",
        radio.checked,
      ])
    }

    /** What Change plan asked the server, dry runs included, in order. */
    function posted(): { plan: string | null; user_ids: string[]; dry_run: boolean }[] {
      return calls
        .filter((call) => call.method === "POST" && call.path === "/api/v1/plan-assignments")
        .map((call) => call.body as { plan: string | null; user_ids: string[]; dry_run: boolean })
    }

    function toast(): string | null | undefined {
      return container.querySelector("[role='status'][aria-atomic]")?.textContent
    }

    function overviewReads(): number {
      return calls.filter((call) => call.path === "/api/v1/users/user-robin/overview").length
    }

    function press(target: Element, key: string) {
      act(() => {
        target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }))
      })
    }

    function changePlan(): HTMLButtonElement {
      return [...card().querySelectorAll("button")].find((item) => item.textContent.trim() === "Change plan")!
    }

    it("shows no plan card and offers no Change plan while no plan exists", async () => {
      await renderPerson(testI18n())
      expect(facts()).toEqual(["User", "Joined just now", "Never signed in"])
      expect(container.querySelector(".person-plan-card")).toBeNull()
      await click(container.querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
      expect(menuLabels()).toEqual(["Make administrator", "Disable", "Create password reset link", "Delete"])
    })

    it("shows a plan card after Synchronization: who gave the plan, whether it limits them, its name and chips", async () => {
      await renderPerson(testI18n(), "user-robin", withPlan(overFamily))
      expect([...container.querySelectorAll("h2")].map((heading) => heading.textContent)).toEqual([
        "Synchronization",
        "Plan",
        "Accounts, Activity, and calls",
      ])
      const day = new Date(onFamily.assigned_at!).toLocaleDateString("en-US", { month: "short", day: "numeric" })
      expect(summary()).toBe(`Given by dana@example.test on ${day}. Plans are on, so it limits robin@example.test now.`)
      expect(card().querySelector(".person-plan-name")?.textContent).toBe("Family")
      const chip = card().querySelector<HTMLElement>(".person-plan-chip")!
      expect(chip.textContent).toBe("Over a limit")
      expect(chip.getAttribute("data-tone")).toBe("attention")
      expect(chip.querySelector("svg[aria-hidden='true']")).not.toBeNull()
      // The card says the plan, so the facts under their name no longer do.
      expect(facts()).toEqual(["User", "Joined just now", "Never signed in"])
      expect(container.querySelector(".page-footnote")?.textContent).toBe(
        "You see whether their synchronization works and how much of their plan they use, never their calendar names, connected account emails, or events.",
      )
    })

    it("shows each limit as a meter with its numbers and a chip, never color alone", async () => {
      await renderPerson(testI18n(), "user-robin", withPlan(overFamily))
      expect(usage()).toEqual([
        ["Active rules", "5 of 5", "Limit reached"],
        ["Calendar accounts", "4 of 3", "Over"],
        ["Integration Tokens", "0 of 2", ""],
        ["Sync speed", "Instant", ""],
      ])
      const meters = [...card().querySelectorAll("meter")]
      expect(meters.map((meter) => meter.getAttribute("aria-valuetext"))).toEqual([
        "5 of 5, limit reached",
        "4 of 3, over the limit",
        "0 of 2",
      ])
      expect(meters.map((meter) => meter.getAttribute("aria-label"))).toEqual([
        "Active rules",
        "Calendar accounts",
        "Integration Tokens",
      ])
      const over = card().querySelectorAll(".plan-usage-row")[1]!
      expect(over.querySelector(".plan-usage-chip svg[aria-hidden='true']")).not.toBeNull()
      expect(over.querySelector(".plan-usage-note")?.textContent).toBe(
        "robin@example.test has 4 calendar accounts and Family allows 3. Their accounts keep syncing, but they can't connect another until one is removed. They see the same on Your plan.",
      )
    })

    it("says what the default plan would do while plans are off, with neutral chips", async () => {
      const off: PersonPlanOverview = {
        ...onFree,
        basis: "plans_off",
        plan: null,
        over: [{ limit: "connected_accounts", in_use: 2, allowed: 1 }],
        use: { ...onFree.use!, connected_accounts: { in_use: 2, allowed: 1 } },
      }
      await renderPerson(testI18n(), "user-robin", withPlan(off))
      expect(summary()).toBe("The default plan. Plans are off, so it limits nobody yet.")
      expect([...card().querySelectorAll(".person-plan-chip")].map((chip) => chip.textContent)).toEqual(["Default", "Would be over"])
      expect(card().querySelector("[data-tone='attention']")).toBeNull()
      expect(usage()[1]).toEqual(["Calendar accounts", "2 of 1", "Would be over"])
      expect(usage()[2]).toEqual(["Integration Tokens", "Not included", ""])
      expect(card().querySelector(".plan-usage-note")).toBeNull()
    })

    it("says no plan limits an administrator, with no meters", async () => {
      const administering = {
        ...robin,
        user: { ...robin.user, role: "installation_administrator" as const },
        plan: { ...onFree, basis: "administrator" as const, plan: null },
      }
      await renderPerson(testI18n(), "user-robin", {
        "GET /api/v1/users/user-robin/overview": jsonResponse(administering),
        "GET /api/v1/plans": jsonResponse(plans),
      })
      expect(summary()).toBe("No plan limits administrators.")
      expect([...card().querySelectorAll(".person-plan-chip")].map((chip) => chip.textContent)).toEqual(["Default", "Not limited"])
      expect(card().querySelector("meter")).toBeNull()
      expect(facts()).toEqual(["Administrator", "Joined just now", "Never signed in"])
    })

    it("shows your own plan card with no Change plan", async () => {
      await renderPerson(testI18n(), "user-dana", {
        "GET /api/v1/users/user-dana/overview": jsonResponse({
          ...robin,
          user: { ...robin.user, id: "user-dana", email: "dana@example.test", role: "installation_administrator" },
          plan: { ...onFree, basis: "administrator", plan: null },
        }),
      })
      expect(summary()).toBe("No plan limits administrators.")
      expect(changePlan()).toBeUndefined()
    })

    it("keeps Change plan on the card, out of their actions menu", async () => {
      await renderPerson(testI18n(), "user-robin", withPlan(onFamily))
      expect(changePlan()).not.toBeUndefined()
      // It opens in the card, not over the page.
      expect(changePlan().hasAttribute("aria-haspopup")).toBe(false)
      await click(container.querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
      expect(menuLabels()).toEqual(["Make administrator", "Disable", "Create password reset link", "Delete"])
    })

    it("changes their plan in the card: one line per plan, the default meaning they follow it, then Save and a toast with Undo", async () => {
      await renderPerson(testI18n(), "user-robin", withPlan(onFamily, { "POST /api/v1/plan-assignments": given(hasFree) }))
      const before = overviewReads()
      await click(changePlan())
      expect(container.querySelector("dialog")).toBeNull()
      const form = chooser()!
      expect(card().contains(form)).toBe(true)
      const title = form.querySelector("h3")!
      expect(title.textContent).toBe("Change plan")
      expect(form.querySelector("[role='radiogroup']")?.getAttribute("aria-labelledby")).toBe(title.id)
      // The page names them, so the chooser does not, and Change plan gives way to it.
      expect(form.textContent).not.toContain("robin@example.test")
      expect(changePlan()).toBeUndefined()
      expect(card().querySelector(".person-plan-held")).toBeNull()
      // What they use stays in view beside the choice.
      expect(usage()).toHaveLength(4)
      // One choice per plan, the default first; no separate way to follow the default.
      expect(options()).toEqual([
        ["Free Default", "1 rule, 1 account, no tokens, every 5 min", false],
        ["Family Current", "5 rules, 3 accounts, 2 tokens, Instant", true],
      ])
      expect(form.textContent).not.toContain("Follow the default plan")
      expect(form.querySelector(".plan-change-note")?.textContent).toBe(
        "People on the default plan move with it when the default changes.",
      )
      expect(document.activeElement).toBe(choice("Family"))

      await click(choice("Free"))
      expect(posted()).toEqual([{ plan: null, user_ids: ["user-robin"], dry_run: true }])
      expect(described(choice("Free"))).toEqual(["1 rule, 1 account, no tokens, every 5 min", "Within every limit"])
      await click(button("Save"))

      expect(posted().at(-1)).toEqual({ plan: null, user_ids: ["user-robin"], dry_run: false })
      expect(chooser()).toBeNull()
      expect(toast()).toBe("robin@example.test now has Free.")
      expect(document.activeElement).toBe(changePlan())
      expect(overviewReads()).toBeGreaterThan(before)
      // The toast says it once: not again on the card or under their name.
      expect(container.querySelector(".command-result")).toBeNull()

      await click(button("Undo"))
      expect(posted().at(-1)).toEqual({ plan: "family", user_ids: ["user-robin"], dry_run: false })
      expect(toast()).toBe("robin@example.test has their plan back.")
    })

    it("says under the option chosen which limit they would be over, announced, in Attention Ochre only while plans are on", async () => {
      const wouldBeOver = jsonResponse({
        dry_run: true,
        people: [
          {
            user_id: "user-robin",
            email: "robin@example.test",
            had: hasFamily,
            has: hasFree,
            over: [{ limit: "connected_accounts", in_use: 2, allowed: 1 }],
          },
        ],
      })
      await renderPerson(testI18n(), "user-robin", withPlan(onFamily, { "POST /api/v1/plan-assignments": wouldBeOver }))
      await click(changePlan())
      await click(choice("Free"))
      expect(described(choice("Free"))).toEqual([
        "1 rule, 1 account, no tokens, every 5 min",
        "Would be over: 2 calendar accounts, 1 allowed",
      ])
      const note = chooser()!.querySelector<HTMLElement>("[role='status'][data-tone='attention']")!
      expect(note.textContent).toBe("Would be over: 2 calendar accounts, 1 allowed")
      expect(note.querySelector("svg[aria-hidden='true']")).not.toBeNull()
      // Only under the option chosen.
      expect(described(choice("Family"))).toEqual(["5 rules, 3 accounts, 2 tokens, Instant"])

      act(() => root?.unmount())
      root = null
      await renderPerson(
        testI18n(),
        "user-robin",
        withPlan(onFamily, {
          "GET /api/v1/plans": jsonResponse({ ...plans, enabled: false }),
          "POST /api/v1/plan-assignments": wouldBeOver,
        }),
      )
      await click(changePlan())
      await click(choice("Free"))
      expect(described(choice("Free"))[1]).toBe("Would be over: 2 calendar accounts, 1 allowed")
      expect(chooser()!.querySelector("[data-tone='attention']")).toBeNull()
    })

    it("closes, changing nothing, on Save with the plan they have, Cancel, or Escape, with focus back on Change plan", async () => {
      await renderPerson(testI18n(), "user-robin", withPlan(onFamily, { "POST /api/v1/plan-assignments": given(hasFree) }))
      await click(changePlan())
      await click(button("Save"))
      expect(chooser()).toBeNull()
      expect(document.activeElement).toBe(changePlan())

      await click(changePlan())
      await click(choice("Free"))
      await click(button("Cancel"))
      expect(chooser()).toBeNull()
      expect(document.activeElement).toBe(changePlan())

      await click(changePlan())
      // Opened again, it starts from the plan they have.
      expect(choice("Family").checked).toBe(true)
      press(choice("Family"), "Escape")
      await settle()
      expect(chooser()).toBeNull()
      expect(document.activeElement).toBe(changePlan())
      expect(posted().every((body) => body.dry_run)).toBe(true)
      expect(toast()).toBe("")
    })

    it("keeps the chooser waiting while the change is on its way, ignoring more input", async () => {
      let posts = 0
      await renderPerson(
        testI18n(),
        "user-robin",
        withPlan(onFamily, {
          "POST /api/v1/plan-assignments": () => ((posts += 1) === 1 ? given(hasFree) : new Promise<Response>(() => undefined)),
        }),
      )
      await click(changePlan())
      await click(choice("Free"))
      const save = button("Save")
      act(() => save.focus())
      await click(save)
      await click(save)
      expect(posted().filter((body) => !body.dry_run)).toHaveLength(1)
      for (const held of [save, button("Cancel")]) expect(held.getAttribute("aria-disabled")).toBe("true")
      expect(save.getAttribute("aria-busy")).toBe("true")
      expect(document.activeElement).toBe(save)
      await click(button("Cancel"))
      press(save, "Escape")
      await settle()
      expect(chooser()).not.toBeNull()
    })

    it("shows the server's refusal in the chooser, and reads the plans again so a removed plan leaves", async () => {
      const refusal = { detail: "no plan has this key", code: "plan_not_found", params: {} }
      const pro = { ...plans.plans[0]!, key: "pro", name: "Pro" }
      let posts = 0
      // Pro is removed elsewhere just as robin is given it: the server refuses, and lists it no more.
      await renderPerson(
        testI18n(),
        "user-robin",
        withPlan(onFamily, {
          "GET /api/v1/plans": () => jsonResponse(posts < 2 ? { ...plans, plans: [...plans.plans, pro] } : plans),
          "POST /api/v1/plan-assignments": () => ((posts += 1) === 1 ? given(hasFree) : jsonResponse(refusal, 404)),
        }),
      )
      const plansRead = () => calls.filter((call) => call.path === "/api/v1/plans").length
      await click(changePlan())
      await click(choice("Pro"))
      const before = plansRead()
      await click(button("Save"))
      expect(chooser()?.querySelector("[role='alert']")?.textContent).toBe(
        "This plan no longer exists. Reload to see the current plans.",
      )
      expect(plansRead()).toBeGreaterThan(before)
      // Pro is gone, so the choice is back on the plan they have.
      expect(options().map(([label, , checked]) => [label, checked])).toEqual([
        ["Free Default", false],
        ["Family Current", true],
      ])
      // Only in the chooser, not again under their name.
      expect(container.querySelectorAll("[role='alert']").length).toBe(1)

      await click(button("Cancel"))
      expect(chooser()).toBeNull()
      expect(container.querySelector("[role='alert']")).toBeNull()
      expect(document.activeElement).toBe(changePlan())
      expect(posted().filter((body) => !body.dry_run)).toHaveLength(1)
    })

    it("keeps one next step open: a command from the menu closes the chooser", async () => {
      await renderPerson(testI18n(), "user-robin", withPlan(onFamily, { "POST /api/v1/plan-assignments": given(hasFree) }))
      await click(changePlan())
      expect(chooser()).not.toBeNull()
      await choose("Delete")
      expect(chooser()).toBeNull()
      expect(container.querySelector("#delete-person-user-robin")).not.toBeNull()

      await click(changePlan())
      expect(container.querySelector("#delete-person-user-robin")).toBeNull()
      expect(chooser()).not.toBeNull()
    })

    it("has no untranslated text with the plan card and the chooser open", async () => {
      await renderPerson(pseudoI18n(), "user-robin", withPlan(overFamily, { "POST /api/v1/plan-assignments": given(hasFree) }))
      await click(card().querySelector<HTMLButtonElement>(".person-plan-change button")!)
      await click(chooser()!.querySelectorAll<HTMLInputElement>("input[type='radio']")[0]!)
      expect(
        untranslatedText(container, ["robin@example.test", "dana@example.test", RULE_NAME, "Family", "Free", ...dateWords()]),
      ).toEqual([])
    })
  })
})
