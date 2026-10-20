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
import type { OverLimit, PeoplePage, PersonRow, PlanSummary, PlansOverview, Registration, SessionStatus } from "@/lib/api"
import type { PlanPanel } from "@/lib/navigation"

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
  use: NO_USE,
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
  use: NO_USE,
}

/** Plans as GET /api/v1/plans answers, with `defaultPlan` marked as the default. */
function overview({
  enabled = false,
  defaultPlan = null,
  plans = [family, free],
  followers = 3,
}: { enabled?: boolean; defaultPlan?: string | null; plans?: PlanSummary[]; followers?: number } = {}): PlansOverview {
  return {
    enabled,
    default_plan: defaultPlan,
    sync_intervals: ["instant", "5_minutes"],
    followers,
    plans: plans.map((plan) => ({ ...plan, is_default: plan.key === defaultPlan })),
  }
}

const INVITATION_ONLY: Registration = { policy: "invitation_only", only_me_available: false }

/** Someone People lists, by email, as Remove names them. */
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

/** What the status card says before any Plan exists. */
const FIRST_VISIT =
  "Everyone can use everything, with no limits. Turning plans on adds a plan named No limits as the default, so nobody is limited until you give someone a smaller plan."

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

function refusal(status: number, code: string, params: Record<string, string | number> = {}): Response {
  return jsonResponse({ detail: "The server's English.", code, params }, status)
}

const NO_CONTENT = { ok: true, status: 204, json: () => Promise.resolve(null) } as Response

type Call = { method: string; path: string; query: URLSearchParams; body: unknown }
/** An answer, one held back as a promise, or one chosen by what was asked, such as a query. */
type Answer = Response | Promise<Response> | ((call: Call) => Response | Promise<Response>)
type Scenario = {
  registration?: Registration
  plans?: PlansOverview
  /** Answers by "METHOD /path", overriding the defaults. A promise lets a test hold an answer back. */
  answers?: Record<string, Answer>
}

let calls: Call[] = []
let routes: Record<string, Answer> = {}

function serve({ registration = INVITATION_ONLY, plans = overview(), answers = {} }: Scenario) {
  const defaults: Record<string, Answer> = {
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
      const call = { method, path, query: new URLSearchParams(search), body }
      calls.push(call)
      const answer = routes[`${method} ${path}`] ?? jsonResponse({})
      return Promise.resolve(typeof answer === "function" ? answer(call) : answer)
    }),
  )
}

let container: HTMLDivElement
let root: Root | null = null
let address: string
/** The people whose pages a link opened, by id. */
let opened: string[] = []
/** The Plan panels the app was asked to open, from elsewhere than the Plans tab. */
let openedPlans: PlanPanel[] = []

function page() {
  return window as typeof window & { happyDOM: { setURL: (url: string) => void } }
}

beforeEach(() => {
  container = document.createElement("div")
  document.body.append(container)
  address = window.location.href
  opened = []
  openedPlans = []
  page().happyDOM.setURL(`${ORIGIN}/people/plans`)
})

afterEach(() => {
  if (root) {
    act(() => root?.unmount())
    root = null
  }
  container.remove()
  page().happyDOM.setURL(address)
  window.scrollTo(0, 0)
  vi.restoreAllMocks()
})

async function settle(times = 8) {
  for (let i = 0; i < times; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

/** How People was arrived at: `panelFocus` as a toast's next step opens a Plan's panel from elsewhere. */
async function renderPlans(i18n: I18n, scenario: Scenario = {}, { panelFocus = false } = {}) {
  serve(scenario)
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <AppToasts>
              <PeopleView
                tab="plans"
                notice={null}
                onOpenPerson={(id) => opened.push(id)}
                onOpenPlan={(panel) => openedPlans.push(panel)}
                panelFocus={panelFocus}
              />
            </AppToasts>
          </QueryClientProvider>
        </ThemeProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
}

function element(id: string): HTMLElement {
  const found = container.querySelector<HTMLElement>(`#${id}`)
  if (!found) throw new Error(`No element ${id}`)
  return found
}

function plansSection(): HTMLElement {
  return element("plans-title").closest("section")!
}

/** Changes what the server answers from now on, as after a change it saved. */
function reply(route: string, response: Answer) {
  routes[route] = response
}

function buttonOrNull(name: string, within: ParentNode = plansSection()): HTMLButtonElement | null {
  return [...within.querySelectorAll("button")].find((candidate) => candidate.textContent.trim() === name) ?? null
}

function button(name: string, within: ParentNode = plansSection()): HTMLButtonElement {
  const found = buttonOrNull(name, within)
  if (!found) throw new Error(`No button "${name}"`)
  return found
}

function focus(target: HTMLElement) {
  act(() => target.focus())
}

function field(id: string): HTMLInputElement {
  return element(id) as HTMLInputElement
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

function sentAll(method: string, path: string): unknown[] {
  return calls.filter((call) => call.method === method && call.path === path).map((call) => call.body)
}

/** The page-level result shown last, as the toast's live region says it. */
function toast(): string | null | undefined {
  return container.querySelector("[role='status'][aria-atomic]")?.textContent
}

/** The toast's own button, such as Undo or Assign people. */
function toastButton(name: string): HTMLButtonElement {
  return button(name, container.querySelector("[role='status'][aria-atomic]")!.parentElement!)
}

/** Opens Everyone, so the Plans tab is gone while its toast stays. */
async function leavePlans() {
  await click([...container.querySelectorAll<HTMLAnchorElement>("nav.page-tabs a")].find((tab) => tab.textContent === "Everyone")!)
  expect(container.querySelector("#plans-title")).toBeNull()
}

function statusCard(): HTMLElement {
  return element("plans-status")
}

function planSwitch(): HTMLButtonElement {
  return element("plans-switch") as HTMLButtonElement
}

/** The status card's facts, each as its label and value. */
function facts(): string[][] {
  return [...statusCard().querySelectorAll(".plans-fact")].map((fact) => [
    fact.querySelector("dt")?.textContent ?? "",
    fact.querySelector("dd")?.textContent ?? "",
  ])
}

function fact(id: string): HTMLElement {
  const found = statusCard().querySelector<HTMLElement>(`[data-fact='${id}'] dd`)
  if (!found) throw new Error(`No fact ${id}`)
  return found
}

/** The row of one Plan in the catalog, by its key. */
function planRow(key: string): HTMLElement {
  const found = container.querySelector<HTMLElement>(`tr[data-plan='${key}']`)
  if (!found) throw new Error(`No row for ${key}`)
  return found
}

/** The keys of the Plans the catalog lists, in order. */
function listed(): (string | null)[] {
  return [...container.querySelectorAll("tr[data-plan]")].map((row) => row.getAttribute("data-plan"))
}

/** A Plan's row, cell by cell, as it reads. */
function cells(key: string): string[] {
  return [...planRow(key).querySelectorAll("th, td")].map((cell) => cell.textContent)
}

function cell(key: string, column: string): HTMLElement {
  const found = planRow(key).querySelector<HTMLElement>(`.plan-col-${column}`)
  if (!found) throw new Error(`No ${column} cell for ${key}`)
  return found
}

/** A Plan's name in the catalog, a link that opens its panel. */
function nameLink(key: string): HTMLAnchorElement {
  return element(`plan-name-${key}`) as HTMLAnchorElement
}

/** Where the browser is now, path and query. */
function here(): string {
  return `${window.location.pathname}${window.location.search}`
}

function panelOrNull(): HTMLElement | null {
  return container.querySelector<HTMLElement>("#plan-panel")
}

/** The side panel beside the catalog, holding one Plan's Limits or People, or a new Plan. */
function panel(): HTMLElement {
  const found = panelOrNull()
  if (!found) throw new Error("No plan panel")
  return found
}

function panelTitle(): HTMLElement {
  return element("plan-panel-title")
}

/** The panel's Close, an icon button at its top. */
function closeButton(): HTMLButtonElement {
  return panel().querySelector<HTMLButtonElement>(".plan-panel-bar button")!
}

/** The panel's tabs, as each reads to a screen reader and where it leads. */
function panelTabs(): [string, string | null, string | null][] {
  return [...panel().querySelectorAll<HTMLAnchorElement>("nav.page-tabs a")].map((tab) => [
    tab.textContent,
    tab.getAttribute("href"),
    tab.getAttribute("aria-current"),
  ])
}

function panelTab(label: string): HTMLAnchorElement {
  const found = [...panel().querySelectorAll<HTMLAnchorElement>("nav.page-tabs a")].find((tab) =>
    tab.textContent.startsWith(label),
  )
  if (!found) throw new Error(`No panel tab ${label}`)
  return found
}

/** The catalog's column headings. */
function headings(): string[] {
  return [...element("plans-catalog").querySelectorAll("thead th")].map((heading) => heading.textContent)
}

async function escape(target: HTMLElement) {
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }))
  })
  await settle()
}

function labelOf(input: HTMLInputElement): string {
  return [...(input.labels ?? [])].map((label) => label.textContent).join(" ")
}

/** One option of a limit field, by the id of the number it holds. */
function limitOption(id: string, label: string): HTMLInputElement {
  const found = [...field(id).closest("fieldset")!.querySelectorAll<HTMLInputElement>("input[type='radio']")].find(
    (radio) => labelOf(radio) === label,
  )
  if (!found) throw new Error(`No option ${label} for ${id}`)
  return found
}

function speedRadio(interval: string): HTMLInputElement {
  return panel().querySelector<HTMLInputElement>(`[role='radiogroup'] input[type='radio'][value='${interval}']`)!
}

function menuTrigger(key: string): HTMLButtonElement {
  return planRow(key).querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!
}

async function openMenu(key: string) {
  await click(menuTrigger(key))
}

/** The open row menu's items, as label and description. */
function menuItems(key: string): [string, string | null][] {
  return [...planRow(key).querySelectorAll("[role='menuitem']")].map((item) => [
    item.querySelector(".overflow-menu-label")?.textContent ?? "",
    item.querySelector(".overflow-menu-description")?.textContent ?? null,
  ])
}

function menuItem(key: string, label: string): HTMLElement {
  const found = [...planRow(key).querySelectorAll<HTMLElement>("[role='menuitem']")].find(
    (item) => item.querySelector(".overflow-menu-label")?.textContent === label,
  )
  if (!found) throw new Error(`No menu item ${label} for ${key}`)
  return found
}

async function chooseFromMenu(key: string, label: string) {
  await openMenu(key)
  await click(menuItem(key, label))
}

/** The row under a Plan's row, where its form, confirmation, or refusal shows. */
function detailsOf(key: string): HTMLElement | null {
  const next = planRow(key).nextElementSibling
  return next?.classList.contains("plan-details-row") ? (next as HTMLElement) : null
}

/** The catalog's head: how many plans there are, and New plan. */
function catalogHead(): HTMLElement {
  return container.querySelector<HTMLElement>(".plans-catalog-head")!
}

/** Someone the assign checklist may list, with the Plan they have now. */
function candidate(email: string, has: { key: string; name: string; on_default: boolean } | null, role: PersonRow["role"] = "user"): PersonRow {
  return {
    ...holder(email),
    role,
    plan: has && { basis: "plan", plan: has, assigned: null, has, over: [], assigned_by: null, assigned_at: null, use: null },
  }
}

const ALEX = candidate("alex@example.test", { key: "family", name: "Family", on_default: true })
const SAM = candidate("sam@example.test", { key: "no-limits", name: "No limits", on_default: false })
const ROBIN = candidate("robin@example.test", { key: "free", name: "Free", on_default: false })
const DANA = candidate("dana@example.test", { key: "family", name: "Family", on_default: true }, "installation_administrator")

/** People as GET /api/v1/users answers the assign checklist, from one page of up to 100. */
function candidates(people: PersonRow[], total = people.length): PeoplePage {
  return { users: people, total, page: 1, page_size: 100 }
}

/** What giving Free does, or would do in a dry run: each person's Plan before, and what they are over after. */
function moved(people: [PersonRow, OverLimit[]][], dryRun = false) {
  return jsonResponse({
    dry_run: dryRun,
    people: people.map(([person, over]) => ({
      user_id: person.id,
      email: person.email,
      had: person.plan?.has ?? null,
      has: { key: "free", name: "Free", on_default: false },
      over,
    })),
  })
}

