/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { OwnPlan, Registration } from "@/lib/api"

import { OwnPlanSection } from "./settings-own-plan"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

/** Someone on their own Family plan, with room left everywhere. */
const family: OwnPlan = {
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

/** Someone on the Default Plan with more rules counting than it allows, as after a demotion. */
const freeOverLimit: OwnPlan = {
  basis: "plan",
  plan: { key: "free", name: "Free", on_default: true },
  limits: { rules: 2, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
  rules_counted: 3,
  connected_accounts: 1,
  integration_tokens: 0,
  instant: false,
  poll_every_minutes: 5,
  may_connect_account: false,
  may_issue_token: false,
  over_rule_limit: true,
}

/** Plans are off: nothing limits anyone, so Your plan stays hidden. */
const plansOff: OwnPlan = {
  basis: "plans_off",
  plan: null,
  limits: null,
  rules_counted: 4,
  connected_accounts: 2,
  integration_tokens: 1,
  instant: true,
  poll_every_minutes: 5,
  may_connect_account: true,
  may_issue_token: true,
  over_rule_limit: false,
}

/** An Installation Administrator, whom no plan limits. */
const administering: OwnPlan = { ...plansOff, basis: "administrator" }

const onlyMe: Registration = { policy: "only_me", only_me_available: true }
const invitationOnly: Registration = { policy: "invitation_only", only_me_available: false }

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

const UNREADABLE = { detail: "database is locked", code: null, params: {} }

type Call = { method: string; path: string }
let calls: Call[] = []

/** Answers by "METHOD /path", reading `answers` at each call so a test can change one. */
function serve(answers: Record<string, Response>) {
  calls = []
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET"
      const path = String(input).split("?")[0] ?? ""
      calls.push({ method, path })
      return Promise.resolve(answers[`${method} ${path}`] ?? jsonResponse({}))
    }),
  )
}

let container: HTMLDivElement
let root: Root | null = null

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

/**
 * What the section reads: the own plan, the Registration Policy (or the answer that reads it, as for
 * a failed read), and whether the User administers.
 */
type Scenario = { ownPlan: Response; registration?: Registration | Response; administrator?: boolean }

async function renderSection(i18n: I18n, { ownPlan, registration = invitationOnly, administrator = false }: Scenario) {
  const answers: Record<string, Response> = {
    "GET /api/v1/account/plan": ownPlan,
    "GET /api/v1/registration": "policy" in registration ? jsonResponse(registration) : registration,
  }
  serve(answers)
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <OwnPlanSection administrator={administrator} />
        </QueryClientProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
  return answers
}

function section(): HTMLElement | null {
  return container.querySelector<HTMLElement>("section#your-plan")
}

function button(label: string): HTMLButtonElement {
  const found = [...container.querySelectorAll("button")].find((item) => item.textContent.trim() === label)
  if (!found) throw new Error(`No button labelled ${label}`)
  return found
}

async function click(target: HTMLElement) {
  act(() => target.click())
  await settle()
}

/** Each limit's row as a person reads it: its title, how much is in use, and what it says past the limit. */
function rows() {
  return [...(section()?.querySelectorAll<HTMLElement>(".own-plan-row") ?? [])].map((row) => ({
    title: row.querySelector("h3")?.textContent,
    value: row.querySelector(".setting-state")?.textContent,
    over: row.querySelector(".field-hint[data-tone='attention']")?.textContent ?? null,
  }))
}

function intro(): string | undefined {
  return section()?.querySelector(".section-heading p")?.textContent
}

