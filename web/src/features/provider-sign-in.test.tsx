/* @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, type ReactNode } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ThemeProvider } from "@/components/theme-provider"
import { StaticI18nProvider } from "@/i18n/provider"
import { testI18n } from "@/i18n/testing"
import { ProviderSignInOptions } from "./provider-sign-in-options"
import { ProviderLinkPage } from "./provider-link-page"
import { SignInMethods } from "./settings-sign-in-methods"
import { SignInProvidersSection } from "./settings-sign-in-providers"
import { AuthScreen } from "./auth-screen"
import { EmailChangeSignIn } from "./email-change-sign-in"
import { PasswordResetPage } from "./password-reset-page"
import { InvitationPage } from "./invitation-page"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let container: HTMLDivElement
let root: Root
let client: QueryClient
let routes: Record<string, unknown>
let calls: { path: string; method: string; body: unknown }[]
const response = (data: unknown, status = 200) => ({ ok: status < 400, status, json: () => Promise.resolve(data) }) as Response
beforeEach(() => {
  window.history.replaceState(null, "", "/")
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  routes = {
    "GET /api/v1/sign-in/providers": { providers: ["google", "microsoft"], capabilities: { google: { can_verify_email: true }, microsoft: { can_verify_email: false } } },
    "GET /api/v1/sign-in/pending": { password_required: true },
    "GET /api/v1/account/sign-in-methods": { has_password: false, identities: [{ id: "identity-google", provider: "google" }] },
    "GET /api/v1/settings/sign-in-providers": ["google", "microsoft"].map(provider => ({ provider, enabled: false, available: true, reason: null, callback_uri: `https://configured.example.test/api/v1/sign-in/${provider}/callback` })),
  }
  client.setQueryData(["session"], { authenticated: true, user: { id: "robin", role: "installation_administrator" } })
  calls = []
  vi.stubGlobal("fetch", vi.fn((path: string, init?: RequestInit) => {
    const method = init?.method ?? "GET"
    calls.push({ path, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
    const answer = routes[`${method} ${path}`] ?? {}
    return Promise.resolve(answer instanceof Response ? answer : response(answer))
  }))
})
afterEach(() => { act(() => root.unmount()); client.clear(); container.remove(); vi.restoreAllMocks() })
async function settle() { for (let i = 0; i < 5; i++) await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) }) }
async function render(node: ReactNode) {
  act(() => root.render(<StaticI18nProvider i18n={testI18n()}><ThemeProvider><QueryClientProvider client={client}>{node}</QueryClientProvider></ThemeProvider></StaticI18nProvider>))
  await settle()
}
function button(text: string) { const found = [...container.querySelectorAll("button")].find(item => item.textContent.trim() === text); expect(found, text).toBeDefined(); return found! }
async function click(element: HTMLElement) { act(() => element.click()); await settle() }
function type(input: HTMLInputElement, value: string) { act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })) }) }
async function submit() { act(() => { container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })) }); await settle() }

describe("Provider sign-in", () => {
  it("shows enabled providers with local identity marks and the separate calendar step", async () => {
    await render(<ProviderSignInOptions />)
    expect(button("Sign in with Google")).toBeDefined()
    expect(button("Sign in with Microsoft")).toBeDefined()
    expect(container.textContent).toContain("Connections")
    for (const img of container.querySelectorAll("img")) expect(img.getAttribute("src")).not.toMatch(/^https?:/)
  })
  it("keeps zero-provider layout empty", async () => {
    routes["GET /api/v1/sign-in/providers"] = { providers: [] }
    await render(<ProviderSignInOptions />)
    expect(container.textContent).toBe("")
  })
  it("never offers provider sign-in during setup", async () => {
    await render(<AuthScreen mode="setup" />)
    expect(calls.some(call => call.path.includes("sign-in/providers"))).toBe(false)
  })
  it("keeps an Invitation provider path when ordinary password acceptance is unavailable", async () => {
    window.history.replaceState(null, "", "/invitation#synthetic-invitation")
    routes["POST /api/v1/invitations/check"] = { usable: false, acceptance: "direct" }
    await render(<InvitationPage onSignedIn={vi.fn()} />)
    const start = button("Sign in with Google")
    expect(start.getAttribute("aria-disabled")).toBe("true")
    expect(start.dataset.state).toBe("unavailable")
    await click(start)
    expect(calls.some(call => call.path.endsWith("/google/start"))).toBe(false)
    type(container.querySelector<HTMLInputElement>("input[type=email]")!, "Robin@example.test")
    expect(start.dataset.state).toBe("ready")
    await click(start)
    expect(calls.find(call => call.path === "/api/v1/sign-in/google/start")?.body).toEqual({ invitation_token: "synthetic-invitation", email: "Robin@example.test" })
  })
  it("offers generic password linking and verified registration without exposing claims", async () => {
    await render(<ProviderLinkPage />)
    expect(container.querySelector('input[type="email"]')).not.toBeNull()
    expect(container.querySelector('a[href="/sign-up"]')).not.toBeNull()
    expect(container.textContent).toContain("Your account")
  })
  it("sets a first password without asking for an existing one", async () => {
    await render(<SignInMethods userId="robin" onDone={vi.fn()} />)
    await click(button("Set password"))
    expect(container.querySelector("#own-current-password")).toBeNull()
    const fields = container.querySelectorAll<HTMLInputElement>('input[type="password"]')
    type(fields[0]!, "synthetic-new-password")
    type(fields[1]!, "synthetic-new-password")
    await submit()
    expect(calls.find(call => call.method === "POST" && call.path === "/api/v1/account/password")?.body).toEqual({ password: "synthetic-new-password" })
    expect(JSON.stringify(client.getMutationCache().getAll().map(m => m.state))).not.toContain("synthetic-new-password")
  })
  it("explains why a last enabled method cannot be removed", async () => {
    await render(<SignInMethods userId="robin" onDone={vi.fn()} />)
    expect(container.textContent).toContain("Set a password")
    expect(button("Remove Google").getAttribute("aria-disabled")).toBe("true")
  })
  it("starts with both administrator switches off and names callback setup", async () => {
    await render(<SignInProvidersSection />)
    const switches = container.querySelectorAll('[role="switch"]')
    expect(switches).toHaveLength(2)
    for (const toggle of switches) expect(toggle.getAttribute("aria-checked")).toBe("false")
    expect(container.textContent).toContain("/api/v1/sign-in/google/callback")
    expect(container.textContent).toContain("/api/v1/sign-in/microsoft/callback")
  })
})

describe("Provider recovery and ownership", () => {
  it("offers only the providers currently enabled", async () => {
    routes["GET /api/v1/sign-in/providers"] = { providers: ["microsoft", "unknown"] }
    await render(<ProviderSignInOptions />)
    expect(container.textContent).not.toContain("Sign in with Google")
    expect(button("Sign in with Microsoft")).toBeDefined()
  })
  it("shows a generic callback failure without reflecting query text", async () => {
    window.history.replaceState(null, "", "/sign-in?provider_result=unavailable&error=private-provider-error")
    await render(<AuthScreen mode="login" />)
    expect(container.textContent).toContain("Provider sign-in could not finish")
    expect(container.textContent).not.toContain("private-provider-error")
  })
  it("refuses stale pending links with a clear way to start again", async () => {
    routes["GET /api/v1/sign-in/pending"] = { password_required: false }
    await render(<ProviderLinkPage />)
    expect(container.querySelector("form")).toBeNull()
    expect(container.textContent).toContain("no longer available")
    expect(container.querySelector('a[href="/sign-in"]')).not.toBeNull()
  })
  it("returns focus and clears passwords after a generic link refusal", async () => {
    routes["POST /api/v1/sign-in/confirm"] = new Response(JSON.stringify({ code: "provider_sign_in_refused" }), { status: 401 })
    await render(<ProviderLinkPage />)
    type(container.querySelector<HTMLInputElement>('#provider-link-email')!, "robin@example.test")
    type(container.querySelector<HTMLInputElement>('#provider-link-password')!, "synthetic-password")
    await submit()
    expect(document.activeElement?.id).toBe("provider-link-email")
    expect(container.querySelector<HTMLInputElement>('#provider-link-password')!.value).toBe("")
    expect(JSON.stringify(client.getMutationCache().getAll().map(m => m.state))).not.toContain("synthetic-password")
  })
  it("keeps pending buttons focusable and starts only once", async () => {
    let finish: (response: Response) => void = () => undefined
    const original = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation((input, init) => (input as string).endsWith("/google/start") ? new Promise(resolve => { finish = resolve }) : original(input, init))
    await render(<ProviderSignInOptions />)
    const google = button("Sign in with Google")
    google.focus()
    await click(google)
    await click(google)
    expect(google.disabled).toBe(false)
    expect(google.getAttribute("aria-busy")).toBe("true")
    expect(document.activeElement).toBe(google)
    act(() => finish(response({}, 503)))
    await settle()
    expect(container.textContent).toContain("Provider sign-in could not finish")
  })
  it("does not redirect a late authorization response after the User switches", async () => {
    let finish: (response: Response) => void = () => undefined
    const original = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation((input, init) => (input as string).endsWith("/google/start") ? new Promise(resolve => { finish = resolve }) : original(input, init))
    const redirect = vi.spyOn(window.location, "assign").mockImplementation(() => undefined)
    const store = vi.spyOn(Storage.prototype, "setItem")
    await render(<ProviderSignInOptions />)
    await click(button("Sign in with Google"))
    act(() => { client.setQueryData(["session"], { user: { id: "ash" } }) })
    act(() => finish(response({ authorization_url: "https://provider.example.test/?state=synthetic-private-proof" })))
    await settle()
    expect(redirect).not.toHaveBeenCalled()
    expect(store.mock.calls.some(call => call.some(value => value.includes("synthetic-private-proof")))).toBe(false)
    expect(JSON.stringify(client.getMutationCache().getAll().map(m => m.state))).not.toContain("synthetic-private-proof")
    expect(JSON.stringify(client.getQueryCache().getAll().map(q => q.state.data))).not.toContain("synthetic-private-proof")
  })
  it("requires the existing password when replacing one and restores focus on cancel", async () => {
    routes["GET /api/v1/account/sign-in-methods"] = { has_password: true, identities: [] }
    await render(<SignInMethods userId="robin" onDone={vi.fn()} />)
    await click(button("Change password"))
    expect(document.activeElement?.id).toBe("own-current-password")
    const fields = container.querySelectorAll<HTMLInputElement>('input[type="password"]')
    type(fields[1]!, "synthetic-new-password")
    type(fields[2]!, "synthetic-new-password")
    await submit()
    expect(calls.some(call => call.method === "PUT")).toBe(false)
    await click(button("Cancel"))
    expect(document.activeElement).toBe(button("Change password"))
  })
  it("retains a linked method after the server refuses its removal", async () => {
    routes["GET /api/v1/account/sign-in-methods"] = { has_password: true, identities: [{ id: "identity-google", provider: "google" }] }
    routes["DELETE /api/v1/account/sign-in-methods/identity-google"] = new Response(JSON.stringify({ code: "last_sign_in_method" }), { status: 409 })
    await render(<SignInMethods userId="robin" onDone={vi.fn()} />)
    await click(button("Remove Google"))
    expect(button("Remove Google")).toBeDefined()
    expect(container.querySelector('[role="alert"]')).not.toBeNull()
  })
  it("explains disabled-provider recovery while preserving the binding", async () => {
    routes["GET /api/v1/sign-in/providers"] = { providers: [] }
    await render(<SignInMethods userId="robin" onDone={vi.fn()} />)
    expect(container.textContent).toContain("Linked, but sign-in is currently unavailable")
    expect(container.textContent).toContain("Password Reset Link")
    expect(button("Remove Google").getAttribute("aria-disabled")).toBe("true")
  })
  it("rolls a refused administrator toggle back and keeps keyboard focus", async () => {
    routes["PUT /api/v1/settings/sign-in-providers/google"] = new Response(JSON.stringify({ code: "last_sign_in_method" }), { status: 409 })
    await render(<SignInProvidersSection />)
    const toggle = container.querySelector<HTMLButtonElement>('[role="switch"]')!
    toggle.focus()
    await click(toggle)
    expect(toggle.getAttribute("aria-checked")).toBe("false")
    expect(document.activeElement).toBe(toggle)
    expect(container.textContent).toContain("Password Reset Link from People")
    expect(container.textContent).toContain("https://configured.example.test/api/v1/sign-in/google/callback")
  })
  it.each(["direct", "verified"])("binds the typed Invitation address with %s password acceptance", async acceptance => {
    window.history.replaceState(null, "", "/invitation#synthetic-invitation")
    routes["POST /api/v1/invitations/check"] = { usable: true, acceptance }
    await render(<InvitationPage onSignedIn={vi.fn()} />)
    expect(container.querySelectorAll('input[type="email"]')).toHaveLength(1)
    type(container.querySelector<HTMLInputElement>('input[type="email"]')!, "robin@example.test")
    expect(container.textContent).not.toContain("Sign in with Microsoft")
    await click(button("Sign in with Google"))
    expect(calls.find(call => call.path === "/api/v1/sign-in/google/start")?.body).toEqual({ invitation_token: "synthetic-invitation", email: "robin@example.test" })
  })
})


describe("Provider review regressions", () => {
  it.each([false, true])("keeps email-change provider guidance conditional: %s", async enabled => {
    routes["GET /api/v1/sign-in/providers"] = { providers: enabled ? ["google"] : [] }
    await render(<EmailChangeSignIn isCurrent={() => true} />)
    expect(container.textContent.includes("Signing in with a provider opens your account")).toBe(enabled)
  })
  it.each([false, true])("describes the sign-in methods actually offered: %s", async enabled => {
    routes["GET /api/v1/sign-in/providers"] = { providers: enabled ? ["google"] : [] }
    await render(<AuthScreen mode="login" />)
    expect(container.textContent.includes("Choose how to sign in.")).toBe(enabled)
    expect(container.textContent.includes("Or use your email and password")).toBe(enabled)
    expect(container.textContent.includes("Use the email and password you sign in with.")).toBe(!enabled)
  })
  it.each([false, true])("restores removal focus and announces completion with remaining same-provider binding: %s", async another => {
    routes["GET /api/v1/account/sign-in-methods"] = { has_password: true, identities: [{ id: "identity-google", provider: "google" }, ...(another ? [{ id: "other-google", provider: "google" }] : [])] }
    const done = vi.fn()
    await render(<SignInMethods userId="robin" onDone={done} />)
    const remove = button("Remove Google")
    remove.focus()
    routes["GET /api/v1/account/sign-in-methods"] = { has_password: true, identities: another ? [{ id: "other-google", provider: "google" }] : [] }
    await click(remove)
    expect(document.activeElement).toBe(button(another ? "Remove Google" : "Link Google"))
    expect(done).toHaveBeenNthCalledWith(1, "")
    expect(done).toHaveBeenLastCalledWith("Google removed from sign-in.")
  })
  it.each([false, true])("respects focus moved during removal and an actor switch: %s", async switched => {
    routes["GET /api/v1/account/sign-in-methods"] = { has_password: true, identities: [{ id: "identity-google", provider: "google" }] }
    let finish: (response: Response) => void = () => undefined
    const original = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation((input, init) => init?.method === "DELETE" ? new Promise(resolve => { finish = resolve }) : original(input, init))
    const done = vi.fn()
    await render(<SignInMethods userId="robin" onDone={done} />)
    await click(button("Remove Google"))
    done.mockClear()
    if (switched) act(() => { client.setQueryData(["session"], { user: { id: "ash" } }) })
    button("Change password").focus()
    act(() => finish(response({})))
    await settle()
    expect(done).toHaveBeenCalledTimes(switched ? 0 : 1)
    expect(document.activeElement).toBe(button("Change password"))
  })
  it("marks pending provider buttons while preserving focus and guarding repeat activation", async () => {
    const original = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation((input, init) => (input as string).endsWith("/google/start") ? new Promise(() => undefined) : original(input, init))
    await render(<ProviderSignInOptions />)
    const google = button("Sign in with Google")
    google.focus()
    await click(google)
    expect(google.dataset.state).toBe("pending")
    expect(container.querySelector('[role="status"]')?.textContent).toContain("Please wait")
    expect(document.activeElement).toBe(google)
    await click(google)
    expect(vi.mocked(fetch).mock.calls.filter(([path]) => (path as string).endsWith("/google/start"))).toHaveLength(1)
    expect(google.getAttribute("aria-disabled")).toBe("true")
  })
})


describe("Final provider review", () => {
  it("keeps refused Invitation recovery and eligible provider admission available together", async () => {
    window.history.replaceState(null, "", "/invitation#synthetic-invitation")
    routes["POST /api/v1/invitations/check"] = { usable: false, acceptance: null }
    await render(<InvitationPage onSignedIn={vi.fn()} />)
    expect(container.querySelector('a[href="/"]')).not.toBeNull()
    expect(container.textContent).toContain("Ask the person who invited you")
    expect(container.textContent).toContain("If this Invitation is still valid")
    expect(container.textContent).not.toContain("Sign in with Microsoft")
    expect(button("Sign in with Google")).toBeDefined()
    expect(container.querySelector(".invitation-provider-fallback")).not.toBeNull()
  })
  it("shows owned callback failure in Your account", async () => {
    window.history.replaceState(null, "", "/settings/account?provider_result=unavailable&error=private-error")
    await render(<SignInMethods userId="robin" onDone={vi.fn()} />)
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Provider sign-in could not finish")
    expect(container.textContent).not.toContain("private-error")
  })
  it.each([false, true])("redirects only a current Invitation and retains no authorization URL, replaced: %s", async replaced => {
    window.history.replaceState(null, "", "/invitation#synthetic-invitation")
    routes["POST /api/v1/invitations/check"] = { usable: false, acceptance: null }
    let finish: (response: Response) => void = () => undefined
    const original = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation((input, init) => (input as string).endsWith("/google/start") ? new Promise(resolve => { finish = resolve }) : original(input, init))
    const redirect = vi.spyOn(window.location, "assign").mockImplementation(() => undefined)
    const store = vi.spyOn(Storage.prototype, "setItem")
    await render(<InvitationPage onSignedIn={vi.fn()} />)
    type(container.querySelector<HTMLInputElement>('input[type="email"]')!, "robin@example.test")
    await click(button("Sign in with Google"))
    if (replaced) window.history.replaceState(null, "", "/invitation#replacement-invitation")
    const authorization = "https://provider.example.test/?state=synthetic-private-proof"
    act(() => finish(response({ authorization_url: authorization })))
    await settle()
    expect(redirect).toHaveBeenCalledTimes(replaced ? 0 : 1)
    if (!replaced) expect(redirect).toHaveBeenCalledWith(authorization)
    expect(store.mock.calls.some(call => call.some(value => value.includes("synthetic-private-proof")))).toBe(false)
    expect(JSON.stringify(client.getMutationCache().getAll().map(m => m.state))).not.toContain("synthetic-private-proof")
    expect(JSON.stringify(client.getQueryCache().getAll().map(q => q.state.data))).not.toContain("synthetic-private-proof")
  })
})


it("explains password recovery removes sign-in providers while preserving calendars", async () => {
  window.history.replaceState(null, "", "/reset-password#synthetic-reset")
  routes["POST /api/v1/password-resets/check"] = { usable: true }
  await render(<PasswordResetPage />)
  expect(container.textContent).toContain("removes all provider sign-in methods")
  expect(container.textContent).toContain("Your calendar connections stay")
})