/** Alex would have 3 rules on Free, which allows 1; Sam would be within it. */
const DRY_RUN = moved(
  [
    [ALEX, [{ limit: "rules", in_use: 3, allowed: 1 }]],
    [SAM, []],
  ],
  true,
)

function assignOf(key: string): HTMLElement {
  return element(`plan-assign-${key}`)
}

/** The assign checklist's people, each as their label, the Plan they have, and what they would be over. */
function assignRows(key: string): (string | null)[][] {
  return [...assignOf(key).querySelectorAll(".plan-assign-person")].map((row) => [
    row.querySelector("label")?.textContent ?? "",
    row.querySelector(".plan-assign-held")?.textContent ?? null,
    row.querySelector(".plan-assign-over")?.textContent ?? null,
  ])
}

function pick(key: string, person: PersonRow): HTMLInputElement {
  return assignOf(key).querySelector<HTMLInputElement>(`#plan-assign-${key}-${person.id}`)!
}

async function check(key: string, person: PersonRow) {
  act(() => pick(key, person).click())
  await settle()
}

function assignCalls(): unknown[] {
  return sentAll("POST", "/api/v1/plan-assignments")
}

describe("People's Plans tab", () => {
  it("is hidden with People under Only me, where the only person administers, and never asks for plans", async () => {
    await renderPlans(testI18n(), { registration: { policy: "only_me", only_me_available: true } })
    expect(container.querySelector("#plans-title")).toBeNull()
    expect(calls.some((call) => call.path === "/api/v1/plans")).toBe(false)
  })

  it("is the Plans tab of People, whose sentence follows the tab, with New plan in the catalog's head", async () => {
    await renderPlans(testI18n())
    expect(container.querySelector("h1")?.textContent).toBe("People")
    expect(container.querySelector(".page-intro")?.textContent).toBe(
      "Plans set how much each person can use and how soon their calendars sync.",
    )
    expect(container.querySelector("nav.page-tabs [aria-current='page']")?.textContent).toBe("Plans")
    expect(element("plans-title").textContent).toBe("Plans")
    expect(element("plans-title").classList.contains("sr-only")).toBe(true)
    // The page header has no action on Plans: New plan sits on the list it adds to.
    expect(container.querySelector(".heading-action")).toBeNull()
    expect(catalogHead().querySelector("h3")?.textContent).toBe("2 plans")
    expect([...catalogHead().querySelectorAll("button")].map((item) => item.textContent.trim())).toEqual(["New plan"])
    expect(buttonOrNull("Invite someone", container)).toBeNull()
  })

  it("starts with the status card and one empty state whose one action is New plan", async () => {
    await renderPlans(testI18n(), { plans: overview({ plans: [] }) })
    expect(statusCard().querySelector("h3")?.textContent).toBe("Plans are off")
    expect(element("plans-status-sentence").textContent).toBe(FIRST_VISIT)
    expect(planSwitch().getAttribute("aria-checked")).toBe("false")
    expect(facts()).toEqual([])
    const empty = element("plans-empty")
    expect(empty.querySelector("h3")?.textContent).toBe("No plans yet")
    expect(empty.querySelector("p")?.textContent).toBe(
      "A plan sets how many rules, calendar accounts, and integration tokens a person can have, and how soon their calendars sync. Make one, then give it to people or make it the default.",
    )
    expect([...empty.querySelectorAll("button")].map((item) => item.textContent.trim())).toEqual(["New plan"])
    expect(container.querySelector(".heading-action")).toBeNull()
    expect(container.querySelector("#plans-catalog")).toBeNull()
  })

  it("shows skeletons in the shape of the status card and the table while plans load", async () => {
    await renderPlans(testI18n(), { answers: { "GET /api/v1/plans": new Promise<Response>(() => undefined) } })
    const loading = plansSection().querySelector("[aria-busy='true']")!
    expect(loading.getAttribute("aria-label")).toBe("Loading plans")
    expect(loading.querySelectorAll(".plans-skeleton-card").length).toBe(2)
    expect(container.querySelector("#plans-status")).toBeNull()
  })

  it("says nothing changed when plans cannot load, with Try again, and the rest still works", async () => {
    await renderPlans(testI18n(), { answers: { "GET /api/v1/plans": jsonResponse({ detail: "boom" }, 500) } })
    const alert = plansSection().querySelector("[role='alert']")!
    expect(alert.textContent).toContain("Plans could not load. Nothing changed: the limits people had still apply.")
    reply("GET /api/v1/plans", jsonResponse(overview()))
    await click(button("Try again", alert))
    expect(plansSection().querySelector("[role='alert']")).toBeNull()
    expect(listed()).toEqual(["family", "free"])
    expect([...container.querySelectorAll("nav.page-tabs a")].map((tab) => tab.textContent)).toEqual([
      "Everyone",
      "Invitations",
      "Plans",
    ])
  })
})

describe("The status card", () => {
  it("says Plans are on, whom they limit, and what everyone else gets, with the switch on", async () => {
    await renderPlans(testI18n(), { plans: overview({ enabled: true, defaultPlan: "free" }) })
    expect(statusCard().querySelector("h3")?.textContent).toBe("Plans are on")
    // The sentence says what the facts cannot: what a limit does, and who gets the default.
    expect(element("plans-status-sentence").textContent).toBe(
      "People can't add more than their plan allows. Anyone without a plan of their own, including people who join later, gets the default plan.",
    )
    const toggle = planSwitch()
    expect(toggle.getAttribute("role")).toBe("switch")
    expect(toggle.getAttribute("aria-checked")).toBe("true")
    expect(toggle.getAttribute("aria-label")).toBe("Plans")
    expect(toggle.getAttribute("aria-describedby")).toBe("plans-status-sentence")
    expect(toggle.querySelector("[data-state-label='on']")?.textContent).toBe("On")
    expect(facts()).toEqual([
      ["Limited now", "5 people"],
      ["Over a limit", "Nobody"],
      ["Default plan", "Free"],
    ])
    // Whom it limits and who is over lead; the default follows on one quieter line where the card
    // is narrow.
    expect([...statusCard().querySelectorAll(".plans-fact[data-secondary]")].map((item) => item.getAttribute("data-fact"))).toEqual([
      "default",
    ])
    expect(statusCard().querySelector("[data-tone='attention']")).toBeNull()
    expect(fact("over").querySelector("a")).toBeNull()
  })

  it("makes who is over a limit the link that shows them in Everyone, with an icon as well as its tone", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ enabled: true, defaultPlan: "free", plans: [{ ...family, over_people: 1 }, free] }),
    })
    const over = fact("over")
    expect(over.textContent).toBe("1 person")
    expect(over.getAttribute("data-tone")).toBe("attention")
    const show = over.querySelector("a")!
    expect(show.textContent).toBe("1 person")
    expect(show.querySelector("svg[aria-hidden='true']")).not.toBeNull()
    expect(show.getAttribute("href")).toBe("/people?over=true")
    expect(show.getAttribute("aria-label")).toBe("Show the 1 person over a limit")
    expect(show.getAttribute("aria-label")).toContain(show.textContent)

    await click(show)
    expect(`${window.location.pathname}${window.location.search}`).toBe("/people?over=true")
    expect(container.querySelector("nav.page-tabs [aria-current='page']")?.textContent).toBe("Everyone")
    const asked = calls.filter((call) => call.method === "GET" && call.path === "/api/v1/users").at(-1)
    expect(Object.fromEntries(asked!.query)).toMatchObject({ over: "true", page: "1", page_size: "50" })
    expect(document.activeElement).toBe(element("people-list-title"))
  })

  it.each([
    ["with a default", overview({ defaultPlan: "free" }), "Nobody is limited. Turning plans on applies each person's plan at once.", "Free"],
    [
      "with someone over",
      overview({ defaultPlan: "free", plans: [{ ...family, over_people: 2 }, free] }),
      "Nobody is limited. Turning plans on applies each person's plan at once.",
      "Free",
    ],
    [
      "with no default",
      overview(),
      "Nobody is limited. Turning plans on applies each person's plan at once, and adds a plan named No limits as the default for everyone without a plan of their own.",
      "None yet",
    ],
  ])("says what turning plans on would do while off %s, with neutral facts", async (_state, plans, sentence, chosen) => {
    await renderPlans(testI18n(), { plans })
    expect(statusCard().querySelector("h3")?.textContent).toBe("Plans are off")
    expect(element("plans-status-sentence").textContent).toBe(sentence)
    expect(planSwitch().getAttribute("aria-checked")).toBe("false")
    expect(planSwitch().querySelector("[data-state-label='off']")?.textContent).toBe("Off")
    expect(facts().map(([label]) => label)).toEqual(["Would limit", "Would be over a limit", "Default plan"])
    expect(fact("default").textContent).toBe(chosen)
    expect(statusCard().querySelector("[data-tone='attention']")).toBeNull()
  })

  it("says Plans limit nobody while the default limits nothing", async () => {
    await renderPlans(testI18n(), { plans: overview({ enabled: true, defaultPlan: "no-limits", plans: [noLimits] }) })
    expect(fact("limited").textContent).toBe("Nobody")
  })

  it("shows who would be over a limit while off, neutral and without the icon, linking to them", async () => {
    await renderPlans(testI18n(), { plans: overview({ defaultPlan: "free", plans: [{ ...family, over_people: 2 }, free] }) })
    const show = fact("over").querySelector("a")!
    expect(show.textContent).toBe("2 people")
    expect(show.querySelector("svg[data-attention]")).toBeNull()
    expect(show.getAttribute("aria-label")).toBe("Show the 2 people who would be over a limit")
  })
})

describe("The Plans switch", () => {
  it("turns plans on with no default at once, showing the No limits plan the server made the default", async () => {
    const on = overview({ enabled: true, defaultPlan: "no-limits", plans: [family, free, noLimits] })
    await renderPlans(testI18n(), { answers: { "PUT /api/v1/plan-settings": jsonResponse(on) } })
    focus(planSwitch())
    await click(planSwitch())
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: true, default_plan: null })
    expect(toast()).toBe("Plans are on. No limits is the default plan, and it limits nobody.")
    expect(planSwitch().getAttribute("aria-checked")).toBe("true")
    expect(document.activeElement).toBe(planSwitch())
    expect(listed()).toEqual(["no-limits", "family", "free"])
    expect(cell("no-limits", "plan").textContent).toBe("No limitsDefault")
  })

  it("turns plans on with the default it has, says whom they limit, and Undo turns them off again", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ defaultPlan: "free" }),
      answers: { "PUT /api/v1/plan-settings": jsonResponse(overview({ enabled: true, defaultPlan: "free" })) },
    })
    await click(planSwitch())
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: true, default_plan: "free" })
    expect(toast()).toBe("Plans are on. They limit 5 people.")
    expect(statusCard().querySelector("h3")?.textContent).toBe("Plans are on")

    reply("PUT /api/v1/plan-settings", jsonResponse(overview({ defaultPlan: "free" })))
    await click(button("Undo", container))
    expect(sentAll("PUT", "/api/v1/plan-settings")).toEqual([
      { enabled: true, default_plan: "free" },
      { enabled: false, default_plan: "free" },
    ])
    expect(toast()).toBe("Plans are off. Nobody is limited.")
    expect(planSwitch().getAttribute("aria-checked")).toBe("false")

    // The next Undo is refused: it says why in a toast, where it was pressed, not under the switch.
    reply("PUT /api/v1/plan-settings", refusal(404, "plan_not_found"))
    await click(toastButton("Undo"))
    expect(toast()).toBe("This plan no longer exists. Reload to see the current plans.")
    expect(container.querySelector("#plans-switch-error")).toBeNull()
  })

  it("says what Undo did, with Undo again, and why that one could not, once the Plans tab is gone", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ defaultPlan: "free" }),
      answers: { "PUT /api/v1/plan-settings": jsonResponse(overview({ enabled: true, defaultPlan: "free" })) },
    })
    await click(planSwitch())
    await leavePlans()

    reply("PUT /api/v1/plan-settings", jsonResponse(overview({ defaultPlan: "free" })))
    await click(toastButton("Undo"))
    expect(sentAll("PUT", "/api/v1/plan-settings").at(-1)).toEqual({ enabled: false, default_plan: "free" })
    expect(toast()).toBe("Plans are off. Nobody is limited.")

    reply("PUT /api/v1/plan-settings", refusal(404, "plan_not_found"))
    await click(toastButton("Undo"))
    expect(sentAll("PUT", "/api/v1/plan-settings").at(-1)).toEqual({ enabled: true, default_plan: "free" })
    expect(toast()).toBe("This plan no longer exists. Reload to see the current plans.")
  })

  it("turns plans off with the default kept", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ enabled: true, defaultPlan: "free" }),
      answers: { "PUT /api/v1/plan-settings": jsonResponse(overview({ defaultPlan: "free" })) },
    })
    await click(planSwitch())
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: false, default_plan: "free" })
    expect(toast()).toBe("Plans are off. Nobody is limited.")
    expect(statusCard().querySelector("h3")?.textContent).toBe("Plans are off")
  })

  it("keeps the switch focused and showing what was asked while it is on its way, ignoring another press", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ defaultPlan: "free" }),
      answers: { "PUT /api/v1/plan-settings": new Promise<Response>(() => undefined) },
    })
    const toggle = planSwitch()
    focus(toggle)
    await click(toggle)
    expect(toggle.getAttribute("aria-checked")).toBe("true")
    expect(toggle.disabled).toBe(false)
    expect(toggle.getAttribute("aria-disabled")).toBe("true")
    expect(document.activeElement).toBe(toggle)
    await click(toggle)
    expect(calls.filter((call) => call.method === "PUT").length).toBe(1)
  })

  it("says why turning plans on was refused under the switch, and moves focus to it", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ defaultPlan: "free" }),
      answers: { "PUT /api/v1/plan-settings": refusal(404, "plan_not_found") },
    })
    await click(planSwitch())
    const error = element("plans-switch-error")
    expect(error.textContent).toBe("This plan no longer exists. Reload to see the current plans.")
    expect(error.getAttribute("role")).toBe("alert")
    expect(planSwitch().getAttribute("aria-checked")).toBe("false")
    expect(planSwitch().getAttribute("aria-describedby")).toBe("plans-status-sentence plans-switch-error")
    expect(document.activeElement).toBe(planSwitch())
    expect(toast()).toBe("")
  })
})

