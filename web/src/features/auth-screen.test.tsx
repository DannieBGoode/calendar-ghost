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

/** Submits the login form against a server that answers 401 with `body`; returns the alert. */
async function logInFailing(i18n: I18n, body: object): Promise<Element | null> {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(body, 401))))
  const { container } = await renderAuth(i18n, "login")
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
  return container.querySelector('[role="alert"]')
}

describe("AuthScreen", () => {
  it("translates the setup screen", async () => {
    const { container } = await renderAuth(pseudoI18n(), "setup")
    expect(untranslatedText(container)).toEqual([])
  })

  it("translates the server's code when the password is incorrect", async () => {
    const body = { detail: "incorrect password", code: "incorrect_password", params: {} }
    const alert = await logInFailing(testI18n(), body)
    expect(alert?.textContent).toBe("That password is incorrect.")
  })

  it("has no untranslated text in a coded error", async () => {
    const body = { detail: "incorrect password", code: "incorrect_password", params: {} }
    const alert = await logInFailing(pseudoI18n(), body)
    expect(alert).not.toBeNull()
    expect(untranslatedText(alert!)).toEqual([])
  })

  it("shows the server's detail for an error without a known code", async () => {
    const alert = await logInFailing(testI18n(), { detail: "incorrect password" })
    expect(alert?.textContent).toBe("incorrect password")
  })
})
