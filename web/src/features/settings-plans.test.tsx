/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { dateWords, pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { PlanSummary, PlansOverview, Registration, SessionStatus } from "@/lib/api"

import { SettingsPage } from "./settings"

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

const family: PlanSummary = {
  key: "family",
  name: "Family",
  limits: { rules: 5, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" },
  is_default: false,
  people: 4,
  limited_people: 3,
}
const free: PlanSummary = {
  key: "free",
  name: "Free",
  limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
  is_default: false,
  people: 2,
  limited_people: 2,
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

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

function refusal(status: number, code: string, params: Record<string, string | number> = {}): Response {
  return jsonResponse({ detail: "The server's English.", code, params }, status)
}

const NO_CONTENT = { ok: true, status: 204, json: () => Promise.resolve(null) } as Response

type Call = { method: string; path: string; body: unknown }
type Scenario = {
  registration?: Registration
  plans?: PlansOverview
  /** Answers by "METHOD /path", overriding the defaults. A promise lets a test hold an answer back. */
  answers?: Record<string, Response | Promise<Response>>
}

let calls: Call[] = []

function serve({ registration = INVITATION_ONLY, plans = overview(), answers = {} }: Scenario) {
  const defaults: Record<string, Response | Promise<Response>> = {
    "GET /api/v1/session": jsonResponse(session),
    "GET /api/v1/providers": jsonResponse([]),
    "GET /api/v1/storage": jsonResponse({
      database: { bytes: 1024 * 1024, reclaimable_bytes: 0, activity_entries: 0, oldest_activity_at: null },
      logs: { bytes: 0, files: 0, oldest_at: null, newest_at: null },
      activity_ages: [30, 90, 180, 365],
    }),
    "GET /api/v1/registration": jsonResponse(registration),
    "GET /api/v1/plans": jsonResponse(plans),
  }
  const routes = { ...defaults, ...answers }
  calls = []
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET"
      const path = String(input).split("?")[0] ?? ""
      const body: unknown = init?.body ? JSON.parse(init.body as string) : undefined
      calls.push({ method, path, body })
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
  page().happyDOM.setURL(`${ORIGIN}/settings/administration`)
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

async function renderAdministration(i18n: I18n, scenario: Scenario = {}) {
  serve(scenario)
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <SettingsPage tab="administration" onOpenTab={() => undefined} onOpenPeople={() => undefined} />
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

function sections(): (string | null)[] {
  return [...container.querySelectorAll(".settings-page > section")].map((item) => item.getAttribute("aria-labelledby"))
}

function button(name: string, within: ParentNode = plansSection()): HTMLButtonElement {
  const found = [...within.querySelectorAll("button")].find((candidate) => candidate.textContent.trim() === name)
  if (!found) throw new Error(`No button "${name}"`)
  return found
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

describe("Plans under Administration", () => {
  it("is hidden under Only me, where the only person administers", async () => {
    await renderAdministration(testI18n(), { registration: { policy: "only_me", only_me_available: true } })
    expect(container.querySelector("[aria-labelledby='plans-title']")).toBeNull()
    expect(sections()).toEqual(["registration-title", "storage-title"])
  })

  it("sits between who can join and storage under Invitation only", async () => {
    await renderAdministration(testI18n())
    expect(sections()).toEqual(["registration-title", "plans-title", "storage-title"])
    expect(plansSection().querySelector("h2")?.textContent).toBe("Plans")
  })

  it("lists each Plan with its limits, interval, people, and which is the default", async () => {
    await renderAdministration(testI18n(), { plans: overview({ defaultPlan: "free" }) })
    expect([...planRow("Family").querySelectorAll("p")].map((line) => line.textContent)).toEqual([
      "5 rules, 3 calendar accounts, 2 tokens",
      "Instant sync, and a check every 5 minutes",
      "4 people",
    ])
    expect([...planRow("Free").querySelectorAll("p")].map((line) => line.textContent)).toEqual([
      "1 rule, 1 calendar account, no tokens",
      "Every 5 minutes",
      "2 people",
    ])
    expect(planRow("Free").textContent).toContain("Default")
    expect(planRow("Family").textContent).not.toContain("Default")
  })

  it("keeps Limit people with plans unavailable until a default exists, and says why", async () => {
    await renderAdministration(testI18n())
    const enabled = field("plans-enabled")
    expect(enabled.disabled).toBe(true)
    expect(element("plans-enabled-hint").textContent).toBe("Choose a default plan first.")
  })

  it("chooses a default, leaving plans off", async () => {
    await renderAdministration(testI18n(), {
      answers: { "PUT /api/v1/plan-settings": jsonResponse(overview({ defaultPlan: "family" })) },
    })
    await choose(select("plans-default"), "family")
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: false, default_plan: "family" })
    expect(status()).toBe("Family is now the default plan.")
    expect(field("plans-enabled").disabled).toBe(false)
    expect(element("plans-enabled-hint").textContent).toBe("While this is off, nobody is limited.")
  })

  it("turns plans on with the default it has", async () => {
    await renderAdministration(testI18n(), {
      plans: overview({ defaultPlan: "free" }),
      answers: { "PUT /api/v1/plan-settings": jsonResponse(overview({ enabled: true, defaultPlan: "free" })) },
    })
    await click(field("plans-enabled"))
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: true, default_plan: "free" })
    expect(status()).toBe("Plans now limit people.")
    expect(field("plans-enabled").checked).toBe(true)
  })

  it("shows the plan asked for, and holds the select, while the default is on its way", async () => {
    const neverAnswered = new Promise<Response>(() => undefined)
    await renderAdministration(testI18n(), { answers: { "PUT /api/v1/plan-settings": neverAnswered } })
    await choose(select("plans-default"), "family")
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: false, default_plan: "family" })
    expect(select("plans-default").value).toBe("family")
    expect(select("plans-default").disabled).toBe(true)
  })

  it("keeps the box ticked, and holds it, while turning plans on is on its way", async () => {
    const neverAnswered = new Promise<Response>(() => undefined)
    await renderAdministration(testI18n(), {
      plans: overview({ defaultPlan: "free" }),
      answers: { "PUT /api/v1/plan-settings": neverAnswered },
    })
    await click(field("plans-enabled"))
    expect(sent("PUT", "/api/v1/plan-settings")).toEqual({ enabled: true, default_plan: "free" })
    expect(field("plans-enabled").checked).toBe(true)
    expect(field("plans-enabled").disabled).toBe(true)
  })

  it("offers no way to clear the default while plans are on", async () => {
    await renderAdministration(testI18n(), { plans: overview({ enabled: true, defaultPlan: "free" }) })
    const none = select("plans-default").querySelector<HTMLOptionElement>("option[value='']")!
    expect(none.textContent).toBe("No default")
    expect(none.disabled).toBe(true)
  })

  it("says why a setting was refused", async () => {
    await renderAdministration(testI18n(), {
      answers: { "PUT /api/v1/plan-settings": refusal(404, "plan_not_found") },
    })
    await choose(select("plans-default"), "family")
    expect(alertText()).toBe("This plan no longer exists. Reload to see the current plans.")
  })

  it("adds a plan, warning that its key cannot change, with Unlimited sent as no limit", async () => {
    const added: PlanSummary = {
      key: "family-2",
      name: "Family Plus",
      limits: { rules: 8, connected_accounts: null, integration_tokens: 0, sync_interval: "5_minutes" },
      is_default: false,
      people: 0,
      limited_people: 0,
    }
    await renderAdministration(testI18n(), { answers: { "POST /api/v1/plans": jsonResponse(added, 201) } })
    await click(button("Add a plan"))
    expect(element("plan-new-key-hint").textContent).toBe(
      "Lower-case letters, digits, and hyphens. The key cannot change later.",
    )
    expect(document.activeElement).toBe(field("plan-new-key"))
    const intervals = select("plan-new-interval")
    expect([...intervals.options].map((option) => [option.value, option.textContent])).toEqual([
      ["instant", "Instant sync, and a check every 5 minutes"],
      ["5_minutes", "Every 5 minutes"],
    ])

    type(field("plan-new-key"), "family-2")
    type(field("plan-new-name"), " Family Plus ")
    await click(field("plan-new-rules-unlimited"))
    type(field("plan-new-rules"), "8")
    await click(field("plan-new-tokens-unlimited"))
    type(field("plan-new-tokens"), "0")
    await choose(intervals, "5_minutes")
    await submit(field("plan-new-key").closest("form")!)

    expect(sent("POST", "/api/v1/plans")).toEqual({
      key: "family-2",
      name: "Family Plus",
      limits: { rules: 8, connected_accounts: null, integration_tokens: 0, sync_interval: "5_minutes" },
    })
    expect(status()).toBe("Family Plus was added.")
    expect(container.querySelector("#plan-edit-new")).toBeNull()
    expect(document.activeElement).toBe(button("Add a plan"))
  })

  it("keeps Save unavailable until each limit has a number or Unlimited", async () => {
    await renderAdministration(testI18n())
    await click(button("Add a plan"))
    type(field("plan-new-key"), "family-2")
    type(field("plan-new-name"), "Family Plus")
    await click(field("plan-new-accounts-unlimited"))
    expect(button("Save plan").disabled).toBe(true)
    type(field("plan-new-accounts"), "2")
    await settle()
    expect(button("Save plan").disabled).toBe(false)
  })

  it.each([
    ["plan-new-rules", "Rules that sync"],
    ["plan-new-accounts", "Calendar accounts"],
    ["plan-new-tokens", "Integration Tokens"],
  ])("labels the %s limit with the shared label, grouping its number and Unlimited", async (id, label) => {
    await renderAdministration(testI18n())
    await click(button("Add a plan"))
    expect(container.querySelector(`label[for='${id}']`)?.textContent).toBe(label)
    const group = element("plan-edit-new").querySelector(`[role='group'][aria-labelledby='${id}-label']`)
    expect(group?.querySelector(`#${id}`)).toBe(field(id))
    expect(group?.querySelector(`#${id}-unlimited`)).toBe(field(`${id}-unlimited`))
  })

  it.each([
    [refusal(409, "plan_key_taken"), "Another plan already uses this key. Choose a different key."],
    [
      refusal(422, "invalid_plan", { reason: "key" }),
      "Use 1 to 32 lower-case letters, digits, and hyphens for the key, starting with a letter or digit.",
    ],
  ])("keeps the new plan's form open with the reason it was refused", async (answer, reason) => {
    await renderAdministration(testI18n(), { answers: { "POST /api/v1/plans": answer } })
    await click(button("Add a plan"))
    type(field("plan-new-key"), "Family")
    type(field("plan-new-name"), "Family")
    await submit(field("plan-new-key").closest("form")!)
    expect(element("plan-edit-new").querySelector("[role='alert']")?.textContent).toBe(reason)
    expect(status()).toBe("")
  })

  it("edits a plan without changing its key, and warns before lowering its rule limit", async () => {
    await renderAdministration(testI18n(), {
      answers: { "PUT /api/v1/plans/family": jsonResponse({ ...family, name: "Family Large" }) },
    })
    await click(button("Edit", planRow("Family")))
    const key = field("plan-family-key")
    expect(key.readOnly).toBe(true)
    expect(key.value).toBe("family")
    expect(container.querySelector("#plan-family-key-hint")).toBeNull()
    expect(document.activeElement).toBe(field("plan-family-name"))
    expect(element("plan-edit-family").querySelector("[data-tone='attention']")).toBeNull()

    type(field("plan-family-rules"), "2")
    await settle()
    expect(element("plan-edit-family").querySelector("[data-tone='attention']")?.textContent).toBe(
      "This plan limits 3 people. Rules beyond a lower limit keep syncing, but no new rule can start until the count is within it.",
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

  it("shows the key it cannot change as read-only, set apart from the fields that can", async () => {
    await renderAdministration(testI18n())
    await click(button("Edit", planRow("Family")))
    const key = field("plan-family-key")
    expect(key.readOnly).toBe(true)
    expect(key.disabled).toBe(false)
    expect(key.classList.contains("field-read-only")).toBe(true)
    expect(field("plan-family-name").classList.contains("field-read-only")).toBe(false)
  })

  it("names the plan each Edit and Remove acts on, for assistive technology", async () => {
    await renderAdministration(testI18n())
    expect(button("Edit", planRow("Family")).getAttribute("aria-label")).toBe("Edit Family")
    expect(button("Remove", planRow("Family")).getAttribute("aria-label")).toBe("Remove Family")
    expect(button("Edit", planRow("Free")).getAttribute("aria-label")).toBe("Edit Free")
    expect(button("Remove", planRow("Free")).getAttribute("aria-label")).toBe("Remove Free")
  })

  it("keeps a save on its way, and then its refusal, while the other plan commands wait", async () => {
    let answer: (response: Response) => void = () => undefined
    const held = new Promise<Response>((resolve) => {
      answer = resolve
    })
    await renderAdministration(testI18n(), { answers: { "PUT /api/v1/plans/family": held } })
    await click(button("Edit", planRow("Family")))
    type(field("plan-family-name"), "Family Large")
    await submit(field("plan-family-name").closest("form")!)
    const form = element("plan-edit-family")
    expect(button("Save plan", form).disabled).toBe(true)
    expect(button("Cancel", form).disabled).toBe(true)
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
    expect(button("Save plan", element("plan-edit-family")).disabled).toBe(true)

    await act(async () => {
      answer(refusal(422, "invalid_plan", { reason: "name" }))
      await Promise.resolve()
    })
    await settle()
    expect(element("plan-edit-family").querySelector("[role='alert']")?.textContent).toBe(
      "Give the plan a name of 1 to 60 characters, without line breaks or other control characters.",
    )
    expect(button("Save plan", element("plan-edit-family")).disabled).toBe(false)
    expect(button("Edit", planRow("Free")).getAttribute("aria-disabled")).toBeNull()
  })

  it("does not warn about a lower rule limit when the plan limits nobody", async () => {
    await renderAdministration(testI18n(), { plans: overview({ plans: [{ ...family, limited_people: 0 }] }) })
    await click(button("Edit", planRow("Family")))
    type(field("plan-family-rules"), "2")
    await settle()
    expect(element("plan-edit-family").querySelector("[data-tone='attention']")).toBeNull()
  })

  it("keeps an interval a later release saved, beside the offered ones", async () => {
    const hourly: PlanSummary = { ...family, limits: { ...family.limits, sync_interval: "60_minutes" } }
    await renderAdministration(testI18n(), { plans: overview({ plans: [hourly] }) })
    expect(planRow("Family").textContent).toContain("Every hour")
    await click(button("Edit", planRow("Family")))
    const intervals = select("plan-family-interval")
    expect([...intervals.options].map((option) => option.value)).toEqual(["instant", "5_minutes", "60_minutes"])
    expect(intervals.value).toBe("60_minutes")
  })

  it("closes the form on Cancel, sending nothing", async () => {
    await renderAdministration(testI18n())
    await click(button("Edit", planRow("Family")))
    await click(button("Cancel"))
    expect(container.querySelector("#plan-edit-family")).toBeNull()
    expect(calls.some((call) => call.method !== "GET")).toBe(false)
    expect(document.activeElement).toBe(button("Edit", planRow("Family")))
  })

  it("asks inline before removing a plan", async () => {
    await renderAdministration(testI18n(), { answers: { "DELETE /api/v1/plans/family": NO_CONTENT } })
    await click(button("Remove", planRow("Family")))
    const confirmation = element("plan-remove-family")
    expect(confirmation.querySelector("h3")?.textContent).toBe("Remove Family?")
    expect(confirmation.querySelector("p")?.textContent).toBe(
      "Nobody can have this plan afterwards. Rules, accounts, and tokens stay as they are.",
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

  it.each([
    [refusal(409, "plan_in_use", { people: 2, count: 2 }), "2 people have this plan. Give them another plan before you remove it."],
    [refusal(409, "plan_in_use", { people: 1, count: 1 }), "1 person has this plan. Give them another plan before you remove it."],
    [refusal(409, "plan_is_default"), "This is the default plan. Choose another default before you remove it."],
  ])("says why a plan cannot be removed", async (answer, reason) => {
    await renderAdministration(testI18n(), { answers: { "DELETE /api/v1/plans/family": answer } })
    await click(button("Remove", planRow("Family")))
    await click(button("Remove plan", element("plan-remove-family")))
    expect(planRow("Family").querySelector("[role='alert']")?.textContent).toBe(reason)
    expect(element("plan-remove-family")).not.toBeNull()
  })

  it("shows its own error with Try again when plans cannot load, and the rest still works", async () => {
    await renderAdministration(testI18n(), { answers: { "GET /api/v1/plans": jsonResponse({ detail: "boom" }, 500) } })
    expect(alertText()).toContain("Plans could not load.")
    expect(button("Try again")).not.toBeNull()
    expect(sections()).toEqual(["registration-title", "plans-title", "storage-title"])
  })

  it("has no untranslated text", async () => {
    await renderAdministration(pseudoI18n(), { plans: overview({ defaultPlan: "free" }) })
    await click(container.querySelector<HTMLButtonElement>("[aria-controls='plan-edit-new']")!)
    expect(untranslatedText(container, [...dateWords(), family.name, free.name])).toEqual([])
    await click(container.querySelector<HTMLButtonElement>("[aria-controls='plan-edit-family']")!)
    type(field("plan-family-rules"), "2")
    await settle()
    expect(untranslatedText(container, [...dateWords(), family.name, free.name])).toEqual([])
    await click(container.querySelector<HTMLButtonElement>("[aria-controls='plan-remove-family']")!)
    expect(untranslatedText(container, [...dateWords(), family.name, free.name])).toEqual([])
  })
})
