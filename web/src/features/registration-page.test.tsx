/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { RegistrationPage } from "./registration-page"
import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const TOKEN = "inv_synthetic-token"
const SIGNED_IN = {
  authenticated: true,
  installation_sends_email: false,
  user: { id: "u2", email: "robin@example.test", role: "user", notify_by_email: true, instant_sync: true, instant_sync_availability: "on", instant_sync_help: null, language: null },
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
  page().happyDOM.setURL(`http://localhost:8000/verify-email${hash}`)
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <RegistrationPage onSignedIn={onSignedIn} />
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

describe("RegistrationPage", () => {
  it("keeps sign-in available on a usable verification form and temporary completion failure", async () => {
    serve({ "/api/v1/registrations/check": jsonResponse({ usable: true, email: "robin@example.test" }), "/api/v1/registrations": jsonResponse({ code: "registration_unavailable" }, 503) })
    await renderPage(testI18n(), `#${TOKEN}`)
    expect(container.querySelector("a[href='/']")).not.toBeNull()
    const fields = container.querySelectorAll<HTMLInputElement>("input[type=password]")
    type(fields[0]!, "a very long password")
    type(fields[1]!, "a very long password")
    await submit()
    expect(container.querySelector("form")).not.toBeNull()
    expect(container.querySelector("[role=alert]")?.textContent).toContain("Joining is unavailable")
    expect(container.querySelector("a[href='/']")).not.toBeNull()
  })

  it("translates the bound-email form and bounds passwords", async () => {
    serve({ "/api/v1/registrations/check": jsonResponse({ usable: true, email: "long-email-address-with-several-parts@example.test" }) })
    await renderPage(pseudoI18n(), `#${TOKEN}`)
    expect(untranslatedText(container, ["long-email-address-with-several-parts@example.test"])).toEqual([])
    expect([...container.querySelectorAll<HTMLInputElement>("input[type=password]")].every((input) => input.maxLength === 1024)).toBe(true)
  })
  it.each([429, 503])("retains a live proof after a temporary check refusal: %s", async (status) => {
    serve({ "/api/v1/registrations/check": jsonResponse({ code: "registration_unavailable" }, status) })
    await renderPage(testI18n(), `#${TOKEN}`)
    expect(container.querySelector("form")).toBeNull()
    expect(container.querySelector("[role=alert]")).not.toBeNull()
    expect([...container.querySelectorAll("button")].some((button) => button.textContent === "Check link again")).toBe(true)
    expect(window.location.hash).toBe(`#${TOKEN}`)
  })
  it("ignores an older completion after a new fragment opens", async () => {
    serve({ "/api/v1/registrations/check": jsonResponse({ usable: true, email: "robin@example.test" }) })
    const normal = vi.mocked(fetch).getMockImplementation()!
    let answer: (response: Response) => void = () => undefined
    vi.mocked(fetch).mockImplementation((input: string | URL | Request, init?: RequestInit) => {
      if ((input instanceof Request ? input.url : String(input)) === "/api/v1/registrations") return new Promise<Response>((resolve) => { answer = resolve })
      return normal(input, init)
    })
    const done = await renderPage(testI18n(), `#${TOKEN}`)
    const fields = container.querySelectorAll<HTMLInputElement>("input[type=password]")
    type(fields[0]!, "a very long password")
    type(fields[1]!, "a very long password")
    await submit()
    act(() => { window.location.hash = "#newer-proof" })
    await settle()
    act(() => answer(jsonResponse(SIGNED_IN)))
    await settle()
    expect(done).not.toHaveBeenCalled()
    expect(window.location.hash).toBe("#newer-proof")
    expect(container.querySelector<HTMLInputElement>("input[type=password]")!.value).toBe("")
  })

  it("shows_bound_email_and_confirms_password", async () => {
    const calls = serve({ "/api/v1/registrations/check": jsonResponse({ usable: true, email: "robin@example.test" }), "/api/v1/registrations": jsonResponse(SIGNED_IN) })
    const done = await renderPage(testI18n(), `#${TOKEN}`)
    expect(container.textContent).toContain("robin@example.test")
    expect(container.querySelector("input[type=email]")).toBeNull()
    const fields = container.querySelectorAll<HTMLInputElement>("input[type=password]")
    type(fields[0]!, "a very long password")
    type(fields[1]!, "different password")
    expect(container.querySelector<HTMLButtonElement>("button[type=submit]")!.disabled).toBe(true)
    type(fields[1]!, "a very long password")
    await submit()
    expect(calls.find((call) => call.url === "/api/v1/registrations")?.body).toEqual({ token: TOKEN, password: "a very long password" })
    expect(done).toHaveBeenCalledOnce()
    expect(window.location.hash).toBe("")
  })
  it("new_fragment_cannot_submit_old_proof", async () => {
    const calls = serve({ "/api/v1/registrations/check": jsonResponse({ usable: true, email: "robin@example.test" }) })
    await renderPage(testI18n(), `#${TOKEN}`)
    const fields = container.querySelectorAll<HTMLInputElement>("input[type=password]")
    type(fields[0]!, "a very long password")
    type(fields[1]!, "a very long password")
    page().happyDOM.setURL("http://localhost:8000/verify-email#newer-proof")
    await submit()
    expect(calls.some((call) => call.url === "/api/v1/registrations")).toBe(false)
  })
  it.each([false, true])("unusable_and_raced_proofs_offer_safe_recovery: %s", async (race) => {
    serve({ "/api/v1/setup": jsonResponse({ administrator_configured: true, public_registration_available: true, password_reset_available: true }), "/api/v1/registrations/check": jsonResponse({ usable: race, email: race ? "robin@example.test" : null }), "/api/v1/registrations": jsonResponse({ code: "link_unusable" }, 410) })
    await renderPage(testI18n(), `#${TOKEN}`)
    if (race) {
      const fields = container.querySelectorAll<HTMLInputElement>("input[type=password]")
      type(fields[0]!, "a very long password")
      type(fields[1]!, "a very long password")
      await submit()
    }
    expect(container.querySelector("form")).toBeNull()
    expect(container.querySelector("a[href='/sign-up']")).not.toBeNull()
    expect(container.querySelector("a[href='/']")).not.toBeNull()
  })
  it("session_failure_offers_sign_in", async () => {
    const calls = serve({ "/api/v1/registrations/check": jsonResponse({ usable: true, email: "robin@example.test" }), "/api/v1/registrations": jsonResponse({ code: "incorrect_credentials" }, 401) })
    await renderPage(testI18n(), `#${TOKEN}`)
    const fields = container.querySelectorAll<HTMLInputElement>("input[type=password]")
    type(fields[0]!, "a very long password")
    type(fields[1]!, "a very long password")
    await submit()
    expect(container.querySelector("form")).toBeNull()
    expect(container.textContent).toContain("Your account was created")
    expect(container.querySelector("a[href='/']")).not.toBeNull()
    expect(calls.filter((call) => call.url === "/api/v1/registrations")).toHaveLength(1)
  })
})
