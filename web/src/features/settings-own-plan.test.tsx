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

const onlyMe: Registration = { policy: "only_me", only_me_available: true, open_available: false, open_unavailable_reason: "identity_email_not_configured" }
const invitationOnly: Registration = { policy: "invitation_only", only_me_available: false, open_available: false, open_unavailable_reason: "identity_email_not_configured" }

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

const UNREADABLE = { detail: "database is locked", code: null, params: {} }

type Call = { method: string; path: string }
let calls: Call[] = []
let openConnections: ReturnType<typeof vi.fn<() => void>>

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
  openConnections = vi.fn<() => void>()
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <OwnPlanSection administrator={administrator} onOpenConnections={openConnections} />
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

/**
 * Each limit's row as a person reads it: its name, what counts, the meter's words, the count or
 * what the row says instead, its chip, and the sentence under it.
 */
function rows() {
  return usageRows().map((row) => ({
    title: textOf(row, ".plan-usage-name"),
    meter: row.querySelector("meter")?.getAttribute("aria-valuetext") ?? null,
    detail: textOf(row, ".plan-usage-detail"),
    value: textOf(row, ".plan-usage-value"),
    chip: textOf(row, ".plan-usage-chip"),
    note: textOf(row, ".plan-usage-note"),
  }))
}

function usageRows(): HTMLElement[] {
  return [...(section()?.querySelectorAll<HTMLElement>(".plan-usage-row") ?? [])]
}

function textOf(within: Element, selector: string): string | null {
  return within.querySelector(selector)?.textContent ?? null
}

/** A row's chip and note tones, and whether each carries its icon, hidden from screen readers. */
function tones(row: Element | undefined) {
  const tone = (selector: string) => row?.querySelector(selector)?.getAttribute("data-tone") ?? null
  const icon = (selector: string) => row?.querySelector(`${selector} svg`)?.getAttribute("aria-hidden") ?? null
  return {
    chip: tone(".plan-usage-chip"),
    chipIcon: icon(".plan-usage-chip"),
    note: tone(".plan-usage-note"),
    noteIcon: icon(".plan-usage-note"),
    meter: tone("[data-tone='over']"),
  }
}

function intro(): string | undefined {
  return section()?.querySelector(".section-heading p")?.textContent
}

/** The card's head: the plan's name as its title, its chips, and who set it. */
function head() {
  const card = section()?.querySelector(".own-plan-card")
  return {
    title: card?.querySelector("h3")?.textContent,
    chips: [...(card?.querySelectorAll(".own-plan-head .person-plan-chip") ?? [])].map((chip) => chip.textContent),
    origin: card?.querySelector(".own-plan-origin")?.textContent,
  }
}

