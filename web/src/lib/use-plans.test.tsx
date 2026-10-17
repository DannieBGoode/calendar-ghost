/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, useEffect } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { StaticI18nProvider } from "@/i18n/provider"
import { testI18n } from "@/i18n/testing"
import type { PlanSummary, PlansOverview } from "@/lib/api"
import { OWN_PLAN_QUERY } from "@/lib/use-own-plan"
import { PLANS_QUERY, type PlanCommands, usePlans } from "@/lib/use-plans"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const family: PlanSummary = {
  key: "family",
  name: "Family",
  limits: { rules: 5, connected_accounts: 3, integration_tokens: 2, sync_interval: "instant" },
  is_default: false,
  people: 4,
  limited_people: 3,
  over_people: 0,
  use: { rules: [], connected_accounts: [], integration_tokens: [] },
}
const free: PlanSummary = {
  key: "free",
  name: "Free",
  limits: { rules: 1, connected_accounts: 1, integration_tokens: 0, sync_interval: "5_minutes" },
  is_default: true,
  people: 2,
  limited_people: 2,
  over_people: 0,
  use: { rules: [], connected_accounts: [], integration_tokens: [] },
}
const overview: PlansOverview = {
  enabled: false,
  default_plan: "free",
  sync_intervals: ["instant", "5_minutes"],
  administrators: 1,
  followers: 2,
  plans: [family, free],
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

const NO_CONTENT = { ok: true, status: 204, json: () => Promise.resolve(null) } as Response

type Call = { method: string; path: string; body: unknown }
let calls: Call[] = []
let root: Root | null = null
let queryClient: QueryClient
let commands: PlanCommands | undefined

function serve(answers: Record<string, Response>) {
  const routes: Record<string, Response> = { "GET /api/v1/plans": jsonResponse(overview), ...answers }
  calls = []
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET"
      const path = String(input)
      const body: unknown = init?.body ? JSON.parse(init.body as string) : undefined
      calls.push({ method, path, body })
      return Promise.resolve(routes[`${method} ${path}`] ?? jsonResponse({}))
    }),
  )
}

function Probe({ onCommands }: { onCommands: (next: PlanCommands) => void }) {
  const plans = usePlans()
  useEffect(() => {
    onCommands(plans)
  })
  return null
}

async function settle() {
  for (let i = 0; i < 6; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

async function render(answers: Record<string, Response> = {}) {
  serve(answers)
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  // Someone's person page and the administrator's own Plan, both open before the change.
  queryClient.setQueryData(["people", "overview", "user-robin"], { plan: null })
  queryClient.setQueryData(OWN_PLAN_QUERY, { basis: "administrator" })
  root = createRoot(document.createElement("div"))
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={testI18n()}>
        <QueryClientProvider client={queryClient}>
          <Probe
            onCommands={(next) => {
              commands = next
            }}
          />
        </QueryClientProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
}

/** Runs one command and waits for its answer and every refresh after it. */
async function run(command: (plans: PlanCommands) => void) {
  act(() => {
    if (commands) command(commands)
  })
  await settle()
}

/** Whether a change marked a query stale, so it reads again when next shown. */
function refreshed(queryKey: readonly unknown[]): boolean {
  return queryClient.getQueryState(queryKey)?.isInvalidated === true
}

beforeEach(() => {
  commands = undefined
})

afterEach(() => {
  if (root) act(() => root?.unmount())
  root = null
  vi.restoreAllMocks()
})

describe("usePlans", () => {
  it("lists every Plan under its own key", async () => {
    await render()
    expect(commands?.plans.data).toEqual(overview)
    expect(queryClient.getQueryData(PLANS_QUERY)).toEqual(overview)
  })

  it("turns Plans on with the default it already has, and reads again what Plans change", async () => {
    const on: PlansOverview = { ...overview, enabled: true }
    await render({ "PUT /api/v1/plan-settings": jsonResponse(on) })
    await run((plans) => plans.setting.mutate({ enabled: true, defaultPlan: "free" }))
    expect(calls.find((call) => call.method === "PUT")).toEqual({
      method: "PUT",
      path: "/api/v1/plan-settings",
      body: { enabled: true, default_plan: "free" },
    })
    expect(queryClient.getQueryData(PLANS_QUERY)).toEqual(on)
    expect(commands?.setting.data).toEqual(on)
    expect(refreshed(["people", "overview", "user-robin"])).toBe(true)
    expect(refreshed(OWN_PLAN_QUERY)).toBe(true)
  })

  it("turns Plans on with no default, as the server then makes No limits the default", async () => {
    const off: PlansOverview = { ...overview, default_plan: null, plans: [family, { ...free, is_default: false }] }
    await render({ "GET /api/v1/plans": jsonResponse(off), "PUT /api/v1/plan-settings": jsonResponse(overview) })
    await run((plans) => plans.setting.mutate({ enabled: true, defaultPlan: null }))
    expect(calls.find((call) => call.method === "PUT")?.body).toEqual({ enabled: true, default_plan: null })
  })

  it("adds, saves, and removes a Plan, listing the Plans again after each", async () => {
    await render({
      "POST /api/v1/plans": jsonResponse({ ...family, key: "family-2", name: "Family Plus" }, 201),
      "PUT /api/v1/plans/family": jsonResponse({ ...family, name: "Family Large" }),
      "DELETE /api/v1/plans/family": NO_CONTENT,
    })
    const listings = () => calls.filter((call) => call.method === "GET" && call.path === "/api/v1/plans").length
    const payload = { key: "family-2", name: "Family Plus", limits: family.limits }
    await run((plans) => plans.define.mutate(payload))
    expect(calls.find((call) => call.method === "POST")?.body).toEqual(payload)
    expect(listings()).toBe(2)

    await run((plans) => plans.change.mutate({ key: "family", payload: { name: "Family Large", limits: family.limits } }))
    expect(calls.find((call) => call.method === "PUT")?.path).toBe("/api/v1/plans/family")
    expect(listings()).toBe(3)

    await run((plans) => plans.remove.mutate("family"))
    expect(calls.find((call) => call.method === "DELETE")?.path).toBe("/api/v1/plans/family")
    expect(listings()).toBe(4)
    expect(refreshed(OWN_PLAN_QUERY)).toBe(true)
  })

  it("gives Plans to people, one call for each move, then reads again what Plans change", async () => {
    await render({ "POST /api/v1/plan-assignments": jsonResponse({ dry_run: false, people: [] }) })
    await run((plans) =>
      plans.assign.mutate({
        from: "free",
        via: "undo",
        moves: [
          { plan: null, userIds: ["user-alex"] },
          { plan: "family", userIds: ["user-sam", "user-lee"] },
        ],
      }),
    )
    expect(calls.filter((call) => call.method === "POST").map((call) => call.body)).toEqual([
      { plan: null, user_ids: ["user-alex"], dry_run: false },
      { plan: "family", user_ids: ["user-sam", "user-lee"], dry_run: false },
    ])
    expect(commands?.assign.data).toHaveLength(2)
    expect(calls.filter((call) => call.method === "GET" && call.path === "/api/v1/plans").length).toBe(2)
    expect(refreshed(["people", "overview", "user-robin"])).toBe(true)
    expect(refreshed(OWN_PLAN_QUERY)).toBe(true)
  })
})
