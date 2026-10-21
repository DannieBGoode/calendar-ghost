/* @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { StaticI18nProvider } from "@/i18n/provider"
import { testI18n } from "@/i18n/testing"
import type { components } from "@/lib/api-schema"

import { IdentityEmailSection } from "./settings-identity-email"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Readiness = components["schemas"]["IdentityEmailResponse"]
const idle: Readiness = { configured: true, unavailable_reason: null, test_state: "idle", tested_at: null }
let container: HTMLDivElement
let root: Root
let state: Readiness
let getFailure: boolean
let postFailure: boolean
let reads: number
let posts: number

beforeEach(() => {
  vi.useFakeTimers()
  state = idle
  getFailure = false
  postFailure = false
  reads = 0
  posts = 0
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
  vi.stubGlobal("fetch", vi.fn((_input: string, init: RequestInit) => {
    if (init.method === "POST") {
      posts += 1
      return Promise.resolve(new Response(postFailure ? '{"detail":"Try later", "code":"identity_email_test_throttled"}' : "", { status: postFailure ? 429 : 202 }))
    }
    reads += 1
    return Promise.resolve(new Response(JSON.stringify(getFailure ? { detail: "Unavailable" } : state), { status: getFailure ? 503 : 200 }))
  }))
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
async function tick(ms = 20) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms) })
}
async function render() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  act(() => root.render(<StaticI18nProvider i18n={testI18n()}><QueryClientProvider client={client}><IdentityEmailSection /></QueryClientProvider></StaticI18nProvider>))
  await tick()
  return client
}
function button() { return container.querySelector<HTMLButtonElement>("button")! }
async function click() { act(() => button().click()); await tick() }

describe("Identity email", () => {
  it("invalidates registration and setup when the current email test succeeds", async () => {
    const client = await render()
    client.setQueryData(["registration"], { open_available: false })
    client.setQueryData(["setup"], { public_registration_available: false })
    state = { ...idle, test_state: "queued" }
    await click()
    state = { ...idle, test_state: "accepted", tested_at: "2026-10-21T12:00:00Z" }
    await tick(1000)
    expect(client.getQueryState(["registration"])?.isInvalidated).toBe(true)
    expect(client.getQueryState(["setup"])?.isInvalidated).toBe(true)
  })

  it.each([
    ["smtp_missing", "CALENDAR_SYNC_SMTP_HOST"], ["smtp_security", "STARTTLS"],
    ["origin_missing", "PUBLIC_URL"], ["origin_invalid", "root origin"],
    ["origin_insecure", "HTTPS"], ["master_key_missing", "Master Key"],
  ] as const)("disables testing with an actionable %s hint", async (reason, hint) => {
    state = { ...idle, configured: false, unavailable_reason: reason }
    await render()
    expect(button().disabled).toBe(true)
    expect(container.textContent).toContain(hint)
  })

  it("test_identity_email_states_and_polling", async () => {
    await render()
    expect(button().disabled).toBe(false)
    expect(container.querySelector("input")).toBeNull()
    const initialReads = reads
    await tick(1500)
    expect(reads).toBe(initialReads)
    state = { ...idle, test_state: "queued" }
    await click()
    expect(posts).toBe(1)
    expect(container.textContent).not.toContain("accepted the test email")
    expect(button().disabled).toBe(true)
    state = { ...idle, test_state: "sending" }
    await tick(1000)
    expect(button().textContent).toBe("Sending test email…")
    state = { ...idle, test_state: "accepted", tested_at: "2026-10-20T12:00:00Z" }
    await tick(1000)
    expect(container.querySelector("[role='status']")?.textContent).toContain("mail server accepted")
    const acceptedReads = reads
    await tick(2000)
    expect(reads).toBe(acceptedReads)
    state = { ...state, test_state: "failed" }
    await click()
    expect(container.textContent).toContain("could not be verified")
    expect(container.textContent).toContain("Last verified")
    state = idle
    await click()
    expect(container.textContent).not.toContain("Last verified")
    state = { ...idle, test_state: "queued" }
    await click()
    act(() => root.unmount())
    const unmountedReads = reads
    await tick(2000)
    expect(reads).toBe(unmountedReads)
  })

  it("recovers from GET failure and reports mutation failure", async () => {
    getFailure = true
    await render()
    expect(container.querySelector("[role='alert']")).not.toBeNull()
    getFailure = false
    await click()
    expect(button().disabled).toBe(false)
    postFailure = true
    await click()
    expect(container.querySelector("[role='alert']")?.textContent).toContain("Three test emails")
  })
})