describe("The catalog", () => {
  it("compares the plans by limit, the default first, with a column for each", async () => {
    const hourly: PlanSummary = { ...noLimits, key: "hourly", name: "Hourly", people: 0, limited_people: 0, limits: { ...noLimits.limits, sync_interval: "60_minutes" } }
    await renderPlans(testI18n(), { plans: overview({ enabled: true, defaultPlan: "free", plans: [family, free, hourly] }) })
    const catalog = element("plans-catalog")
    expect(catalog.querySelector("h3")?.textContent).toBe("3 plans")
    expect([...catalog.querySelectorAll("thead th")].map((heading) => heading.textContent)).toEqual([
      "Plan",
      "Active rules",
      "Calendar accounts",
      "Integration tokens",
      "Sync speed",
      "People",
      "Actions",
    ])
    expect(listed()).toEqual(["free", "family", "hourly"])
    expect(cells("free")).toEqual(["FreeDefault", "1", "1", "None", "Every 5 min", "2 people", ""])
    // Each plan's name heads its row, so a screen reader names the plan as it moves down a column.
    const heading = planRow("free").querySelector("th")!
    expect(heading.getAttribute("scope")).toBe("row")
    expect(heading.getAttribute("role")).toBe("rowheader")
    expect(heading.contains(nameLink("free"))).toBe(true)
    expect(planRow("free").querySelectorAll("th").length).toBe(1)
    expect(cells("family")).toEqual(["Family", "5", "3", "2", "Instant", "4 people", ""])
    expect(cells("hourly")).toEqual(["Hourly", "Unlimited", "Unlimited", "Unlimited", "Every hour", "Nobody", ""])
    // A limit is ink, None too, since it is a limit of zero; no limit is muted, as Nobody is.
    expect(cell("free", "tokens").hasAttribute("data-muted")).toBe(false)
    expect(cell("free", "rules").hasAttribute("data-muted")).toBe(false)
    expect(cell("hourly", "rules").getAttribute("data-muted")).toBe("true")
    expect(cell("hourly", "people").querySelector(".plan-nobody")).not.toBeNull()
    expect(cell("family", "speed").querySelector("svg[aria-hidden='true']")).not.toBeNull()
    expect(cell("family", "rules").getAttribute("data-label")).toBe("Active rules")
    expect(catalog.querySelector(".plans-catalog-note")?.textContent).toBe(
      "People counts include administrators, who are never limited. Paused rules and drafts are not active.",
    )
  })

  it("opens a plan from anywhere on its row, as Activity's rows do, leaving its links and menu to themselves", async () => {
    await renderPlans(testI18n(), { plans: overview({ enabled: true, defaultPlan: "free" }) })
    await click(cell("family", "rules"))
    expect(here()).toBe("/people/plans/family")
    expect(panelTitle().textContent).toBe("Family")
    expect(document.activeElement).toBe(panelTitle())
    // Beside the panel, another row opens its own plan in place of the open one.
    await click(cell("free", "speed"))
    expect(here()).toBe("/people/plans/free")
    expect(panelTitle().textContent).toBe("Free")

    await click(closeButton())
    await openMenu("family")
    await click(planRow("family").querySelector<HTMLElement>("[role='menu']")!)
    expect(panelOrNull()).toBeNull()
    expect(here()).toBe("/people/plans")
    await click(cell("family", "people").querySelector("a")!)
    expect(here()).toBe("/people?plan=family")
    expect(panelOrNull()).toBeNull()
  })

  it("links who has a plan to Everyone, filtered by it, from the list's heading", async () => {
    await renderPlans(testI18n(), { plans: overview({ defaultPlan: "free" }) })
    const people = cell("family", "people").querySelector("a")!
    expect(people.textContent).toBe("4 people")
    expect(people.getAttribute("href")).toBe("/people?plan=family")
    expect(people.getAttribute("aria-label")).toBe("Show the 4 people who have Family")
    await click(people)
    expect(`${window.location.pathname}${window.location.search}`).toBe("/people?plan=family")
    expect(container.querySelector("nav.page-tabs [aria-current='page']")?.textContent).toBe("Everyone")
    expect(container.querySelector<HTMLSelectElement>("#people-plan")?.value).toBe("family")
    expect(document.activeElement).toBe(element("people-list-title"))
  })

  it("marks how many on a plan are over a limit, in Attention Ochre with an icon, linking to them", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ enabled: true, defaultPlan: "free", plans: [{ ...family, over_people: 1 }, free] }),
    })
    const chip = cell("family", "people").querySelector<HTMLAnchorElement>("a.plan-over")!
    expect(chip.textContent).toBe("1 over a limit")
    expect(chip.getAttribute("data-tone")).toBe("attention")
    expect(chip.querySelector("svg[aria-hidden='true']")).not.toBeNull()
    expect(chip.getAttribute("href")).toBe("/people?plan=family&over=true")
    expect(chip.getAttribute("aria-label")).toBe("1 over a limit on Family")
    expect(chip.getAttribute("aria-label")).toContain(chip.textContent)
    expect(cell("free", "people").querySelector(".plan-over")).toBeNull()

    await click(chip)
    expect(`${window.location.pathname}${window.location.search}`).toBe("/people?plan=family&over=true")
    expect(container.querySelector<HTMLSelectElement>("#people-limits")?.value).toBe("over")
  })

  it("says how many would be over, neutral and without the icon, while plans are off", async () => {
    await renderPlans(testI18n(), { plans: overview({ defaultPlan: "free", plans: [{ ...family, over_people: 2 }, free] }) })
    const chip = cell("family", "people").querySelector<HTMLAnchorElement>("a.plan-over")!
    expect(chip.textContent).toBe("2 would be over")
    expect(chip.hasAttribute("data-tone")).toBe(false)
    expect(chip.querySelector("svg")).toBeNull()
    expect(chip.getAttribute("aria-label")).toBe("2 would be over on Family")
    expect(chip.getAttribute("aria-label")).toContain(chip.textContent)
  })
})

describe("A plan's row menu", () => {
  it("offers Edit, Assign people, Make default with whom it moves, Duplicate, and Remove with why it waits", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ defaultPlan: "free" }),
      answers: { "GET /api/v1/users": jsonResponse(holders(["robin@example.test", "sam@example.test"], 4)) },
    })
    expect(menuTrigger("family").getAttribute("aria-label")).toBe("More actions for Family")
    await openMenu("family")
    expect(menuItems("family")).toEqual([
      ["Edit", null],
      ["Assign people", null],
      ["Make default", "People without a plan of their own (3 now) move to Family."],
      ["Duplicate", null],
      ["Remove", "robin@example.test, sam@example.test, and 2 more have Family. Give them another plan first."],
    ])
    expect(menuItem("family", "Remove").getAttribute("aria-disabled")).toBe("true")
    // A divider, a separator to assistive technology, sets Remove apart.
    expect(menuItem("family", "Remove").previousElementSibling?.tagName).toBe("HR")
    // The first three by email, from everyone who has the plan, as People counts them, once the menu opens.
    const asked = calls.filter((call) => call.method === "GET" && call.path === "/api/v1/users")
    expect(asked.map((call) => Object.fromEntries(call.query))).toEqual([
      { plan: "family", sort: "email", order: "asc", page: "1", page_size: "3" },
    ])
  })

  it("counts who has a plan while their names load, or when they cannot", async () => {
    let answer: (response: Response) => void = () => undefined
    const held = new Promise<Response>((resolve) => {
      answer = resolve
    })
    await renderPlans(testI18n(), { answers: { "GET /api/v1/users": held } })
    await openMenu("family")
    expect(menuItems("family").at(-1)).toEqual(["Remove", "4 people have Family. Give them another plan first."])
    await act(async () => {
      answer(jsonResponse({ detail: "boom" }, 500))
      await Promise.resolve()
    })
    await settle()
    expect(menuItems("family").at(-1)).toEqual(["Remove", "4 people have Family. Give them another plan first."])
  })

  it("offers no Make default on the default, whose Remove says to make another plan the default first", async () => {
    await renderPlans(testI18n(), { plans: overview({ defaultPlan: "free" }) })
    await openMenu("free")
    expect(menuItems("free")).toEqual([
      ["Edit", null],
      ["Assign people", null],
      ["Duplicate", null],
      ["Remove", "Make another plan the default first."],
    ])
    expect(menuItem("free", "Remove").getAttribute("aria-disabled")).toBe("true")
    await click(menuItem("free", "Remove"))
    expect(detailsOf("free")).toBeNull()
    expect(calls.some((call) => call.method === "DELETE")).toBe(false)
  })

  it("makes a plan the default at once, says so, and Undo gives the default back", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ enabled: true, defaultPlan: "free" }),
      answers: { "PUT /api/v1/plan-settings": jsonResponse(overview({ enabled: true, defaultPlan: "family" })) },
    })
    await chooseFromMenu("family", "Make default")
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: true, default_plan: "family" })
    expect(toast()).toBe("Family is the default plan now.")
    expect(listed()).toEqual(["family", "free"])
    expect(cell("family", "plan").textContent).toBe("FamilyDefault")
    expect(document.activeElement).toBe(menuTrigger("family"))

    reply("PUT /api/v1/plan-settings", jsonResponse(overview({ enabled: true, defaultPlan: "free" })))
    await click(button("Undo", container))
    expect(sentAll("PUT", "/api/v1/plan-settings").at(-1)).toEqual({ enabled: true, default_plan: "free" })
    expect(toast()).toBe("Free is the default plan now.")
    expect(listed()).toEqual(["free", "family"])

    // The next Undo is refused: it says why in a toast, not on the plan's row.
    reply("PUT /api/v1/plan-settings", refusal(404, "plan_not_found"))
    await click(toastButton("Undo"))
    expect(toast()).toBe("This plan no longer exists. Reload to see the current plans.")
    expect(detailsOf("family")).toBeNull()
  })

  it("says Make default moves nobody now when everyone has a plan of their own", async () => {
    await renderPlans(testI18n(), { plans: overview({ defaultPlan: "free", followers: 0 }) })
    await openMenu("family")
    // Free's 2 people were given it as their own plan, so they keep it.
    expect(menuItems("family")[2]).toEqual([
      "Make default",
      "Everyone has a plan of their own now. People who join later get Family. 2 people keep Free, which was given to them.",
    ])
  })

  it("says why making a plan the default was refused on its row", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ defaultPlan: "free" }),
      answers: { "PUT /api/v1/plan-settings": refusal(404, "plan_not_found") },
    })
    await chooseFromMenu("family", "Make default")
    const alert = detailsOf("family")?.querySelector("[role='alert']")
    expect(alert?.textContent).toBe("This plan no longer exists. Reload to see the current plans.")
    expect(container.querySelector("#plans-switch-error")).toBeNull()
    expect(toast()).toBe("")
  })

  it("asks on the row before removing a plan nobody has, and says once it is removed", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ plans: [{ ...family, people: 0, limited_people: 0 }, free] }),
      answers: { "DELETE /api/v1/plans/family": NO_CONTENT },
    })
    await openMenu("family")
    expect(menuItems("family").at(-1)).toEqual(["Remove", null])
    expect(menuItem("family", "Remove").hasAttribute("aria-disabled")).toBe(false)
    await click(menuItem("family", "Remove"))
    const confirmation = element("plan-remove-family")
    expect(detailsOf("family")?.contains(confirmation)).toBe(true)
    expect(confirmation.querySelector("h3")?.textContent).toBe("Remove Family?")
    expect(document.activeElement).toBe(confirmation.querySelector("h3"))
    expect(confirmation.querySelector("p")?.textContent).toBe(
      "Nobody has this plan, so removing it changes nothing for anyone. You can't undo this.",
    )
    await click(button("Keep plan", confirmation))
    expect(container.querySelector("#plan-remove-family")).toBeNull()
    expect(sent("DELETE", "/api/v1/plans/family")).toBeUndefined()
    expect(document.activeElement).toBe(menuTrigger("family"))

    await chooseFromMenu("family", "Remove")
    reply("GET /api/v1/plans", jsonResponse(overview({ plans: [free] })))
    await click(button("Remove plan", element("plan-remove-family")))
    expect(calls.some((call) => call.method === "DELETE" && call.path === "/api/v1/plans/family")).toBe(true)
    expect(toast()).toBe("Family was removed.")
    expect(listed()).toEqual(["free"])
    expect(document.activeElement).toBe(button("New plan", catalogHead()))
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
    await chooseFromMenu("family", "Remove")
    const confirmation = element("plan-remove-family")
    const confirm = button("Remove plan", confirmation)
    const keep = button("Keep plan", confirmation)
    focus(confirm)
    await click(confirm)
    for (const waiting of [confirm, keep]) {
      expect(waiting.disabled).toBe(false)
      expect(waiting.getAttribute("aria-disabled")).toBe("true")
    }
    expect(document.activeElement).toBe(confirm)
    await click(keep)
    expect(element("plan-remove-family")).toBe(confirmation)

    // Someone was given the plan meanwhile.
    await act(async () => {
      answer(refusal(409, "plan_in_use", { people: 1, count: 1 }))
      await Promise.resolve()
    })
    await settle()
    expect(detailsOf("family")?.querySelector("[role='alert']")?.textContent).toBe(
      "1 person has this plan. Give them another plan before you remove it.",
    )
    expect(document.activeElement).toBe(confirm)
    expect(confirm.getAttribute("aria-disabled")).toBeNull()
  })
})