describe("OwnPlanSection", () => {
  const HIDDEN: [string, Scenario][] = [
    ["while plans are off", { ownPlan: jsonResponse(plansOff) }],
    ["for an answer that names no basis", { ownPlan: jsonResponse({}) }],
    ["for an administrator under Only Me, where plans have no effect", { ownPlan: jsonResponse(administering), registration: onlyMe, administrator: true }],
    ["when it cannot load, for an administrator under Only Me", { ownPlan: jsonResponse(UNREADABLE, 500), registration: onlyMe, administrator: true }],
    [
      "when it cannot load, for an administrator while the Registration Policy cannot load either",
      { ownPlan: jsonResponse(UNREADABLE, 500), registration: jsonResponse(UNREADABLE, 500), administrator: true },
    ],
  ]

  it.each(HIDDEN)("stays hidden %s", async (_case, scenario) => {
    await renderSection(testI18n(), scenario)
    expect(section()).toBeNull()
    expect(container.textContent).toBe("")
  })

  it("tells an administrator under Invitation Only that no plan limits them", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(administering), registration: invitationOnly, administrator: true })
    expect(section()?.querySelector("h2")?.textContent).toBe("Your plan")
    expect(section()?.getAttribute("aria-labelledby")).toBe("your-plan-title")
    expect(intro()).toBe("You administer this installation, so no plan limits you.")
    expect(rows()).toEqual([])
    expect(section()?.querySelector(".own-plan-card")).toBeNull()
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

  it("names the plan and who set it, then one row per limit with a meter and its numbers, then how to change it", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse(family) })
    expect(intro()).toBe("What you can use here, and how much of it you use now.")
    expect(head()).toEqual({ title: "Family", chips: [], origin: "Set by your administrator" })
    expect(rows()).toEqual([
      { title: "Active rules", meter: "3 of 5", detail: null, value: "3 of 5", chip: null, note: null },
      { title: "Calendar accounts", meter: "2 of 3", detail: null, value: "2 of 3", chip: null, note: null },
      { title: "Integration tokens", meter: "0 of 2", detail: null, value: "0 of 2", chip: null, note: null },
      { title: "Sync speed", meter: null, detail: null, value: "Instant", chip: null, note: null },
    ])
    expect(section()?.querySelector("[data-tone='attention'], [data-tone='over'], .plan-usage-note")).toBeNull()
    // Each meter is named by its limit, so a screen reader hears which limit a value is for.
    expect([...section()!.querySelectorAll("meter")].map((meter) => meter.getAttribute("aria-label"))).toEqual([
      "Active rules",
      "Calendar accounts",
      "Integration tokens",
    ])
    expect(section()?.querySelector(".plan-usage-hint")?.textContent).toBe(
      "Running rules, and rules waiting for you to reauthorize an account. Paused rules and drafts don't count.",
    )
    const closing = [...section()!.querySelectorAll(".plan-usage-row, .own-plan-close")]
    expect(closing.at(-1)?.textContent).toBe("To change your plan, ask your administrator.")
  })

  it("says the default plan, a plan that includes no tokens, and a slower sync in words", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse({ ...freeOverLimit, rules_counted: 1, over_rule_limit: false }) })
    expect(head()).toEqual({ title: "Free", chips: [], origin: "The default plan" })
    expect(rows().slice(2)).toEqual([
      { title: "Integration tokens", meter: null, detail: "Your plan does not include integration tokens.", value: "Not included", chip: null, note: null },
      { title: "Sync speed", meter: null, detail: "Instant sync is not part of your plan.", value: "Every 5 minutes", chip: null, note: null },
    ])

    act(() => root?.unmount())
    root = null
    const hourly: OwnPlan = {
      ...freeOverLimit,
      limits: { ...freeOverLimit.limits!, sync_interval: "60_minutes" },
      poll_every_minutes: 60,
    }
    await renderSection(testI18n(), { ownPlan: jsonResponse(hourly) })
    expect(rows().at(-1)).toEqual(
      { title: "Sync speed", meter: null, detail: "Instant sync is not part of your plan.", value: "Every hour", chip: null, note: null },
    )
  })

  it("says No limit where the plan sets none, with how many are in use and no meter", async () => {
    const unlimited: OwnPlan = {
      ...family,
      limits: { rules: null, connected_accounts: null, integration_tokens: null, sync_interval: "instant" },
    }
    await renderSection(testI18n(), { ownPlan: jsonResponse(unlimited) })
    expect(rows().map((row) => [row.detail, row.value, row.meter, row.note])).toEqual([
      ["No limit", "3 in use", null, null],
      ["No limit", "2 in use", null, null],
      ["No limit", "0 in use", null, null],
      [null, "Instant", null, null],
    ])
  })

  it("says Limit reached at a limit, and how to start another rule", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse({ ...freeOverLimit, rules_counted: 2, over_rule_limit: false }) })
    const [rulesRow] = usageRows()
    expect(rows()[0]).toEqual({
      title: "Active rules",
      meter: "2 of 2, limit reached",
      detail: null,
      value: "2 of 2",
      chip: "Limit reached",
      note: "To start another rule, pause one first.",
    })
    // At the limit nothing is wrong: the chip and the note stay neutral, with an icon beside the note.
    expect(tones(rulesRow)).toEqual({ chip: "neutral", chipIcon: null, note: "info", noteIcon: "true", meter: null })
    expect(head().chips).toEqual([])
  })

  it("marks a limit past what the plan allows with words, an icon, and its tone, never color alone", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse({ ...freeOverLimit, connected_accounts: 3 }) })
    expect(head().chips).toEqual(["Over a limit"])
    expect(section()?.querySelector(".own-plan-head .person-plan-chip svg")?.getAttribute("aria-hidden")).toBe("true")
    expect(rows().slice(0, 2)).toEqual([
      {
        title: "Active rules",
        meter: "3 of 2, over the limit",
        detail: null,
        value: "3 of 2",
        chip: "Over",
        note: "You have 3 active rules and your plan allows 2. They keep syncing, but you can't start another until fewer are active.",
      },
      {
        title: "Calendar accounts",
        meter: "3 of 1, over the limit",
        detail: null,
        value: "3 of 1",
        chip: "Over",
        note: "You have 3 calendar accounts and your plan allows 1. They keep syncing, but you can't connect another until you remove one in Connections.",
      },
    ])
    const [rulesRow, accountsRow, tokensRow] = usageRows()
    const over = { chip: "attention", chipIcon: "true", note: "attention", noteIcon: "true", meter: "over" }
    expect(tones(rulesRow)).toEqual(over)
    expect(tones(accountsRow)).toEqual(over)
    expect(tokensRow?.querySelector("[data-tone='attention'], [data-tone='over']")).toBeNull()
  })

  it("opens Connections from the sentence under calendar accounts, where one can be removed", async () => {
    await renderSection(testI18n(), { ownPlan: jsonResponse({ ...freeOverLimit, connected_accounts: 2 }) })
    const link = section()?.querySelector<HTMLAnchorElement>(".plan-usage-note a")
    expect(link?.textContent).toBe("Connections")
    expect(link?.getAttribute("href")).toBe("/settings/connections")
    await click(link!)
    expect(openConnections).toHaveBeenCalledOnce()
  })

  it("moves focus to its heading and scrolls itself into view once when the address names it, as See your plan does", async () => {
    window.history.replaceState(null, "", "/settings/account#your-plan")
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined)
    await renderSection(testI18n(), { ownPlan: jsonResponse(family) })
    const heading = section()?.querySelector("h2")
    expect(heading?.getAttribute("tabindex")).toBe("-1")
    expect(document.activeElement).toBe(heading)

    await settle()
    expect(scrolled).toHaveBeenCalledOnce()
    expect(scrolled.mock.contexts[0]).toBe(section())
  })

  it("moves focus to its heading on arrival even when it cannot load, so the error is read next", async () => {
    window.history.replaceState(null, "", "/settings/account#your-plan")
    vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined)
    await renderSection(testI18n(), { ownPlan: jsonResponse(UNREADABLE, 500) })
    expect(document.activeElement).toBe(section()?.querySelector("h2"))
  })

  it("leaves focus alone and does not scroll when the address names something else", async () => {
    window.history.replaceState(null, "", "/settings/account")
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined)
    await renderSection(testI18n(), { ownPlan: jsonResponse(family) })
    expect(section()).not.toBeNull()
    expect(document.activeElement).not.toBe(section()?.querySelector("h2"))
    expect(scrolled).not.toHaveBeenCalled()
  })

  it("shows its own error with Try again when it cannot load, and loads on Try again", async () => {
    const answers = await renderSection(testI18n(), { ownPlan: jsonResponse(UNREADABLE, 500) })
    const alert = section()?.querySelector("[role='alert']")
    expect(alert?.textContent).toBe("Your plan could not load.Try again")

    answers["GET /api/v1/account/plan"] = jsonResponse(family)
    await click(button("Try again"))
    expect(section()?.querySelector("[role='alert']")).toBeNull()
    expect(head().title).toBe("Family")
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

  const SHOWN: [string, Scenario][] = [
    ["a limited person over their rule limit", { ownPlan: jsonResponse(freeOverLimit) }],
    ["a limited person over every limit", { ownPlan: jsonResponse({ ...freeOverLimit, connected_accounts: 2, integration_tokens: 1 }) }],
    ["a limited person with room left", { ownPlan: jsonResponse(family) }],
    ["an administrator under Invitation Only", { ownPlan: jsonResponse(administering), administrator: true }],
    ["a plan that cannot load", { ownPlan: jsonResponse(UNREADABLE, 500) }],
  ]

  it.each(SHOWN)("has no untranslated text for %s", async (_case, scenario) => {
    await renderSection(pseudoI18n(), scenario)
    expect(section()).not.toBeNull()
    expect(untranslatedText(container, ["Family", "Free"])).toEqual([])
  })
})
