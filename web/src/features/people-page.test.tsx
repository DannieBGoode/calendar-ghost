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
import { appLocationFromPathname } from "@/lib/navigation"
import type {
  InstallationHealthReport,
  PendingInvitation,
  PeoplePage,
  Person,
  PersonPlanOverview,
  PersonRow,
  PlanSummary,
  PlansOverview,
  SessionStatus,
} from "@/lib/api"

import { PeopleView } from "./people-page"

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
const firstUser: Person = { ...me, id: "user-first", email: null, role: "user" }
const jordan: Person = { ...me, id: "user-jordan", email: "jordan@example.test", role: "user" }
const invitation: PendingInvitation = { id: "inv-1", created_at: justNow, expires_at: nextWeek }

const session: SessionStatus = {
  authenticated: true,
  installation_sends_email: true,
  user: { id: me.id, email: me.email, role: "installation_administrator", notify_by_email: true, instant_sync: true, instant_sync_availability: "on", instant_sync_help: null, language: null },
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

/** What the Operator Overview says of someone with nothing set up yet. */
const NOTHING_SET_UP: Omit<PersonRow, keyof Person> = {
  verdict: "setup",
  problems: 0,
  last_synced_at: null,
  resources: { rules: 0, connected_accounts: 0, activity_entries: 0, provider_calls: [], since: "2026-09-10" },
  plan: null,
}

/** What the Operator Overview says of people who have more than nothing set up. */
const OVERVIEWS: Record<string, Partial<PersonRow>> = {
  "user-robin": { verdict: "stopped", problems: 2 },
  "user-sam": { verdict: "healthy" },
}

const FREE = { key: "free", name: "Free", on_default: true }
const FAMILY = { key: "family", name: "Family", on_default: false }

/** How much of a Plan with `planSummary`'s limits a person uses: nothing but their calendar accounts. */
function used(accounts = 0): NonNullable<PersonPlanOverview["use"]> {
  return {
    rules: { in_use: 0, allowed: 1 },
    connected_accounts: { in_use: accounts, allowed: 1 },
    integration_tokens: { in_use: 0, allowed: 0 },
    sync_interval: "5_minutes",
  }
}

/** Nobody gave the Plan: the person has the default. */
const NOT_GIVEN = { assigned_by: null, assigned_at: null }

/** Each person's Plan once a Plan exists: Dana administers, Robin is over Family, Sam has the default. */
const PLANS_HELD: Record<string, PersonPlanOverview> = {
  "user-dana": { basis: "administrator", plan: null, assigned: null, has: FREE, over: [], ...NOT_GIVEN, use: used() },
  "user-robin": {
    basis: "plan",
    plan: FAMILY,
    assigned: { key: "family", name: "Family" },
    has: FAMILY,
    over: [{ limit: "connected_accounts", in_use: 2, allowed: 1 }],
    assigned_by: "dana@example.test",
    assigned_at: "2026-10-12T09:00:00+00:00",
    use: used(2),
  },
  "user-sam": { basis: "plan", plan: FREE, assigned: null, has: FREE, over: [], ...NOT_GIVEN, use: used() },
  "user-jordan": {
    basis: "plan",
    plan: FAMILY,
    assigned: { key: "family", name: "Family" },
    has: FAMILY,
    over: [],
    assigned_by: "dana@example.test",
    assigned_at: "2026-10-12T09:00:00+00:00",
    use: used(1),
  },
}

/** The same page once a Plan exists, each person with the Plan they have. */
function withPlans(page: PeoplePage): PeoplePage {
  return { ...page, users: page.users.map((user) => ({ ...user, plan: PLANS_HELD[user.id] ?? null })) }
}

function planSummary(key: string, name: string, isDefault: boolean): PlanSummary {
  return {
    key,
    name,
    limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
    is_default: isDefault,
    people: 1,
    limited_people: 1,
    over_people: 0,
    use: { rules: [], connected_accounts: [], integration_tokens: [] },
  }
}

const PLANS: PlansOverview = {
  enabled: true,
  default_plan: "free",
  sync_intervals: ["instant", "5_minutes"],
  followers: 2,
  plans: [planSummary("family", "Family", false), planSummary("free", "Free", true)],
}

function onePage(users: Person[], page: Partial<PeoplePage> = {}): PeoplePage {
  const rows = users.map((user) => ({ ...NOTHING_SET_UP, ...OVERVIEWS[user.id], ...user }))
  return { users: rows, total: users.length, page: 1, page_size: 50, ...page }
}

const health: InstallationHealthReport = {
  status: "stopped",
  needs_attention: true,
  incidents: [],
  users: { stopped: 1, healthy: 1, setup: 2 },
  disabled_users: 1,
  checked_at: justNow,
  hints: [],
}

type Call = { method: string; path: string; query: URLSearchParams; body: unknown }
type Scenario = {
  /** The page's path, `/people` unless given. */
  path?: string
  /** The address the page opens at, after the path. */
  search?: string
  /** Answers GET /api/v1/users from what it was asked for. */
  people?: (query: URLSearchParams) => Response
  /** Answers by "METHOD /path", overriding the defaults. */
  answers?: Record<string, Response>
}

let calls: Call[] = []

function serve({ people = () => jsonResponse(onePage([me, robin, sam])), answers = {} }: Scenario) {
  const defaults: Record<string, Response> = {
    "GET /api/v1/session": jsonResponse(session),
    "GET /api/v1/registration": jsonResponse({ policy: "invitation_only", only_me_available: false }),
    "GET /api/v1/invitations": jsonResponse([invitation]),
    "GET /api/v1/installation/health": jsonResponse(health),
    "POST /api/v1/invitations": jsonResponse({ id: "inv-2", token: "inv_synthetic", expires_at: nextWeek }, 201),
    "DELETE /api/v1/invitations/inv-1": { ok: true, status: 204, json: () => Promise.resolve(null) } as Response,
    "POST /api/v1/users/user-robin/password-reset-links": jsonResponse(
      { id: "reset-1", token: "reset_synthetic", expires_at: nextWeek },
      201,
    ),
    "DELETE /api/v1/users/user-robin": jsonResponse({ rules: 2, deleted: 5, detached: 0, left: 0 }),
    "GET /api/v1/plans": jsonResponse({ enabled: false, default_plan: null, sync_intervals: ["instant", "5_minutes"], plans: [] }),
  }
  const routes = { ...defaults, ...answers }
  calls = []
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET"
      const [path = "", search = ""] = String(input).split("?")
      const query = new URLSearchParams(search)
      const body: unknown = init?.body ? JSON.parse(init.body as string) : undefined
      calls.push({ method, path, query, body })
      if (method === "GET" && path === "/api/v1/users") return Promise.resolve(people(query))
      return Promise.resolve(routes[`${method} ${path}`] ?? jsonResponse({}))
    }),
  )
}

let container: HTMLDivElement
let root: Root | null = null
let address: string
let openPerson: ReturnType<typeof vi.fn<(personId: string) => void>>

function page() {
  return window as typeof window & { happyDOM: { setURL: (url: string) => void } }
}

beforeEach(() => {
  container = document.createElement("div")
  document.body.append(container)
  address = window.location.href
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

async function wait(milliseconds: number) {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, milliseconds))
  })
  await settle()
}

function showPeople(i18n: I18n, queryClient: QueryClient, visit = 0) {
  const tab = appLocationFromPathname(window.location.pathname).peopleTab ?? "everyone"
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <AppToasts>
              <PeopleView key={visit} tab={tab} notice={null} onOpenPerson={openPerson} onOpenPlan={vi.fn()} />
            </AppToasts>
          </QueryClientProvider>
        </ThemeProvider>
      </StaticI18nProvider>,
    )
  })
}

async function renderPeople(i18n: I18n, scenario: Scenario = {}) {
  page().happyDOM.setURL(`${ORIGIN}${scenario.path ?? "/people"}${scenario.search ?? ""}`)
  serve(scenario)
  openPerson = vi.fn<(personId: string) => void>()
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  showPeople(i18n, queryClient)
  await settle()
  return queryClient
}

function button(label: string, scope: ParentNode = container): HTMLButtonElement {
  const found = [...scope.querySelectorAll("button")].find((item) => item.textContent.trim() === label)
  if (!found) throw new Error(`No button labelled ${label}`)
  return found
}

function rows(): HTMLTableRowElement[] {
  return [...container.querySelectorAll<HTMLTableRowElement>("tr.person-row")]
}

function personRow(email: string): HTMLTableRowElement {
  const row = rows().find((item) => item.querySelector(".person-email")?.textContent.startsWith(email))
  if (!row) throw new Error(`No person ${email}`)
  return row
}

function cells(row: HTMLTableRowElement): string[] {
  return [...row.querySelectorAll("th, td")].map((cell) => cell.textContent.trim())
}