describe("A refused removal", () => {
  it("reads the plans again, so the row and its menu say who has the plan now, in place of a confirmation that no longer holds", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ plans: [{ ...family, people: 0, limited_people: 0 }, free] }),
      answers: { "DELETE /api/v1/plans/family": refusal(409, "plan_in_use", { people: 1, count: 1 }) },
    })
    await chooseFromMenu("family", "Remove")
    const confirm = button("Remove plan", element("plan-remove-family"))
    focus(confirm)
    const read = calls.filter((call) => call.method === "GET" && call.path === "/api/v1/plans").length
    // Someone was given the plan meanwhile, in another tab.
    reply("GET /api/v1/plans", jsonResponse(overview({ plans: [{ ...family, people: 1, limited_people: 1 }, free] })))
    await click(confirm)
    expect(calls.filter((call) => call.method === "GET" && call.path === "/api/v1/plans").length).toBeGreaterThan(read)
    expect(cell("family", "people").textContent).toBe("1 person")
    expect(container.querySelector("#plan-remove-family")).toBeNull()
    expect(detailsOf("family")?.querySelector("[role='alert']")?.textContent).toBe(
      "1 person has this plan. Give them another plan before you remove it.",
    )
    expect(planRow("family").hasAttribute("data-open")).toBe(false)
    expect(document.activeElement).toBe(menuTrigger("family"))
    await openMenu("family")
    expect(menuItem("family", "Remove").getAttribute("aria-disabled")).toBe("true")
  })
})

describe("A plan's panel", () => {
  it("opens over an unchanged catalog at the plan's address with focus on its title", async () => {
    await renderPlans(testI18n(), { plans: overview({ enabled: true, defaultPlan: "free" }) })
    const originalHeadings = headings()
    const originalFacts = facts()
    const originalSentence = element("plans-status-sentence").textContent
    const originalNote = element("plans-catalog").querySelector(".plans-catalog-note")?.textContent
    const name = nameLink("family")
    expect(name.getAttribute("href")).toBe("/people/plans/family")
    expect(name.textContent).toBe("Family")
    expect(name.hasAttribute("aria-current")).toBe(false)
    await click(name)

    expect(here()).toBe("/people/plans/family")
    expect(panel().tagName).toBe("ASIDE")
    expect(panel().getAttribute("aria-labelledby")).toBe("plan-panel-title")
    expect(panel().querySelector(".plan-panel-label")?.textContent).toBe("Plan")
    expect(closeButton().getAttribute("aria-label")).toBe("Close")
    expect(panelTitle().textContent).toBe("Family")
    expect(document.activeElement).toBe(panelTitle())
    expect(panel().querySelector(".plan-panel-meta")?.textContent).toBe(
      "4 people have Family. 5 active rules, 3 calendar accounts, 2 integration tokens, with Instant sync.",
    )
    expect(panelTabs()).toEqual([
      ["Limits", "/people/plans/family", "page"],
      ["People44 have it", "/people/plans/family/people", null],
    ])
    expect(panel().querySelector("nav.page-tabs")?.getAttribute("aria-label")).toBe("Family")

    // Opening a drawer preserves the summary and every table column.
    expect(statusCard().querySelector("h3")?.textContent).toBe("Plans are on")
    expect(element("plans-status-sentence").textContent).toBe(originalSentence)
    expect(facts()).toEqual(originalFacts)
    // The catalog marks the open Plan without removing comparison data.
    expect(headings()).toEqual(originalHeadings)
    expect(element("plans-catalog").querySelector(".plans-catalog-note")?.textContent).toBe(
      originalNote,
    )
    expect(planRow("family").getAttribute("data-selected")).toBe("true")
    expect(nameLink("family").getAttribute("aria-current")).toBe("page")
    expect(planRow("free").hasAttribute("data-selected")).toBe(false)
    expect(container.querySelector("[aria-haspopup='menu']")).not.toBeNull()
    // The panel's footer holds the one primary action, so New plan turns outline.
    expect(button("New plan", catalogHead()).className).not.toContain("bg-primary")
  })

  it.each([
    ["Close", () => closeButton()],
    ["Cancel", () => button("Cancel", panel())],
  ])("closes with %s, back at the plans' address with focus on the plan's name", async (_how, control) => {
    await renderPlans(testI18n())
    await click(nameLink("family"))
    await click(control())
    expect(panelOrNull()).toBeNull()
    expect(here()).toBe("/people/plans")
    expect(document.activeElement).toBe(nameLink("family"))
    expect(headings()).toHaveLength(7)
    expect(facts().map(([label]) => label)).toEqual(["Would limit", "Would be over a limit", "Default plan"])
  })

  it("returns the page to where it was before the panel opened once Close closes it", async () => {
    await renderPlans(testI18n())
    window.scrollTo(0, 120)
    await click(nameLink("family"))
    // Scrolled meanwhile, as to reach the panel's footer.
    window.scrollTo(0, 400)
    await click(closeButton())
    expect(window.scrollY).toBe(120)
    expect(document.activeElement).toBe(nameLink("family"))
  })

  it("returns the page to where it was before the panel opened once a save closes it", async () => {
    const saved: PlanSummary = { ...family, name: "Family Large" }
    await renderPlans(testI18n(), { answers: { "PUT /api/v1/plans/family": jsonResponse(saved) } })
    window.scrollTo(0, 0)
    await click(nameLink("family"))
    window.scrollTo(0, 160)
    type(field("plan-edit-family-name"), "Family Large")
    await settle()
    reply("GET /api/v1/plans", jsonResponse(overview({ plans: [saved, free] })))
    await submit(field("plan-edit-family-name").closest("form")!)
    expect(panelOrNull()).toBeNull()
    expect(window.scrollY).toBe(0)
  })

  it("opens as a modal drawer and locks background scrolling until it closes", async () => {
    await renderPlans(testI18n())
    await click(nameLink("family"))
    const drawer = panel().closest("dialog")!
    expect(drawer.open).toBe(true)
    expect(drawer.getAttribute("aria-labelledby")).toBe("plan-panel-title")
    expect(document.body.style.overflow).toBe("hidden")
    await click(closeButton())
    expect(document.body.style.overflow).not.toBe("hidden")
  })

  it("closes with Escape from anywhere in it", async () => {
    await renderPlans(testI18n())
    await click(nameLink("free"))
    await escape(field("plan-edit-free-name"))
    expect(panelOrNull()).toBeNull()
    expect(here()).toBe("/people/plans")
    expect(document.activeElement).toBe(nameLink("free"))
  })

  it("brings its title into view as it takes focus, as when it takes the catalog's place on a narrow screen", async () => {
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined)
    await renderPlans(testI18n())
    await click(nameLink("family"))
    expect(document.activeElement).toBe(panelTitle())
    expect(scrolled).toHaveBeenCalledOnce()
    expect(scrolled.mock.contexts[0]).toBe(panelTitle())
    expect(scrolled.mock.calls[0]).toEqual([{ block: "nearest" }])
  })

  it.each([
    ["on arrival, with focus inside the modal", false],
    ["with focus on its title when the app opens it from elsewhere, as a toast's next step does", true],
  ])("opens at its own address, at the tab it names, %s", async (_how, panelFocus) => {
    page().happyDOM.setURL(`${ORIGIN}/people/plans/free/people`)
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined)
    await renderPlans(
      testI18n(),
      { answers: { "GET /api/v1/users": jsonResponse(candidates([ALEX])), "POST /api/v1/plan-assignments": DRY_RUN } },
      { panelFocus },
    )
    expect(panelTitle().textContent).toBe("Free")
    expect(panelTabs().map(([label, , current]) => [label, current])).toEqual([
      ["Limits", null],
      ["People22 have it", "page"],
    ])
    expect(panel().contains(assignOf("free"))).toBe(true)
    expect(document.activeElement).toBe(panelTitle())
    expect(scrolled.mock.contexts).toEqual(panelFocus ? [panelTitle()] : [])
  })

  it("switches between Limits and People at their own addresses, keeping focus on the tab", async () => {
    await renderPlans(testI18n(), {
      answers: { "GET /api/v1/users": jsonResponse(candidates([ALEX])), "POST /api/v1/plan-assignments": DRY_RUN },
    })
    await click(nameLink("free"))
    const people = panelTab("People")
    focus(people)
    await click(people)
    expect(here()).toBe("/people/plans/free/people")
    expect(panel().contains(assignOf("free"))).toBe(true)
    expect(container.querySelector("#plan-edit-free-name")).toBeNull()
    expect(document.activeElement).toBe(people)
    // The plan's name in the catalog opens its Limits, with focus on the panel's title.
    await click(nameLink("free"))
    expect(here()).toBe("/people/plans/free")
    expect(document.activeElement).toBe(panelTitle())
    await click(panelTab("People"))
    await click(panelTab("Limits"))
    expect(here()).toBe("/people/plans/free")
    expect(field("plan-edit-free-name").value).toBe("Free")
  })

  it("opens another plan in place of the open one", async () => {
    await renderPlans(testI18n())
    await click(nameLink("family"))
    await click(nameLink("free"))
    expect(here()).toBe("/people/plans/free")
    expect(panelTitle().textContent).toBe("Free")
    expect(document.activeElement).toBe(panelTitle())
    expect(panel().querySelector(".plan-panel-meta")?.textContent).toBe(
      "2 people have Free. 1 active rule, 1 calendar account, no integration tokens, every 5 minutes.",
    )
  })

  it("says a plan nobody has, and one with no limits, in as few words", async () => {
    const spare: PlanSummary = { ...noLimits, key: "spare", name: "Spare", people: 0, limited_people: 0 }
    await renderPlans(testI18n(), { plans: overview({ plans: [family, spare] }) })
    await click(nameLink("spare"))
    expect(panel().querySelector(".plan-panel-meta")?.textContent).toBe("Nobody has Spare yet. Unlimited, with Instant sync.")
    expect(panelTabs()[1]?.[0]).toBe("People")
  })

  it("says when no plan has its address, and still closes", async () => {
    page().happyDOM.setURL(`${ORIGIN}/people/plans/gone`)
    await renderPlans(testI18n())
    expect(panelTitle().textContent).toBe("Plan not found")
    expect(panel().querySelector("[role='status']")?.textContent).toBe(
      "No plan has this address. It may have been removed.",
    )
    expect(panel().querySelector("nav.page-tabs")).toBeNull()
    await click(closeButton())
    expect(here()).toBe("/people/plans")
    expect(panelOrNull()).toBeNull()
  })

  it("adds a history entry to open a panel and to close it, and replaces it to open another, as Activity does", async () => {
    await renderPlans(testI18n(), {
      answers: { "GET /api/v1/users": jsonResponse(candidates([ALEX])), "POST /api/v1/plan-assignments": DRY_RUN },
    })
    const before = window.history.length
    await click(nameLink("family"))
    await click(nameLink("free"))
    expect(window.history.length).toBe(before + 1)
    await click(panelTab("People"))
    expect(window.history.length).toBe(before + 2)
    await click(closeButton())
    expect(window.history.length).toBe(before + 3)
    expect(here()).toBe("/people/plans")
  })
})

