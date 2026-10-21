/* @vitest-environment happy-dom */
import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, expect, it, vi } from "vitest"

import { OwnEmailItem } from "@/features/settings-own-email"
import { StaticI18nProvider } from "@/i18n/provider"
import { testI18n } from "@/i18n/testing"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const response = (body: unknown, status = 200) => ({ ok: status < 400, status, json: () => Promise.resolve(body) }) as Response
const pending = (id: string, email = `${id}@example.test`) => ({ mode: "verified", reason: null, pending: { id, email, expires_at: "2026-10-22T12:00:00Z" } })
let container: HTMLDivElement
let root: Root
let client: QueryClient
let announced: ReturnType<typeof vi.fn<(message: string) => void>>
let status = pending("one")
let finishCancel: (value: Response) => void
beforeEach(() => {
  container = document.createElement("div"); document.body.append(container)
  status = pending("one")
  announced = vi.fn()
  vi.stubGlobal("fetch", vi.fn((input: string | URL, init?: RequestInit) => {
    if (init?.method === "DELETE") return new Promise<Response>((resolve) => { finishCancel = resolve })
    return Promise.resolve(response(status))
  }))
})
afterEach(() => {
  act(() => root.unmount()); client.clear(); container.remove(); focusManager.setFocused(undefined); vi.restoreAllMocks()
})
async function settle() { for (let i = 0; i < 6; i++) await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) }) }
async function render() {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(["session"], { authenticated: true, user: { id: "owner" } })
  root = createRoot(container)
  act(() => root.render(<StaticI18nProvider i18n={testI18n()}><QueryClientProvider client={client}><OwnEmailItem email="current@example.test" onDone={announced} /></QueryClientProvider></StaticI18nProvider>))
  await settle()
}
function button(text: string) { return [...container.querySelectorAll("button")].find((b) => b.textContent === text)! }

it("keeps a newer pending request when an older cancellation finishes, without announcing the newer one cancelled", async () => {
  await render()
  act(() => button("Cancel email change").click())
  await settle()
  status = pending("two")
  await act(() => client.setQueryData(["own-email-change", "owner"], status))
  act(() => finishCancel(response(null, 204)))
  await settle()
  expect(container.textContent).toContain("two@example.test")
  expect(container.textContent).not.toContain("one@example.test")
  expect(announced).not.toHaveBeenCalled()
  expect(vi.mocked(fetch).mock.calls.some(([url, init]) => (typeof url === "string" && url.endsWith("request_id=one")) && init?.method === "DELETE")).toBe(true)
})

it("refetches on window focus and wraps long addresses without truncating them", async () => {
  const long = `${"long".repeat(45)}@example.test`
  status = pending("one", long)
  await render()
  expect(container.textContent).toContain(long)
  expect(container.querySelector('[class*="overflow-wrap:anywhere"]')).not.toBeNull()
  status = pending("two")
  act(() => focusManager.setFocused(false))
  act(() => focusManager.setFocused(true))
  await settle()
  expect(container.textContent).toContain("two@example.test")
  expect(container.textContent).not.toContain(long)
})


it("keeps cancellation available when SMTP is removed and requires clearing the pending request before direct change", async () => {
  status = { ...pending("one"), mode: "direct" }
  await render()
  expect(button("Change email").disabled).toBe(true)
  expect(button("Cancel email change").disabled).toBe(false)
  expect(container.textContent).toContain("Cancel the pending change")
})