describe("OwnPlanSection", () => {
  it("stays hidden while plans are off", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(plansOff) })
    expect(section()).toBeNull()
    expect(container.textContent).toBe("")
  })

  it("stays hidden for an answer that names no basis", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse({}) })
    expect(section()).toBeNull()
  })

  it("stays hidden for an administrator under Only Me, where plans have no effect", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(administering), registration: onlyMe, administrator: true })
    expect(section()).toBeNull()
  })

  it("tells an administrator under Invitation Only that no plan limits them", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(administering), registration: invitationOnly, administrator: true })
    expect(section()?.querySelector("h2")?.textContent).toBe("Your plan")
    expect(section()?.getAttribute("aria-labelledby")).toBe("your-plan-title")
    expect(intro()).toBe("You administer this installation, so no plan limits you.")
    expect(rows()).toEqual([])
    expect(section()?.textContent).not.toContain("ask your administrator")
  })

  it("asks for the Registration Policy only as an administrator, since nobody else may read it", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(family) })
    expect(calls.map((call) => call.path)).not.toContain("/api/v1/registration")

    act(() => root?.unmount())
    root = null
    await renderSection(testI18n(), { ownPlan: jsonResponse(administering), administrator: true })
    expect(calls.map((call) => call.path)).toContain("/api/v1/registration")
  })

  it("names the plan, then gives one row per limit with how much is in use, then how to change it", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(family) })
    expect(intro()).toBe("You have Family, chosen by your administrator.")
    expect(rows()).toEqual([
      { title: "Rules that can sync", value: "3 of 5 in use", over: null },
      { title: "Calendar accounts you can connect", value: "2 of 3 in use", over: null },
      { title: "Integration Tokens you can have", value: "0 of 2 in use", over: null },
      { title: "How soon calendars sync", value: "Instant sync, and a check every 5 minutes", over: null },
    ])
    // What counts toward each limit, in the words of the plan's editor.
    expect(section()?.querySelector(".own-plan-row p:not(.setting-state)")?.textContent).toBe("Paused rules and drafts don't count.")
    const rowsAndClose = [...section()!.querySelectorAll(".own-plan-row, .own-plan-close")]
    expect(rowsAndClose.at(-1)?.textContent).toBe("To change your plan, ask your administrator.")
  })

  it("names the default plan by its name alone, with a plan that includes no tokens and a slower sync", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse({ ...freeOverLimit, rules_counted: 2, over_rule_limit: false }) })
    expect(intro()).toBe("You have Free, chosen by your administrator.")
    expect(rows().map((row) => row.value)).toEqual(["2 of 2 in use", "1 of 1 in use", "Not included", "Every 5 minutes"])
  })

  it("says No limit where the plan sets none", async () => {
    const unlimited: OwnPlan = {
      ...family,
      limits: { rules: null, connected_accounts: null, integration_tokens: null, sync_interval: "instant" },
    }
    await renderSection(testI18n(), { ownPlan: jsonResponse(unlimited) })
    expect(rows().map((row) => row.value)).toEqual([
      "No limit, 3 in use",
      "No limit, 2 in use",
      "No limit, 0 in use",
      "Instant sync, and a check every 5 minutes",
    ])
  })

  it("marks a limit in use past what the plan allows with words, an icon, and its tone, never color alone", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse({ ...freeOverLimit, connected_accounts: 3 }) })
    const [rulesRow, accountsRow, tokensRow] = [...section()!.querySelectorAll<HTMLElement>(".own-plan-row")]
    expect(rows().slice(0, 2)).toEqual([
      {
        title: "Rules that can sync",
        value: "3 in use, 2 allowed",
        over: "You have more rules in use than your plan allows. They keep syncing, but you cannot start another until you pause or remove one.",
      },
      {
        title: "Calendar accounts you can connect",
        value: "3 in use, 1 allowed",
        over: "You have more calendar accounts than your plan allows. They keep working, but you cannot connect another until you delete one.",
      },
    ])
    for (const row of [rulesRow, accountsRow]) {
      expect(row?.querySelector(".setting-state")?.getAttribute("data-tone")).toBe("attention")
      expect(row?.querySelector(".field-hint[data-tone='attention'] svg")?.getAttribute("aria-hidden")).toBe("true")
    }
    expect(tokensRow?.querySelector("[data-tone]")).toBeNull()
  })

  it("marks nothing while every count fits", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(family) })
    expect(section()?.querySelector("[data-tone]")).toBeNull()
  })

  it("moves focus to its heading when the address names it, as See your plan does", async () => {
    window.history.replaceState(null, "", "/settings/account#your-plan")
    vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined)
    await renderSection(testI18n(), { ownPlan: jsonResponse(family) })
    const heading = section()?.querySelector("h2")
    expect(heading?.getAttribute("tabindex")).toBe("-1")
    expect(document.activeElement).toBe(heading)
  })

  it("moves focus to its heading on arrival even when it cannot load, so the error is read next", async () => {
    window.history.replaceState(null, "", "/settings/account#your-plan")
    vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined)
    await renderSection(testI18n(), { ownPlan: jsonResponse(UNREADABLE, 500) })
    expect(document.activeElement).toBe(section()?.querySelector("h2"))
  })

  it("leaves focus alone when the address names something else", async () => {
    window.history.replaceState(null, "", "/settings/account")
    await renderSection(testI18n(), { ownPlan: jsonResponse(family) })
    expect(document.activeElement).not.toBe(section()?.querySelector("h2"))
  })

  it("scrolls itself into view once when the address names it, as a link beside a limit does", async () => {
    window.history.replaceState(null, "", "/settings/account#your-plan")
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined)
    await renderSection(testI18n(), { ownPlan: jsonResponse(family) })
    await settle()

    expect(scrolled).toHaveBeenCalledOnce()
    expect(scrolled.mock.contexts[0]).toBe(section())
  })

  it("does not scroll when the address names something else", async () => {
    window.history.replaceState(null, "", "/settings/account")
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined)
    await renderSection(testI18n(), { ownPlan: jsonResponse(family) })
    expect(section()).not.toBeNull()
    expect(scrolled).not.toHaveBeenCalled()
  })

  it("shows its own error with Try again when it cannot load, and loads on Try again", async () => {
    const answers = await renderSection(testI18n(), { ownPlan: jsonResponse(UNREADABLE, 500) })
    const alert = section()?.querySelector("[role='alert']")
    expect(alert?.textContent).toBe("Your plan could not load.Try again")

    answers["GET /api/v1/account/plan"] = jsonResponse(family)
    await click(button("Try again"))
    expect(section()?.querySelector("[role='alert']")).toBeNull()
    expect(intro()).toBe("You have Family, chosen by your administrator.")
  })

  it("hides a failed load from an administrator under Only Me, where plans have no effect", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(UNREADABLE, 500), registration: onlyMe, administrator: true })
    expect(section()).toBeNull()
  })

  it("shows its own error with Try again to an administrator under Invitation Only when it cannot load", async () => {
    await renderSection(testI18n(), {
      ownPlan: jsonResponse(UNREADABLE, 500),
      registration: invitationOnly,
      administrator: true,
    })
    expect(section()?.querySelector("[role='alert']")?.textContent).toBe("Your plan could not load.Try again")
    expect(button("Try again")).not.toBeNull()
  })

  it("hides a failed load from an administrator while the Registration Policy cannot load either", async () => {
    await renderSection(testI18n(), {
      ownPlan: jsonResponse(UNREADABLE, 500),
      registration: jsonResponse(UNREADABLE, 500),
      administrator: true,
    })
    expect(section()).toBeNull()
    expect(container.querySelector("#your-plan-title")).toBeNull()
    expect(container.textContent).not.toContain("Your plan could not load.")
  })

  const SHOWN: [string, Scenario][] = [
    ["a limited person over their rule limit", { ownPlan: jsonResponse(freeOverLimit) }],
    ["an administrator under Invitation Only", { ownPlan: jsonResponse(administering), administrator: true }],
    ["a plan that cannot load", { ownPlan: jsonResponse(UNREADABLE, 500) }],
  ]

  it.each(SHOWN)("has no untranslated text for %s", async (_case, scenario) => {
    await renderSection(pseudoI18n(), scenario)
    expect(section()).not.toBeNull()
    expect(untranslatedText(container, ["Family", "Free"])).toEqual([])
  })
})
