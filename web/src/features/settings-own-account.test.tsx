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

const administrator: SignedInUser = { ...user, role: "installation_administrator" }

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
    "GET /api/v1/account/deletion": jsonResponse({ needs_another_administrator: false, last_user: false }),
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
let openPeople: ReturnType<typeof vi.fn<() => void>>

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

async function renderSection(
  i18n: I18n,
  {
    sendsEmail = true,
    answers = {},
    signedIn = user,
    cached = {},
  }: {
    sendsEmail?: boolean
    answers?: Record<string, Response>
    signedIn?: SignedInUser
    /** Answers already in the cache, by query key, as another tab left them. */
    cached?: Record<string, unknown>
  } = {},
) {
  serve(answers)
  openPeople = vi.fn<() => void>()
  root = createRoot(container)
  // As fresh as the app keeps answers, so a test can tell a cached answer from a new one.
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } })
  for (const [key, data] of Object.entries(cached)) queryClient.setQueryData([key], data)
  act(() => {
    root?.render(
      <StaticI18nProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <OwnAccountSection user={signedIn} sendsEmail={sendsEmail} onOpenPeople={openPeople} />
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

function deletion(answer: { needs_another_administrator?: boolean; last_user?: boolean }): Response {
  return jsonResponse({ needs_another_administrator: false, last_user: false, ...answer })
}

function deletionItem(): HTMLElement {
  const heading = [...container.querySelectorAll("h3")].find((item) => item.textContent === "Delete your account")
  if (!heading) throw new Error("No deletion item")
  return heading.closest<HTMLElement>(".setting-item")!
}

function incidentEmails(): HTMLElement {
  const heading = [...container.querySelectorAll("h3")].find((item) => item.textContent === "Incident emails")
  if (!heading) throw new Error("No incident emails item")
  return heading.closest<HTMLElement>(".setting-item")!
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

  it("has no untranslated text for the last person here, or an administrator who cannot leave yet", async () => {
    await renderSection(pseudoI18n(), { answers: { "GET /api/v1/account/deletion": deletion({ last_user: true }) } })
    await click(container.querySelector<HTMLButtonElement>("#own-delete-toggle")!)
    expect(untranslatedText(container, [user.email!])).toEqual([])
    act(() => root?.unmount())
    root = null
    await renderSection(pseudoI18n(), {
      signedIn: administrator,
      answers: { "GET /api/v1/account/deletion": deletion({ needs_another_administrator: true }) },
    })
    expect(untranslatedText(container, [user.email!])).toEqual([])
  })

  it("has no untranslated text where the installation sends no email", async () => {
    await renderSection(pseudoI18n(), { sendsEmail: false })
    expect(untranslatedText(container, [user.email!])).toEqual([])
    act(() => root?.unmount())
    root = null
    await renderSection(pseudoI18n(), { sendsEmail: false, signedIn: administrator })
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

  it("tells a User their administrator can set up incident emails where the installation sends none", async () => {
    await renderSection(testI18n(), { sendsEmail: false })
    expect(container.querySelector("#own-incident-emails")).toBeNull()
    expect(incidentEmails().textContent).toContain(
      "Your administrator can set up email for this Calendar Ghost. Until then, incidents appear in Activity.",
    )
    expect(incidentEmails().querySelector("a")).toBeNull()
  })

  it("tells an administrator how to set up incident emails where the installation sends none", async () => {
    await renderSection(testI18n(), { sendsEmail: false, signedIn: administrator })
    expect(container.querySelector("#own-incident-emails")).toBeNull()
    expect(incidentEmails().textContent).toContain(
      "To send incident emails, add SMTP settings to .env and restart Calendar Ghost. Until then, incidents appear in Activity.",
    )
    const help = incidentEmails().querySelector("a")
    expect(help?.textContent).toBe("How to set up email (opens in a new tab)")
    expect(help?.getAttribute("href")).toBe(
      "https://calendarghost.com/docs/troubleshooting#incident-emails-are-unavailable-or-never-arrive",
    )
    expect(help?.getAttribute("target")).toBe("_blank")
    expect(help?.getAttribute("rel")).toBe("noreferrer")
  })

  it("asks the only administrator to make someone else an administrator before deleting their account", async () => {
    await renderSection(testI18n(), {
      signedIn: administrator,
      answers: { "GET /api/v1/account/deletion": deletion({ needs_another_administrator: true }) },
    })
    expect(container.querySelector("#own-delete-toggle")).toBeNull()
    const item = deletionItem()
    expect(item.querySelector("h3")?.textContent).toBe("Delete your account")
    expect(item.textContent).toContain(
      "Someone else must be an administrator before you can delete your account. Make another person an administrator on the People page, then come back.",
    )
    const link = item.querySelector<HTMLAnchorElement>("a")!
    expect(link.textContent).toBe("Open People")
    expect(link.getAttribute("href")).toBe("/people")
    const plain = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 })
    act(() => {
      link.dispatchEvent(plain)
    })
    expect(plain.defaultPrevented).toBe(true)
    expect(openPeople).toHaveBeenCalledOnce()
  })

  it("asks again whether the account can be deleted each time it is shown", async () => {
    // Making someone else an administrator on the People page, then coming back, offers deletion.
    await renderSection(testI18n(), {
      signedIn: administrator,
      cached: { "account-deletion": { needs_another_administrator: true, last_user: false } },
    })
    expect(container.querySelector("#own-delete-toggle")).not.toBeNull()
  })

  it("tells the last person here that Calendar Ghost returns to setup", async () => {
    await renderSection(testI18n(), { answers: { "GET /api/v1/account/deletion": deletion({ last_user: true }) } })
    await click(button("Delete your account"))
    expect(container.querySelector("#own-delete-confirmation p")?.textContent).toBe(
      "You are the last person here. This deletes your sign-in, rules, Google connections, tokens, and Activity, and Calendar Ghost returns to setup, where the next person to open it creates the administrator. Choose below what happens to the events your rules wrote. Your own events and your Google accounts stay as they are. Backups taken before now keep your records until they rotate out. This cannot be undone.",
    )
  })

  it("deletes your own account, keeping the events your rules wrote when you choose, then signs you out", async () => {
    await renderSection(testI18n())
    queryClient.setQueryData(["rules"], [{ id: "rule-private" }])
    expect(deletionItem().querySelector("p")?.textContent).toBe(
      "Deletes your sign-in, rules, and Google connections. You choose whether the events your rules wrote go too. Your Google accounts and your own events stay.",
    )
    await click(button("Delete your account"))
    const confirmation = container.querySelector<HTMLElement>("#own-delete-confirmation")!
    expect(confirmation.querySelector("p")?.textContent).toBe(
      "This deletes your sign-in, rules, Google connections, tokens, and Activity, and signs you out. Choose below what happens to the events your rules wrote. Your own events and your Google accounts stay as they are. Backups taken before now keep your records until they rotate out. This cannot be undone.",
    )
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

describe("Cancelling a form", () => {
  it("forgets what was typed and the error shown, so the form opens fresh", async () => {
    const refused = jsonResponse({ detail: "wrong", code: "incorrect_password", params: {} }, 403)
    await renderSection(testI18n(), { answers: { "PUT /api/v1/account/email": refused } })
    await click(container.querySelector<HTMLButtonElement>("#own-email-toggle")!)
    type(field("own-email"), "robin@home.example.test")
    type(field("own-email-password"), "not the password")
    await submit(container.querySelector<HTMLFormElement>("form")!)
    expect(container.querySelector("[role='alert']")).not.toBeNull()

    await click(button("Cancel"))
    await click(container.querySelector<HTMLButtonElement>("#own-email-toggle")!)

    expect(field("own-email").value).toBe("")
    expect(field("own-email-password").value).toBe("")
    expect(container.querySelector("[role='alert']")).toBeNull()
  })

  it("does the same for the password form", async () => {
    await renderSection(testI18n())
    await click(container.querySelector<HTMLButtonElement>("#own-password-toggle")!)
    type(field("own-current-password"), "old password")

    await click(button("Cancel"))
    await click(container.querySelector<HTMLButtonElement>("#own-password-toggle")!)

    expect(field("own-current-password").value).toBe("")
  })
})
