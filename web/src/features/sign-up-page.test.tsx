/* @vitest-environment happy-dom */

import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { SignUpPage } from "./sign-up-page"
import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

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
  page().happyDOM.setURL(`http://localhost:8000/sign-up${hash}`)
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <SignUpPage />
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

describe("SignUpPage", () => {
  it("keeps generic sent state when returning from the email app", async () => {
    serve({ "/api/v1/setup": jsonResponse({ administrator_configured: true, public_registration_available: true }), "/api/v1/registrations/request": jsonResponse({ accepted: true }, 202) })
    await renderPage(testI18n(), "")
    type(container.querySelector<HTMLInputElement>("input[type=email]")!, "robin@example.test")
    await submit()
    let answer: (response: Response) => void = () => undefined
    vi.mocked(fetch).mockImplementation(() => new Promise<Response>((resolve) => { answer = resolve }))
    act(() => focusManager.setFocused(false))
    act(() => focusManager.setFocused(true))
    await settle()
    expect(container.querySelector('[role="status"]')?.textContent).toContain("If this address can join")
    expect(container.querySelector("form")).toBeNull()
    act(() => answer(jsonResponse({ administrator_configured: true, public_registration_available: true })))
    await settle()
    focusManager.setFocused(undefined)
  })

  it("rechecks availability and recovers when joining closes after entry", async () => {
    serve({ "/api/v1/setup": jsonResponse({ administrator_configured: true, public_registration_available: true }) })
    await renderPage(testI18n(), "")
    type(container.querySelector<HTMLInputElement>("input[type=email]")!, "robin@example.test")
    serve({ "/api/v1/setup": jsonResponse({ administrator_configured: true, public_registration_available: false }), "/api/v1/registrations/request": jsonResponse({ code: "registration_unavailable" }, 503) })
    await submit()
    expect(container.querySelector("form")).toBeNull()
    expect(container.querySelector("h2")?.textContent).toBe("Joining is unavailable")
    expect(container.querySelector("a[href='/']")).not.toBeNull()
  })

  it("translates the email-only flow", async () => {
    serve({ "/api/v1/setup": jsonResponse({ administrator_configured: true, public_registration_available: true }) })
    await renderPage(pseudoI18n(), "")
    expect(untranslatedText(container)).toEqual([])
  })
  it.each([429, 503])("retains a safe next step when admission answers %s after opening", async (status) => {
    serve({ "/api/v1/setup": jsonResponse({ administrator_configured: true, public_registration_available: true }), "/api/v1/registrations/request": jsonResponse({ code: status === 429 ? "registration_network_throttled" : "registration_unavailable", detail: "Internal diagnostic must not be shown for unavailability" }, status) })
    await renderPage(testI18n(), "")
    type(container.querySelector<HTMLInputElement>("input[type=email]")!, "robin@example.test")
    await submit()
    expect(container.querySelector("[role=alert]")).not.toBeNull()
    expect(container.querySelector("a[href='/']")).not.toBeNull()
    expect(container.textContent).not.toContain("If this address can join")
    if (status === 503) expect(container.textContent).not.toContain("Internal diagnostic")
  })

  it("requests_email_only_and_shows_generic_sent_state", async () => {
    const calls = serve({ "/api/v1/setup": jsonResponse({ administrator_configured: true, public_registration_available: true }), "/api/v1/registrations/request": jsonResponse({ accepted: true }, 202) })
    await renderPage(testI18n(), "")
    expect(container.querySelector("input[type=password]")).toBeNull()
    type(container.querySelector<HTMLInputElement>("input[type=email]")!, "robin@example.test")
    await submit()
    expect(calls.find((call) => call.url === "/api/v1/registrations/request")?.body).toEqual({ email: "robin@example.test", invitation_token: null })
    expect(container.querySelector('[role="status"]')?.textContent).toContain("If this address can join")
  })
  it("resend_uses_same_form_and_limits", async () => {
    const calls = serve({ "/api/v1/setup": jsonResponse({ administrator_configured: true, public_registration_available: true }), "/api/v1/registrations/request": jsonResponse({ accepted: true }, 202) })
    await renderPage(testI18n(), "")
    type(container.querySelector<HTMLInputElement>("input[type=email]")!, "robin@example.test")
    await submit()
    act(() => [...container.querySelectorAll("button")].find((button) => button.textContent === "Resend or edit email")!.click())
    await settle()
    expect(container.querySelector<HTMLInputElement>("input[type=email]")!.value).toBe("robin@example.test")
    await submit()
    expect(calls.filter((call) => call.url === "/api/v1/registrations/request")).toHaveLength(2)
  })
  it("unavailable_has_sign_in_next_step", async () => {
    serve({ "/api/v1/setup": jsonResponse({ administrator_configured: true, public_registration_available: false }) })
    await renderPage(testI18n(), "")
    expect(container.querySelector("form")).toBeNull()
    expect(container.querySelector("a[href='/']")).not.toBeNull()
  })
})
