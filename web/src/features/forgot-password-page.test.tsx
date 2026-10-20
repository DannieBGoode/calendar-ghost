/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ForgotPasswordPage } from "./forgot-password-page"
import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: Root | null = null

beforeEach(() => {
  container = document.createElement("div")
  document.body.append(container)
})

afterEach(() => {
  act(() => root?.unmount())
  root = null
  container.remove()
  vi.restoreAllMocks()
})

function json(body: unknown, status = 200) {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

function serve(available = true, response = json({ accepted: true }, 202)) {
  const fetch = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>((url) => Promise.resolve(url === "/api/v1/setup"
    ? json({ administrator_configured: true, password_reset_available: available })
    : response))
  vi.stubGlobal("fetch", fetch)
  return fetch
}

async function settle() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
}

async function renderPage(i18n: I18n = testI18n()) {
  root = createRoot(container)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => root?.render(
    <StaticI18nProvider i18n={i18n}><ThemeProvider><QueryClientProvider client={client}>
      <ForgotPasswordPage />
    </QueryClientProvider></ThemeProvider></StaticI18nProvider>,
  ))
  await settle()
  await settle()
}

function typeEmail(value: string) {
  const input = container.querySelector<HTMLInputElement>("input")!
  act(() => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set?.call(input, value)
    input.dispatchEvent(new Event("input", { bubbles: true }))
  })
}

async function submit() {
  act(() => { container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })) })
  await settle()
  await settle()
}

describe("ForgotPasswordPage", () => {
  it("asks only for email, sends the exact body, and gives a generic sent state", async () => {
    const fetch = serve()
    await renderPage()
    expect(container.querySelectorAll("input")).toHaveLength(1)
    expect(container.querySelector("input")?.type).toBe("email")
    typeEmail("person@example.test")
    await submit()
    const request = fetch.mock.calls.find(([url]) => url === "/api/v1/password-resets/request")
    expect(request?.[1]).toMatchObject({ method: "POST", body: JSON.stringify({ email: "person@example.test" }) })
    expect(container.querySelector('[role="status"]')?.textContent).toBe("If this address can receive a reset link, we will send one.")
    expect(container.textContent).not.toContain("person@example.test")
    expect(container.querySelector<HTMLAnchorElement>("a[href='/']")?.textContent).toBe("Back to sign in")
    expect(container.querySelector("form")).toBeNull()
    act(() => [...container.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === "Try again or use another email")!.click())
    await settle()
    expect(container.querySelector<HTMLInputElement>("input")?.value).toBe("person@example.test")
    expect(document.activeElement).toBe(container.querySelector("input"))
    await submit()
    expect(fetch.mock.calls.filter(([url]) => url === "/api/v1/password-resets/request")).toHaveLength(2)
  })

  it.each([
    [429, "reset_network_throttled", "Too many reset attempts from this network. Wait a while, then try again."],
    [429, "reset_global_throttled", "Password reset is busy. Wait a while, then try again."],
    [503, "reset_storage_unavailable", "Password reset is temporarily unavailable. Try again shortly."],
    [503, "identity_email_not_configured", "Email recovery is unavailable. Ask your administrator for a password reset link."],
  ])("translates %s %s while preserving the email for retry", async (status, code, message) => {
    serve(true, json({ detail: "server detail", code, params: {} }, status))
    await renderPage()
    typeEmail("person@example.test")
    await submit()
    expect(container.querySelector('[role="alert"]')?.textContent).toBe(message)
    expect(container.querySelector<HTMLInputElement>("input")?.value).toBe("person@example.test")
    expect(container.querySelector<HTMLButtonElement>("button[type=submit]")?.disabled).toBe(false)
  })

  it("retries a failed request through the same form", async () => {
    const fetch = serve(true, json({ detail: "busy", code: "reset_storage_unavailable", params: {} }, 503))
    await renderPage()
    typeEmail("person@example.test")
    await submit()
    expect(container.querySelector('[role="alert"]')).not.toBeNull()
    fetch.mockResolvedValue(json({ accepted: true }, 202))
    await submit()
    expect(container.querySelector('[role="status"]')?.textContent).toBe("If this address can receive a reset link, we will send one.")
    expect(container.querySelector('[role="alert"]')).toBeNull()
    expect(document.activeElement).toBe(container.querySelector('[role="status"]'))
  })

  it("explains administrator recovery at a direct unavailable address", async () => {
    const fetch = serve(false)
    await renderPage()
    expect(container.querySelector("form")).toBeNull()
    expect(container.textContent).toContain("Ask your administrator for a password reset link.")
    expect(container.querySelector("a[href='/']")).not.toBeNull()
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it("translates the request and sent states", async () => {
    serve()
    await renderPage(pseudoI18n())
    expect(untranslatedText(container)).toEqual([])
    typeEmail("person@example.test")
    await submit()
    expect(untranslatedText(container)).toEqual([])
  })
})
