/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { PasswordResetPage } from "./password-reset-page"
import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const TOKEN = "reset_synthetic-token"

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

async function renderPage(i18n: I18n, hash = `#${TOKEN}`) {
  page().happyDOM.setURL(`http://localhost:8000/password-reset${hash}`)
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <PasswordResetPage />
          </QueryClientProvider>
        </ThemeProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
}

function type(input: HTMLInputElement, value: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set?.call(input, value)
    input.dispatchEvent(new Event("input", { bubbles: true }))
  })
}

async function resetTo(password: string) {
  const [first, second] = container.querySelectorAll<HTMLInputElement>("input[type=password]")
  type(first!, password)
  type(second!, password)
  await act(async () => {
    container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
  await settle()
}

describe("PasswordResetPage", () => {
  it("translates the form, the refusal, and the confirmation", async () => {
    serve({
      "/api/v1/password-resets/check": jsonResponse({ usable: true }),
      "/api/v1/password-resets": { ok: true, status: 204, json: () => Promise.resolve(null) } as Response,
    })
    await renderPage(pseudoI18n())
    expect(container.querySelector("form")).not.toBeNull()
    expect(untranslatedText(container)).toEqual([])

    await resetTo("a very long password")
    expect(container.querySelector("form")).toBeNull()
    expect(untranslatedText(container)).toEqual([])

    act(() => root?.unmount())
    root = null
    serve({ "/api/v1/password-resets/check": jsonResponse({ usable: false }) })
    await renderPage(pseudoI18n())
    expect(untranslatedText(container)).toEqual([])
  })

  it("sets the new password with the token from the address, then offers to sign in", async () => {
    const calls = serve({
      "/api/v1/password-resets/check": jsonResponse({ usable: true }),
      "/api/v1/password-resets": { ok: true, status: 204, json: () => Promise.resolve(null) } as Response,
    })
    await renderPage(testI18n())
    expect(calls[0]).toEqual({ url: "/api/v1/password-resets/check", method: "POST", body: { token: TOKEN } })

    await resetTo("a very long password")

    expect(calls.find((call) => call.url === "/api/v1/password-resets")).toEqual({
      url: "/api/v1/password-resets",
      method: "POST",
      body: { token: TOKEN, password: "a very long password" },
    })
    expect(container.querySelector("h2")?.textContent).toBe("Your password was changed")
    expect(container.querySelector<HTMLAnchorElement>("a[href='/']")?.textContent).toBe("Sign in")
    // The used link leaves the address bar.
    expect(window.location.hash).toBe("")
  })

  it("starts over for a newer link opened in the same tab", async () => {
    serve({
      "/api/v1/password-resets/check": jsonResponse({ usable: true }),
      "/api/v1/password-resets": { ok: true, status: 204, json: () => Promise.resolve(null) } as Response,
    })
    await renderPage(testI18n())
    await resetTo("a very long password")
    expect(container.querySelector("h2")?.textContent).toBe("Your password was changed")

    // Opening another link to this page changes only the fragment; the page is not reloaded.
    const calls = serve({
      "/api/v1/password-resets/check": jsonResponse({ usable: true }),
      "/api/v1/password-resets": { ok: true, status: 204, json: () => Promise.resolve(null) } as Response,
    })
    act(() => {
      window.location.hash = "#reset_newer-token"
    })
    await settle()

    expect(calls[0]).toEqual({ url: "/api/v1/password-resets/check", method: "POST", body: { token: "reset_newer-token" } })
    expect(container.querySelector("h2")?.textContent).toBe("Your new password")
    expect(container.querySelector<HTMLInputElement>("input[type=password]")!.value).toBe("")
    await resetTo("another long password")
    expect(calls.find((call) => call.url === "/api/v1/password-resets")?.body).toEqual({
      token: "reset_newer-token",
      password: "another long password",
    })
  })

  it("ignores an older link's answer that arrives after a newer link was opened", async () => {
    serve({ "/api/v1/password-resets/check": jsonResponse({ usable: true }) })
    const served = vi.mocked(fetch).getMockImplementation()!
    let answerOlder: (response: Response) => void = () => undefined
    vi.mocked(fetch).mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      const url = input instanceof Request ? input.url : String(input)
      if (url !== "/api/v1/password-resets") return served(input, init)
      return new Promise<Response>((resolve) => {
        answerOlder = resolve
      })
    })
    await renderPage(testI18n())
    await resetTo("a very long password")

    act(() => {
      window.location.hash = "#reset_newer-token"
    })
    await settle()
    act(() => answerOlder({ ok: true, status: 204, json: () => Promise.resolve(null) } as Response))
    await settle()

    // The newer link stays in the address, so it still works after a reload.
    expect(window.location.hash).toBe("#reset_newer-token")
    expect(container.querySelector("h2")?.textContent).toBe("Your new password")
    expect(container.querySelector("form")).not.toBeNull()
  })

  it("refuses a link that was used or expired", async () => {
    serve({ "/api/v1/password-resets/check": jsonResponse({ usable: false }) })
    await renderPage(testI18n())
    expect(container.querySelector("form")).toBeNull()
    expect(container.querySelector("h2")?.textContent).toBe("This link cannot be used")
  })

  it("explains the server's refusal", async () => {
    serve({
      "/api/v1/password-resets/check": jsonResponse({ usable: true }),
      "/api/v1/password-resets": jsonResponse({ detail: "gone", code: "link_unusable", params: {} }, 410),
    })
    await renderPage(testI18n())
    await resetTo("a very long password")
    expect(container.querySelector('[role="alert"]')?.textContent).toBe(
      "This link was already used, replaced, or has expired. Ask your administrator for a new one.",
    )
  })
})
