/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { dateWords, pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { PeoplePage, PersonRow, PlanSummary, PlansOverview, Registration, SessionStatus } from "@/lib/api"

import { PeopleView } from "./people-page"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const ORIGIN = "http://localhost:8000"

const session: SessionStatus = {
  authenticated: true,
  installation_sends_email: true,
  user: {
    id: "user-dana",
    email: "dana@example.test",
    role: "installation_administrator",
    notify_by_email: true,
    instant_sync: true,
    instant_sync_availability: "on",
    instant_sync_help: null,
    language: null,
  },
}

/** Nobody a Plan limits has anything it counts. */
const NO_USE: PlanSummary["use"] = { rules: [], connected_accounts: [], integration_tokens: [] }

/** Held by 4 people, one of them an administrator, so it limits 3: one has 4 rules, two have 1. */
const family: PlanSummary = {
  key: "family",
  name: "Family",
  limits: { rules: 5, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" },
  is_default: false,
  people: 4,
  limited_people: 3,
  over_people: 0,
  use: {
    rules: [
      { in_use: 4, people: 1 },
      { in_use: 1, people: 2 },
    ],
    connected_accounts: [],
    integration_tokens: [],
  },
}
const free: PlanSummary = {
  key: "free",
  name: "Free",
  limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
  is_default: false,
  people: 2,
  limited_people: 2,
  over_people: 0,
  use: { rules: [], connected_accounts: [], integration_tokens: [] },
}

/** The Plan the server makes the default when Plans turn on with none. */
const noLimits: PlanSummary = {
  key: "no-limits",
  name: "No limits",
  limits: { rules: null, connected_accounts: null, integration_tokens: null, sync_interval: "instant" },
  is_default: false,
  people: 3,
  limited_people: 2,
  over_people: 0,
  use: { rules: [], connected_accounts: [], integration_tokens: [] },
}

/** Plans as GET /api/v1/plans answers, with `defaultPlan` marked as the default. */
function overview({
  enabled = false,
  defaultPlan = null,
  plans = [family, free],
}: { enabled?: boolean; defaultPlan?: string | null; plans?: PlanSummary[] } = {}): PlansOverview {
  return {
    enabled,
    default_plan: defaultPlan,
    sync_intervals: ["instant", "5_minutes"],
    plans: plans.map((plan) => ({ ...plan, is_default: plan.key === defaultPlan })),
  }
}

const INVITATION_ONLY: Registration = { policy: "invitation_only", only_me_available: false }

/** Someone People lists, by email, as the Remove note names them. */
function holder(email: string): PersonRow {
  return {
    id: `user-${email.split("@")[0]}`,
    email,
    role: "user",
    state: "active",
    created_at: "2026-10-01T09:00:00Z",
    last_sign_in_at: null,
    verdict: "healthy",
    problems: 0,
    last_synced_at: null,
    resources: { rules: 0, connected_accounts: 0, activity_entries: 0, provider_calls: [], since: "2026-09-10" },
    plan: null,
  }
}

/** The first people who have a Plan, as GET /api/v1/users?plan= answers, and how many have it. */
function holders(emails: string[], total = emails.length): PeoplePage {
  return { users: emails.map(holder), total, page: 1, page_size: 3 }
}

/** What Limit people with plans says while off with no default plan. */
const OFF_NO_DEFAULT =
  "Off. Limits nobody. There is no default plan yet, so turning this on adds a plan named No limits as the default. It limits nobody until you give someone a smaller plan."

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

function refusal(status: number, code: string, params: Record<string, string | number> = {}): Response {
  return jsonResponse({ detail: "The server's English.", code, params }, status)
}

const NO_CONTENT = { ok: true, status: 204, json: () => Promise.resolve(null) } as Response

type Call = { method: string; path: string; query: URLSearchParams; body: unknown }
type Scenario = {
  registration?: Registration
  plans?: PlansOverview
  /** Answers by "METHOD /path", overriding the defaults. A promise lets a test hold an answer back. */
  answers?: Record<string, Response | Promise<Response>>
}

let calls: Call[] = []
let routes: Record<string, Response | Promise<Response>> = {}

function serve({ registration = INVITATION_ONLY, plans = overview(), answers = {} }: Scenario) {
  const defaults: Record<string, Response | Promise<Response>> = {
    "GET /api/v1/session": jsonResponse(session),
    "GET /api/v1/registration": jsonResponse(registration),
    "GET /api/v1/invitations": jsonResponse([]),
    "GET /api/v1/plans": jsonResponse(plans),
    "GET /api/v1/users": jsonResponse(holders(["robin@example.test"])),
    "GET /api/v1/installation/health": jsonResponse({
      status: "healthy",
      needs_attention: false,
      incidents: [],
      users: { healthy: 1 },
      disabled_users: 0,
      checked_at: "2026-10-16T09:00:00Z",
      hints: [],
    }),
  }
  routes = { ...defaults, ...answers }
  calls = []
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET"
      const [path = "", search = ""] = String(input).split("?")
      const body: unknown = init?.body ? JSON.parse(init.body as string) : undefined
      calls.push({ method, path, query: new URLSearchParams(search), body })
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
  page().happyDOM.setURL(`${ORIGIN}/people/plans`)
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

async function renderPlans(i18n: I18n, scenario: Scenario = {}) {
  serve(scenario)
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <PeopleView tab="plans" notice={null} onOpenPerson={() => undefined} />
          </QueryClientProvider>
        </ThemeProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
}

function plansSection(): HTMLElement {
  const found = container.querySelector<HTMLElement>("[aria-labelledby='plans-title']")
  if (!found) throw new Error("No Plans section")
  return found
}

/** Changes what the server answers from now on, as after a change it saved. */
function reply(route: string, response: Response) {
  routes[route] = response
}

function sections(): (string | null)[] {
  return [...container.querySelectorAll(".people-page > section")].map((item) => item.getAttribute("aria-labelledby"))
}

function buttonOrNull(name: string, within: ParentNode = plansSection()): HTMLButtonElement | null {
  return [...within.querySelectorAll("button")].find((candidate) => candidate.textContent.trim() === name) ?? null
}

function button(name: string, within: ParentNode = plansSection()): HTMLButtonElement {
  const found = buttonOrNull(name, within)
  if (!found) throw new Error(`No button "${name}"`)
  return found
}

/** A Plan row's lines under its name: its limits, how soon it syncs, and whom it limits. */
function copyLines(name: string): (string | null)[] {
  return [...planRow(name).querySelectorAll(".setting-copy p")].map((line) => line.textContent)
}

/** Whether each element comes after the one before it on the page. */
function inOrder(...elements: Element[]): boolean {
  return elements.every(
    (item, index) => index === 0 || Boolean(elements[index - 1]!.compareDocumentPosition(item) & Node.DOCUMENT_POSITION_FOLLOWING),
  )
}

function focus(target: HTMLElement) {
  act(() => target.focus())
}

/** The row of one Plan, by its name. */
function planRow(name: string): HTMLElement {
  const found = [...plansSection().querySelectorAll<HTMLElement>(".setting-item")].find(
    (item) => item.querySelector("h3")?.textContent === name,
  )
  if (!found) throw new Error(`No row for ${name}`)
  return found
}

function element(id: string): HTMLElement {
  const found = container.querySelector<HTMLElement>(`#${id}`)
  if (!found) throw new Error(`No element ${id}`)
  return found
}

function field(id: string): HTMLInputElement {
  return element(id) as HTMLInputElement
}

function select(id: string): HTMLSelectElement {
  return element(id) as HTMLSelectElement
}

async function click(target: HTMLElement) {
  act(() => target.click())
  await settle()
}

function type(input: HTMLInputElement, value: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set?.call(input, value)
    input.dispatchEvent(new Event("input", { bubbles: true }))
  })
}

async function choose(select: HTMLSelectElement, value: string) {
  act(() => {
    select.value = value
    select.dispatchEvent(new Event("change", { bubbles: true }))
  })
  await settle()
}

async function submit(form: HTMLFormElement) {
  await act(async () => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
  await settle()
}

function sent(method: string, path: string): unknown {
  return calls.find((call) => call.method === method && call.path === path)?.body
}

function status(): string | null | undefined {
  return plansSection().querySelector("[role='status']")?.textContent
}

function alertText(): string | null | undefined {
  return plansSection().querySelector("[role='alert']")?.textContent
}

/** What the Remove note on a Plan someone has says, without its link. */
function inUseNote(key: string): string | null | undefined {
  return element(`plan-remove-${key}`).querySelector("p")?.textContent
}

describe("People's Plans tab", () => {
  it("is hidden with People under Only me, where the only person administers, and never asks for plans", async () => {
    await renderPlans(testI18n(), { registration: { policy: "only_me", only_me_available: true } })
    expect(container.querySelector("[aria-labelledby='plans-title']")).toBeNull()
    expect(calls.some((call) => call.path === "/api/v1/plans")).toBe(false)
  })

  it("is the Plans tab of People under Invitation only", async () => {
    await renderPlans(testI18n())
    expect(container.querySelector("h1")?.textContent).toBe("People")
    expect(container.querySelector("nav.page-tabs [aria-current='page']")?.textContent).toBe("Plans")
    expect(sections()).toEqual(["plans-title"])
    expect(plansSection().querySelector("h2")?.textContent).toBe("Plans")
  })

  it("starts with an empty state whose one action is Add a plan", async () => {
    await renderPlans(testI18n(), { plans: overview({ plans: [] }) })
    expect(plansSection().querySelector("h3")?.textContent).toBe("No plans yet")
    expect(plansSection().textContent).toContain(
      "Add a plan with the limits you want. Make it the default to limit everyone, or give it to someone from their page to limit only them.",
    )
    expect([...plansSection().querySelectorAll("button")].map((item) => item.textContent.trim())).toEqual(["Add a plan"])
    expect(container.querySelector("#plans-default")).toBeNull()
    expect(container.querySelector("#plans-enabled")).toBeNull()
  })

  it("adds the first plan from the empty state, then offers the default and the on/off control", async () => {
    const added: PlanSummary = { ...free, people: 0, limited_people: 0 }
    await renderPlans(testI18n(), {
      plans: overview({ plans: [] }),
      answers: { "POST /api/v1/plans": jsonResponse(added, 201) },
    })
    await click(button("Add a plan"))
    expect(document.activeElement).toBe(field("plan-new-name"))
    type(field("plan-new-name"), "Free")
    reply("GET /api/v1/plans", jsonResponse(overview({ plans: [added] })))
    await submit(field("plan-new-name").closest("form")!)

    expect(status()).toBe("Free was added.")
    expect(plansSection().textContent).not.toContain("No plans yet")
    expect(copyLines("Free")).toEqual(["1 rule, 1 calendar account, no Integration Tokens", "Every 5 minutes", "Nobody has it."])
    expect(document.activeElement).toBe(button("Add a plan"))
    expect(inOrder(planRow("Free"), button("Add a plan"), select("plans-default"), field("plans-enabled"))).toBe(true)
  })

  it("puts the plans first, then the default, then the on/off control, each step after the one it needs", async () => {
    await renderPlans(testI18n(), { plans: overview({ defaultPlan: "free" }) })
    expect(
      inOrder(planRow("Family"), planRow("Free"), button("Add a plan"), select("plans-default"), field("plans-enabled")),
    ).toBe(true)
  })

  it("lists each Plan with its limits, interval, who has it, and whom it limits, marking the default", async () => {
    await renderPlans(testI18n(), { plans: overview({ enabled: true, defaultPlan: "free" }) })
    expect(copyLines("Family")).toEqual([
      "5 rules, 3 calendar accounts, 2 Integration Tokens",
      "Instant sync, and a check every 5 minutes",
      "4 people have it. Limits 3 people.",
    ])
    expect(copyLines("Free")).toEqual([
      "1 rule, 1 calendar account, no Integration Tokens",
      "Every 5 minutes",
      "2 people have it. Limits 2 people.",
    ])
    expect(planRow("Free").querySelector(".plan-title")?.textContent).toBe("FreeDefault")
    expect(planRow("Family").querySelector(".plan-title")?.textContent).toBe("Family")
  })

  it("says who has a plan, and whom it will limit once plans are on", async () => {
    const spare: PlanSummary = { ...family, key: "spare", name: "Spare", people: 1, limited_people: 0 }
    const unused: PlanSummary = { ...family, key: "unused", name: "Unused", people: 0, limited_people: 0 }
    await renderPlans(testI18n(), {
      plans: overview({ plans: [family, { ...free, limited_people: 1 }, spare, unused] }),
    })
    expect(copyLines("Family")[2]).toBe("4 people have it. Limits 3 people once plans are on.")
    expect(copyLines("Free")[2]).toBe("2 people have it. Limits 1 person once plans are on.")
    expect(copyLines("Spare")[2]).toBe("1 person has it. Limits nobody.")
    expect(copyLines("Unused")[2]).toBe("Nobody has it.")
  })

  it.each([
    ["on", true],
    ["off", false],
  ])("says who has a plan that limits nothing, and that it limits nobody, while plans are %s", async (_state, enabled) => {
    await renderPlans(testI18n(), { plans: overview({ enabled, defaultPlan: "free", plans: [free, noLimits] }) })
    expect(copyLines("No limits")).toEqual([
      "No limit on rules, calendar accounts, or Integration Tokens",
      "Instant sync, and a check every 5 minutes",
      "3 people have it. Limits nobody.",
    ])
  })

  it("answers who has a plan the same way on its row and in its Remove note", async () => {
    const robinOnly: PlanSummary = { ...noLimits, people: 1, limited_people: 1 }
    await renderPlans(testI18n(), { plans: overview({ enabled: true, defaultPlan: "free", plans: [free, robinOnly] }) })
    expect(copyLines("No limits")[2]).toBe("1 person has it. Limits nobody.")
    await click(button("Remove", planRow("No limits")))
    expect(inUseNote("no-limits")).toBe("robin@example.test has No limits. Give them another plan to remove it.")
    expect(element("plans-enabled-hint").textContent).toBe("On. Limits 2 people.")
  })

  it.each([
    [1, "1 has more than this plan allows."],
    [2, "2 have more than this plan allows."],
  ])("says how many people a plan limits have more than it allows (%i), in words and with an icon", async (over, line) => {
    await renderPlans(testI18n(), {
      plans: overview({ enabled: true, defaultPlan: "free", plans: [{ ...family, over_people: over }, free] }),
    })
    expect(copyLines("Family")).toEqual([
      "5 rules, 3 calendar accounts, 2 Integration Tokens",
      "Instant sync, and a check every 5 minutes",
      "4 people have it. Limits 3 people.",
      line,
    ])
    const marked = planRow("Family").querySelector("[data-tone='attention']")
    expect(marked?.textContent).toBe(line)
    expect(marked?.querySelector("svg[aria-hidden='true']")).not.toBeNull()
    expect(planRow("Free").querySelector("[data-tone='attention']")).toBeNull()
  })

  it.each([
    ["off with a default", overview({ defaultPlan: "free" }), "Off. Limits nobody."],
    ["off with no default", overview(), OFF_NO_DEFAULT],
    ["on", overview({ enabled: true, defaultPlan: "free" }), "On. Limits 5 people."],
    ["on for one person", overview({ enabled: true, defaultPlan: "free", plans: [{ ...free, limited_people: 1 }] }), "On. Limits 1 person."],
    ["on with only No limits", overview({ enabled: true, defaultPlan: "no-limits", plans: [noLimits] }), "On. Limits nobody yet."],
  ])("says whether plans are on and whom they limit: %s", async (_state, plans, hint) => {
    await renderPlans(testI18n(), { plans })
    const box = field("plans-enabled")
    expect(box.disabled).toBe(false)
    expect(box.checked).toBe(plans.enabled)
    expect(element(box.getAttribute("aria-labelledby")!).textContent).toBe("Limit people with plans")
    expect(box.getAttribute("aria-describedby")).toBe("plans-enabled-hint")
    expect(element("plans-enabled-hint").textContent).toBe(hint)
  })

  it("turns plans on with no default, showing the No limits plan the server made the default", async () => {
    const on = overview({ enabled: true, defaultPlan: "no-limits", plans: [family, free, noLimits] })
    await renderPlans(testI18n(), { answers: { "PUT /api/v1/plan-settings": jsonResponse(on) } })
    await click(field("plans-enabled"))
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: true, default_plan: null })
    expect(status()).toBe("Plans are on. No limits is the new default plan, and it limits nothing.")
    expect(field("plans-enabled").checked).toBe(true)
    // Family and Free limit the people who have them; No limits limits nobody.
    expect(element("plans-enabled-hint").textContent).toBe("On. Limits 5 people.")
    expect(select("plans-default").value).toBe("no-limits")
    expect(planRow("No limits").querySelector(".plan-title")?.textContent).toBe("No limitsDefault")
  })

  it("turns plans on with the default it has, and says how many people they now limit", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ defaultPlan: "free" }),
      answers: { "PUT /api/v1/plan-settings": jsonResponse(overview({ enabled: true, defaultPlan: "free" })) },
    })
    await click(field("plans-enabled"))
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: true, default_plan: "free" })
    expect(status()).toBe("Plans now limit 5 people.")
    expect(field("plans-enabled").checked).toBe(true)
    expect(element("plans-enabled-hint").textContent).toBe("On. Limits 5 people.")
  })

  it("turns plans on with the default chosen but not saved yet, and says so before", async () => {
    await renderPlans(testI18n(), {
      answers: { "PUT /api/v1/plan-settings": jsonResponse(overview({ enabled: true, defaultPlan: "free" })) },
    })
    await choose(select("plans-default"), "free")
    expect(element("plans-enabled-hint").textContent).toBe(
      "Off. Limits nobody. Turning this on also makes Free the default plan.",
    )

    await click(field("plans-enabled"))
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: true, default_plan: "free" })
    expect(status()).toBe("Plans now limit 5 people.")
    expect(select("plans-default").value).toBe("free")
    expect(buttonOrNull("Save default")).toBeNull()
    expect(element("plans-enabled-hint").textContent).toBe("On. Limits 5 people.")
  })

  it("turns plans on with No default chosen but not saved yet, which adds No limits, and says so before", async () => {
    await renderPlans(testI18n(), { plans: overview({ defaultPlan: "free" }) })
    await choose(select("plans-default"), "")
    expect(element("plans-enabled-hint").textContent).toBe(OFF_NO_DEFAULT)
    await click(field("plans-enabled"))
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: true, default_plan: null })
  })

  it("turns plans off with the default the select shows, so no unsaved choice is left behind", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ enabled: true, defaultPlan: "free" }),
      answers: { "PUT /api/v1/plan-settings": jsonResponse(overview({ defaultPlan: "family" })) },
    })
    await choose(select("plans-default"), "family")
    await click(field("plans-enabled"))
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: false, default_plan: "family" })
    expect(status()).toBe("Plans no longer limit anyone.")
    expect(select("plans-default").value).toBe("family")
    expect(buttonOrNull("Save default")).toBeNull()
  })

  it("keeps the unsaved default chosen when turning plans on is refused", async () => {
    await renderPlans(testI18n(), {
      answers: { "PUT /api/v1/plan-settings": refusal(404, "plan_not_found") },
    })
    await choose(select("plans-default"), "free")
    await click(field("plans-enabled"))
    expect(element("plans-enabled-error").textContent).toBe(
      "This plan no longer exists. Reload to see the current plans.",
    )
    expect(document.activeElement).toBe(field("plans-enabled"))
    expect(select("plans-default").value).toBe("free")
    expect(buttonOrNull("Save default")).not.toBeNull()
  })

  it("keeps the box ticked and focused while turning plans on is on its way, ignoring another click", async () => {
    const neverAnswered = new Promise<Response>(() => undefined)
    await renderPlans(testI18n(), {
      plans: overview({ defaultPlan: "free" }),
      answers: { "PUT /api/v1/plan-settings": neverAnswered },
    })
    const box = field("plans-enabled")
    focus(box)
    await click(box)
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: true, default_plan: "free" })
    expect(box.checked).toBe(true)
    expect(box.disabled).toBe(false)
    expect(box.getAttribute("aria-disabled")).toBe("true")
    expect(document.activeElement).toBe(box)

    await click(box)
    expect(calls.filter((call) => call.method === "PUT").length).toBe(1)
    expect(box.checked).toBe(true)
    expect(select("plans-default").getAttribute("aria-disabled")).toBe("true")
  })

  it("says why turning plans on was refused under the box, and moves focus to it", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ defaultPlan: "free" }),
      answers: { "PUT /api/v1/plan-settings": refusal(404, "plan_not_found") },
    })
    const box = field("plans-enabled")
    await click(box)
    const error = element("plans-enabled-error")
    expect(error.textContent).toBe("This plan no longer exists. Reload to see the current plans.")
    expect(error.getAttribute("role")).toBe("alert")
    expect(box.checked).toBe(false)
    expect(box.getAttribute("aria-invalid")).toBe("true")
    expect(box.getAttribute("aria-describedby")).toBe("plans-enabled-hint plans-enabled-error")
    expect(document.activeElement).toBe(box)
    expect(container.querySelector("#plans-default-error")).toBeNull()
  })

  it("chooses a default only once Save default is pressed", async () => {
    await renderPlans(testI18n(), {
      answers: { "PUT /api/v1/plan-settings": jsonResponse(overview({ defaultPlan: "family" })) },
    })
    expect(buttonOrNull("Save default")).toBeNull()
    await choose(select("plans-default"), "family")
    expect(sent("PUT", "/api/v1/plan-settings")).toBeUndefined()
    expect(buttonOrNull("Save default")).not.toBeNull()
    // Choosing the saved default again leaves nothing to save.
    await choose(select("plans-default"), "")
    expect(buttonOrNull("Save default")).toBeNull()

    await choose(select("plans-default"), "family")
    await click(button("Save default"))
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: false, default_plan: "family" })
    expect(status()).toBe("Family is now the default plan.")
    expect(buttonOrNull("Save default")).toBeNull()
    expect(document.activeElement).toBe(select("plans-default"))
    expect(element("plans-enabled-hint").textContent).toBe("Off. Limits nobody.")
  })

  it("keeps the default's controls focusable while it saves, showing the plan asked for", async () => {
    const neverAnswered = new Promise<Response>(() => undefined)
    await renderPlans(testI18n(), { answers: { "PUT /api/v1/plan-settings": neverAnswered } })
    await choose(select("plans-default"), "family")
    const save = button("Save default")
    focus(save)
    await click(save)
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: false, default_plan: "family" })
    for (const held of [select("plans-default"), save]) {
      expect(held.disabled).toBe(false)
      expect(held.getAttribute("aria-disabled")).toBe("true")
    }
    expect(save.getAttribute("aria-busy")).toBe("true")
    expect(document.activeElement).toBe(save)

    await click(save)
    await choose(select("plans-default"), "free")
    expect(calls.filter((call) => call.method === "PUT").length).toBe(1)
    expect(select("plans-default").value).toBe("family")
    expect(field("plans-enabled").getAttribute("aria-disabled")).toBe("true")
  })

  it.each([
    ["family", refusal(404, "plan_not_found"), "This plan no longer exists. Reload to see the current plans."],
    ["", refusal(409, "plans_need_default"), "Plans can't be on without a default plan. Choose another default instead."],
  ])("says why choosing %j as the default was refused under the select, and moves focus to it", async (chosen, answer, reason) => {
    await renderPlans(testI18n(), {
      plans: overview({ defaultPlan: chosen ? "free" : "family" }),
      answers: { "PUT /api/v1/plan-settings": answer },
    })
    await choose(select("plans-default"), chosen)
    await click(button("Save default"))
    const error = element("plans-default-error")
    expect(error.textContent).toBe(reason)
    expect(error.getAttribute("role")).toBe("alert")
    expect(select("plans-default").getAttribute("aria-invalid")).toBe("true")
    expect(select("plans-default").getAttribute("aria-describedby")).toBe("plans-default-hint plans-default-error")
    expect(document.activeElement).toBe(select("plans-default"))
    expect(container.querySelector("#plans-enabled-error")).toBeNull()

    // Choosing again puts the refusal away.
    await choose(select("plans-default"), "free")
    expect(container.querySelector("#plans-default-error")).toBeNull()
    expect(select("plans-default").hasAttribute("aria-invalid")).toBe(false)
  })

  it("offers no way to clear the default while plans are on", async () => {
    await renderPlans(testI18n(), { plans: overview({ enabled: true, defaultPlan: "free" }) })
    const none = select("plans-default").querySelector<HTMLOptionElement>("option[value='']")!
    expect(none.textContent).toBe("No default")
    expect(none.disabled).toBe(true)
  })

  it("adds a plan without a key, which the server makes from its name, with No limit sent as no limit", async () => {
    const added: PlanSummary = {
      key: "family-2",
      name: "Family Plus",
      limits: { rules: 8, connected_accounts: null, integration_tokens: 0, sync_interval: "5_minutes" },
      is_default: false,
      people: 0,
      limited_people: 0,
      over_people: 0,
      use: { rules: [], connected_accounts: [], integration_tokens: [] },
    }
    await renderPlans(testI18n(), { answers: { "POST /api/v1/plans": jsonResponse(added, 201) } })
    await click(button("Add a plan"))
    expect(container.querySelector("#plan-new-key")).toBeNull()
    expect(document.activeElement).toBe(field("plan-new-name"))
    const intervals = select("plan-new-interval")
    expect([...intervals.options].map((option) => [option.value, option.textContent])).toEqual([
      ["instant", "Instant sync, and a check every 5 minutes"],
      ["5_minutes", "Every 5 minutes"],
    ])

    type(field("plan-new-name"), " Family Plus ")
    await click(field("plan-new-rules-unlimited"))
    type(field("plan-new-rules"), "8")
    await click(field("plan-new-tokens-unlimited"))
    type(field("plan-new-tokens"), "0")
    await choose(intervals, "5_minutes")
    await submit(field("plan-new-name").closest("form")!)

    expect(sent("POST", "/api/v1/plans")).toStrictEqual({
      name: "Family Plus",
      limits: { rules: 8, connected_accounts: null, integration_tokens: 0, sync_interval: "5_minutes" },
    })
    expect(status()).toBe("Family Plus was added.")
    expect(container.querySelector("#plan-edit-new")).toBeNull()
    expect(document.activeElement).toBe(button("Add a plan"))
  })

  it("keeps Save unavailable until each limit has a number or No limit, and says why", async () => {
    await renderPlans(testI18n())
    await click(button("Add a plan"))
    type(field("plan-new-name"), "Family Plus")
    await click(field("plan-new-accounts-unlimited"))
    expect(button("Save plan").getAttribute("aria-disabled")).toBe("true")
    expect(element("plan-edit-new").textContent).toContain(
      "Enter how many calendar accounts they can connect, from 1 to 10,000, or choose No limit.",
    )
    type(field("plan-new-accounts"), "2")
    await settle()
    expect(button("Save plan").getAttribute("aria-disabled")).toBeNull()
  })

  it("keeps the new plan's form open with the reason it was refused, under the field it names", async () => {
    await renderPlans(testI18n(), {
      answers: { "POST /api/v1/plans": refusal(422, "invalid_plan", { reason: "name" }) },
    })
    await click(button("Add a plan"))
    type(field("plan-new-name"), "Family Plus")
    await submit(field("plan-new-name").closest("form")!)
    expect(element("plan-edit-new").querySelector("[role='alert']")?.textContent).toBe(
      "Give the plan a name of 1 to 60 characters, without line breaks or other control characters.",
    )
    expect(field("plan-new-name").getAttribute("aria-invalid")).toBe("true")
    expect(document.activeElement).toBe(field("plan-new-name"))
    expect(status()).toBe("")
  })

  it("refuses a name another plan has before sending it, and shows the server's refusal the same way", async () => {
    await renderPlans(testI18n(), {
      answers: { "POST /api/v1/plans": refusal(409, "plan_name_taken", { name: "Family plus" }) },
    })
    await click(button("Add a plan"))
    type(field("plan-new-name"), " family ")
    await submit(field("plan-new-name").closest("form")!)
    expect(sent("POST", "/api/v1/plans")).toBeUndefined()
    expect(element("plan-edit-new").querySelector("[role='alert']")?.textContent).toBe(
      "Another plan is named Family. Choose a different name.",
    )
    expect(field("plan-new-name").getAttribute("aria-invalid")).toBe("true")
    expect(document.activeElement).toBe(field("plan-new-name"))

    // Added meanwhile by someone else: the server refuses it the same way.
    type(field("plan-new-name"), "Family Plus")
    await submit(field("plan-new-name").closest("form")!)
    expect(sent("POST", "/api/v1/plans")).toMatchObject({ name: "Family Plus" })
    expect(element("plan-edit-new").querySelector("[role='alert']")?.textContent).toBe(
      "Another plan is named Family plus. Choose a different name.",
    )
    expect(field("plan-new-name").getAttribute("aria-invalid")).toBe("true")
    expect(document.activeElement).toBe(field("plan-new-name"))
  })

  it("lets a plan keep its own name, and refuses another plan's, while editing", async () => {
    await renderPlans(testI18n(), {
      answers: { "PUT /api/v1/plans/family": jsonResponse({ ...family, name: "FAMILY" }) },
    })
    await click(button("Edit", planRow("Family")))
    type(field("plan-family-name"), "free")
    await submit(field("plan-family-name").closest("form")!)
    expect(sent("PUT", "/api/v1/plans/family")).toBeUndefined()
    expect(element("plan-edit-family").querySelector("[role='alert']")?.textContent).toBe(
      "Another plan is named Free. Choose a different name.",
    )
    type(field("plan-family-name"), "FAMILY")
    await submit(field("plan-family-name").closest("form")!)
    expect(sent("PUT", "/api/v1/plans/family")).toMatchObject({ name: "FAMILY" })
  })

  it("edits a plan without showing its key, and warns before lowering its rule limit", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ enabled: true, defaultPlan: "free" }),
      answers: { "PUT /api/v1/plans/family": jsonResponse({ ...family, name: "Family Large" }) },
    })
    await click(button("Edit", planRow("Family")))
    expect(container.querySelector("#plan-family-key")).toBeNull()
    expect(document.activeElement).toBe(field("plan-family-name"))
    expect(element("plan-edit-family").querySelector("[data-tone='attention']")?.textContent).toBe("")

    type(field("plan-family-rules"), "2")
    await settle()
    expect(element("plan-family-rules-warning").textContent).toBe(
      "1 person on this plan has more rules syncing than this. Their rules keep syncing, but they cannot start another.",
    )
    type(field("plan-family-name"), "Family Large")
    await submit(field("plan-family-name").closest("form")!)

    expect(sent("PUT", "/api/v1/plans/family")).toEqual({
      name: "Family Large",
      limits: { rules: 2, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" },
    })
    expect(status()).toBe("Family Large was saved.")
    expect(container.querySelector("#plan-edit-family")).toBeNull()
    expect(document.activeElement).toBe(button("Edit", planRow("Family")))
  })

  it("names the plan each Edit and Remove acts on, for assistive technology", async () => {
    await renderPlans(testI18n())
    expect(button("Edit", planRow("Family")).getAttribute("aria-label")).toBe("Edit Family")
    expect(button("Remove", planRow("Family")).getAttribute("aria-label")).toBe("Remove Family")
    expect(button("Edit", planRow("Free")).getAttribute("aria-label")).toBe("Edit Free")
    expect(button("Remove", planRow("Free")).getAttribute("aria-label")).toBe("Remove Free")
  })

  it("names what each toggle opens only while it is open", async () => {
    await renderPlans(testI18n())
    const edit = button("Edit", planRow("Family"))
    const add = button("Add a plan")
    expect(edit.hasAttribute("aria-controls")).toBe(false)
    expect(add.hasAttribute("aria-controls")).toBe(false)
    await click(edit)
    expect(edit.getAttribute("aria-controls")).toBe("plan-edit-family")
    expect(element("plan-edit-family")).not.toBeNull()
    await click(add)
    expect(edit.hasAttribute("aria-controls")).toBe(false)
    expect(element(add.getAttribute("aria-controls")!).querySelector("form")).not.toBeNull()
  })

  it("keeps a save on its way, and then its refusal, while the other plan commands wait", async () => {
    let answer: (response: Response) => void = () => undefined
    const held = new Promise<Response>((resolve) => {
      answer = resolve
    })
    await renderPlans(testI18n(), { answers: { "PUT /api/v1/plans/family": held } })
    await click(button("Edit", planRow("Family")))
    type(field("plan-family-name"), "Family Large")
    await submit(field("plan-family-name").closest("form")!)
    const form = element("plan-edit-family")
    for (const held of [button("Save plan", form), button("Cancel", form)]) {
      expect(held.disabled).toBe(false)
      expect(held.getAttribute("aria-disabled")).toBe("true")
    }
    for (const waiting of [
      button("Edit", planRow("Family")),
      button("Remove", planRow("Family")),
      button("Edit", planRow("Free")),
      button("Remove", planRow("Free")),
      button("Add a plan"),
    ]) {
      expect(waiting.getAttribute("aria-disabled")).toBe("true")
    }

    // Edit again, and another plan's Edit, change nothing while the save is on its way.
    await click(button("Edit", planRow("Family")))
    await click(button("Edit", planRow("Free")))
    expect(container.querySelector("#plan-edit-free")).toBeNull()
    expect(button("Save plan", element("plan-edit-family")).getAttribute("aria-disabled")).toBe("true")

    await act(async () => {
      answer(refusal(422, "invalid_plan", { reason: "name" }))
      await Promise.resolve()
    })
    await settle()
    expect(element("plan-edit-family").querySelector("[role='alert']")?.textContent).toBe(
      "Give the plan a name of 1 to 60 characters, without line breaks or other control characters.",
    )
    expect(document.activeElement).toBe(field("plan-family-name"))
    expect(button("Save plan", element("plan-edit-family")).getAttribute("aria-disabled")).toBeNull()
    expect(button("Edit", planRow("Free")).getAttribute("aria-disabled")).toBeNull()
  })

  it("says what a lower limit will do once plans are on, while they are off", async () => {
    await renderPlans(testI18n(), { plans: overview({ defaultPlan: "free" }) })
    await click(button("Edit", planRow("Family")))
    type(field("plan-family-rules"), "2")
    await settle()
    expect(element("plan-family-rules-warning").textContent).toBe(
      "1 person on this plan has more rules syncing than this. Once plans are on, their rules keep syncing, but they cannot start another.",
    )
  })

  it("does not warn about a lower rule limit when the plan limits nobody", async () => {
    await renderPlans(testI18n(), { plans: overview({ plans: [{ ...family, limited_people: 0, use: NO_USE }] }) })
    await click(button("Edit", planRow("Family")))
    type(field("plan-family-rules"), "2")
    await settle()
    expect(element("plan-family-rules-warning").textContent).toBe("")
  })

  it("keeps an interval a later release saved, beside the offered ones", async () => {
    const hourly: PlanSummary = { ...family, limits: { ...family.limits, sync_interval: "60_minutes" } }
    await renderPlans(testI18n(), { plans: overview({ plans: [hourly] }) })
    expect(planRow("Family").textContent).toContain("Every hour")
    await click(button("Edit", planRow("Family")))
    const intervals = select("plan-family-interval")
    expect([...intervals.options].map((option) => option.value)).toEqual(["instant", "5_minutes", "60_minutes"])
    expect(intervals.value).toBe("60_minutes")
  })

  it("closes the form on Cancel, sending nothing", async () => {
    await renderPlans(testI18n())
    await click(button("Edit", planRow("Family")))
    await click(button("Cancel"))
    expect(container.querySelector("#plan-edit-family")).toBeNull()
    expect(calls.some((call) => call.method !== "GET")).toBe(false)
    expect(document.activeElement).toBe(button("Edit", planRow("Family")))
  })

  it("replaces Remove on the default plan with how to remove it", async () => {
    await renderPlans(testI18n(), { plans: overview({ defaultPlan: "free" }) })
    expect(buttonOrNull("Remove", planRow("Free"))).toBeNull()
    expect(planRow("Free").querySelector(".plan-remove-note")?.textContent).toBe(
      "Default plan. Choose another default to remove it.",
    )
    expect(button("Edit", planRow("Free"))).not.toBeNull()
    expect(button("Remove", planRow("Family"))).not.toBeNull()
  })

  it.each([
    [["robin@example.test"], 1, "robin@example.test has Family. Give them another plan to remove it."],
    [
      ["robin@example.test", "sam@example.test"],
      2,
      "robin@example.test and sam@example.test have Family. Give them another plan to remove it.",
    ],
    [
      ["ada@example.test", "robin@example.test", "sam@example.test"],
      3,
      "ada@example.test, robin@example.test, and sam@example.test have Family. Give them another plan to remove it.",
    ],
    [
      ["ada@example.test", "robin@example.test", "sam@example.test"],
      5,
      "ada@example.test, robin@example.test, sam@example.test, and 2 more have Family. Give them another plan to remove it.",
    ],
  ])("names who has a plan (%j of %i), instead of asking to remove it", async (emails, people, reason) => {
    await renderPlans(testI18n(), {
      plans: overview({ plans: [{ ...family, people }, free] }),
      answers: { "GET /api/v1/users": jsonResponse(holders(emails, people)) },
    })
    const remove = button("Remove", planRow("Family"))
    await click(remove)
    expect(remove.getAttribute("aria-expanded")).toBe("true")
    const shown = element("plan-remove-family")
    expect(inUseNote("family")).toBe(reason)
    expect(document.activeElement).toBe(shown)
    expect(buttonOrNull("Remove plan")).toBeNull()
    // The first three by email, from everyone who has the plan, as People counts them.
    const asked = calls.filter((call) => call.method === "GET" && call.path === "/api/v1/users")
    expect(asked.map((call) => Object.fromEntries(call.query))).toEqual([
      { plan: "family", sort: "email", order: "asc", page: "1", page_size: "3" },
    ])
    const link = shown.querySelector("a")!
    expect(link.textContent).toBe("Show who has Family")
    expect(link.getAttribute("href")).toBe("/people?plan=family")

    await click(remove)
    expect(container.querySelector("#plan-remove-family")).toBeNull()
    expect(remove.getAttribute("aria-expanded")).toBe("false")
    expect(calls.some((call) => call.method === "DELETE")).toBe(false)
  })

  it("says how many have a plan while their names load, or when they cannot", async () => {
    let answer: (response: Response) => void = () => undefined
    const held = new Promise<Response>((resolve) => {
      answer = resolve
    })
    await renderPlans(testI18n(), { answers: { "GET /api/v1/users": held } })
    await click(button("Remove", planRow("Family")))
    expect(inUseNote("family")).toBe("4 people have Family. Give them another plan to remove it.")
    // The sentence is announced again once it names them.
    expect(element("plan-remove-family").querySelector("p")?.getAttribute("aria-live")).toBe("polite")
    expect(element("plan-remove-family").querySelector("a")?.getAttribute("href")).toBe("/people?plan=family")

    await act(async () => {
      answer(jsonResponse({ detail: "boom" }, 500))
      await Promise.resolve()
    })
    await settle()
    expect(inUseNote("family")).toBe("4 people have Family. Give them another plan to remove it.")
  })

  it("opens Everyone filtered by the plan from its Remove note, at the list", async () => {
    await renderPlans(testI18n(), { plans: overview({ plans: [{ ...family, people: 1 }, free] }) })
    await click(button("Remove", planRow("Family")))
    await click(element("plan-remove-family").querySelector("a")!)

    expect(`${window.location.pathname}${window.location.search}`).toBe("/people?plan=family")
    expect(container.querySelector("nav.page-tabs [aria-current='page']")?.textContent).toBe("Everyone")
    const listed = calls.filter((call) => call.method === "GET" && call.path === "/api/v1/users").at(-1)
    expect(Object.fromEntries(listed!.query)).toMatchObject({ plan: "family", page: "1", page_size: "50" })
    expect(container.querySelector<HTMLSelectElement>("#people-plan")?.value).toBe("family")
    expect(document.activeElement).toBe(element("people-list-title"))
  })

  it("asks inline before removing a plan nobody has", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ plans: [{ ...family, people: 0, limited_people: 0 }, free] }),
      answers: { "DELETE /api/v1/plans/family": NO_CONTENT },
    })
    await click(button("Remove", planRow("Family")))
    const confirmation = element("plan-remove-family")
    expect(confirmation.querySelector("h3")?.textContent).toBe("Remove Family?")
    expect(confirmation.querySelector("p")?.textContent).toBe(
      "Nobody has this plan, so removing it changes nothing for anyone. You can't undo this.",
    )
    await click(button("Keep plan", confirmation))
    expect(container.querySelector("#plan-remove-family")).toBeNull()
    expect(sent("DELETE", "/api/v1/plans/family")).toBeUndefined()

    await click(button("Remove", planRow("Family")))
    await click(button("Remove plan", element("plan-remove-family")))
    expect(calls.some((call) => call.method === "DELETE" && call.path === "/api/v1/plans/family")).toBe(true)
    expect(status()).toBe("Family was removed.")
    expect(container.querySelector("#plan-remove-family")).toBeNull()
    expect(document.activeElement).toBe(button("Add a plan"))
  })

  it("keeps Remove plan and Keep plan focusable while the removal is on its way, then says why it was refused", async () => {
    let answer: (response: Response) => void = () => undefined
    const held = new Promise<Response>((resolve) => {
      answer = resolve
    })
    await renderPlans(testI18n(), {
      plans: overview({ plans: [{ ...family, people: 0, limited_people: 0 }, free] }),
      answers: { "DELETE /api/v1/plans/family": held },
    })
    await click(button("Remove", planRow("Family")))
    const confirmation = element("plan-remove-family")
    const confirm = button("Remove plan", confirmation)
    const keep = button("Keep plan", confirmation)
    focus(confirm)
    await click(confirm)
    for (const waiting of [confirm, keep]) {
      expect(waiting.disabled).toBe(false)
      expect(waiting.getAttribute("aria-disabled")).toBe("true")
    }
    expect(confirm.getAttribute("aria-busy")).toBe("true")
    expect(document.activeElement).toBe(confirm)
    await click(keep)
    await click(confirm)
    expect(element("plan-remove-family")).toBe(confirmation)
    expect(calls.filter((call) => call.method === "DELETE").length).toBe(1)

    // Someone was given the plan meanwhile.
    await act(async () => {
      answer(refusal(409, "plan_in_use", { people: 1, count: 1 }))
      await Promise.resolve()
    })
    await settle()
    expect(planRow("Family").querySelector("[role='alert']")?.textContent).toBe(
      "1 person has this plan. Give them another plan before you remove it.",
    )
    expect(document.activeElement).toBe(confirm)
    expect(confirm.getAttribute("aria-disabled")).toBeNull()
  })

  it("shows its own error with Try again when plans cannot load, and the rest still works", async () => {
    await renderPlans(testI18n(), { answers: { "GET /api/v1/plans": jsonResponse({ detail: "boom" }, 500) } })
    expect(alertText()).toContain("Plans could not load.")
    expect(button("Try again")).not.toBeNull()
    expect(sections()).toEqual(["plans-title"])
    expect([...container.querySelectorAll("nav.page-tabs a")].map((tab) => tab.textContent)).toEqual([
      "Everyone",
      "Invitations",
      "Plans",
    ])
    expect(button("Invite someone", container)).not.toBeNull()
  })

  it("has no untranslated text in the empty state", async () => {
    await renderPlans(pseudoI18n(), { plans: overview({ plans: [] }) })
    expect(untranslatedText(container, dateWords())).toEqual([])
  })

  it("has no untranslated text", async () => {
    const spare: PlanSummary = { ...family, key: "spare", name: "Spare", people: 0, limited_people: 0 }
    await renderPlans(pseudoI18n(), {
      plans: overview({ enabled: true, defaultPlan: "free", plans: [{ ...family, over_people: 1 }, free, spare] }),
    })
    const names = [...dateWords(), family.name, free.name, spare.name, "robin@example.test"]
    expect(untranslatedText(container, names)).toEqual([])
    await choose(select("plans-default"), "family")
    await click(planRow("Family").querySelectorAll("button")[1]!)
    expect(untranslatedText(container, names)).toEqual([])
    await click(planRow("Spare").querySelectorAll("button")[1]!)
    expect(untranslatedText(container, names)).toEqual([])
    await click(planRow("Family").querySelectorAll("button")[0]!)
    type(field("plan-family-rules"), "2")
    await settle()
    expect(untranslatedText(container, names)).toEqual([])
    await click(element("plans-add"))
    expect(untranslatedText(container, names)).toEqual([])
  })
})
