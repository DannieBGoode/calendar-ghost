/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, createElement } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it } from "vitest"

import { CalendarReplacement } from "./calendar-replacement"
import type { ConnectedAccount, DiscoveredCalendar, RuleDetail } from "@/lib/api"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: Root | null = null
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

const accounts: ConnectedAccount[] = ["a", "b"].map((id) => ({
  id,
  display_name: `Account ${id}`,
  email: `${id}@example.test`,
  provider: "google",
  avatar_url: null,
  state: "connected",
  rule_count: 1,
  authorized_at: "2026-10-02T00:00:00Z",
}))

function calendar(id: string): DiscoveredCalendar {
  return { id, summary: id, access_role: "owner", writable: true, primary: false }
}

function detail(sourceCalendar: string, destinationCalendar: string): RuleDetail {
  return {
    id: "rule-1",
    source: { connected_account_id: "a", calendar_id: sourceCalendar, calendar_name: null },
    destination: { connected_account_id: "b", calendar_id: destinationCalendar, calendar_name: null },
    privacy_policy: "busy_only",
    sync_all_day_events: true,
    tentative_events: "mark",
    unanswered_invitations: "as_tentative",
    state: "enabled",
    reprojection_required: false,
    initial_lookback_days: 30,
    mapping_count: 0,
    last_sync: null,
    last_reconciliation: null,
    latest_preview: null,
    running: null,
  }
}

function render(rule: RuleDetail) {
  act(() => {
    root?.render(
      createElement(
        QueryClientProvider,
        { client: queryClient },
        createElement(CalendarReplacement, {
          detail: rule,
          accounts,
          destinationName: "Work",
          destinationConnected: true,
          onReplaced: () => undefined,
        }),
      ),
    )
  })
}

function select(id: string): HTMLSelectElement {
  const found = container.querySelector<HTMLSelectElement>(`#${id}`)
  if (!found) throw new Error(`No select #${id}`)
  return found
}

beforeEach(() => {
  queryClient.setQueryData(["calendars", "a"], [calendar("personal"), calendar("family")])
  queryClient.setQueryData(["calendars", "b"], [calendar("work"), calendar("team")])
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
  render(detail("personal", "work"))
  const open = Array.from(container.querySelectorAll("button")).find((button) =>
    button.textContent.includes("Replace calendars"),
  )
  act(() => {
    open?.dispatchEvent(new MouseEvent("click", { bubbles: true }))
  })
})

afterEach(() => {
  act(() => {
    root?.unmount()
  })
  root = null
  container.remove()
})

describe("CalendarReplacement", () => {
  it("follows the rule while a field is untouched, so a refreshed rule never shows stale calendars", () => {
    render(detail("family", "team"))

    expect(select("replace-source-calendar").value).toBe("family")
    expect(select("replace-destination-calendar").value).toBe("team")
  })

  it("keeps the administrator's edit when the rule refreshes", () => {
    const destination = select("replace-destination-calendar")
    act(() => {
      destination.value = "team"
      destination.dispatchEvent(new Event("change", { bubbles: true }))
    })

    render(detail("family", "work"))

    expect(select("replace-source-calendar").value).toBe("family")
    expect(select("replace-destination-calendar").value).toBe("team")
  })
})
