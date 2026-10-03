/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, createElement } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { RuleBuilder } from "./rules"
import type { ConnectedAccount, DiscoveredCalendar } from "@/lib/api"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function account(id: string): ConnectedAccount {
  return {
    id,
    display_name: `Account ${id}`,
    email: `${id}@example.test`,
    provider: "google",
    avatar_url: null,
    state: "connected",
    rule_count: 0,
    authorized_at: "2026-10-02T00:00:00Z",
  }
}

// Source account: one writable calendar, one read-only.
const accountA = account("a")
const workA: DiscoveredCalendar = { id: "work-a", summary: "Work A", access_role: "owner", writable: true, primary: true }
const holidaysA: DiscoveredCalendar = { id: "holidays-a", summary: "Holidays A", access_role: "reader", writable: false, primary: false }

// Initial destination account: two writable calendars, one read-only.
const accountB = account("b")
const workB1: DiscoveredCalendar = { id: "work-b1", summary: "Work B1", access_role: "owner", writable: true, primary: true }
const holidaysB: DiscoveredCalendar = { id: "holidays-b", summary: "Holidays B", access_role: "reader", writable: false, primary: false }
const workB2: DiscoveredCalendar = { id: "work-b2", summary: "Work B2", access_role: "owner", writable: true, primary: false }

// A switch target with its own single writable calendar.
const accountD = account("d")
const workD1: DiscoveredCalendar = { id: "work-d1", summary: "Work D1", access_role: "owner", writable: true, primary: true }

// A switch target with no writable calendars at all.
const accountC = account("c")
const holidaysC: DiscoveredCalendar = { id: "holidays-c", summary: "Holidays C", access_role: "reader", writable: false, primary: true }

const calendarsByAccount: Record<string, DiscoveredCalendar[]> = {
  a: [workA, holidaysA],
  b: [workB1, holidaysB, workB2],
  c: [holidaysC],
  d: [workD1],
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
})

function renderBuilder(accounts: ConnectedAccount[], onCreated = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  for (const [id, calendars] of Object.entries(calendarsByAccount)) {
    queryClient.setQueryData(["calendars", id], calendars)
  }
  root = createRoot(container)
  act(() => {
    root?.render(
      createElement(
        QueryClientProvider,
        { client: queryClient },
        createElement(RuleBuilder, { accounts, onCreated }),
      ),
    )
  })
  return queryClient
}

function click(element: Element) {
  act(() => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
  })
}

function selectOptions(id: string): HTMLOptionElement[] {
  return Array.from(container.querySelectorAll(`#${id} option`)) as HTMLOptionElement[]
}

function selectElement(id: string): HTMLSelectElement {
  return container.querySelector(`#${id}`) as HTMLSelectElement
}

/** Switches an AccountSelect combobox (scoped to its own wrapper) to the account at `targetId`. */
function switchAccount(triggerId: string, targetId: string) {
  const trigger = container.querySelector(`#${triggerId}`) as HTMLButtonElement
  const wrapper = trigger.closest(".account-select") as HTMLElement
  click(trigger)
  const options = Array.from(wrapper.querySelectorAll('[role="option"]'))
  const target = options.find((option) => option.textContent?.includes(`Account ${targetId}`))
  if (!target) throw new Error(`No account option for ${targetId}`)
  click(target)
}

describe("RuleBuilder", () => {
  it("keeps read-only calendars selectable as Source Calendars", () => {
    renderBuilder([accountA, accountB])

    const options = selectOptions("source-calendar")
    expect(options.map((option) => option.value)).toEqual([workA.id, holidaysA.id])
    expect(selectElement("source-calendar").disabled).toBe(false)
  })

  it("excludes read-only calendars from Destination options and never defaults to one", () => {
    renderBuilder([accountA, accountB])

    const options = selectOptions("destination-calendar")
    expect(options.map((option) => option.value)).toEqual([workB1.id, workB2.id])
    expect(options.some((option) => option.value === holidaysB.id)).toBe(false)
    // The default destination (no explicit choice made yet) must be a writable calendar.
    expect(selectElement("destination-calendar").value).toBe(workB1.id)
  })

  it("refreshes destination options to the newly selected account's writable calendars", () => {
    renderBuilder([accountA, accountB, accountD, accountC])

    expect(selectOptions("destination-calendar").map((option) => option.value)).toEqual([workB1.id, workB2.id])

    switchAccount("destination-account", "d")

    const options = selectOptions("destination-calendar")
    expect(options.map((option) => option.value)).toEqual([workD1.id])
    expect(selectElement("destination-calendar").value).toBe(workD1.id)
  })

  it("offers no destination and blocks submission for an account with no writable calendars", () => {
    renderBuilder([accountA, accountB, accountD, accountC])

    switchAccount("destination-account", "c")

    const destinationSelect = selectElement("destination-calendar")
    expect(selectOptions("destination-calendar")).toHaveLength(0)
    expect(destinationSelect.disabled).toBe(true)
    expect(destinationSelect.value).toBe("")
    expect(container.textContent).toContain("This account has no writable calendars to choose.")

    const submit = container.querySelector('button[type="submit"]') as HTMLButtonElement
    expect(submit.disabled).toBe(true)
  })
})
