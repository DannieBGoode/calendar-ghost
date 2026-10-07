/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import App from "./App"
import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n } from "@/i18n/testing"
import { untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { Dashboard } from "@/lib/api"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const dashboard: Dashboard = {
  status: "setup",
  needs_attention: false,
  problems: [],
  connected_accounts: 0,
  disconnected_accounts: 0,
  lapsed_accounts: 0,
  sync_rules: 0,
  enabled_rules: 0,
  stopped_rules: 0,
  open_incidents: 0,
  last_synced_at: null,
  blocked_events: 0,
  blocked_entry_id: null,
  blocked_rule_id: null,
}

const RESPONSES: Record<string, unknown> = {
  "/api/v1/setup": { administrator_configured: true },
  "/api/v1/session": { authenticated: true },
  "/api/v1/dashboard": dashboard,
  "/api/v1/rules": [],
  "/api/v1/accounts": [],
  "/api/v1/google/configuration": { configured: false, redirect_uri: null },
  "/api/v1/recent-changes": [],
}

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: () => Promise.resolve(body) } as Response
}

let container: HTMLDivElement
let root: Root | null = null

beforeEach(() => {
  container = document.createElement("div")
  document.body.append(container)
  vi.stubGlobal("fetch", vi.fn((input: string | URL) => Promise.resolve(respond(String(input)))))
  function respond(url: string): Response {
    const path = url.split("?")[0] ?? ""
    if (path in RESPONSES) return jsonResponse(RESPONSES[path])
    return jsonResponse({})
  }
})

afterEach(() => {
  if (root) {
    act(() => root?.unmount())
    root = null
  }
  container.remove()
  localStorage.clear()
  vi.restoreAllMocks()
})

async function settle(times = 6) {
  for (let i = 0; i < times; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

async function renderApp(i18n: I18n) {
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <App />
          </QueryClientProvider>
        </ThemeProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
  return { container }
}

describe("App", () => {
  it("translates the whole page", async () => {
    const { container } = await renderApp(pseudoI18n())
    const header = container.querySelector("header")
    const footer = container.querySelector("footer")
    expect(header).not.toBeNull()
    expect(footer).not.toBeNull()
    expect(untranslatedText(container)).toEqual([])
  })

  it("links the footer to the troubleshooting guide in a new tab", async () => {
    const { container } = await renderApp(testI18n())
    const help = [...container.querySelectorAll("footer a")].find((link) => link.textContent === "Get help")
    expect(help?.getAttribute("href")).toBe("https://calendarghost.com/docs/troubleshooting")
    expect(help?.getAttribute("target")).toBe("_blank")
  })

  it("titles the page in the active language", async () => {
    await renderApp(testI18n())
    expect(document.title).toBe("Overview – Calendar Ghost")
  })
})