describe("Leaving a plan's changes not saved", () => {
  /** The panel footer's question before its changes are dropped, while it asks. */
  function question(): HTMLElement | null {
    return panel().querySelector<HTMLElement>(".plan-panel-question")
  }

  it("asks before Escape drops them, keeps them on Keep editing, and closes on Discard", async () => {
    await renderPlans(testI18n())
    await click(nameLink("family"))
    type(field("plan-edit-family-rules"), "2")
    await settle()
    focus(field("plan-edit-family-rules"))
    await escape(field("plan-edit-family-rules"))
    expect(here()).toBe("/people/plans/family")
    expect(question()?.querySelector("p")?.textContent).toBe("Discard 1 change?")
    expect(document.activeElement).toBe(button("Keep editing", panel()))

    await click(button("Keep editing", panel()))
    expect(question()).toBeNull()
    expect(field("plan-edit-family-rules").value).toBe("2")
    expect(document.activeElement).toBe(field("plan-edit-family-rules"))

    await click(closeButton())
    expect(question()).not.toBeNull()
    await click(button("Discard", panel()))
    expect(panelOrNull()).toBeNull()
    expect(here()).toBe("/people/plans")
    expect(document.activeElement).toBe(nameLink("family"))
    expect(calls.some((call) => call.method !== "GET")).toBe(false)

    // Opened again, the plan shows what it has saved, and closes at once.
    await click(nameLink("family"))
    expect(field("plan-edit-family-rules").value).toBe("5")
    await escape(field("plan-edit-family-rules"))
    expect(panelOrNull()).toBeNull()
  })

  it("asks before another plan, or the panel's People tab, takes the place of the changes", async () => {
    await renderPlans(testI18n(), {
      answers: { "GET /api/v1/users": jsonResponse(candidates([ALEX])), "POST /api/v1/plan-assignments": DRY_RUN },
    })
    await click(nameLink("family"))
    type(field("plan-edit-family-name"), "Family Large")
    await settle()

    await click(nameLink("free"))
    expect(here()).toBe("/people/plans/family")
    expect(panelTitle().textContent).toBe("Family")
    expect(question()).not.toBeNull()
    await click(button("Keep editing", panel()))

    await click(panelTab("People"))
    expect(here()).toBe("/people/plans/family")
    expect(field("plan-edit-family-name").value).toBe("Family Large")
    await click(button("Keep editing", panel()))

    await click(nameLink("free"))
    await click(button("Discard", panel()))
    expect(here()).toBe("/people/plans/free")
    expect(panelTitle().textContent).toBe("Free")
    expect(document.activeElement).toBe(panelTitle())
    expect(question()).toBeNull()
  })

  it("asks before People's other tabs, or a link to Everyone, leave a new plan", async () => {
    await renderPlans(testI18n(), { plans: overview({ enabled: true, defaultPlan: "free" }) })
    await click(button("New plan", catalogHead()))
    type(field("plan-new-name"), "Team")
    await settle()

    const everyone = [...container.querySelectorAll<HTMLAnchorElement>("nav.page-tabs a")].find((tab) => tab.textContent === "Everyone")!
    await click(everyone)
    expect(here()).toBe("/people/plans/new")
    expect(question()).not.toBeNull()
    await click(button("Keep editing", panel()))

    await click(cell("family", "people").querySelector("a")!)
    expect(here()).toBe("/people/plans/new")
    await click(button("Discard", panel()))
    expect(here()).toBe("/people?plan=family")
    expect(container.querySelector("nav.page-tabs [aria-current='page']")?.textContent).toBe("Everyone")
  })
})