function header(label: string): HTMLTableCellElement {
  const found = [...container.querySelectorAll<HTMLTableCellElement>("thead th")].find(
    (cell) => cell.textContent.trim() === label,
  )
  if (!found) throw new Error(`No column ${label}`)
  return found
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

async function select(id: string, value: string) {
  const field = container.querySelector<HTMLSelectElement>(`#${id}`)!
  act(() => {
    field.value = value
    field.dispatchEvent(new Event("change", { bubbles: true }))
  })
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

/** What the last request for people asked for, by parameter. */
function lastPeopleQuery(): Record<string, string> {
  const call = calls.filter((item) => item.method === "GET" && item.path === "/api/v1/users").at(-1)
  if (!call) throw new Error("People were never requested")
  return Object.fromEntries(call.query)
}

function peopleRequests(): number {
  return calls.filter((item) => item.method === "GET" && item.path === "/api/v1/users").length
}

/** What the last command on someone said, as screen readers hear it. */
function status(): string | undefined {
  return container.querySelector(".people-command-status")?.textContent
}

/** A person's Plan cell. */
function plan(email: string): HTMLElement {
  return personRow(email).querySelector<HTMLElement>(".person-col-plan")!
}

/** A person's Plan, by name, then each chip beside it. */
function planCell(email: string): string[] {
  const cell = plan(email)
  return [
    cell.querySelector(".person-plan-name")?.textContent ?? "",
    ...[...cell.querySelectorAll(".person-plan-chip")].map((chip) => chip.textContent.trim()),
  ]
}

describe("People page", () => {
  it("has no untranslated text with people, invitations, menus, and links to pass on", async () => {
    await renderPeople(pseudoI18n(), { people: () => jsonResponse(onePage([me, robin, sam, firstUser])) })
    await click(personRow("robin@example.test").querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
    expect(container.querySelector("[role='menu']")).not.toBeNull()
    const fixtures = [me.email!, robin.email!, sam.email!, `${ORIGIN}/invitation#inv_synthetic`, ...dateWords()]
    expect(untranslatedText(container, fixtures)).toEqual([])

    await click(container.querySelector<HTMLButtonElement>("#invite-someone")!)
    expect(container.querySelector(".link-reveal")).not.toBeNull()
    expect(untranslatedText(container, fixtures)).toEqual([])
  })

  it("asks for the first page of everyone, in the order they joined", async () => {
    await renderPeople(testI18n())
    expect(lastPeopleQuery()).toEqual({ sort: "joined", order: "asc", page: "1", page_size: "50" })
  })

  it("lists people with their email, role, state, and sign-ins, and no actions on yourself", async () => {
    await renderPeople(testI18n(), { people: () => jsonResponse(onePage([me, robin, sam, firstUser])) })
    expect([...container.querySelectorAll("thead th")].map((cell) => cell.textContent.trim())).toEqual([
      "Email",
      "Sync",
      "Role",
      "State",
      "Joined",
      "Last sign-in",
      "Actions",
    ])
    expect(cells(personRow("dana@example.test"))).toEqual([
      "dana@example.testYou",
      "Not set up",
      "Administrator",
      "Active",
      "just now",
      "just now",
      "",
    ])
    expect(personRow("dana@example.test").querySelector("[aria-haspopup='menu']")).toBeNull()
    // Each person's email heads their row, so a screen reader names them as it moves down a column.
    const heading = personRow("robin@example.test").querySelector("th")!
    expect(heading.getAttribute("scope")).toBe("row")
    expect(heading.getAttribute("role")).toBe("rowheader")
    expect(heading.querySelector(".person-email")?.textContent).toBe("robin@example.test")
    expect(cells(personRow("robin@example.test")).slice(1, 6)).toEqual([
      "Stopped2 problems",
      "User",
      "Active",
      "just now",
      "Never",
    ])
    expect(cells(personRow("sam@example.test")).slice(1, 4)).toEqual(["Healthy", "User", "Disabled"])
    expect(personRow("No email yet").querySelector("[aria-haspopup='menu']")).not.toBeNull()
    expect(personRow("robin@example.test").querySelector("[aria-haspopup='menu']")?.getAttribute("aria-label")).toBe(
      "Actions for robin@example.test",
    )
  })

  it("shows each person's plan by name, with chips for the default, a limit they are over, and administrators", async () => {
    await renderPeople(testI18n(), {
      people: () => jsonResponse(withPlans(onePage([me, robin, sam]))),
      answers: { "GET /api/v1/plans": jsonResponse(PLANS) },
    })
    expect([...container.querySelectorAll("thead th")].map((cell) => cell.textContent.trim())).toEqual([
      "Select all",
      "Email",
      "Sync",
      "Role",
      "State",
      "Plan",
      "Joined",
      "Last sign-in",
      "Actions",
    ])
    expect(planCell("dana@example.test")).toEqual(["Free", "Default", "Not limited"])
    expect(planCell("sam@example.test")).toEqual(["Free", "Default"])
    expect(planCell("robin@example.test")).toEqual(["Family", "Over a limit"])
    // Over a limit: a chip in Attention Ochre with its icon, and which limit, in words, on a muted
    // line under it, for every reader.
    const over = plan("robin@example.test").querySelector("[data-tone='attention']")!
    expect(over.textContent).toBe("Over a limit")
    expect(over.querySelector("svg[aria-hidden='true']")).not.toBeNull()
    const detail = plan("robin@example.test").querySelector(".person-plan-detail")!
    expect(detail.textContent).toBe("2 calendar accounts, 1 allowed")
    expect(detail.closest(".sr-only")).toBeNull()
    expect(plan("robin@example.test").querySelector(".sr-only")).toBeNull()
    expect(plan("sam@example.test").getAttribute("data-label")).toBe("Plan")
  })

  it("says what someone would be over, neutral, while plans are off", async () => {
    const off = (page: PeoplePage): PeoplePage => ({
      ...page,
      users: page.users.map((user) => ({ ...user, plan: user.plan && { ...user.plan, basis: "plans_off" as const, plan: null } })),
    })
    await renderPeople(testI18n(), {
      people: () => jsonResponse(off(withPlans(onePage([me, robin])))),
      answers: { "GET /api/v1/plans": jsonResponse({ ...PLANS, enabled: false }) },
    })
    expect(planCell("robin@example.test")).toEqual(["Family", "Would be over"])
    expect(plan("robin@example.test").querySelector("[data-tone='attention']")).toBeNull()
    expect(plan("robin@example.test").querySelector(".person-plan-detail")?.textContent).toBe("2 calendar accounts, 1 allowed")
  })

  it("shows no Plan column or filter, and asks for no plans, while no plan exists", async () => {
    await renderPeople(testI18n())
    expect([...container.querySelectorAll("thead th")].map((cell) => cell.textContent.trim())).not.toContain("Plan")
    expect(container.querySelector(".person-col-plan")).toBeNull()
    expect(container.querySelector("#people-plan")).toBeNull()
    expect(calls.some((call) => call.path === "/api/v1/plans")).toBe(false)
  })

  it("filters by plan from the first page, kept in the address", async () => {
    await renderPeople(testI18n(), {
      search: "?page=2",
      people: () => jsonResponse(withPlans(onePage([me, robin, sam], { total: 60 }))),
      answers: { "GET /api/v1/plans": jsonResponse(PLANS) },
    })
    const plan = container.querySelector<HTMLSelectElement>("#people-plan")!
    expect(container.querySelector("label[for='people-plan']")?.textContent).toBe("Plan")
    expect([...plan.options].map((option) => [option.value, option.textContent])).toEqual([
      ["", "Any plan"],
      ["family", "Family"],
      ["free", "Free (default)"],
    ])
    await select("people-plan", "family")
    expect(lastPeopleQuery()).toMatchObject({ plan: "family", page: "1" })
    expect(window.location.search).toBe("?plan=family")
    await select("people-plan", "")
    expect(lastPeopleQuery().plan).toBeUndefined()
    expect(window.location.search).toBe("")
  })

  it("narrows to the people over a limit of their plan, kept in the address beside the plan", async () => {
    await renderPeople(testI18n(), {
      search: "?page=2",
      people: () => jsonResponse(withPlans(onePage([me, robin, sam], { total: 60 }))),
      answers: { "GET /api/v1/plans": jsonResponse(PLANS) },
    })
    const limits = container.querySelector<HTMLSelectElement>("#people-limits")!
    expect(container.querySelector("label[for='people-limits']")?.textContent).toBe("Limits")
    expect([...limits.options].map((option) => [option.value, option.textContent])).toEqual([
      ["", "Anyone"],
      ["over", "Over a limit"],
    ])
    await select("people-limits", "over")
    expect(lastPeopleQuery()).toMatchObject({ over: "true", page: "1" })
    expect(window.location.search).toBe("?over=true")
    await select("people-plan", "family")
    expect(lastPeopleQuery()).toMatchObject({ plan: "family", over: "true" })
    expect(window.location.search).toBe("?plan=family&over=true")
    await select("people-limits", "")
    expect(lastPeopleQuery().over).toBeUndefined()
    expect(window.location.search).toBe("?plan=family")
  })

  it("restores the over-a-limit filter from the address, reading plans so it shows", async () => {
    await renderPeople(testI18n(), {
      search: "?over=true",
      people: () => jsonResponse(onePage([], { total: 0 })),
      answers: { "GET /api/v1/plans": jsonResponse(PLANS) },
    })
    expect(lastPeopleQuery()).toMatchObject({ over: "true" })
    expect(container.querySelector<HTMLSelectElement>("#people-limits")!.value).toBe("over")
    await click(button("Clear filters"))
    expect(lastPeopleQuery().over).toBeUndefined()
    expect(container.querySelector<HTMLSelectElement>("#people-limits")!.value).toBe("")
  })

  it("restores a plan filter from the address, even for a plan that no longer exists", async () => {
    await renderPeople(testI18n(), {
      search: "?plan=free",
      people: () => jsonResponse(withPlans(onePage([sam]))),
      answers: { "GET /api/v1/plans": jsonResponse(PLANS) },
    })
    expect(lastPeopleQuery()).toMatchObject({ plan: "free" })
    expect(container.querySelector<HTMLSelectElement>("#people-plan")!.value).toBe("free")

    act(() => root?.unmount())
    root = null
    await renderPeople(testI18n(), {
      search: "?plan=gone",
      people: () => jsonResponse(onePage([], { total: 0 })),
      answers: { "GET /api/v1/plans": jsonResponse(PLANS) },
    })
    const plan = container.querySelector<HTMLSelectElement>("#people-plan")!
    expect(plan.value).toBe("gone")
    expect(plan.selectedOptions[0]?.textContent).toBe("A plan that no longer exists")
    await click(button("Clear filters"))
    expect(lastPeopleQuery().plan).toBeUndefined()
  })

  it("has no untranslated text with each person's plan", async () => {
    await renderPeople(pseudoI18n(), {
      people: () => jsonResponse(withPlans(onePage([me, robin, sam]))),
      answers: { "GET /api/v1/plans": jsonResponse(PLANS) },
    })
    const fixtures = [me.email!, robin.email!, sam.email!, "Family", "Free", ...dateWords()]
    expect(untranslatedText(container, fixtures)).toEqual([])
  })

  it("restores the search, filters, sort, and page from the address", async () => {
    await renderPeople(testI18n(), {
      search: "?search=rob&role=user&state=disabled&verdict=stopped&sort=email&order=desc&page=2",
      people: () => jsonResponse(onePage([robin], { page: 2, total: 51 })),
    })
    expect(lastPeopleQuery()).toEqual({
      search: "rob",
      role: "user",
      state: "disabled",
      verdict: "stopped",
      sort: "email",
      order: "desc",
      page: "2",
      page_size: "50",
    })
    expect(container.querySelector<HTMLSelectElement>("#people-verdict")!.value).toBe("stopped")
    expect(container.querySelector<HTMLInputElement>("#people-search")!.value).toBe("rob")
    expect(container.querySelector<HTMLSelectElement>("#people-role")!.value).toBe("user")
    expect(container.querySelector<HTMLSelectElement>("#people-state")!.value).toBe("disabled")
    expect(header("Email").getAttribute("aria-sort")).toBe("descending")
    expect(header("Joined").getAttribute("aria-sort")).toBeNull()
  })

  it("searches by part of an email once typing pauses, from the first page", async () => {
    await renderPeople(testI18n(), { search: "?page=2", people: () => jsonResponse(onePage([robin], { total: 60 })) })
    const before = peopleRequests()
    const length = window.history.length
    type(container.querySelector<HTMLInputElement>("#people-search")!, "rob")
    await settle()
    expect(peopleRequests()).toBe(before)

    await wait(350)
    expect(lastPeopleQuery()).toMatchObject({ search: "rob", page: "1" })
    expect(`${window.location.pathname}${window.location.search}`).toBe("/people?search=rob")
    // Typing replaces the address rather than adding a history entry for each pause.
    expect(window.history.length).toBe(length)
  })

  it("shows how everyone's synchronization is doing above the list, naming nobody", async () => {
    await renderPeople(testI18n())
    const summary = container.querySelector<HTMLElement>("[aria-labelledby='installation-health-title']")!
    expect(summary.querySelector("h2")?.textContent).toBe("Installation health")
    // Nothing here is the administrator's to fix: people see their own steps on their dashboard.
    expect(summary.querySelector(".installation-health-lead")?.textContent).toBe(
      "Nothing needs you1 of 4 people has something to fix on their own dashboard.",
    )
    expect([...summary.querySelectorAll("button")].map((item) => item.textContent)).toEqual([
      "Stopped: 1",
      "Not set up: 2",
      "Healthy: 1",
      "Disabled: 1",
    ])
    expect(summary.querySelector("summary")?.textContent).toBe("What each sync status means")
    expect(summary.textContent).not.toContain("robin@example.test")
  })

  it("shows disabled people from their own count", async () => {
    await renderPeople(testI18n())
    const summary = () => container.querySelector<HTMLElement>("[aria-labelledby='installation-health-title']")!
    await click(button("Disabled: 1", summary()))
    expect(lastPeopleQuery()).toMatchObject({ state: "disabled" })
    expect(lastPeopleQuery().verdict).toBeUndefined()
    expect(button("Disabled: 1", summary()).getAttribute("aria-pressed")).toBe("true")
  })

  it("marks a count pressed whenever the filters show exactly its people, however they were set", async () => {
    await renderPeople(testI18n())
    await select("people-verdict", "stopped")
    const summary = () => container.querySelector<HTMLElement>("[aria-labelledby='installation-health-title']")!
    // Any state also shows disabled people, whom the count leaves out.
    expect(button("Stopped: 1", summary()).getAttribute("aria-pressed")).toBe("false")
    await select("people-state", "active")
    expect(button("Stopped: 1", summary()).getAttribute("aria-pressed")).toBe("true")
  })

  it("filters by a verdict from Installation Health, and shows everyone again", async () => {
    await renderPeople(testI18n(), { search: "?page=2", people: () => jsonResponse(onePage([robin], { total: 60 })) })
    const summary = () => container.querySelector<HTMLElement>("[aria-labelledby='installation-health-title']")!
    await click(button("Stopped: 1", summary()))
    expect(lastPeopleQuery()).toMatchObject({ verdict: "stopped", page: "1" })
    // The count leaves out disabled people, so it shows only people who may sign in.
    expect(lastPeopleQuery()).toMatchObject({ state: "active" })
    expect(window.location.search).toBe("?state=active&verdict=stopped")
    expect(button("Stopped: 1", summary()).getAttribute("aria-pressed")).toBe("true")

    await click(button("Stopped: 1", summary()))
    expect(lastPeopleQuery().verdict).toBeUndefined()
    expect(lastPeopleQuery().state).toBeUndefined()
    expect(window.location.search).toBe("")
  })

  it("says when the installation itself stopped synchronizing", async () => {
    const stalled = { ...health, status: "stalled", incidents: [{ kind: "scheduler_stalled", since: justNow }] }
    await renderPeople(testI18n(), { answers: { "GET /api/v1/installation/health": jsonResponse(stalled) } })
    const summary = container.querySelector<HTMLElement>("[aria-labelledby='installation-health-title']")!
    expect(summary.textContent).toContain("Scheduled synchronization stopped running just now.")
  })

  it("warns that a client secret expires, which only the administrator can fix", async () => {
    const expiring = {
      ...health,
      needs_attention: true,
      incidents: [{ kind: "client_secret_expiring", since: justNow, provider: "outlook", expires_on: "2099-04-12" }],
    }
    await renderPeople(testI18n(), { answers: { "GET /api/v1/installation/health": jsonResponse(expiring) } })
    const summary = container.querySelector<HTMLElement>("[aria-labelledby='installation-health-title']")!

    expect(summary.querySelector(".installation-health-lead")?.textContent).toBe(
      "Needs youOnly you can fix what is below.",
    )
    expect(summary.textContent).toContain(
      "The Microsoft client secret expires on April 12, 2099. Put a new one in place before then, or every Microsoft account stops.",
    )
  })

  it("says when a client secret already expired", async () => {
    const expired = {
      ...health,
      needs_attention: true,
      incidents: [{ kind: "client_secret_expiring", since: justNow, provider: "outlook", expires_on: "2000-01-31" }],
    }
    await renderPeople(testI18n(), { answers: { "GET /api/v1/installation/health": jsonResponse(expired) } })
    const summary = container.querySelector<HTMLElement>("[aria-labelledby='installation-health-title']")!

    expect(summary.textContent).toContain("The Microsoft client secret expired on January 31, 2000.")
  })

  it("suggests each likely cause people share, with how to fix it", async () => {
    const hinted = {
      ...health,
      hints: [
        { kind: "shared_cause", cause: "api_disabled", users: 2, anchor: "the-google-calendar-api-is-turned-off", provider: "google" },
        {
          kind: "testing_mode",
          cause: "access_revoked",
          users: 3,
          anchor: "google-accounts-stop-working-7-days-after-connecting",
          provider: "google",
        },
      ],
    }
    await renderPeople(testI18n(), { answers: { "GET /api/v1/installation/health": jsonResponse(hinted) } })
    const summary = container.querySelector<HTMLElement>("[aria-labelledby='installation-health-title']")!

    // Something only the administrator can fix leads the card.
    expect(summary.querySelector(".installation-health-lead")?.textContent).toBe(
      "Needs youOnly you can fix what is below.",
    )
    const hints = [...summary.querySelectorAll("li.installation-hint")]
    expect(hints.map((hint) => hint.querySelector("p")?.textContent)).toEqual([
      "2 people are affected because the Google Calendar API is turned off for this installation.",
      "3 people lost access about 7 days after connecting, which usually means the OAuth app at Google is in Testing mode.",
    ])
    expect(hints.map((hint) => hint.querySelector("a")?.getAttribute("href"))).toEqual([
      "https://calendarghost.com/docs/troubleshooting#the-google-calendar-api-is-turned-off",
      "https://calendarghost.com/docs/troubleshooting#google-accounts-stop-working-7-days-after-connecting",
    ])
    // Each link says which hint it fixes, so a screen reader can tell them apart.
    expect(hints[0]?.querySelector("a")?.getAttribute("aria-label")).toContain("How to fix: 2 people are affected")
  })

  it("shows no hints when nothing suggests one", async () => {
    await renderPeople(testI18n())
    expect(container.querySelector(".installation-hints")).toBeNull()
  })

  it("filters and sorts by sync status, kept in the address", async () => {
    await renderPeople(testI18n())
    await select("people-verdict", "review")
    expect(lastPeopleQuery()).toMatchObject({ verdict: "review", page: "1" })
    await click(header("Sync").querySelector("button")!)
    expect(lastPeopleQuery()).toMatchObject({ verdict: "review", sort: "verdict", order: "asc" })
    expect(header("Sync").getAttribute("aria-sort")).toBe("ascending")
    expect(window.location.search).toBe("?verdict=review&sort=verdict")
  })

  it("opens a person's page from their email", async () => {
    await renderPeople(testI18n())
    const link = personRow("robin@example.test").querySelector<HTMLAnchorElement>("a.person-email")!
    expect(link.getAttribute("href")).toBe("/people/user-robin")
    await click(link)
    expect(openPerson).toHaveBeenCalledWith("user-robin")
  })

  it("filters by role and state from the first page", async () => {
    await renderPeople(testI18n(), { search: "?page=3", people: () => jsonResponse(onePage([robin], { total: 200 })) })
    await select("people-role", "installation_administrator")
    expect(lastPeopleQuery()).toMatchObject({ role: "installation_administrator", page: "1" })
    await select("people-state", "active")
    expect(lastPeopleQuery()).toMatchObject({ role: "installation_administrator", state: "active", page: "1" })
    expect(window.location.search).toBe("?role=installation_administrator&state=active")
  })

  it("sorts by a column, and reverses it on a second click", async () => {
    await renderPeople(testI18n())
    expect(header("Joined").getAttribute("aria-sort")).toBe("ascending")
    await click(header("Email").querySelector("button")!)
    expect(lastPeopleQuery()).toMatchObject({ sort: "email", order: "asc" })
    expect(header("Email").getAttribute("aria-sort")).toBe("ascending")
    expect(header("Joined").getAttribute("aria-sort")).toBeNull()

    await click(header("Email").querySelector("button")!)
    expect(lastPeopleQuery()).toMatchObject({ sort: "email", order: "desc" })
    expect(header("Email").getAttribute("aria-sort")).toBe("descending")

    await click(header("Last sign-in").querySelector("button")!)
    expect(lastPeopleQuery()).toMatchObject({ sort: "last_sign_in", order: "asc" })
    expect(window.location.search).toBe("?sort=last_sign_in")
    expect(header("Role").querySelector("button")).toBeNull()
  })

  it("pages through everyone, saying who is shown", async () => {
    const page = (query: URLSearchParams) =>
      jsonResponse(onePage([robin], { page: Number(query.get("page")), total: 1234 }))
    await renderPeople(testI18n(), { search: "?page=2", people: page })
    const pages = container.querySelector<HTMLElement>("nav[aria-label='Pages of people']")!
    expect(pages.textContent).toContain("Showing 51 to 51 of 1,234 people")
    expect(button("Previous", pages).disabled).toBe(false)
    expect(button("Next", pages).disabled).toBe(false)

    const length = window.history.length
    await click(button("Next", pages))
    expect(lastPeopleQuery()).toMatchObject({ page: "3" })
    expect(window.location.search).toBe("?page=3")
    // Each page is its own history entry, so Back returns to the one before.
    expect(window.history.length).toBe(length + 1)

    await click(button("Previous", pages))
    await click(button("Previous", pages))
    expect(lastPeopleQuery()).toMatchObject({ page: "1" })
    expect(window.location.search).toBe("")
    expect(button("Previous", pages).disabled).toBe(true)
  })

  it("offers no other page when everyone fits on one", async () => {
    const full = Array.from({ length: 50 }, (_, index) => ({ ...robin, id: `user-${index}`, email: `p${index}@example.test` }))
    await renderPeople(testI18n(), { people: () => jsonResponse(onePage(full, { total: 50 })) })
    const pages = container.querySelector<HTMLElement>("nav[aria-label='Pages of people']")!
    expect(pages.textContent).toBe("Showing 1 to 50 of 50 people")
    expect(pages.querySelector("button")).toBeNull()
  })

  it("disables Next on the last page", async () => {
    await renderPeople(testI18n(), { search: "?page=2", people: () => jsonResponse(onePage([robin], { page: 2, total: 51 })) })
    const pages = container.querySelector<HTMLElement>("nav[aria-label='Pages of people']")!
    expect(button("Previous", pages).disabled).toBe(false)
    expect(button("Next", pages).disabled).toBe(true)
  })

  it("says when nobody matches, and clears the filters", async () => {
    await renderPeople(testI18n(), {
      search: "?search=zz&role=user&state=disabled",
      people: (query) => jsonResponse(onePage(query.has("search") ? [] : [me, robin])),
    })
    expect(container.querySelector(".empty-panel h3")?.textContent).toBe("Nobody matches")
    expect(container.querySelector("table")).toBeNull()
    await click(button("Clear filters"))
    expect(lastPeopleQuery()).toEqual({ sort: "joined", order: "asc", page: "1", page_size: "50" })
    expect(container.querySelector<HTMLInputElement>("#people-search")!.value).toBe("")
    expect(rows()).toHaveLength(2)
  })

  it("offers the first page when a linked page is past the end", async () => {
    await renderPeople(testI18n(), {
      search: "?page=9",
      people: (query) => jsonResponse(onePage(query.get("page") === "9" ? [] : [me], { total: 1 })),
    })
    expect(container.querySelector(".empty-panel h3")?.textContent).toBe("This page is empty")
    await click(button("Go to the first page"))
    expect(lastPeopleQuery()).toMatchObject({ page: "1" })
    expect(rows()).toHaveLength(1)
  })

  it("offers to try again when people cannot load", async () => {
    await renderPeople(testI18n(), { people: () => jsonResponse({ detail: "down" }, 500) })
    const failure = container.querySelector("[role='alert']")!
    expect(failure.querySelector("h1")?.textContent).toBe("People could not load")
    const before = peopleRequests()
    await click(button("Try again", failure))
    expect(peopleRequests()).toBe(before + 1)
  })

  it("makes someone an administrator", async () => {
    await renderPeople(testI18n(), {
      answers: { "PUT /api/v1/users/user-robin/role": jsonResponse({ ...robin, role: "installation_administrator" }) },
    })
    await choose("robin@example.test", "Make administrator")
    expect(sent("PUT", "/api/v1/users/user-robin/role")?.body).toEqual({ role: "installation_administrator" })
    expect(status()).toBe("robin@example.test is now an administrator.")
    // Shown beside the person it changed, not below the whole list.
    expect(personRow("robin@example.test").nextElementSibling?.querySelector(".command-result")?.textContent).toBe(
      "robin@example.test is now an administrator.",
    )
  })

  it("offers Change plan in each row's actions only once a plan exists", async () => {
    await renderPeople(testI18n())
    await click(personRow("robin@example.test").querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
    const labels = () =>
      [...personRow("robin@example.test").querySelectorAll("[role='menuitem'] .overflow-menu-label")].map(
        (label) => label.textContent,
      )
    expect(labels()).toEqual(["Make administrator", "Disable", "Create password reset link", "Delete"])

    act(() => root?.unmount())
    root = null
    await renderPeople(testI18n(), {
      people: () => jsonResponse(withPlans(onePage([me, robin, sam]))),
      answers: { "GET /api/v1/plans": jsonResponse(PLANS) },
    })
    await click(personRow("robin@example.test").querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
    expect(labels()).toEqual(["Make administrator", "Disable", "Change plan", "Create password reset link", "Delete"])
  })

  it("disables and enables a person", async () => {
    await renderPeople(testI18n(), {
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

  it("explains the server's refusal to remove the last administrator beside that person", async () => {
    const refusal = { detail: "last", code: "last_administrator", params: {} }
    await renderPeople(testI18n(), {
      people: () => jsonResponse(onePage([me, { ...robin, role: "installation_administrator" }])),
      answers: { "PUT /api/v1/users/user-robin/role": jsonResponse(refusal, 409) },
    })
    await choose("robin@example.test", "Remove administrator")
    expect(sent("PUT", "/api/v1/users/user-robin/role")?.body).toEqual({ role: "user" })
    expect(personRow("robin@example.test").nextElementSibling?.querySelector("[role='alert']")?.textContent).toBe(
      "Someone else must be an administrator first. Calendar Ghost always keeps one who can sign in.",
    )
  })

  it("creates a password reset link to pass on, shown once", async () => {
    await renderPeople(testI18n())
    await choose("robin@example.test", "Create password reset link")
    expect(sent("POST", "/api/v1/users/user-robin/password-reset-links")).toBeDefined()
    const reveal = container.querySelector(".link-reveal")!
    expect(reveal.querySelector("h3")?.textContent).toBe("Copy the password reset link for robin@example.test now")
    expect(reveal.querySelector<HTMLInputElement>("input")!.value).toBe(`${ORIGIN}/password-reset#reset_synthetic`)

    await click(button("Done", reveal))
    expect(container.querySelector(".link-reveal")).toBeNull()
    expect(document.activeElement?.getAttribute("aria-label")).toBe("Actions for robin@example.test")
  })

  it("keeps password recovery reachable for another User admitted under Only Me", async () => {
    await renderPeople(testI18n(), { answers: { "GET /api/v1/registration": jsonResponse({ policy: "only_me", only_me_available: false }) } })
    expect(container.querySelector("#invite-someone")).toBeNull()
    expect(container.querySelector('a[href="/settings/administration"]')).not.toBeNull()
    await choose("robin@example.test", "Create password reset link")
    expect(container.querySelector<HTMLInputElement>(".link-reveal input")!.value).toBe(`${ORIGIN}/password-reset#reset_synthetic`)
  })

  it("runs one command at a time, so a second reset link cannot revoke the one shown", async () => {
    await renderPeople(testI18n())
    // Hold each reset link's answer, so a later request can answer first.
    const held: ((response: Response) => void)[] = []
    const served = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const path = input instanceof Request ? input.url : String(input)
      if (init?.method !== "POST" || !path.endsWith("/password-reset-links")) return served(input, init)
      return new Promise<Response>((resolve) => held.push(resolve))
    })
    const resetFor = (number: number) => jsonResponse({ id: `reset-${number}`, token: `reset_${number}`, expires_at: nextWeek }, 201)
    const resetItem = () =>
      [...personRow("robin@example.test").querySelectorAll<HTMLButtonElement>("[role='menuitem']")].find(
        (item) => item.querySelector(".overflow-menu-label")?.textContent === "Create password reset link",
      )!

    // Two quick clicks, before the page shows that the first is running.
    await click(personRow("robin@example.test").querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
    const item = resetItem()
    act(() => {
      item.click()
      item.click()
    })
    await settle()
    expect(held).toHaveLength(1)

    // While it runs, every command on everyone waits, deletion included.
    await click(personRow("sam@example.test").querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
    const samItems = [...personRow("sam@example.test").querySelectorAll<HTMLButtonElement>("[role='menuitem']")]
    expect(samItems.map((menuItem) => menuItem.getAttribute("aria-disabled"))).toEqual(["true", "true", "true", "true"])
    await click(samItems.at(-1)!)
    expect(container.querySelector("#delete-person-user-sam")).toBeNull()
    await click(personRow("robin@example.test").querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
    await click(resetItem())
    expect(held).toHaveLength(1)

    // Answer in reverse order: any later request first, then the first.
    for (const [index, answer] of [...held.entries()].reverse()) {
      act(() => answer(resetFor(index + 1)))
      await settle()
    }
    expect(container.querySelector<HTMLInputElement>(".link-reveal input")!.value).toBe(`${ORIGIN}/password-reset#reset_1`)
    expect(personRow("robin@example.test").querySelector("[aria-haspopup='menu']")).not.toBeNull()
    await click(personRow("robin@example.test").querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
    expect(resetItem().getAttribute("aria-disabled")).toBeNull()
  })

  it("keeps running one command at a time when the page opens again", async () => {
    const i18n = testI18n()
    const queryClient = await renderPeople(i18n)
    const held: ((response: Response) => void)[] = []
    const served = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const path = input instanceof Request ? input.url : String(input)
      if (init?.method !== "POST" || !path.endsWith("/password-reset-links")) return served(input, init)
      return new Promise<Response>((resolve) => held.push(resolve))
    })
    const resetFor = (number: number) => jsonResponse({ id: `reset-${number}`, token: `reset_${number}`, expires_at: nextWeek }, 201)

    await choose("robin@example.test", "Create password reset link")
    expect(held).toHaveLength(1)

    // Choosing People again opens a fresh page while the first link is still on its way.
    showPeople(i18n, queryClient, 1)
    await settle()
    await click(personRow("robin@example.test").querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
    const items = [...personRow("robin@example.test").querySelectorAll<HTMLButtonElement>("[role='menuitem']")]
    expect(items.map((item) => item.getAttribute("aria-disabled"))).toEqual(["true", "true", "true", "true"])
    await click(items.find((item) => item.textContent.startsWith("Create password reset link"))!)
    expect(held).toHaveLength(1)

    // A disabled item leaves the menu open; close it before choosing again.
    await click(personRow("robin@example.test").querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
    act(() => held[0]!(resetFor(1)))
    await settle()
    await choose("robin@example.test", "Create password reset link")
    expect(held).toHaveLength(2)
    act(() => held[1]!(resetFor(2)))
    await settle()
    expect(container.querySelector<HTMLInputElement>(".link-reveal input")!.value).toBe(`${ORIGIN}/password-reset#reset_2`)
  })

  it("says plainly what deleting someone removes, and deletes only after confirming", async () => {
    await renderPeople(testI18n())
    await click(personRow("robin@example.test").querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
    const item = [...personRow("robin@example.test").querySelectorAll("[role='menuitem']")].at(-1)!
    expect(item.textContent).toBe(
      "DeleteDeletes their sign-in, rules, and calendar connections, and the events their rules wrote. Their calendar accounts and their own events stay.",
    )
    await click(item as HTMLElement)
    const confirmation = container.querySelector<HTMLElement>("#delete-person-user-robin")!
    expect(confirmation.querySelector("h3")?.textContent).toBe("Delete robin@example.test permanently?")
    expect(confirmation.querySelector("p")?.textContent).toBe(
      "This deletes their sign-in, rules, calendar connections, tokens, and Activity. The events their rules wrote are deleted from their calendars wherever Calendar Ghost can still reach them. Their own events and their calendar accounts stay as they are. Backups taken before now keep their records until they rotate out. This cannot be undone.",
    )
    expect(sent("DELETE", "/api/v1/users/user-robin")).toBeUndefined()

    await click(button("Delete permanently", confirmation))
    expect(sent("DELETE", "/api/v1/users/user-robin")).toBeDefined()
    expect(status()).toBe("robin@example.test was deleted. 5 events their rules wrote were deleted.")
  })

  it("shows People first, with Invitations a tab away that counts those waiting, then Plans", async () => {
    await renderPeople(testI18n())
    const tabs = [...container.querySelectorAll<HTMLAnchorElement>("nav.page-tabs a")]
    expect(tabs.map((tab) => [tab.textContent, tab.getAttribute("href")])).toEqual([
      ["Everyone", "/people"],
      ["Invitations11 waiting", "/people/invitations"],
      ["Plans", "/people/plans"],
    ])
    expect(tabs[0]!.getAttribute("aria-current")).toBe("page")
    expect(rows()).toHaveLength(3)

    await click(tabs[1]!)
    expect(window.location.pathname).toBe("/people/invitations")
    expect(rows()).toHaveLength(0)
    expect(container.querySelector("#invitations-title")?.textContent).toBe("Invitations waiting")
    expect(container.querySelector(".invitation-item h3")?.textContent).toMatch(/^Expires in [67] days$/)
  })

  it.each([
    ["/people/invitations", "Invitations – People – Calendar Ghost"],
    ["/people/plans", "Plans – People – Calendar Ghost"],
  ])("names the browser tab after the tab shown at %s", async (path, title) => {
    await renderPeople(testI18n(), { path })
    expect(document.title).toBe(title)
  })

  it("says what each tab is for, and offers Invite someone beside the page title, but not on Plans", async () => {
    await renderPeople(testI18n(), { answers: { "GET /api/v1/plans": jsonResponse(PLANS) } })
    const intro = () => container.querySelector(".page-intro-current")?.textContent
    const actions = () =>
      [...container.querySelectorAll(".heading-action:not(.heading-action-placeholder) button")].map((item) =>
        item.textContent.trim(),
      )
    expect(intro()).toBe(
      "The people who sign in here and whether their synchronization works. You see their email, role, sign-ins, plan, and sync status, never their calendars, connected account emails, or events.",
    )
    expect(actions()).toEqual(["Invite someone"])
    const tabs = [...container.querySelectorAll<HTMLAnchorElement>("nav.page-tabs a")]
    await click(tabs[2]!)
    expect(intro()).toBe(
      "Plans set how much each person can use and how soon their calendars sync.",
    )
    // New plan sits in the catalog's head, on the list it adds to.
    expect(actions()).toEqual([])
    expect(container.querySelector(".page-intro-reserve")?.textContent).toBe(
      "The people who sign in here and whether their synchronization works. You see their email, role, sign-ins, plan, and sync status, never their calendars, connected account emails, or events.",
    )
    expect(container.querySelector(".heading-action-placeholder button")?.textContent.trim()).toBe("Invite someone")
    await click(tabs[1]!)
    expect(actions()).toEqual(["Invite someone"])
    expect(container.querySelector(".page-intro-reserve")).toBeNull()
    expect(container.querySelector(".heading-action-placeholder")).toBeNull()
  })

  it("opens Plans in place, and asks for plans only there", async () => {
    await renderPeople(testI18n())
    expect(calls.some((call) => call.path === "/api/v1/plans")).toBe(false)
    const plans = [...container.querySelectorAll<HTMLAnchorElement>("nav.page-tabs a")].find(
      (tab) => tab.textContent === "Plans",
    )!
    await click(plans)
    expect(window.location.pathname).toBe("/people/plans")
    expect(plans.getAttribute("aria-current")).toBe("page")
    expect(rows()).toHaveLength(0)
    expect(container.querySelector("#plans-title")?.textContent).toBe("Plans")
    expect(calls.some((call) => call.method === "GET" && call.path === "/api/v1/plans")).toBe(true)
  })

  it("returns to the person you opened when you come back to People", async () => {
    await renderPeople(testI18n())
    const link = personRow("robin@example.test").querySelector<HTMLAnchorElement>("a.person-email")!
    await click(link)
    act(() => root?.unmount())
    root = createRoot(container)
    showPeople(testI18n(), new QueryClient({ defaultOptions: { queries: { retry: false } } }), 1)
    await settle()
    expect(document.activeElement?.textContent).toBe("robin@example.test")
  })

  it("opens at Invitations from its own address, and says when none are waiting", async () => {
    await renderPeople(testI18n(), { path: "/people/invitations", answers: { "GET /api/v1/invitations": jsonResponse([]) } })
    expect(container.querySelector("nav.page-tabs [aria-current='page']")?.textContent).toBe("Invitations")
    expect(container.querySelector(".empty-panel h3")?.textContent).toBe("No invitations are waiting")
  })

  it("invites someone with a link shown once, and revokes a waiting invitation", async () => {
    await renderPeople(testI18n())
    await click(button("Invite someone"))
    expect(sent("POST", "/api/v1/invitations")).toBeDefined()
    // Creating one opens Invitations, where the link is.
    expect(window.location.pathname).toBe("/people/invitations")
    const reveal = container.querySelector(".link-reveal")!
    expect(reveal.querySelector<HTMLInputElement>("input")!.value).toBe(`${ORIGIN}/invitation#inv_synthetic`)
    expect(reveal.textContent).toContain("It works once, until")

    await click(button("Done", reveal))
    // The link is gone, so focus returns to the button that made it.
    expect(document.activeElement?.id).toBe("invite-someone")

    await click(button("Revoke"))
    expect(sent("DELETE", "/api/v1/invitations/inv-1")).toBeDefined()
    expect(document.activeElement?.id).toBe("invitations-title")
  })
})

/** The conjunction `format.list` writes between people's emails comes from Intl locale data, like dates. */
const LIST_WORDS = new Intl.ListFormat("en-US", { style: "long", type: "conjunction" })
  .formatToParts(["a", "b"])
  .filter((part) => part.type === "literal")
  .map((part) => part.value.trim())

/** What giving `people` the Plan `has` answers, dry run or not: the Plan each had, and nothing over. */
function given(people: Person[], has = { key: "free", name: "Free", on_default: false }): Response {
  return jsonResponse({
    dry_run: false,
    people: people.map((person) => ({ user_id: person.id, email: person.email, had: PLANS_HELD[person.id]?.has ?? null, has, over: [] })),
  })
}

/** Everyone once a Plan exists: Dana, Robin and Jordan on Family, Sam on the default, Free. */
async function renderPlanned(i18n: I18n, answers: Record<string, Response> = {}) {
  return renderPeople(i18n, {
    people: () => jsonResponse(withPlans(onePage([me, robin, jordan, sam]))),
    answers: { "GET /api/v1/plans": jsonResponse(PLANS), ...answers },
  })
}

function checkbox(label: string): HTMLInputElement {
  const found = container.querySelector<HTMLInputElement>(`input[type='checkbox'][aria-label=${JSON.stringify(label)}]`)
  if (found) return found
  const labelled = [...container.querySelectorAll<HTMLInputElement>("input[type='checkbox']")].find((input) =>
    [...(input.labels ?? [])].some((item) => item.textContent.trim() === label),
  )
  if (!labelled) throw new Error(`No checkbox ${label}`)
  return labelled
}

function bulkBar(): HTMLElement {
  return container.querySelector<HTMLElement>(".people-bulk-bar")!
}

function popover(): HTMLElement | null {
  return container.querySelector<HTMLElement>("dialog")
}

function choice(label: string, scope: ParentNode = popover()!): HTMLInputElement {
  const found = [...scope.querySelectorAll<HTMLInputElement>("input[type='radio']")].find((radio) =>
    [...(radio.labels ?? [])].some((item) => item.textContent.startsWith(label)),
  )
  if (!found) throw new Error(`No choice ${label}`)
  return found
}

/** Each choice in the popover: its name with its badges, and whether it is chosen. */
function choices(scope: ParentNode = popover()!): [string, boolean][] {
  return [...scope.querySelectorAll<HTMLInputElement>("input[type='radio']")].map((radio) => [
    [...(radio.labels ?? [])].map((item) => item.textContent).join(" "),
    radio.checked,
  ])
}

/** What a dry run says under a choice, once it answers. */
function noteUnder(label: string): string | undefined {
  const ids = choice(label).getAttribute("aria-describedby")?.split(" ") ?? []
  return ids.length > 1 ? document.getElementById(ids.at(-1)!)?.textContent : undefined
}

function toast(): string | null | undefined {
  return container.querySelector("[role='status'][aria-atomic]")?.textContent
}

function assignments(): unknown[] {
  return calls.filter((call) => call.method === "POST" && call.path === "/api/v1/plan-assignments").map((call) => call.body)
}

function press(target: Element, key: string) {
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }))
  })
}

describe("Changing plans from Everyone", () => {
  it("selects people by row or the whole page, and says so in the bar above the table", async () => {
    await renderPlanned(testI18n())
    expect(bulkBar().textContent).toBe("Select people to change their plan together.")
    expect(container.querySelector(".people-bulk-bar [role='region'], .people-bulk-bar[role='region']")).not.toBeNull()

    await click(checkbox("Select robin@example.test"))
    await click(checkbox("Select jordan@example.test"))
    expect(checkbox("Select robin@example.test").checked).toBe(true)
    expect(personRow("robin@example.test").getAttribute("data-selected")).toBe("true")
    expect(bulkBar().querySelector(".people-bulk-count")?.textContent).toBe("2 selected")
    expect(button("Change plan", bulkBar()).getAttribute("aria-haspopup")).toBe("dialog")
    expect(checkbox("Select all").indeterminate).toBe(true)

    await click(checkbox("Select all"))
    expect(bulkBar().querySelector(".people-bulk-count")?.textContent).toBe("4 selected")
    expect(checkbox("Select all").indeterminate).toBe(false)
    expect(checkbox("Select all").checked).toBe(true)
    await click(checkbox("Select all"))
    expect(bulkBar().querySelector(".people-bulk-count")).toBeNull()

    await click(checkbox("Select sam@example.test"))
    await click(button("Clear selection", bulkBar()))
    expect(checkbox("Select sam@example.test").checked).toBe(false)
    expect(document.activeElement).toBe(checkbox("Select all"))
  })

  it("offers no selection while no plan exists", async () => {
    await renderPeople(testI18n())
    expect(container.querySelector("input[type='checkbox']")).toBeNull()
    expect(container.querySelector(".people-bulk-bar")).toBeNull()
  })

  it("forgets the selection when the search or filters change", async () => {
    await renderPlanned(testI18n())
    await click(checkbox("Select robin@example.test"))
    await select("people-role", "user")
    expect(checkbox("Select robin@example.test").checked).toBe(false)
    expect(bulkBar().querySelector(".people-bulk-count")).toBeNull()
  })

  it("changes several people's plan from a popover, after a dry run, with Undo in a toast", async () => {
    await renderPlanned(testI18n(), { "POST /api/v1/plan-assignments": given([robin, jordan]) })
    await click(checkbox("Select robin@example.test"))
    await click(checkbox("Select jordan@example.test"))
    const change = button("Change plan", bulkBar())
    await click(change)

    const dialog = popover()!
    expect(change.getAttribute("aria-expanded")).toBe("true")
    expect(change.getAttribute("aria-controls")).toBe(dialog.id)
    const title = dialog.querySelector("h3")!
    expect(title.textContent).toBe("Change plan for 2 people")
    expect(dialog.getAttribute("aria-labelledby")).toBe(title.id)
    // One line per plan, the default first; what both have now is chosen and marked Current.
    expect(choices()).toEqual([
      ["Free Default", false],
      ["Family Current", true],
    ])
    expect(dialog.querySelector(".plan-change-note")?.textContent).toBe(
      "People on the default plan move with it when the default changes.",
    )
    expect(document.activeElement).toBe(choice("Family"))

    // Free is the default, so they follow it.
    await click(choice("Free"))
    expect(assignments()).toEqual([{ plans: { "user-robin": null, "user-jordan": null }, dry_run: true }])
    expect(noteUnder("Free")).toBe("Nobody would be over a limit")

    await click(button("Save", dialog))
    expect(assignments().at(-1)).toEqual({ plans: { "user-robin": null, "user-jordan": null }, dry_run: false })
    expect(popover()).toBeNull()
    expect(toast()).toBe("2 people now have Free.")
    // The selection is done with: the bar is at rest, and focus waits on the list's heading.
    expect(bulkBar().querySelector(".people-bulk-count")).toBeNull()
    expect(document.activeElement?.id).toBe("people-list-title")

    await click(button("Undo"))
    expect(assignments().at(-1)).toEqual({ plans: { "user-robin": "family", "user-jordan": "family" }, dry_run: false })
    expect(toast()).toBe("2 people have their plans back.")
  })

  it("counts who has each plan when they differ, and asks for a choice before Save sends anything", async () => {
    await renderPlanned(testI18n(), { "POST /api/v1/plan-assignments": given([robin, sam]) })
    await click(checkbox("Select robin@example.test"))
    await click(checkbox("Select sam@example.test"))
    await click(button("Change plan", bulkBar()))
    expect(choices()).toEqual([
      ["Free Default 1 has it", false],
      ["Family 1 has it", false],
    ])
    expect(document.activeElement).toBe(choice("Free"))

    await click(button("Save", popover()!))
    const group = popover()!.querySelector("[role='radiogroup']")!
    expect(group.getAttribute("aria-invalid")).toBe("true")
    expect(popover()!.querySelector("[role='alert']")?.textContent).toBe("Choose a plan first.")
    expect(document.getElementById(group.getAttribute("aria-describedby")!.split(" ").at(-1)!)?.textContent).toBe(
      "Choose a plan first.",
    )
    expect(document.activeElement).toBe(choice("Free"))
    expect(assignments()).toEqual([])

    await click(choice("Family"))
    expect(popover()!.querySelector("[role='alert']")).toBeNull()
    expect(group.hasAttribute("aria-invalid")).toBe(false)
    expect(assignments()).toEqual([{ plans: { "user-robin": "family", "user-sam": "family" }, dry_run: true }])
    expect(noteUnder("Family")).toBe("Nobody would be over a limit")

    // Robin had Family of their own and Sam followed Free: Undo gives each theirs in one request.
    await click(button("Save", popover()!))
    await click(button("Undo"))
    expect(assignments().slice(2)).toEqual([{ plans: { "user-robin": "family", "user-sam": null }, dry_run: false }])
    expect(toast()).toBe("2 people have their plans back.")
  })

  it("says what Undo did, or why it could not, once the change leaves nobody in the list", async () => {
    const changes = () => assignments().filter((body) => !(body as { dry_run: boolean }).dry_run).length
    // Everyone narrowed to Family: once its people have Free nobody is left, and Undo brings them back.
    const family = () => jsonResponse(withPlans(onePage(changes() % 2 === 1 ? [] : [robin, jordan])))
    await renderPeople(testI18n(), {
      search: "?plan=family",
      people: family,
      answers: { "GET /api/v1/plans": jsonResponse(PLANS), "POST /api/v1/plan-assignments": given([robin, jordan]) },
    })
    async function giveEveryoneFree() {
      await click(checkbox("Select all"))
      await click(button("Change plan", bulkBar()))
      await click(choice("Free"))
      await click(button("Save", popover()!))
      expect(toast()).toBe("2 people now have Free.")
      expect(rows()).toHaveLength(0)
      expect(container.querySelector(".people-bulk-bar")).toBeNull()
      // The bar left with the people; focus stays on the list's heading rather than nowhere.
      expect(document.activeElement?.id).toBe("people-list-title")
    }

    await giveEveryoneFree()
    await click(button("Undo"))
    expect(assignments().at(-1)).toEqual({ plans: { "user-robin": "family", "user-jordan": "family" }, dry_run: false })
    expect(toast()).toBe("2 people have their plans back.")
    expect(rows()).toHaveLength(2)

    await giveEveryoneFree()
    const served = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation((input, init) =>
      init?.method === "POST" && (input as string).startsWith("/api/v1/plan-assignments")
        ? Promise.resolve(jsonResponse({ detail: "gone", code: "plan_not_found", params: {} }, 404))
        : served(input, init),
    )
    await click(button("Undo"))
    expect(toast()).toBe("This plan no longer exists. Reload to see the current plans.")
    expect(container.querySelector(".people-roster [role='alert']")).toBeNull()
  })

  it("says what Undo did once Everyone is gone, as when Plans opens", async () => {
    await renderPlanned(testI18n(), { "POST /api/v1/plan-assignments": given([robin]) })
    await click(checkbox("Select robin@example.test"))
    await click(button("Change plan", bulkBar()))
    await click(choice("Free"))
    await click(button("Save", popover()!))
    await click([...container.querySelectorAll<HTMLAnchorElement>("nav.page-tabs a")].find((tab) => tab.textContent === "Plans")!)
    expect(rows()).toHaveLength(0)
    await click(button("Undo"))
    expect(assignments().at(-1)).toEqual({ plans: { "user-robin": "family" }, dry_run: false })
    expect(toast()).toBe("robin@example.test has their plan back.")
  })

  it("leaves the popover where it placed itself: its chooser does not scroll the page as it opens", async () => {
    await renderPlanned(testI18n())
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined)
    await click(checkbox("Select robin@example.test"))
    await click(button("Change plan", bulkBar()))
    const dialog = popover()!
    expect(scrolled.mock.contexts.filter((element) => dialog.contains(element as Node))).toEqual([])
  })

  it("marks the popover's rows at their end as it opens and once scrolled there, where the fade at its cut edge goes, and keeps every row readable", async () => {
    await renderPlanned(testI18n())
    await choose("robin@example.test", "Change plan")
    const list = popover()!.querySelector<HTMLElement>(".plan-change-options")!
    // Nothing is laid out here, so every row fits above the cut edge: no fade from the start.
    expect(list.hasAttribute("data-end")).toBe(true)
    // Capped, the rows scroll inside, and some sit below the cut edge.
    Object.defineProperty(list, "clientHeight", { configurable: true, value: 120 })
    Object.defineProperty(list, "scrollHeight", { configurable: true, value: 200 })
    const scrollTo = (top: number) => {
      list.scrollTop = top
      act(() => {
        list.dispatchEvent(new Event("scroll"))
      })
    }
    scrollTo(30)
    expect(list.hasAttribute("data-end")).toBe(false)
    scrollTo(80)
    expect(list.hasAttribute("data-end")).toBe(true)
    // The fade is only drawn: a screen reader still has every plan.
    expect(choices()).toEqual([
      ["Free Default", false],
      ["Family Current", true],
    ])
  })

  it("closes the popover on Escape or Cancel, changing nothing, with focus back on Change plan", async () => {
    await renderPlanned(testI18n(), { "POST /api/v1/plan-assignments": given([robin, sam]) })
    await click(checkbox("Select robin@example.test"))
    await click(checkbox("Select sam@example.test"))
    await click(button("Change plan", bulkBar()))
    await click(choice("Free"))
    press(choice("Free"), "Escape")
    await settle()
    expect(popover()).toBeNull()
    expect(document.activeElement).toBe(button("Change plan", bulkBar()))

    await click(button("Change plan", bulkBar()))
    // Opened again, nothing is chosen, as they have different plans.
    expect(choices().some(([, checked]) => checked)).toBe(false)
    await click(button("Cancel", popover()!))
    expect(popover()).toBeNull()
    expect(document.activeElement).toBe(button("Change plan", bulkBar()))
    expect(assignments().every((body) => (body as { dry_run: boolean }).dry_run)).toBe(true)
  })

  it("keeps the popover open and waiting while the change is on its way, and shows a refusal in it", async () => {
    let answer: (response: Response) => void = () => undefined
    await renderPlanned(testI18n(), { "POST /api/v1/plan-assignments": given([robin, jordan]) })
    await click(checkbox("Select robin@example.test"))
    await click(checkbox("Select jordan@example.test"))
    await click(button("Change plan", bulkBar()))
    await click(choice("Free"))
    expect(noteUnder("Free")).toBe("Nobody would be over a limit")
    const held = new Promise<Response>((resolve) => {
      answer = resolve
    })
    const served = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation((input, init) =>
      init?.method === "POST" && (input as string).startsWith("/api/v1/plan-assignments") ? held : served(input, init),
    )
    const save = button("Save", popover()!)
    act(() => save.focus())
    await click(save)
    expect(save.getAttribute("aria-disabled")).toBe("true")
    expect(save.getAttribute("aria-busy")).toBe("true")
    expect(button("Cancel", popover()!).getAttribute("aria-disabled")).toBe("true")
    expect(document.activeElement).toBe(save)
    press(save, "Escape")
    expect(popover()).not.toBeNull()

    act(() => answer(jsonResponse({ detail: "gone", code: "invalid_assignment", params: {} }, 422)))
    await settle()
    expect(popover()?.querySelector("[role='alert']")?.textContent).not.toBe("")
    expect(popover()?.querySelector("[role='alert']")).not.toBeNull()
    expect(toast()).toBe("")
  })

  it("changes one person's plan from their row's actions, with Undo in a toast", async () => {
    await renderPlanned(testI18n(), {
      "POST /api/v1/plan-assignments": given([robin], { key: "free", name: "Free", on_default: true }),
    })
    await choose("robin@example.test", "Change plan")
    const dialog = popover()!
    expect(personRow("robin@example.test").contains(dialog)).toBe(true)
    // The popover is the row's only next step: no empty row of details opens under it.
    expect(personRow("robin@example.test").nextElementSibling?.classList.contains("person-details-row")).toBe(false)
    expect(dialog.querySelector("h3")?.textContent).toBe("Change plan for robin@example.test")
    expect(choices()).toEqual([
      ["Free Default", false],
      ["Family Current", true],
    ])
    expect(document.activeElement).toBe(choice("Family"))

    await click(choice("Free"))
    expect(assignments().at(-1)).toEqual({ plans: { "user-robin": null }, dry_run: true })
    expect(noteUnder("Free")).toBe("Within every limit")
    await click(button("Save", dialog))
    expect(assignments().at(-1)).toEqual({ plans: { "user-robin": null }, dry_run: false })
    expect(popover()).toBeNull()
    expect(toast()).toBe("robin@example.test now has Free.")
    // The toast says it, so no line under the row repeats it.
    expect(personRow("robin@example.test").nextElementSibling?.classList.contains("person-details-row")).toBe(false)
    expect(document.activeElement?.getAttribute("aria-label")).toBe("Actions for robin@example.test")

    await click(button("Undo"))
    expect(assignments().at(-1)).toEqual({ plans: { "user-robin": "family" }, dry_run: false })
    expect(toast()).toBe("robin@example.test has their plan back.")
  })

  it("says what a change from a row did, with Undo, even once it leaves nobody in the list", async () => {
    const changes = () => assignments().filter((body) => !(body as { dry_run: boolean }).dry_run).length
    // Everyone narrowed to Family: once robin has Free nobody is left, and Undo brings them back.
    const family = () => jsonResponse(withPlans(onePage(changes() % 2 === 1 ? [] : [robin])))
    await renderPeople(testI18n(), {
      search: "?plan=family",
      people: family,
      answers: { "GET /api/v1/plans": jsonResponse(PLANS), "POST /api/v1/plan-assignments": given([robin]) },
    })
    await choose("robin@example.test", "Change plan")
    await click(choice("Free"))
    await click(button("Save", popover()!))
    expect(rows()).toHaveLength(0)
    expect(toast()).toBe("robin@example.test now has Free.")
    // The row and its actions are gone, so focus waits on the list's heading.
    expect(document.activeElement?.id).toBe("people-list-title")

    await click(button("Undo"))
    expect(assignments().at(-1)).toEqual({ plans: { "user-robin": "family" }, dry_run: false })
    expect(toast()).toBe("robin@example.test has their plan back.")
    expect(rows()).toHaveLength(1)
  })

  it("shows a refused change for one person in their popover, and nothing on the row", async () => {
    await renderPlanned(testI18n(), { "POST /api/v1/plan-assignments": given([robin]) })
    await choose("robin@example.test", "Change plan")
    await click(choice("Free"))
    const served = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation((input, init) =>
      init?.method === "POST" && (input as string).startsWith("/api/v1/plan-assignments")
        ? Promise.resolve(jsonResponse({ detail: "gone", code: "plan_not_found", params: {} }, 404))
        : served(input, init),
    )
    await click(button("Save", popover()!))
    expect(popover()?.querySelector("[role='alert']")?.textContent).toBe(
      "This plan no longer exists. Reload to see the current plans.",
    )
    expect(personRow("robin@example.test").nextElementSibling?.classList.contains("person-details-row")).toBe(false)
    expect(toast()).toBe("")
    await click(button("Cancel", popover()!))
    expect(container.querySelector("[role='alert']")).toBeNull()
    expect(document.activeElement?.getAttribute("aria-label")).toBe("Actions for robin@example.test")
  })

  it("has no untranslated text with people selected and the popover open", async () => {
    const i18n = pseudoI18n()
    await renderPlanned(i18n, { "POST /api/v1/plan-assignments": given([robin, jordan]) })
    const boxes = [...container.querySelectorAll<HTMLInputElement>("tbody input[type='checkbox']")]
    await click(boxes[1]!)
    await click(boxes[2]!)
    await click(bulkBar().querySelector<HTMLButtonElement>("button[aria-haspopup='dialog']")!)
    await click(popover()!.querySelectorAll<HTMLInputElement>("input[type='radio']")[0]!)
    const fixtures = [me.email!, robin.email!, sam.email!, jordan.email!, "Family", "Free", ...LIST_WORDS, ...dateWords()]
    expect(untranslatedText(container, fixtures)).toEqual([])
  })
})

describe("Invitations and plans", () => {
  it("says which plan an invited person gets once a plan is the default", async () => {
    await renderPeople(testI18n(), { path: "/people/invitations", answers: { "GET /api/v1/plans": jsonResponse(PLANS) } })
    expect(container.querySelector(".invitation-plan")?.textContent).toBe(
      "They get the default plan, Free. You can change it after they join.",
    )
  })

  it("says nothing about plans with no default, or when plans cannot be read", async () => {
    await renderPeople(testI18n(), { path: "/people/invitations" })
    expect(calls.some((call) => call.path === "/api/v1/plans")).toBe(true)
    expect(container.querySelector(".invitation-plan")).toBeNull()

    act(() => root?.unmount())
    root = null
    await renderPeople(testI18n(), {
      path: "/people/invitations",
      answers: { "GET /api/v1/plans": jsonResponse({ detail: "no", code: "plans_unavailable", params: {} }, 503) },
    })
    expect(container.querySelector(".invitation-plan")).toBeNull()
    expect(container.querySelector("[role='alert']")).toBeNull()
  })
})
