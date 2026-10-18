/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, useEffect } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, describe, expect, it, vi } from "vitest"

import { StaticI18nProvider } from "@/i18n/provider"
import { testI18n } from "@/i18n/testing"
import type { IntegrationToken, OwnPlan } from "@/lib/api"
import { type AccountCommands, useAccountCommands } from "@/lib/use-account-commands"
import { type IntegrationTokens, useIntegrationTokens } from "@/lib/use-integration-tokens"
import {
  OWN_PLAN_QUERY,
  useAccountLimitReason,
  useOwnPlan,
  usePlanWarning,
  useRuleLimitNote,
  useTokenLimitReason,
} from "@/lib/use-own-plan"
import { RULE_CHANGE_QUERIES } from "@/lib/use-rule-commands"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

/** A User at every limit of their Plan, with more rules counted than it allows. */
const atEveryLimit: OwnPlan = {
  basis: "plan",
  plan: { key: "free", name: "Free", on_default: true },
  limits: { rules: 1, connected_accounts: 2, integration_tokens: 0, sync_interval: "5_minutes" },
  rules_counted: 2,
  connected_accounts: 2,
  integration_tokens: 0,
  instant: false,
  poll_every_minutes: 5,
  may_connect_account: false,
  may_issue_token: false,
  over_rule_limit: true,
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

type Hints = {
  loaded: boolean
  warning: boolean
  account: string | undefined
  token: string | undefined
  rules: string | undefined
}

/** What every hint reads when the Plan gives none: nothing limits, or the Plan is unknown. */
const NO_HINTS: Hints = { loaded: true, warning: false, account: undefined, token: undefined, rules: undefined }

let root: Root | null = null
let hints: Hints = { ...NO_HINTS, loaded: false }
let queryClient: QueryClient

function Probe({ onHints }: { onHints: (next: Hints) => void }) {
  const loaded = !useOwnPlan().isPending
  const warning = usePlanWarning()
  const account = useAccountLimitReason()
  const token = useTokenLimitReason()
  const rules = useRuleLimitNote()
  useEffect(() => {
    onHints({ loaded, warning, account, token, rules })
  })
  return null
}

/** Renders the hints with `answer` to every read; `cached` is a Plan read before, such as on another page. */
async function render(answer: Response, cached?: OwnPlan) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(answer)),
  )
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (cached) queryClient.setQueryData(OWN_PLAN_QUERY, cached)
  root = createRoot(document.createElement("div"))
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={testI18n()}>
        <QueryClientProvider client={queryClient}>
          <Probe
            onHints={(next) => {
              hints = next
            }}
          />
        </QueryClientProvider>
      </StaticI18nProvider>,
    )
  })
  for (let i = 0; i < 4; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

afterEach(() => {
  if (root) act(() => root?.unmount())
  root = null
  vi.restoreAllMocks()
})

describe("own plan hints", () => {
  it("reads the signed-in User's Plan once, under its own key", async () => {
    await render(jsonResponse(atEveryLimit))
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe("/api/v1/account/plan")
    expect(queryClient.getQueryData(OWN_PLAN_QUERY)).toEqual(atEveryLimit)
  })

  it("warns and says why Connect and new tokens are unavailable at the Plan's limits", async () => {
    await render(jsonResponse(atEveryLimit))
    expect(hints).toEqual({
      loaded: true,
      warning: true,
      account: "Your plan allows 2 calendar accounts, and disconnected accounts count too.",
      token: "Your plan does not include integration tokens. To get one, ask your administrator.",
      rules: "Your plan lets 1 rule sync at once.",
    })
  })

  it.each([
    [1, "Your plan allows 1 integration token, and it is in use. Revoke it to issue another."],
    [3, "Your plan allows 3 integration tokens, and all are in use. Revoke one to issue another."],
  ])("says a limit of %i tokens is in use, and how to make room", async (limit, reason) => {
    await render(
      jsonResponse({ ...atEveryLimit, limits: { ...atEveryLimit.limits, integration_tokens: limit }, integration_tokens: limit }),
    )
    expect(hints.token).toBe(reason)
  })

  it("names the Plan's rule limit while the Plan has room, as a note beside Create sync rule", async () => {
    await render(
      jsonResponse({
        ...atEveryLimit,
        limits: { ...atEveryLimit.limits, rules: 3 },
        rules_counted: 0,
        may_connect_account: true,
        may_issue_token: true,
        over_rule_limit: false,
      }),
    )
    expect(hints).toEqual({ ...NO_HINTS, rules: "Your plan lets 3 rules sync at once." })
  })

  it("names no rule limit for a Plan that sets none", async () => {
    await render(jsonResponse({ ...atEveryLimit, limits: { ...atEveryLimit.limits, rules: null }, over_rule_limit: false }))
    expect(hints.rules).toBeUndefined()
  })

  it("says nothing but the rule limit while the Plan has room", async () => {
    await render(
      jsonResponse({ ...atEveryLimit, may_connect_account: true, may_issue_token: true, over_rule_limit: false }),
    )
    expect(hints).toEqual({ ...NO_HINTS, rules: "Your plan lets 1 rule sync at once." })
  })

  it("says nothing for an administrator or while Plans are off", async () => {
    await render(
      jsonResponse({
        ...atEveryLimit,
        basis: "administrator",
        plan: null,
        limits: null,
        may_connect_account: true,
        may_issue_token: true,
        over_rule_limit: false,
      }),
    )
    expect(hints).toEqual(NO_HINTS)
  })

  it("gives no hint and no warning for an empty answer", async () => {
    await render(jsonResponse({}))
    expect(hints).toEqual(NO_HINTS)
  })

  it("gives no hint, no warning, and no rule limit when the Plan cannot be read, so every control stays enabled", async () => {
    await render(jsonResponse({ detail: "Internal Server Error" }, 500))
    expect(hints).toEqual(NO_HINTS)
  })

  it("drops the hints read before once the Plan cannot be read again, so a place freed since is not kept closed", async () => {
    await render(jsonResponse({ detail: "Internal Server Error" }, 500), atEveryLimit)
    // The failed refresh keeps the earlier answer in the cache; the hints must not follow it.
    expect(queryClient.getQueryState(OWN_PLAN_QUERY)?.status).toBe("error")
    expect(queryClient.getQueryData(OWN_PLAN_QUERY)).toEqual(atEveryLimit)
    expect(hints).toEqual(NO_HINTS)
  })
})

const NO_CONTENT = { ok: true, status: 204, json: () => Promise.resolve(null) } as Response

/** An unrevoked token the person can revoke. */
const homeMonitor: IntegrationToken = {
  id: "token-1",
  name: "Home monitor",
  scopes: ["status:read"],
  created_at: "2026-10-15T09:00:00Z",
  last_used_at: null,
  revoked_at: null,
}

type Commands = { accounts: AccountCommands; tokens: IntegrationTokens }
let commands: Commands | undefined

/** Answers each account and token command by its method and path. */
function serveCommands() {
  const routes: Record<string, Response> = {
    "GET /api/v1/integration-tokens": jsonResponse([homeMonitor]),
    "POST /api/v1/integration-tokens": jsonResponse({ ...homeMonitor, token: "cg_synthetic_token" }, 201),
    "DELETE /api/v1/integration-tokens/token-1": NO_CONTENT,
    "POST /api/v1/accounts/account-1/disconnect": jsonResponse({ id: "account-1", display_name: "Work" }),
    "DELETE /api/v1/accounts/account-1": NO_CONTENT,
  }
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL, init?: RequestInit) =>
      Promise.resolve(routes[`${init?.method ?? "GET"} ${String(input)}`] ?? jsonResponse({})),
    ),
  )
}