describe("Editing a plan", () => {
  it("edits in the panel without its key, warns before lowering a limit, and closes once saved, back on its row", async () => {
    const saved: PlanSummary = { ...family, name: "Family Large", limits: { ...family.limits, rules: 2 } }
    await renderPlans(testI18n(), {
      plans: overview({ enabled: true, defaultPlan: "free" }),
      answers: { "PUT /api/v1/plans/family": jsonResponse(saved) },
    })
    await click(nameLink("family"))
    const entries = window.history.length
    expect(field("plan-edit-family-name").value).toBe("Family")

    type(field("plan-edit-family-rules"), "2")
    await settle()
    expect(element("plan-edit-family-rules-warning").textContent).toBe(
      "1 person on Family has more active rules than this. Their rules keep syncing, but they can't start another.",
    )
    type(field("plan-edit-family-name"), "Family Large")
    await settle()
    expect(panel().querySelector(".plan-panel-changes")?.textContent).toBe("2 changes not saved")
    reply("GET /api/v1/plans", jsonResponse(overview({ enabled: true, defaultPlan: "free", plans: [saved, free] })))
    const save = button("Save plan", panel())
    focus(save)
    await submit(field("plan-edit-family-name").closest("form")!)
    expect(sent("PUT", "/api/v1/plans/family")).toEqual({
      name: "Family Large",
      limits: { rules: 2, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" },
    })
    expect(toast()).toBe("Family Large was saved.")
    // Saved, nothing is left to discard: the panel closes without asking, in place of its address.
    expect(panelOrNull()).toBeNull()
    expect(here()).toBe("/people/plans")
    expect(window.history.length).toBe(entries)
    expect(nameLink("family").textContent).toBe("Family Large")
    expect(document.activeElement).toBe(nameLink("family"))
    expect(headings()).toHaveLength(7)
  })

  it("still asks before closing changes a refused save kept", async () => {
    await renderPlans(testI18n(), {
      answers: { "PUT /api/v1/plans/family": refusal(422, "invalid_plan", { reason: "name" }) },
    })
    await click(nameLink("family"))
    type(field("plan-edit-family-name"), "Family Large")
    await submit(field("plan-edit-family-name").closest("form")!)
    expect(panel().querySelector("[role='alert']")).not.toBeNull()
    await click(closeButton())
    expect(here()).toBe("/people/plans/family")
    expect(panel().querySelector(".plan-panel-question p")?.textContent).toBe("Discard 1 change?")
    expect(toast()).toBe("")
  })

  it("opens the same panel from Edit in the row menu, and closes it on Cancel, sending nothing", async () => {
    await renderPlans(testI18n())
    await chooseFromMenu("family", "Edit")
    expect(here()).toBe("/people/plans/family")
    expect(document.activeElement).toBe(panelTitle())
    await click(button("Cancel", panel()))
    expect(panelOrNull()).toBeNull()
    expect(calls.some((call) => call.method !== "GET")).toBe(false)
    expect(document.activeElement).toBe(nameLink("family"))
  })

  it("lets a plan keep its own name, and refuses another plan's before sending it", async () => {
    await renderPlans(testI18n(), {
      answers: { "PUT /api/v1/plans/family": jsonResponse({ ...family, name: "FAMILY" }) },
    })
    await click(nameLink("family"))
    type(field("plan-edit-family-name"), "free")
    await submit(field("plan-edit-family-name").closest("form")!)
    expect(sent("PUT", "/api/v1/plans/family")).toBeUndefined()
    expect(panel().querySelector("[role='alert']")?.textContent).toBe("Another plan is named Free. Choose a different name.")
    expect(document.activeElement).toBe(field("plan-edit-family-name"))
    type(field("plan-edit-family-name"), "FAMILY")
    await submit(field("plan-edit-family-name").closest("form")!)
    expect(sent("PUT", "/api/v1/plans/family")).toMatchObject({ name: "FAMILY" })
  })

  it("gives every field an id of its own, even in a plan keyed as a field is named", async () => {
    const named: PlanSummary = { ...free, key: "name", name: "Name" }
    await renderPlans(testI18n(), { plans: overview({ plans: [named, { ...free, key: "rules", name: "Rules" }] }) })
    await click(nameLink("name"))
    const ids = [...container.querySelectorAll("[id]")].map((node) => node.id)
    expect(ids.filter((id, index) => ids.indexOf(id) !== index)).toEqual([])
    const label = [...panel().querySelectorAll("label")].find((one) => one.textContent === "Name")!
    expect((document.getElementById(label.htmlFor) as HTMLInputElement).value).toBe("Name")
  })

  it("keeps a save on its way, and then its refusal, while the other plan commands wait", async () => {
    let answer: (response: Response) => void = () => undefined
    const held = new Promise<Response>((resolve) => {
      answer = resolve
    })
    await renderPlans(testI18n(), { answers: { "PUT /api/v1/plans/family": held } })
    await click(nameLink("family"))
    type(field("plan-edit-family-name"), "Family Large")
    await submit(field("plan-edit-family-name").closest("form")!)
    for (const waiting of [button("Save plan", panel()), button("Cancel", panel()), closeButton()]) {
      expect(waiting.disabled).toBe(false)
      expect(waiting.getAttribute("aria-disabled")).toBe("true")
    }
    for (const waiting of [nameLink("free"), button("New plan", catalogHead()), panelTab("People")]) {
      expect(waiting.getAttribute("aria-disabled")).toBe("true")
    }

    // Another plan, New plan, another tab, Close, and Escape change nothing while the save is on its way.
    await click(nameLink("free"))
    await click(button("New plan", catalogHead()))
    await click(panelTab("People"))
    await click(closeButton())
    await escape(field("plan-edit-family-name"))
    expect(here()).toBe("/people/plans/family")
    expect(panelTitle().textContent).toBe("Family")

    await act(async () => {
      answer(refusal(422, "invalid_plan", { reason: "name" }))
      await Promise.resolve()
    })
    await settle()
    expect(panel().querySelector("[role='alert']")?.textContent).toBe(
      "Give the plan a name of 1 to 60 characters, without line breaks or other control characters.",
    )
    expect(document.activeElement).toBe(field("plan-edit-family-name"))
    expect(nameLink("free").hasAttribute("aria-disabled")).toBe(false)
  })

  it("says what a lower limit will do once plans are on, while they are off", async () => {
    await renderPlans(testI18n(), { plans: overview({ defaultPlan: "free" }) })
    await click(nameLink("family"))
    type(field("plan-edit-family-rules"), "2")
    await settle()
    expect(element("plan-edit-family-rules-warning").textContent).toBe(
      "1 person on Family has more active rules than this. Once plans are on, their rules keep syncing, but they can't start another.",
    )
  })
})

describe("A new plan", () => {
  const added: PlanSummary = {
    key: "family-2",
    name: "Family Plus",
    limits: { rules: 8, connected_accounts: null, integration_tokens: 0, sync_interval: "5_minutes" },
    is_default: false,
    people: 0,
    limited_people: 0,
    over_people: 0,
    use: NO_USE,
  }

  it("adds a plan from New plan in the panel, without a key, then closes it with focus on the new plan's name", async () => {
    await renderPlans(testI18n(), { answers: { "POST /api/v1/plans": jsonResponse(added, 201) } })
    const open = button("New plan", catalogHead())
    expect(open.className).toContain("bg-primary")
    await click(open)
    const entries = window.history.length
    expect(here()).toBe("/people/plans/new")
    expect(panelTitle().textContent).toBe("New plan")
    expect(document.activeElement).toBe(panelTitle())
    expect(panel().querySelector("nav.page-tabs")).toBeNull()
    expect(panel().querySelector(".plan-panel-meta")).toBeNull()
    expect(open.className).not.toContain("bg-primary")

    type(field("plan-new-name"), " Family Plus ")
    await click(limitOption("plan-new-rules", "Up to"))
    type(field("plan-new-rules"), "8")
    await click(limitOption("plan-new-tokens", "None"))
    await click(speedRadio("5_minutes"))
    reply("GET /api/v1/plans", jsonResponse(overview({ plans: [family, added, free] })))
    await submit(field("plan-new-name").closest("form")!)

    expect(sent("POST", "/api/v1/plans")).toStrictEqual({
      name: "Family Plus",
      limits: { rules: 8, connected_accounts: null, integration_tokens: 0, sync_interval: "5_minutes" },
    })
    expect(toast()).toBe("Family Plus was added.")
    expect(toastButton("Assign people")).not.toBeNull()
    // Added, nothing is left to discard: the panel closes without asking, and Back never
    // returns to an empty New plan, as the address is replaced.
    expect(panelOrNull()).toBeNull()
    expect(here()).toBe("/people/plans")
    expect(window.history.length).toBe(entries)
    expect(listed()).toEqual(["family", "family-2", "free"])
    expect(document.activeElement).toBe(nameLink("family-2"))
    expect(open.className).toContain("bg-primary")
  })

  it("opens the new plan's People tab from Assign people in its toast, with focus on the panel's title", async () => {
    await renderPlans(testI18n(), {
      answers: {
        "POST /api/v1/plans": jsonResponse(added, 201),
        "GET /api/v1/users": jsonResponse(candidates([ALEX])),
        "POST /api/v1/plan-assignments": DRY_RUN,
      },
    })
    await click(button("New plan", catalogHead()))
    type(field("plan-new-name"), "Family Plus")
    reply("GET /api/v1/plans", jsonResponse(overview({ plans: [family, added, free] })))
    await submit(field("plan-new-name").closest("form")!)
    const entries = window.history.length

    const assign = toastButton("Assign people")
    focus(assign)
    await click(assign)
    expect(here()).toBe("/people/plans/family-2/people")
    expect(window.history.length).toBe(entries + 1)
    expect(panelTitle().textContent).toBe("Family Plus")
    expect(panelTabs().map(([label, , current]) => [label, current])).toEqual([
      ["Limits", null],
      ["People", "page"],
    ])
    expect(panel().contains(assignOf("family-2"))).toBe(true)
    expect(document.activeElement).toBe(panelTitle())
    expect(toast()).toBe("")
    expect(openedPlans).toEqual([])
  })

  it("opens the new plan's People tab through the app once the Plans tab is gone", async () => {
    await renderPlans(testI18n(), { answers: { "POST /api/v1/plans": jsonResponse(added, 201) } })
    await click(button("New plan", catalogHead()))
    type(field("plan-new-name"), "Family Plus")
    reply("GET /api/v1/plans", jsonResponse(overview({ plans: [family, added, free] })))
    await submit(field("plan-new-name").closest("form")!)

    await leavePlans()
    await click(toastButton("Assign people"))
    expect(openedPlans).toEqual([{ plan: "family-2", tab: "people" }])
    expect(here()).toBe("/people")
  })

  it("returns focus to New plan when the new plan is not listed yet", async () => {
    await renderPlans(testI18n(), { answers: { "POST /api/v1/plans": jsonResponse(added, 201) } })
    await click(button("New plan", catalogHead()))
    type(field("plan-new-name"), "Family Plus")
    await submit(field("plan-new-name").closest("form")!)
    expect(toast()).toBe("Family Plus was added.")
    expect(panelOrNull()).toBeNull()
    expect(document.activeElement).toBe(button("New plan", catalogHead()))
  })

  it("adds the first plan from the empty state, which the catalog then replaces", async () => {
    const first: PlanSummary = { ...free, people: 0, limited_people: 0 }
    await renderPlans(testI18n(), {
      plans: overview({ plans: [] }),
      answers: { "POST /api/v1/plans": jsonResponse(first, 201) },
    })
    await click(button("New plan", element("plans-empty")))
    expect(here()).toBe("/people/plans/new")
    expect(element("plans-empty")).not.toBeNull()
    expect(element("plans-status-sentence").textContent).toContain("Everyone can use everything, with no limits.")
    expect(document.activeElement).toBe(panelTitle())
    type(field("plan-new-name"), "Free")
    reply("GET /api/v1/plans", jsonResponse(overview({ plans: [first] })))
    await submit(field("plan-new-name").closest("form")!)

    expect(toast()).toBe("Free was added.")
    expect(container.querySelector("#plans-empty")).toBeNull()
    expect(panelOrNull()).toBeNull()
    expect(listed()).toEqual(["free"])
    expect(cell("free", "people").textContent).toBe("Nobody")
    expect(here()).toBe("/people/plans")
    expect(document.activeElement).toBe(nameLink("free"))
  })

  it("closes the new plan's panel on Cancel, returning focus to New plan", async () => {
    await renderPlans(testI18n())
    await click(button("New plan", catalogHead()))
    await click(button("Cancel", panel()))
    expect(panelOrNull()).toBeNull()
    expect(here()).toBe("/people/plans")
    expect(document.activeElement).toBe(button("New plan", catalogHead()))
  })

  it("returns focus to New plan in the empty state once its panel closes", async () => {
    await renderPlans(testI18n(), { plans: overview({ plans: [] }) })
    await click(button("New plan", element("plans-empty")))
    await click(closeButton())
    expect(document.activeElement).toBe(button("New plan", element("plans-empty")))
  })

  it("keeps the new plan's panel open with the reason it was refused, under the field it names", async () => {
    await renderPlans(testI18n(), {
      answers: { "POST /api/v1/plans": refusal(422, "invalid_plan", { reason: "name" }) },
    })
    await click(button("New plan", catalogHead()))
    type(field("plan-new-name"), "Family Plus")
    await submit(field("plan-new-name").closest("form")!)
    expect(panel().querySelector("[role='alert']")?.textContent).toBe(
      "Give the plan a name of 1 to 60 characters, without line breaks or other control characters.",
    )
    expect(field("plan-new-name").getAttribute("aria-invalid")).toBe("true")
    expect(document.activeElement).toBe(field("plan-new-name"))
    expect(here()).toBe("/people/plans/new")
    expect(toast()).toBe("")
    // What was refused is still not saved, so closing asks first.
    await click(closeButton())
    expect(here()).toBe("/people/plans/new")
    expect(panel().querySelector(".plan-panel-question p")?.textContent).toBe("Discard 1 change?")
  })

  it("refuses a name another plan has before sending it, and shows the server's refusal the same way", async () => {
    await renderPlans(testI18n(), {
      answers: { "POST /api/v1/plans": refusal(409, "plan_name_taken", { name: "Family plus" }) },
    })
    await click(button("New plan", catalogHead()))
    type(field("plan-new-name"), " family ")
    await submit(field("plan-new-name").closest("form")!)
    expect(sent("POST", "/api/v1/plans")).toBeUndefined()
    expect(panel().querySelector("[role='alert']")?.textContent).toBe("Another plan is named Family. Choose a different name.")
    expect(document.activeElement).toBe(field("plan-new-name"))

    // Added meanwhile by someone else: the server refuses it the same way.
    type(field("plan-new-name"), "Family Plus")
    await submit(field("plan-new-name").closest("form")!)
    expect(sent("POST", "/api/v1/plans")).toMatchObject({ name: "Family Plus" })
    expect(panel().querySelector("[role='alert']")?.textContent).toBe(
      "Another plan is named Family plus. Choose a different name.",
    )
  })

  it("duplicates a plan as a new plan at its own address, with its limits and a name of its own, saved like any new plan", async () => {
    const copy: PlanSummary = { ...free, key: "free-copy", name: "Free copy", people: 0, limited_people: 0 }
    await renderPlans(testI18n(), { answers: { "POST /api/v1/plans": jsonResponse(copy, 201) } })
    await chooseFromMenu("free", "Duplicate")
    expect(here()).toBe("/people/plans/new?copy=free")
    expect(panelTitle().textContent).toBe("New plan")
    expect(document.activeElement).toBe(panelTitle())
    expect(panel().querySelector(".plan-panel-meta")?.textContent).toBe("Starts with the limits of Free.")
    expect(field("plan-new-name").value).toBe("Free copy")
    expect(limitOption("plan-new-tokens", "None").checked).toBe(true)
    reply("GET /api/v1/plans", jsonResponse(overview({ plans: [family, free, copy] })))
    await submit(field("plan-new-name").closest("form")!)
    expect(sent("POST", "/api/v1/plans")).toStrictEqual({ name: "Free copy", limits: free.limits })
    expect(toast()).toBe("Free copy was added.")
    expect(panelOrNull()).toBeNull()
    expect(here()).toBe("/people/plans")
    expect(document.activeElement).toBe(nameLink("free-copy"))
  })

  it("opens a duplicate from its address", async () => {
    page().happyDOM.setURL(`${ORIGIN}/people/plans/new?copy=family`)
    await renderPlans(testI18n())
    expect(panelTitle().textContent).toBe("New plan")
    expect(field("plan-new-name").value).toBe("Family copy")
    expect(field("plan-new-rules").value).toBe("5")
  })
})

/** Robin has Free, and 2 calendar accounts where Free allows 1. */
const ROBIN_OVER: PersonRow = {
  ...ROBIN,
  plan: { ...ROBIN.plan!, over: [{ limit: "connected_accounts", in_use: 2, allowed: 1 }] },
}
const JORDAN = candidate("jordan@example.test", { key: "free", name: "Free", on_default: false })

/** Who Assign people may list, and, asked by Free's key, who has Free now. */
function freeAndOthers(others: PersonRow[], holding: PersonRow[] = [ROBIN_OVER, JORDAN]) {
  return (call: Call) => jsonResponse(candidates(call.query.get("plan") === "free" ? holding : others))
}

/** Opens Free's Assign people, with Family the default, `others` to list, and `dryRun` as the dry run's answer. */
async function assignFree(
  others: PersonRow[],
  { holding, enabled = true, dryRun = DRY_RUN }: { holding?: PersonRow[]; enabled?: boolean; dryRun?: Response } = {},
) {
  await renderPlans(testI18n(), {
    plans: overview({ enabled, defaultPlan: "family" }),
    answers: { "GET /api/v1/users": freeAndOthers(others, holding), "POST /api/v1/plan-assignments": dryRun },
  })
  await chooseFromMenu("free", "Assign people")
}

describe("Assigning people from a plan", () => {
  it("lists who does not have the plan, with the plan each has and what they would be over, administrators last", async () => {
    await assignFree([ALEX, DANA, ROBIN, SAM])
    expect(here()).toBe("/people/plans/free/people")
    const assign = assignOf("free")
    expect(panel().contains(assign)).toBe(true)
    expect(document.activeElement).toBe(panelTitle())
    expect(assign.querySelector("h4")?.textContent).toBe("Assign people")
    expect(assign.querySelector(".plan-assign-intro")?.textContent).toBe(
      "They move to Free at once. Administrators are listed last; no plan limits them.",
    )
    // Everyone by email, from one page of 100, and a dry run for everyone a plan could limit.
    const asked = calls.filter((call) => call.method === "GET" && call.path === "/api/v1/users" && !call.query.has("plan"))
    expect(Object.fromEntries(asked.at(-1)!.query)).toEqual({ sort: "email", order: "asc", page: "1", page_size: "100" })
    expect(assignCalls()).toEqual([{ plans: { "user-alex": "free", "user-sam": "free" }, dry_run: true }])
    expect(assign.querySelector(".plan-assign-found")?.textContent).toBe("3 found")
    expect(assignRows("free")).toEqual([
      ["alex@example.test", "Has Family, the default", "Would be over: 3 active rules, 1 allowed"],
      ["sam@example.test", "Has No limits", null],
      ["dana@example.testYou", "Never limited, whatever plan they have", null],
    ])
    expect(assign.querySelector(".plan-assign-group")?.textContent).toBe("Administrators")
    expect(assign.querySelector(".plan-assign-over svg[aria-hidden='true']")).not.toBeNull()
    expect(pick("free", ALEX).getAttribute("aria-describedby")).toBe(
      "plan-assign-free-user-alex-held plan-assign-free-user-alex-over",
    )
    const give = button("Give Free", panel())
    expect(give.closest(".plan-panel-foot")).not.toBeNull()
    expect(give.getAttribute("aria-disabled")).toBe("true")
    expect(element(give.getAttribute("aria-describedby")!).textContent).toBe("Choose who gets Free.")
    expect(panel().querySelector(".plan-assign-selected")?.textContent).toBe("0 selected")
    await click(give)
    expect(assignCalls()).toHaveLength(1)
  })

  it("gives the plan to the people chosen at once, says so, and Undo gives each the plan they had", async () => {
    await assignFree([ALEX, SAM])
    await check("free", ALEX)
    const note = () => assignOf("free").querySelector(".plan-assign-note")
    expect(note()?.textContent).toBe(
      "alex@example.test will have more than Free allows. Everything they have keeps working, but they can't add more until they are within it.",
    )
    await check("free", SAM)
    expect(panel().querySelector(".plan-assign-selected")?.textContent).toBe("2 selected")

    reply("POST /api/v1/plan-assignments", moved([[ALEX, [{ limit: "rules", in_use: 3, allowed: 1 }]], [SAM, []]]))
    const give = button("Give Free to 2 people", panel())
    focus(give)
    await click(give)
    expect(assignCalls().at(-1)).toEqual({ plans: { "user-alex": "free", "user-sam": "free" }, dry_run: false })
    expect(toast()).toBe("2 people now have Free.")
    // The panel stays, ready for more, with nobody chosen.
    expect(here()).toBe("/people/plans/free/people")
    expect(panel().querySelector(".plan-assign-selected")?.textContent).toBe("0 selected")
    expect(document.activeElement).toBe(give)
    // Plans and People read again, so the counts follow.
    expect(calls.filter((call) => call.method === "GET" && call.path === "/api/v1/plans").length).toBeGreaterThan(1)

    // One call gives each back the Plan they had, so a refusal restores nobody.
    const before = assignCalls().length
    await click(button("Undo", container))
    expect(assignCalls().slice(before)).toEqual([{ plans: { "user-alex": null, "user-sam": "no-limits" }, dry_run: false }])
    expect(toast()).toBe("2 people have their plans back.")
  })

  it("gives the default plan as following it, so they move with it when the default changes", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ enabled: true, defaultPlan: "free" }),
      answers: { "GET /api/v1/users": freeAndOthers([SAM]), "POST /api/v1/plan-assignments": moved([[SAM, []]], true) },
    })
    await chooseFromMenu("free", "Assign people")
    expect(assignOf("free").querySelector(".plan-assign-intro")?.textContent).toBe(
      "They follow Free, the default plan, at once, and move with it when the default changes. Administrators are listed last; no plan limits them.",
    )
    // Choosing the default means having no plan of their own, as Change plan sends it.
    expect(assignCalls()).toEqual([{ plans: { "user-sam": null }, dry_run: true }])
    await check("free", SAM)
    expect(assignOf("free").querySelector(".plan-assign-note")).toBeNull()
    reply("POST /api/v1/plan-assignments", moved([[SAM, []]]))
    await click(button("Give Free to 1 person", panel()))
    expect(assignCalls().at(-1)).toEqual({ plans: { "user-sam": null }, dry_run: false })
    expect(toast()).toBe("sam@example.test now has Free.")
  })

  it("finds people by part of their email, and says when nobody else is found", async () => {
    await renderPlans(testI18n(), {
      plans: overview({ enabled: true, defaultPlan: "family" }),
      answers: {
        "GET /api/v1/users": (call) =>
          jsonResponse(call.query.get("search") === "rob" ? candidates([ROBIN]) : candidates([ALEX, SAM], 120)),
        "POST /api/v1/plan-assignments": DRY_RUN,
      },
    })
    await chooseFromMenu("free", "Assign people")
    expect(assignOf("free").querySelector(".plan-assign-found")?.textContent).toBe(
      "2 found. Search by email to find someone else.",
    )
    await check("free", SAM)
    const search = field("plan-assign-free-search")
    expect(container.querySelector("label[for='plan-assign-free-search']")?.textContent).toBe("Search by email")
    type(search, "rob")
    act(() => {
      search.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }))
    })
    await settle()
    const asked = calls.filter((call) => call.method === "GET" && call.path === "/api/v1/users").at(-1)
    expect(asked?.query.get("search")).toBe("rob")
    expect(assignRows("free")).toEqual([])
    expect(assignOf("free").querySelector(".plan-assign-found")?.textContent).toBe("Nobody else found")
    // Who was chosen stays chosen while the search changes.
    expect(panel().querySelector(".plan-assign-selected")?.textContent).toBe("1 selected")
  })

  it("keeps saying who chosen would be over once a search hides them, and asks the dry run about them too", async () => {
    const over: Record<string, OverLimit[]> = { "user-alex": [{ limit: "rules", in_use: 3, allowed: 1 }] }
    await renderPlans(testI18n(), {
      plans: overview({ enabled: true, defaultPlan: "family" }),
      answers: {
        "GET /api/v1/users": (call) => jsonResponse(candidates(call.query.get("search") === "sam" ? [SAM] : [ALEX, SAM])),
        "POST /api/v1/plan-assignments": (call) => {
          const ids = Object.keys((call.body as { plans: Record<string, string | null> }).plans)
          return moved(
            [ALEX, SAM].filter((person) => ids.includes(person.id)).map((person) => [person, over[person.id] ?? []]),
            true,
          )
        },
      },
    })
    await chooseFromMenu("free", "Assign people")
    await check("free", ALEX)
    const note = "alex@example.test will have more than Free allows. Everything they have keeps working, but they can't add more until they are within it."
    expect(assignOf("free").querySelector(".plan-assign-note")?.textContent).toBe(note)
    const search = field("plan-assign-free-search")
    type(search, "sam")
    act(() => {
      search.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }))
    })
    await settle()
    expect(assignRows("free").map(([label]) => label)).toEqual(["sam@example.test"])
    await check("free", SAM)
    expect(assignOf("free").querySelector(".plan-assign-note")?.textContent).toBe(note)
    expect(assignCalls().at(-1)).toEqual({ plans: { "user-sam": "free", "user-alex": "free" }, dry_run: true })
  })

  it("asks the dry run about at most 100 people, the chosen first, and gives to at most 100 at a time", async () => {
    const many = Array.from({ length: 100 }, (_, index) =>
      candidate(`p${String(index).padStart(3, "0")}@example.test`, { key: "no-limits", name: "No limits", on_default: false }),
    )
    const over: OverLimit[] = [{ limit: "rules", in_use: 3, allowed: 1 }]
    await renderPlans(testI18n(), {
      plans: overview({ enabled: true, defaultPlan: "family" }),
      answers: {
        "GET /api/v1/users": (call) => jsonResponse(call.query.get("search") === "sam" ? candidates([SAM]) : candidates(many, 150)),
        // As the server answers: about at most 100 people at once.
        "POST /api/v1/plan-assignments": (call) => {
          const ids = Object.keys((call.body as { plans: Record<string, string | null> }).plans)
          if (ids.length > 100) return refusal(422, "invalid_assignment", { reason: "too_many", limit: 100, count: 100 })
          return moved(
            [...many, SAM].filter((person) => ids.includes(person.id)).map((person) => [person, person === many[0] || person === SAM ? over : []]),
            true,
          )
        },
      },
    })
    await chooseFromMenu("free", "Assign people")
    const search = field("plan-assign-free-search")
    type(search, "sam")
    act(() => {
      search.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }))
    })
    await settle()
    await check("free", SAM)
    await escape(search)
    expect(assignRows("free")).toHaveLength(100)
    expect(assignRows("free")[0]).toEqual(["p000@example.test", "Has No limits", "Would be over: 3 active rules, 1 allowed"])
    expect(assignOf("free").querySelector(".plan-assign-note")?.textContent).toBe(
      "sam@example.test will have more than Free allows. Everything they have keeps working, but they can't add more until they are within it.",
    )

    act(() => {
      for (const person of many) pick("free", person).click()
    })
    await settle()
    const give = button("Give Free to 101 people", panel())
    expect(give.getAttribute("aria-disabled")).toBe("true")
    expect(element(give.getAttribute("aria-describedby")!).textContent).toBe("Choose at most 100 people at a time.")
    await click(give)
    expect(assignCalls().every((call) => (call as { dry_run: boolean }).dry_run)).toBe(true)
    expect(assignCalls().every((call) => Object.keys((call as { plans: Record<string, string | null> }).plans).length <= 100)).toBe(true)
  })

  it("clears the search with Escape without closing the panel", async () => {
    await renderPlans(testI18n(), {
      answers: { "GET /api/v1/users": freeAndOthers([ALEX]), "POST /api/v1/plan-assignments": DRY_RUN },
    })
    await chooseFromMenu("free", "Assign people")
    const search = field("plan-assign-free-search")
    type(search, "rob")
    await escape(search)
    expect(search.value).toBe("")
    expect(panelOrNull()).not.toBeNull()
    await escape(search)
    expect(panelOrNull()).toBeNull()
  })

  it("keeps the command on its way, then says why it was refused, keeping who was chosen", async () => {
    let answer: (response: Response) => void = () => undefined
    await assignFree([ALEX, SAM])
    await check("free", SAM)
    routes["POST /api/v1/plan-assignments"] = new Promise<Response>((resolve) => {
      answer = resolve
    })
    const give = button("Give Free to 1 person", panel())
    focus(give)
    await click(give)
    expect(give.getAttribute("aria-disabled")).toBe("true")
    expect(document.activeElement).toBe(give)
    await click(give)
    await click(button("Cancel", panel()))
    expect(assignCalls()).toHaveLength(2)
    expect(panelOrNull()).not.toBeNull()

    await act(async () => {
      answer(refusal(422, "invalid_assignment", { reason: "unknown_people" }))
      await Promise.resolve()
    })
    await settle()
    expect(panel().querySelector("[role='alert']")?.textContent).toBe(
      "Someone you chose no longer has access to this Calendar Ghost. Reload and try again.",
    )
    expect(pick("free", SAM).checked).toBe(true)
    expect(toast()).toBe("")
  })

  it("closes on Cancel, giving nothing, and returns focus to the plan's name", async () => {
    await assignFree([ALEX, SAM])
    await check("free", SAM)
    await click(button("Cancel", panel()))
    expect(panelOrNull()).toBeNull()
    expect(assignCalls()).toEqual([{ plans: { "user-alex": "free", "user-sam": "free" }, dry_run: true }])
    expect(document.activeElement).toBe(nameLink("free"))
  })

  it("lists people without a dry run when the only ones found administer", async () => {
    await assignFree([DANA])
    expect(assignRows("free")).toEqual([["dana@example.testYou", "Never limited, whatever plan they have", null]])
    expect(assignCalls()).toEqual([])
  })

  it("says why Undo was refused in a toast, where it was pressed, not under the panel or the plan's row", async () => {
    await assignFree([SAM], { dryRun: moved([[SAM, []]], true) })
    await check("free", SAM)
    reply("POST /api/v1/plan-assignments", moved([[SAM, []]]))
    await click(button("Give Free to 1 person", panel()))
    reply("POST /api/v1/plan-assignments", refusal(404, "plan_not_found"))
    await click(toastButton("Undo"))
    expect(toast()).toBe("This plan no longer exists. Reload to see the current plans.")
    expect(panel().querySelector("[role='alert']")).toBeNull()
    await click(closeButton())
    expect(detailsOf("free")).toBeNull()
  })

  it("says what Undo did once the Plans tab is gone", async () => {
    await assignFree([SAM], { dryRun: moved([[SAM, []]], true) })
    await check("free", SAM)
    reply("POST /api/v1/plan-assignments", moved([[SAM, []]]))
    await click(button("Give Free to 1 person", panel()))
    await leavePlans()
    await click(toastButton("Undo"))
    expect(assignCalls().at(-1)).toEqual({ plans: { "user-sam": "no-limits" }, dry_run: false })
    expect(toast()).toBe("sam@example.test has their plan back.")
  })
})

