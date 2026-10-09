/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { dateWords, pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { PendingInvitation, PeoplePage, Person, PersonRow, SessionStatus } from "@/lib/api"

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
const invitation: PendingInvitation = { id: "inv-1", created_at: justNow, expires_at: nextWeek }

const session: SessionStatus = {
  authenticated: true,
  installation_sends_email: true,
  user: { id: me.id, email: me.email, role: "installation_administrator", notify_by_email: true, language: null },
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
}

function onePage(users: Person[], page: Partial<PeoplePage> = {}): PeoplePage {
  return { users: users.map((user) => ({ ...NOTHING_SET_UP, ...user })), total: users.length, page: 1, page_size: 50, ...page }
}

type Call = { method: string; path: string; query: URLSearchParams; body: unknown }
type Scenario = {
  /** The address the page opens at, after `/people`. */
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
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <PeopleView key={visit} />
          </QueryClientProvider>
        </ThemeProvider>
      </StaticI18nProvider>,
    )
  })
}

async function renderPeople(i18n: I18n, scenario: Scenario = {}) {
  page().happyDOM.setURL(`${ORIGIN}/people${scenario.search ?? ""}`)
  serve(scenario)
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
  return [...row.querySelectorAll("td")].map((cell) => cell.textContent.trim())
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

function status(): string | undefined {
  return container.querySelector("[aria-labelledby='people-list-title'] p[role='status']:not(.sr-only)")?.textContent
}

describe("People page", () => {
  it("has no untranslated text with people, invitations, menus, and links to pass on", async () => {
    await renderPeople(pseudoI18n(), { people: () => jsonResponse(onePage([me, robin, sam, firstUser])) })
    await click(container.querySelector<HTMLButtonElement>("#invite-someone")!)
    await click(personRow("robin@example.test").querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!)
    expect(container.querySelector("[role='menu']")).not.toBeNull()
    expect(container.querySelector(".link-reveal")).not.toBeNull()
    const fixtures = [me.email!, robin.email!, sam.email!, `${ORIGIN}/invitation#inv_synthetic`, ...dateWords()]
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
      "Role",
      "State",
      "Joined",
      "Last sign-in",
      "Actions",
    ])
    expect(cells(personRow("dana@example.test"))).toEqual([
      "dana@example.testYou",
      "Administrator",
      "Active",
      "just now",
      "just now",
      "",
    ])
    expect(personRow("dana@example.test").querySelector("[aria-haspopup='menu']")).toBeNull()
    expect(cells(personRow("robin@example.test")).slice(1, 5)).toEqual(["User", "Active", "just now", "Never"])
    expect(cells(personRow("sam@example.test"))[2]).toBe("Disabled")
    expect(personRow("No email yet").querySelector("[aria-haspopup='menu']")).not.toBeNull()
    expect(personRow("robin@example.test").querySelector("[aria-haspopup='menu']")?.getAttribute("aria-label")).toBe(
      "Actions for robin@example.test",
    )
  })

  it("restores the search, filters, sort, and page from the address", async () => {
    await renderPeople(testI18n(), {
      search: "?search=rob&role=user&state=disabled&sort=email&order=desc&page=2",
      people: () => jsonResponse(onePage([robin], { page: 2, total: 51 })),
    })
    expect(lastPeopleQuery()).toEqual({
      search: "rob",
      role: "user",
      state: "disabled",
      sort: "email",
      order: "desc",
      page: "2",
      page_size: "50",
    })
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

  it("disables Next on the last page", async () => {
    const full = Array.from({ length: 50 }, (_, index) => ({ ...robin, id: `user-${index}`, email: `p${index}@example.test` }))
    await renderPeople(testI18n(), { people: () => jsonResponse(onePage(full, { total: 50 })) })
    const pages = container.querySelector<HTMLElement>("nav[aria-label='Pages of people']")!
    expect(pages.textContent).toContain("Showing 1 to 50 of 50 people")
    expect(button("Previous", pages).disabled).toBe(true)
    expect(button("Next", pages).disabled).toBe(true)
  })

  it("says when nobody matches, and clears the filters", async () => {
    await renderPeople(testI18n(), {
      search: "?search=zz&role=user&state=disabled",
      people: (query) => jsonResponse(onePage(query.has("search") ? [] : [me, robin])),
    })
    expect(container.querySelector(".empty-panel h2")?.textContent).toBe("Nobody matches")
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
    expect(container.querySelector(".empty-panel h2")?.textContent).toBe("This page is empty")
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
      "DeleteDeletes their sign-in, rules, and Google connections, and the events their rules wrote. Their Google accounts and their own events stay.",
    )
    await click(item as HTMLElement)
    const confirmation = container.querySelector<HTMLElement>("#delete-person-user-robin")!
    expect(confirmation.querySelector("h3")?.textContent).toBe("Delete robin@example.test permanently?")
    expect(confirmation.querySelector("p")?.textContent).toBe(
      "This deletes their sign-in, rules, Google connections, tokens, and Activity. The events their rules wrote are deleted from their calendars wherever Calendar Ghost can still reach them. Their own events and their Google accounts stay as they are. Backups taken before now keep their records until they rotate out. This cannot be undone.",
    )
    expect(sent("DELETE", "/api/v1/users/user-robin")).toBeUndefined()

    await click(button("Delete permanently", confirmation))
    expect(sent("DELETE", "/api/v1/users/user-robin")).toBeDefined()
    expect(status()).toBe("robin@example.test was deleted. 5 events their rules wrote were deleted.")
  })

  it("invites someone with a link shown once, and revokes a waiting invitation", async () => {
    await renderPeople(testI18n())
    await click(button("Invite someone"))
    expect(sent("POST", "/api/v1/invitations")).toBeDefined()
    const reveal = container.querySelector(".link-reveal")!
    expect(reveal.querySelector<HTMLInputElement>("input")!.value).toBe(`${ORIGIN}/invitation#inv_synthetic`)
    expect(reveal.textContent).toContain("It works once, until")

    await click(button("Revoke"))
    expect(sent("DELETE", "/api/v1/invitations/inv-1")).toBeDefined()
  })
})
