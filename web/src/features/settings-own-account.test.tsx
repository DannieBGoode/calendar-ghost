/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"
import type { SignedInUser } from "@/lib/api"

import { OwnAccountSection } from "./settings-own-account"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const user: SignedInUser = {
  id: "user-robin",
  email: "robin@example.test",
  role: "user",
  notify_by_email: true,
  language: null,
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as Response
}

const NO_CONTENT = { ok: true, status: 204, json: () => Promise.resolve(null) } as Response

type Call = { method: string; path: string; body: unknown }
let calls: Call[] = []

function serve(answers: Record<string, Response> = {}) {
  const routes: Record<string, Response> = {
    "PUT /api/v1/account/email": jsonResponse({ ...user, email: "robin@home.example.test" }),
    "PUT /api/v1/account/password": NO_CONTENT,
    "PUT /api/v1/account/notifications": jsonResponse({ ...user, notify_by_email: false }),
    "DELETE /api/v1/account": jsonResponse({ rules: 1, deleted: 3, detached: 0, left: 0 }),
    ...answers,
  }
  calls = []
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL, init?: RequestInit) => {
      const method = init?.method ?? "GET"
      const path = String(input)
      const body: unknown = init?.body ? JSON.parse(init.body as string) : undefined
      calls.push({ method, path, body })
      return Promise.resolve(routes[`${method} ${path}`] ?? jsonResponse({}))
    }),
  )
}

let container: HTMLDivElement
let root: Root | null = null
let queryClient: QueryClient

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

async function settle(times = 6) {
  for (let i = 0; i < times; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

async function renderSection(i18n: I18n, { sendsEmail = true, answers = {} } = {}) {
  serve(answers)
  root = createRoot(container)
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <OwnAccountSection user={user} sendsEmail={sendsEmail} />
        </QueryClientProvider>
      </StaticI18nProvider>,
    )
  })
  await settle()
}

function button(label: string, scope: ParentNode = container): HTMLButtonElement {
  const found = [...scope.querySelectorAll("button")].find((item) => item.textContent.trim() === label)
  if (!found) throw new Error(`No button labelled ${label}`)
  return found
}

function field(id: string): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>(`#${id}`)
  if (!input) throw new Error(`No field ${id}`)
  return input
}

function type(input: HTMLInputElement, value: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set?.call(input, value)
    input.dispatchEvent(new Event("input", { bubbles: true }))
  })
}

async function click(target: HTMLElement) {
  act(() => target.click())
  await settle()
}

async function submit(form: HTMLFormElement) {
  await act(async () => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
  await settle()
}

function sent(method: string, path: string): unknown {
  return calls.find((call) => call.method === method && call.path === path)?.body
}

function status(): string | null | undefined {
  return container.querySelector("[role='status']")?.textContent
}

describe("OwnAccountSection", () => {
  it("has no untranslated text with every form open", async () => {
    await renderSection(pseudoI18n())
    for (const id of ["own-email-toggle", "own-password-toggle", "own-delete-toggle"]) {
      await click(container.querySelector<HTMLButtonElement>(`#${id}`)!)
    }
    expect(container.querySelector("#own-delete-confirmation")).not.toBeNull()
    expect(untranslatedText(container, [user.email!])).toEqual([])
  })

  it("has no untranslated text where the installation sends no email", async () => {
    await renderSection(pseudoI18n(), { sendsEmail: false })
    expect(untranslatedText(container, [user.email!])).toEqual([])
  })

  it("changes the email with the current password", async () => {
    await renderSection(testI18n())
    expect(container.textContent).toContain("robin@example.test")
    await click(button("Change email"))
    type(field("own-email"), "robin@home.example.test")
    type(field("own-email-password"), "a very long password")
    await submit(field("own-email").form!)

    expect(sent("PUT", "/api/v1/account/email")).toEqual({
      email: "robin@home.example.test",
      password: "a very long password",
    })
    expect(status()).toBe("You now sign in with robin@home.example.test.")
  })

  it("changes the password once the new one is confirmed, and says other devices were signed out", async () => {
    await renderSection(testI18n())
    await click(button("Change password"))
    type(field("own-current-password"), "the old long password")
    type(field("own-new-password"), "a very long password")
    type(field("own-new-password-confirmation"), "a different password")
    expect(button("Save password").disabled).toBe(true)

    type(field("own-new-password-confirmation"), "a very long password")
    await submit(field("own-new-password").form!)

    expect(sent("PUT", "/api/v1/account/password")).toEqual({
      current_password: "the old long password",
      new_password: "a very long password",
    })
    expect(status()).toBe("Your password was changed. Your other devices were signed out.")
  })

  it("explains an incorrect current password", async () => {
    const refusal = { detail: "wrong", code: "incorrect_password", params: {} }
    await renderSection(testI18n(), { answers: { "PUT /api/v1/account/password": jsonResponse(refusal, 403) } })
    await click(button("Change password"))
    type(field("own-current-password"), "not the password")
    type(field("own-new-password"), "a very long password")
    type(field("own-new-password-confirmation"), "a very long password")
    await submit(field("own-new-password").form!)
    expect(container.querySelector("[role='alert']")?.textContent).toBe("That password is incorrect.")
  })

  it("turns incident emails off", async () => {
    await renderSection(testI18n())
    const toggle = field("own-incident-emails")
    expect(toggle.checked).toBe(true)
    await click(toggle)
    expect(sent("PUT", "/api/v1/account/notifications")).toEqual({ notify_by_email: false })
    expect(status()).toBe("Calendar Ghost no longer emails you about incidents. They still appear in Activity.")
  })

  it("says incident emails are unavailable where the installation sends no email", async () => {
    await renderSection(testI18n(), { sendsEmail: false })
    expect(field("own-incident-emails").disabled).toBe(true)
    expect(container.textContent).toContain(
      "This Calendar Ghost does not send email, so incidents appear only in Activity.",
    )
  })

  it("deletes your own account, keeping the events your rules wrote when you choose, then signs you out", async () => {
    await renderSection(testI18n())
    queryClient.setQueryData(["rules"], [{ id: "rule-private" }])
    await click(button("Delete your account"))
    const confirmation = container.querySelector<HTMLElement>("#own-delete-confirmation")!
    expect(confirmation.querySelector<HTMLInputElement>("input[value='delete']")!.checked).toBe(true)
    expect(button("Delete my account", confirmation).disabled).toBe(true)

    await click(confirmation.querySelector<HTMLInputElement>("input[value='detach']")!)
    type(field("own-delete-password"), "a very long password")
    await click(button("Delete my account", confirmation))

    expect(sent("DELETE", "/api/v1/account")).toEqual({ password: "a very long password", projections: "detach" })
    // Nothing the deleted User could see stays in memory.
    expect(queryClient.getQueryData(["rules"])).toBeUndefined()
  })
})