/** Who has Free now, each as their email, what they are over, and their Change plan's name. */
function holderRows(): (string | null)[][] {
  return [...element("plan-holders-free").querySelectorAll("li.plan-holder")].map((row) => [
    row.querySelector("a")?.textContent ?? "",
    row.querySelector(".plan-holder-state")?.textContent ?? null,
    row.querySelector("button")?.getAttribute("aria-label") ?? null,
  ])
}

function changeOf(person: PersonRow): HTMLElement {
  return element(`plan-change-${person.id}`)
}

function changeChoice(person: PersonRow, label: string): HTMLInputElement {
  const found = [...changeOf(person).querySelectorAll<HTMLInputElement>("input[type='radio']")].find((radio) =>
    labelOf(radio).startsWith(label),
  )
  if (!found) throw new Error(`No choice ${label}`)
  return found
}

describe("Who has a plan now", () => {
  it("lists who has the plan, what each is over, and links to them and to Everyone", async () => {
    const admin = candidate("dana@example.test", { key: "free", name: "Free", on_default: false }, "installation_administrator")
    await assignFree([ALEX], { holding: [admin, JORDAN, ROBIN_OVER] })
    const holders = element("plan-holders-free")
    expect(holders.querySelector("h4")?.textContent).toBe("Have Free now")
    const asked = calls.filter((call) => call.method === "GET" && call.query.get("plan") === "free").at(-1)
    expect(Object.fromEntries(asked!.query)).toEqual({ plan: "free", sort: "email", order: "asc", page: "1", page_size: "100" })
    const show = [...holders.querySelectorAll("a")].find((link) => link.textContent === "Show in Everyone")!
    expect(show.getAttribute("href")).toBe("/people?plan=free")
    expect(holderRows()).toEqual([
      ["dana@example.test", "Never limited", "Change plan for dana@example.test"],
      ["jordan@example.test", "Within every limit", "Change plan for jordan@example.test"],
      ["robin@example.test", "2 calendar accounts, 1 allowed", "Change plan for robin@example.test"],
    ])
    const robin = [...holders.querySelectorAll<HTMLElement>(".plan-holder-state")].at(-1)!
    expect(robin.getAttribute("data-tone")).toBe("attention")
    expect(robin.querySelector("svg[aria-hidden='true']")).not.toBeNull()

    const link = [...holders.querySelectorAll("a")].find((item) => item.textContent === "robin@example.test")!
    expect(link.getAttribute("href")).toBe("/people/user-robin")
    await click(link)
    expect(opened).toEqual(["user-robin"])

    await click(show)
    expect(here()).toBe("/people?plan=free")
    expect(container.querySelector("nav.page-tabs [aria-current='page']")?.textContent).toBe("Everyone")
  })

  it("says what each would be over, neutral, while plans are off, and when nobody has the plan", async () => {
    await assignFree([ALEX], { holding: [ROBIN_OVER], enabled: false })
    expect(holderRows()[0]?.[1]).toBe("Would be over: 2 calendar accounts, 1 allowed")
    expect(element("plan-holders-free").querySelector("[data-tone]")).toBeNull()

    reply("GET /api/v1/users", freeAndOthers([ALEX], []))
    await click(closeButton())
    await chooseFromMenu("free", "Assign people")
    expect(element("plan-holders-free").querySelector(".plan-have-empty")?.textContent).toBe("Nobody has Free yet.")
  })

  it("changes one person's plan from the list after a dry run, and Undo gives it back", async () => {
    await assignFree([ALEX])
    const change = element("plan-holders-free").querySelector<HTMLButtonElement>(
      "button[aria-label='Change plan for robin@example.test']",
    )!
    expect(change.getAttribute("aria-expanded")).toBe("false")
    await click(change)
    expect(change.getAttribute("aria-expanded")).toBe("true")
    const chooser = changeOf(ROBIN_OVER)
    expect(change.getAttribute("aria-controls")).toBe(chooser.id)
    expect(chooser.querySelector("h5")?.textContent).toBe("Change plan for robin@example.test")
    // The same compact chooser as everywhere: one line per plan, the default first, what they have chosen.
    expect(
      [...chooser.querySelectorAll<HTMLInputElement>("input[type='radio']")].map((radio) => [labelOf(radio), radio.checked]),
    ).toEqual([
      ["Family Default", false],
      ["Free Current", true],
    ])
    expect(document.activeElement).toBe(changeChoice(ROBIN_OVER, "Free"))
    expect(chooser.textContent).toContain("5 rules, 3 accounts, 2 tokens, Instant")
    expect(chooser.textContent).toContain("People on the default plan move with it when the default changes.")

    reply("POST /api/v1/plan-assignments", moved([[ROBIN_OVER, [{ limit: "rules", in_use: 6, allowed: 5 }]]], true))
    // Family is the default, so choosing it means robin follows the default.
    await click(changeChoice(ROBIN_OVER, "Family"))
    expect(assignCalls().at(-1)).toEqual({ plans: { "user-robin": null }, dry_run: true })
    const note = chooser.querySelector("[role='status'][data-tone='attention']")
    expect(note?.textContent).toBe("Would be over: 6 active rules, 5 allowed")

    reply("POST /api/v1/plan-assignments", moved([[ROBIN_OVER, []]]))
    await click(button("Save", chooser))
    expect(assignCalls().at(-1)).toEqual({ plans: { "user-robin": null }, dry_run: false })
    expect(toast()).toBe("robin@example.test now has Family.")
    expect(container.querySelector("#plan-change-user-robin")).toBeNull()
    expect(document.activeElement).toBe(element("plan-holders-free").querySelector("h4"))

    await click(button("Undo", container))
    expect(assignCalls().at(-1)).toEqual({ plans: { "user-robin": "free" }, dry_run: false })
    expect(toast()).toBe("robin@example.test has their plan back.")
  })

  it("closes the chooser on Cancel, changing nothing, with focus back on Change plan", async () => {
    await assignFree([ALEX])
    const change = element("plan-holders-free").querySelector<HTMLButtonElement>(
      "button[aria-label='Change plan for jordan@example.test']",
    )!
    await click(change)
    await click(button("Cancel", changeOf(JORDAN)))
    expect(container.querySelector("#plan-change-user-jordan")).toBeNull()
    expect(document.activeElement).toBe(change)
    expect(assignCalls().every((call) => (call as { dry_run: boolean }).dry_run)).toBe(true)
    expect(panelOrNull()).not.toBeNull()
  })

  it("scrolls the chooser fully into view as it opens under them, with focus staying on the plan they have", async () => {
    await assignFree([ALEX])
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined)
    await click(
      element("plan-holders-free").querySelector<HTMLButtonElement>("button[aria-label='Change plan for jordan@example.test']")!,
    )
    expect(scrolled).toHaveBeenCalledOnce()
    expect(scrolled.mock.contexts[0]).toBe(changeOf(JORDAN))
    expect(scrolled.mock.calls[0]?.[0]).toMatchObject({ block: "nearest" })
    expect(document.activeElement).toBe(changeChoice(JORDAN, "Free"))
  })

  it("says why a change was refused under the chooser", async () => {
    await assignFree([ALEX])
    await click(
      element("plan-holders-free").querySelector<HTMLButtonElement>("button[aria-label='Change plan for jordan@example.test']")!,
    )
    await click(changeChoice(JORDAN, "Family"))
    reply("POST /api/v1/plan-assignments", refusal(404, "plan_not_found"))
    await click(button("Save", changeOf(JORDAN)))
    expect(changeOf(JORDAN).querySelector("[role='alert']")?.textContent).toBe(
      "This plan no longer exists. Reload to see the current plans.",
    )
    expect(panel().querySelector(".plan-panel-foot [role='alert']")).toBeNull()
    expect(toast()).toBe("")
  })
})

