/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { AddEmailScreen } from "./add-email-screen"
import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
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
  vi.restoreAllMocks()
})

async function renderScreen(i18n: I18n) {
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  await act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <AddEmailScreen />
          </QueryClientProvider>
        </ThemeProvider>
      </StaticI18nProvider>,
    )
    return Promise.resolve()
  })
}

async function addEmail(value: string) {
  const input = container.querySelector<HTMLInputElement>("input[type=email]")!
  act(() => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set?.call(input, value)
    input.dispatchEvent(new Event("input", { bubbles: true }))
  })
  await act(async () => {
    container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
}

describe("AddEmailScreen", () => {
  it("translates every word", async () => {
    await renderScreen(pseudoI18n())
    expect(untranslatedText(container)).toEqual([])
  })

  it("saves the email the upgraded administrator signs in with from now on", async () => {
    const fetch = vi.fn(() => Promise.resolve(jsonResponse({ id: "u", email: "admin@example.test" })))
    vi.stubGlobal("fetch", fetch)
    await renderScreen(testI18n())

    await addEmail("admin@example.test")

    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe("/api/v1/account/email")
    expect(init.method).toBe("PUT")
    expect(JSON.parse(init.body as string)).toEqual({ email: "admin@example.test" })
  })

  it("explains an email someone else already uses", async () => {
    const body = { detail: "taken", code: "email_taken", params: {} }
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(body, 409))))
    await renderScreen(testI18n())

    await addEmail("admin@example.test")

    expect(container.querySelector('[role="alert"]')?.textContent).toBe(
      "Someone else already signs in with this email.",
    )
  })
})
