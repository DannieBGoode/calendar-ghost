/* @vitest-environment happy-dom */
import { dehydrate, QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

import App from "@/App"
import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { pseudoI18n, testI18n, untranslatedText } from "@/i18n/testing"
import type { I18n } from "@/i18n/translator"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const TOKEN = "email_synthetic-proof"
const TARGET = "new.owner@example.test"
const pending = (email = TARGET) => ({ mode: "verified", pending: { id: "request-one", email, expires_at: "2026-10-22T12:00:00Z" } })
const USER = { id: "owner", email: "owner@example.test", role: "user" }
const session = (id = "owner") => ({ authenticated: true, user: { ...USER, id } })
const response = (body: unknown, status = 200) => ({ ok: status < 400, status, json: () => Promise.resolve(body) }) as Response
const NO_CONTENT = response(null, 204)
let container: HTMLDivElement
let root: Root
let client: QueryClient
let routes: Record<string, Response | (() => Promise<Response>)>
let calls: { method: string; url: string; body: unknown }[]
const page = window as typeof window & { happyDOM: { setURL: (url: string) => void } }
beforeEach(() => {
  page.happyDOM.setURL(`http://localhost:8000/email-change#${TOKEN}`)
  container = document.createElement("div")
  document.body.append(container)
  routes = {
    "GET /api/v1/session": response(session()),
    "GET /api/v1/account/email-change": response(pending()),
    "GET /api/v1/setup": response({ administrator_configured: true }),
    "POST /api/v1/account/email-change/check": response({ usable: true }),
    "POST /api/v1/account/email-change/confirm": NO_CONTENT,
  }
  calls = []
  vi.stubGlobal("fetch", vi.fn((input: string | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? "GET"
    calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
    const answer = routes[`${method} ${url}`] ?? response({})
    return typeof answer === "function" ? answer() : Promise.resolve(answer)
  }))
})
afterEach(() => {
  act(() => root.unmount())
  client.clear()
  container.remove()
  page.happyDOM.setURL("http://localhost:8000/")
  vi.restoreAllMocks()
})
async function settle() {
  for (let i = 0; i < 6; i++) await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
}
async function render(i18n: I18n = testI18n()) {
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: 2 } } })
  root = createRoot(container)
  act(() => root.render(<StaticI18nProvider i18n={i18n}><ThemeProvider><QueryClientProvider client={client}><App /></QueryClientProvider></ThemeProvider></StaticI18nProvider>))
  await settle()
}
function type(selector: string, value: string) {
  const field = container.querySelector<HTMLInputElement>(selector)!
  act(() => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set?.call(field, value)
    field.dispatchEvent(new Event("input", { bubbles: true }))
  })
}
async function submit() {
  await act(() => container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })))
  await settle()
}
function button(label: string) { return [...container.querySelectorAll("button")].find((b) => b.textContent === label)! }
function deferred() {
  let resolve: (value: Response) => void = () => undefined
  const promise = new Promise<Response>((done) => { resolve = done })
  return { promise, resolve }
}

it("routes to inline sign-in without checking the proof, preserves it through sign-in, and confirms with current password", async () => {
  routes["GET /api/v1/session"] = response({ authenticated: false, user: null })
  routes["POST /api/v1/session"] = () => { routes["GET /api/v1/session"] = response(session()); return Promise.resolve(NO_CONTENT) }
  await render()
  expect(container.querySelector("h1")?.textContent).toBe("Confirm your email change")
  expect(calls.some((c) => c.url.endsWith("/check"))).toBe(false)
  type("input[type=email]", USER.email)
  type("input[type=password]", "synthetic password")
  await submit()
  expect(calls.find((c) => c.url.endsWith("/check"))?.body).toEqual({ token: TOKEN })
  expect(container.textContent).toContain(USER.email)
  type("input[type=password]", "synthetic password")
  await submit()
  expect(calls.find((c) => c.url.endsWith("/confirm"))?.body).toEqual({ token: TOKEN, password: "synthetic password" })
  expect(container.textContent).toContain("Your other devices were signed out")
  expect(container.querySelector("a[href='/settings/account']")).not.toBeNull()
  expect(window.location.hash).toBe("")
  expect(document.activeElement).toBe(container.querySelector("a[href='/settings/account']"))
  expect(JSON.stringify(dehydrate(client))).not.toContain(TOKEN)
  expect(JSON.stringify(client.getMutationCache().getAll().map((m) => m.state))).not.toContain(TOKEN)
  expect(calls.filter((c) => c.method === "GET" && c.url.endsWith("/session")).length).toBeGreaterThan(2)
})

it("shows neutral unusable state, own-account retry and account switching without disclosing another address", async () => {
  routes["POST /api/v1/account/email-change/check"] = response({ usable: false })
  routes["DELETE /api/v1/session"] = () => { routes["GET /api/v1/session"] = response({ authenticated: false, user: null }); return Promise.resolve(NO_CONTENT) }
  await render()
  expect(container.textContent).toContain("This link cannot be used with this account")
  expect(container.querySelector("input[type=password]")).toBeNull()
  expect(container.querySelector("a[href='/settings/account']")).not.toBeNull()
  act(() => button("Use another account").click())
  await settle()
  expect(container.querySelector("input[type=email]")).not.toBeNull()
  expect(window.location.hash).toBe(`#${TOKEN}`)
})

it("ignores a late usable check after a User switch and clears the prior User's cached records", async () => {
  const older = deferred()
  routes["POST /api/v1/account/email-change/check"] = () => older.promise
  await render()
  client.setQueryData(["accounts"], [{ email: "private@example.test" }])
  routes["POST /api/v1/account/email-change/check"] = response({ usable: false })
  await act(() => client.setQueryData(["session"], session("someone-else")))
  older.resolve(response({ usable: true }))
  await settle()
  expect(container.querySelector("input[type=password]")).toBeNull()
  expect(container.textContent).toContain("This link cannot be used with this account")
  expect(client.getQueryData(["accounts"])).toBeUndefined()
})