function CommandsProbe({ onCommands }: { onCommands: (next: Commands) => void }) {
  const accounts = useAccountCommands(undefined)
  const tokens = useIntegrationTokens()
  useEffect(() => {
    onCommands({ accounts, tokens })
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

/**
 * Runs one account or token command beside a Your plan that was already read, and answers
 * whether the command marked it stale, so it reads again when next shown.
 */
async function refreshesOwnPlan(command: (current: Commands) => void): Promise<boolean> {
  serveCommands()
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  queryClient.setQueryData(OWN_PLAN_QUERY, atEveryLimit)
  root = createRoot(document.createElement("div"))
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={testI18n()}>
        <QueryClientProvider client={queryClient}>
          <CommandsProbe
            onCommands={(next) => {
              commands = next
            }}
          />
        </QueryClientProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
  expect(queryClient.getQueryState(OWN_PLAN_QUERY)?.isInvalidated).toBe(false)
  act(() => {
    if (commands) command(commands)
  })
  await settle()
  return queryClient.getQueryState(OWN_PLAN_QUERY)?.isInvalidated === true
}

describe("own plan refresh", () => {
  it("reads the Plan again after every rule change, which can change how many rules count", () => {
    expect(RULE_CHANGE_QUERIES).toContainEqual(OWN_PLAN_QUERY)
  })

  it("reads the Plan again after an account is disconnected, which stops its rules", async () => {
    expect(await refreshesOwnPlan(({ accounts }) => accounts.disconnect.mutate("account-1"))).toBe(true)
  })

  it("reads the Plan again after an account is deleted, which frees a calendar account", async () => {
    expect(await refreshesOwnPlan(({ accounts }) => accounts.permanentDelete.mutate("account-1"))).toBe(true)
  })

  it("reads the Plan again after a token is issued", async () => {
    expect(await refreshesOwnPlan(({ tokens }) => tokens.issue.mutate())).toBe(true)
  })

  it("reads the Plan again after a token is revoked", async () => {
    expect(await refreshesOwnPlan(({ tokens }) => tokens.revoke.mutate(homeMonitor))).toBe(true)
  })
})