describe("Plans in other languages", () => {
  it("has no untranslated text in the empty state", async () => {
    await renderPlans(pseudoI18n(), { plans: overview({ plans: [] }) })
    expect(untranslatedText(container, dateWords())).toEqual([])
    await click(element("plans-new"))
    expect(untranslatedText(container, dateWords())).toEqual([])
  })

  it("has no untranslated text", async () => {
    const spare: PlanSummary = { ...family, key: "spare", name: "Spare", people: 0, limited_people: 0 }
    await renderPlans(pseudoI18n(), {
      plans: overview({ enabled: true, defaultPlan: "free", plans: [{ ...family, over_people: 1 }, free, spare] }),
    })
    const names = [...dateWords(), family.name, free.name, spare.name, "robin@example.test"]
    expect(untranslatedText(container, names)).toEqual([])
    await openMenu("family")
    expect(untranslatedText(container, names)).toEqual([])
    await openMenu("spare")
    // Remove, the last item: nobody has Spare.
    await click([...planRow("spare").querySelectorAll<HTMLElement>("[role='menuitem']")].at(-1)!)
    expect(element("plan-remove-spare")).not.toBeNull()
    expect(untranslatedText(container, names)).toEqual([])
  })

  it("has no untranslated text in a plan's panel", async () => {
    await renderPlans(pseudoI18n(), { plans: overview({ enabled: true, defaultPlan: "free" }) })
    await click(nameLink("family"))
    type(field("plan-edit-family-rules"), "2")
    await settle()
    const names = [...dateWords(), family.name, free.name]
    expect(untranslatedText(container, names)).toEqual([])
    await click(closeButton())
    await click(button(pseudoI18n().t("people.plans.new"), catalogHead()))
    expect(untranslatedText(container, names)).toEqual([])
  })

  it("has no untranslated text while assigning people or changing someone's plan", async () => {
    await renderPlans(pseudoI18n(), {
      plans: overview({ enabled: true, defaultPlan: "family" }),
      answers: { "GET /api/v1/users": freeAndOthers([ALEX, DANA, SAM], [ROBIN_OVER, JORDAN]), "POST /api/v1/plan-assignments": DRY_RUN },
    })
    await openMenu("free")
    // Assign people, the second item.
    await click(planRow("free").querySelectorAll<HTMLElement>("[role='menuitem']")[1]!)
    await check("free", ALEX)
    await click(element("plan-holders-free").querySelector<HTMLButtonElement>("li.plan-holder button")!)
    await click(changeOf(ROBIN_OVER).querySelectorAll<HTMLInputElement>("input[type='radio']")[1]!)
    const names = [
      ...dateWords(),
      family.name,
      free.name,
      noLimits.name,
      ALEX.email!,
      DANA.email!,
      SAM.email!,
      ROBIN.email!,
      JORDAN.email!,
    ]
    expect(untranslatedText(container, names)).toEqual([])
  })
})