it.each([200, 403])("ignores late confirmation %s after a fragment change, preserving the new token and clearing typed state", async (status) => {
  const older = deferred()
  routes["POST /api/v1/account/email-change/confirm"] = () => older.promise
  await render()
  type("input[type=password]", "synthetic password")
  await submit()
  expect(container.querySelector<HTMLInputElement>("input[type=password]")?.value).toBe("")
  act(() => { window.location.hash = "#email_new-proof" })
  older.resolve(response({ detail: "wrong", code: "incorrect_password", params: {} }, status))
  await settle()
  expect(window.location.hash).toBe("#email_new-proof")
  expect(container.textContent).not.toContain("Your other devices were signed out")
  expect(container.querySelector("[role=alert]")).toBeNull()
  expect(container.querySelector<HTMLInputElement>("input[type=password]")?.value).toBe("")
})

it("does not retry confirmation, clears the password, and offers retry when the proof expires during submission", async () => {
  routes["POST /api/v1/account/email-change/confirm"] = response({ detail: "gone", code: "email_change_proof_unusable", params: {} }, 410)
  await render()
  type("input[type=password]", "synthetic password")
  await submit()
  expect(container.querySelector("input[type=password]")).toBeNull()
  expect(container.querySelector("a[href='/settings/account']")).not.toBeNull()
  expect(calls.filter((c) => c.url.endsWith("/confirm"))).toHaveLength(1)
})

it("translates usable, complete and unavailable states without storing proof or password", async () => {
  const stored = vi.spyOn(Storage.prototype, "setItem")
  await render(pseudoI18n())
  expect(untranslatedText(container, [USER.email, TARGET])).toEqual([])
  type("input[type=password]", "synthetic password")
  await submit()
  expect(untranslatedText(container, [USER.email, TARGET])).toEqual([])
  expect(stored.mock.calls.flat().join(" ")).not.toContain(TOKEN)
  expect(JSON.stringify(dehydrate(client))).not.toContain("synthetic password")
})


it.each([200, 403])("ignores a late confirmation %s after a User switch, with no password, error or success crossing accounts", async (code) => {
  const older = deferred()
  routes["POST /api/v1/account/email-change/confirm"] = () => older.promise
  await render()
  type("input[type=password]", "synthetic password")
  await submit()
  routes["POST /api/v1/account/email-change/check"] = response({ usable: false })
  await act(() => client.setQueryData(["session"], session("another-user")))
  act(() => older.resolve(response({ detail: "wrong", code: "incorrect_password", params: {} }, code)))
  await settle()
  expect(container.textContent).not.toContain("Your other devices were signed out")
  expect(container.querySelector("input[type=password]")).toBeNull()
  expect(container.querySelector("[role=alert]")).toBeNull()
  expect(window.location.hash).toBe(`#${TOKEN}`)
})

it("cannot flash a usable answer when the fragment changes before hashchange is delivered", async () => {
  const older = deferred()
  routes["POST /api/v1/account/email-change/check"] = () => older.promise
  await render()
  routes["POST /api/v1/account/email-change/check"] = response({ usable: false })
  // The address changes before the earlier response is delivered.
  window.history.replaceState(null, "", "/email-change#new_synthetic-proof")
  act(() => older.resolve(response({ usable: true })))
  await settle()
  expect(container.querySelector("input[type=password]")).toBeNull()
  expect(window.location.hash).toBe("#new_synthetic-proof")
})

it("keeps an incorrect-password refusal at its field and a spent link out of success", async () => {
  routes["POST /api/v1/account/email-change/confirm"] = response({ detail: "wrong", code: "incorrect_password", params: {} }, 403)
  await render()
  type("input[type=password]", "synthetic password")
  await submit()
  const field = container.querySelector<HTMLInputElement>("input[type=password]")!
  expect(field.value).toBe("")
  expect(field.getAttribute("aria-invalid")).toBe("true")
  expect(document.activeElement).toBe(field)
  expect(container.querySelector("[role=alert]")?.textContent).toBe("That password is incorrect.")
})

it("reads the pending target freshly only after the current proof is usable", async () => {
  const proof = deferred()
  routes["POST /api/v1/account/email-change/check"] = () => proof.promise
  await render()
  client.setQueryData(["own-email-change", "owner"], pending("cached@example.test"))
  expect(calls.some((c) => c.url === "/api/v1/account/email-change")).toBe(false)
  expect(container.querySelector("input[type=password]")).toBeNull()
  act(() => proof.resolve(response({ usable: true })))
  await settle()
  expect(container.textContent).toContain(`New email: ${TARGET}`)
  expect(container.textContent).not.toContain("cached@example.test")
  expect(container.querySelector("input[type=password]")).not.toBeNull()
})

it.each(["token", "User"])("ignores a late pending target after a %s switch", async (boundary) => {
  const status = deferred()
  routes["GET /api/v1/account/email-change"] = () => status.promise
  await render()
  expect(container.querySelector("input[type=password]")).toBeNull()
  routes["POST /api/v1/account/email-change/check"] = response({ usable: false })
  if (boundary === "token") window.history.replaceState(null, "", "/email-change#new_synthetic-proof")
  else await act(() => client.setQueryData(["session"], session("another-user")))
  act(() => status.resolve(response(pending("stale@example.test"))))
  await settle()
  expect(container.textContent).not.toContain("stale@example.test")
  expect(container.querySelector("input[type=password]")).toBeNull()
})
