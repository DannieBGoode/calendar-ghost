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

async function renderAuth(i18n: I18n, mode: "setup" | "login", passwordOnly = false) {
  root = createRoot(container)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  // A thenable callback makes act flush the first queries before it returns.
  await act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <AuthScreen mode={mode} passwordOnly={passwordOnly} />
          </QueryClientProvider>
        </ThemeProvider>
      </StaticI18nProvider>,
    )
    return Promise.resolve()
  })
  return { container }
}

function type(input: HTMLInputElement, value: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set?.call(input, value)
    input.dispatchEvent(new Event("input", { bubbles: true }))
  })
}

async function submit(container: HTMLElement) {
  const form = container.querySelector("form")!
  await act(async () => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
}

function sentBody(fetch: ReturnType<typeof vi.fn>): unknown {
  const init = fetch.mock.calls[0]?.[1] as RequestInit | undefined
  return init?.body ? JSON.parse(init.body as string) : undefined
}

/** Submits the login form against a server that answers 401 with `body`; returns the alert. */
async function logInFailing(i18n: I18n, body: object): Promise<Element | null> {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(body, 401))))
  const { container } = await renderAuth(i18n, "login")
  type(container.querySelector<HTMLInputElement>("input[type=email]")!, "person@example.test")
  type(container.querySelector<HTMLInputElement>("input[type=password]")!, "a very long password")
  await submit(container)
  return container.querySelector('[role="alert"]')
}

describe("AuthScreen", () => {
  it("translates the setup screen", async () => {
    const { container } = await renderAuth(pseudoI18n(), "setup")
    expect(untranslatedText(container)).toEqual([])
  })

  it("translates the sign-in screen", async () => {
    const { container } = await renderAuth(pseudoI18n(), "login", true)
    expect(untranslatedText(container)).toEqual([])
  })

  it("translates the server's code when the email or password is incorrect", async () => {
    const body = { detail: "no match", code: "incorrect_credentials", params: {} }
    const alert = await logInFailing(testI18n(), body)
    expect(alert?.textContent).toBe("That email and password do not match.")
  })

  it("signs in with the email and password", async () => {
    const fetch = vi.fn(() => Promise.resolve(jsonResponse({ authenticated: true, user: null })))
    vi.stubGlobal("fetch", fetch)
    const { container } = await renderAuth(testI18n(), "login")
    type(container.querySelector<HTMLInputElement>("input[type=email]")!, "person@example.test")
    type(container.querySelector<HTMLInputElement>("input[type=password]")!, "a very long password")

    await submit(container)

    expect(sentBody(fetch)).toEqual({ email: "person@example.test", password: "a very long password" })
  })

  it("asks for an email before signing in, unless the installation still allows the password alone", async () => {
    const fetch = vi.fn(() => Promise.resolve(jsonResponse({ authenticated: true, user: null })))
    vi.stubGlobal("fetch", fetch)
    const required = await renderAuth(testI18n(), "login")
    expect(required.container.querySelector<HTMLInputElement>("input[type=email]")!.required).toBe(true)
    act(() => root?.unmount())

    const { container } = await renderAuth(testI18n(), "login", true)
    type(container.querySelector<HTMLInputElement>("input[type=password]")!, "a very long password")
    await submit(container)

    expect(container.querySelector<HTMLInputElement>("input[type=email]")!.required).toBe(false)
    expect(sentBody(fetch)).toEqual({ email: null, password: "a very long password" })
  })

  it("creates the administrator with an email and a confirmed password", async () => {
    const fetch = vi.fn(() => Promise.resolve(jsonResponse({ authenticated: true, user: null })))
    vi.stubGlobal("fetch", fetch)
    const { container } = await renderAuth(testI18n(), "setup")
    const [password, confirmation] = container.querySelectorAll<HTMLInputElement>("input[type=password]")
    type(password!, "a very long password")
    type(confirmation!, "a very long password")
    const button = container.querySelector<HTMLButtonElement>("button[type=submit]")!
    expect(button.disabled).toBe(true)

    type(container.querySelector<HTMLInputElement>("input[type=email]")!, "admin@example.test")
    await submit(container)

    expect(sentBody(fetch)).toEqual({ email: "admin@example.test", password: "a very long password" })
  })

  it("has no untranslated text in a coded error", async () => {
    const body = { detail: "no match", code: "incorrect_credentials", params: {} }
    const alert = await logInFailing(pseudoI18n(), body)
    expect(alert).not.toBeNull()
    expect(untranslatedText(alert!)).toEqual([])
  })

  it("shows the server's detail for an error without a known code", async () => {
    const alert = await logInFailing(testI18n(), { detail: "incorrect password" })
    expect(alert?.textContent).toBe("incorrect password")
  })
})
