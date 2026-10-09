/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { InvitationPage } from "./invitation-page"
import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const TOKEN = "inv_synthetic-token"
const SIGNED_IN = {
  authenticated: true,
  installation_sends_email: false,
  user: { id: "u2", email: "robin@example.test", role: "user", notify_by_email: true, language: null },
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

type Call = { url: string; method: string; body: unknown }

function serve(routes: Record<string, Response>): Call[] {
  const calls: Call[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push({ url, method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body as string) : undefined })
      return Promise.resolve(routes[url] ?? jsonResponse({}))
    }),
  )
  return calls
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

async function settle(times = 6) {
  for (let i = 0; i < times; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

async function renderPage(i18n: I18n, hash: string, onSignedIn = vi.fn()) {
  page().happyDOM.setURL(`http://localhost:8000/invitation${hash}`)
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <InvitationPage onSignedIn={onSignedIn} />
          </QueryClientProvider>
        </ThemeProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
  return onSignedIn
}

function type(input: HTMLInputElement, value: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set?.call(input, value)
    input.dispatchEvent(new Event("input", { bubbles: true }))
  })
}

async function submit() {
  await act(async () => {
    container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
  await settle()
}

function fillForm(email: string, password: string, confirmation = password) {
  type(container.querySelector<HTMLInputElement>("input[type=email]")!, email)
  const [first, second] = container.querySelectorAll<HTMLInputElement>("input[type=password]")
  type(first!, password)
  type(second!, confirmation)
}

describe("InvitationPage", () => {
  it("translates the form", async () => {
    serve({ "/api/v1/invitations/check": jsonResponse({ usable: true }) })
    await renderPage(pseudoI18n(), `#${TOKEN}`)
    expect(container.querySelector("form")).not.toBeNull()
    expect(untranslatedText(container)).toEqual([])
  })

  it("translates the refusal", async () => {
    serve({ "/api/v1/invitations/check": jsonResponse({ usable: false }) })
    await renderPage(pseudoI18n(), `#${TOKEN}`)
    expect(container.querySelector("form")).toBeNull()
    expect(untranslatedText(container)).toEqual([])
  })

  it("checks the token from the address before offering the form", async () => {
    const calls = serve({ "/api/v1/invitations/check": jsonResponse({ usable: true }) })
    await renderPage(testI18n(), `#${TOKEN}`)
    expect(calls[0]).toEqual({ url: "/api/v1/invitations/check", method: "POST", body: { token: TOKEN } })
    expect(container.querySelector("form")).not.toBeNull()
  })

  it("refuses a link that was used, revoked, or expired, and offers to sign in", async () => {
    serve({ "/api/v1/invitations/check": jsonResponse({ usable: false }) })
    await renderPage(testI18n(), `#${TOKEN}`)
    expect(container.querySelector("form")).toBeNull()
    expect(container.querySelector("h2")?.textContent).toBe("This invitation cannot be used")
    expect(container.querySelector<HTMLAnchorElement>("a[href='/']")?.textContent).toBe("Go to sign in")
  })

  it("refuses an address without a token without asking the server", async () => {
    const calls = serve({})
    await renderPage(testI18n(), "")
    expect(calls).toEqual([])
    expect(container.querySelector("h2")?.textContent).toBe("This invitation cannot be used")
  })

  it("joins with the token, the email, and a confirmed password, then leaves the token behind", async () => {
    const calls = serve({
      "/api/v1/invitations/check": jsonResponse({ usable: true }),
      "/api/v1/invitations/accept": jsonResponse(SIGNED_IN),
    })
    const onSignedIn = await renderPage(testI18n(), `#${TOKEN}`)
    fillForm("robin@example.test", "a very long password", "a different password")
    expect(container.querySelector<HTMLButtonElement>("button[type=submit]")!.disabled).toBe(true)

    fillForm("robin@example.test", "a very long password")
    await submit()

    expect(calls.find((call) => call.url === "/api/v1/invitations/accept")).toEqual({
      url: "/api/v1/invitations/accept",
      method: "POST",
      body: { token: TOKEN, email: "robin@example.test", password: "a very long password" },
    })
    expect(onSignedIn).toHaveBeenCalledOnce()
    expect(window.location.pathname).toBe("/overview")
    expect(window.location.hash).toBe("")
  })

  it("explains a link that stopped working while the form was open", async () => {
    serve({
      "/api/v1/invitations/check": jsonResponse({ usable: true }),
      "/api/v1/invitations/accept": jsonResponse({ detail: "gone", code: "link_unusable", params: {} }, 410),
    })
    const onSignedIn = await renderPage(testI18n(), `#${TOKEN}`)
    fillForm("robin@example.test", "a very long password")
    await submit()

    expect(container.querySelector('[role="alert"]')?.textContent).toBe(
      "This link was already used, replaced, or has expired. Ask your administrator for a new one.",
    )
    expect(onSignedIn).not.toHaveBeenCalled()
  })
})
