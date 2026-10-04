/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { AuthScreen } from "./auth-screen"
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
  localStorage.clear()
  vi.restoreAllMocks()
})

async function renderAuth(i18n: I18n, mode: "setup" | "login") {
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  // A thenable callback makes act flush the first queries before it returns.
  await act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <AuthScreen mode={mode} />
          </QueryClientProvider>
        </ThemeProvider>
      </StaticI18nProvider>,
    )
    return Promise.resolve()
  })
  return { container }
}

describe("AuthScreen", () => {
  it("translates the setup screen", async () => {
    const { container } = await renderAuth(pseudoI18n(), "setup")
    expect(untranslatedText(container)).toEqual([])
  })

  it("shows the server's detail when the password is incorrect", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse({ detail: "incorrect password" }, 401))))
    const { container } = await renderAuth(testI18n(), "login")
    const input = container.querySelector<HTMLInputElement>("input[type=password]")!
    act(() => {
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set?.call(input, "a very long password")
      input.dispatchEvent(new Event("input", { bubbles: true }))
    })
    const form = container.querySelector("form")!
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    const alert = container.querySelector('[role="alert"]')
    expect(alert?.textContent).toBe("incorrect password")
  })
})
