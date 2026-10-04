/* @vitest-environment happy-dom */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, createElement } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { IntegrationsSection } from "./settings"
import { api, type IntegrationToken, type IssuedIntegrationToken } from "@/lib/api"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const kuma: IntegrationToken = {
  id: "token-kuma",
  name: "Uptime Kuma",
  scope: "status:read",
  created_at: "2026-10-01T09:00:00Z",
  last_used_at: null,
  revoked_at: null,
}
const homepage: IntegrationToken = { ...kuma, id: "token-homepage", name: "Homepage" }
const issued: IssuedIntegrationToken = {
  ...kuma,
  id: "token-agent",
  name: "Claude Code",
  token: "cgs_synthetic-token-shown-once",
}

let container: HTMLDivElement
let root: Root | null = null
let clipboard: PropertyDescriptor | undefined
let address: string

function page() {
  return window as typeof window & { happyDOM: { setURL: (url: string) => void } }
}

beforeEach(() => {
  container = document.createElement("div")
  document.body.append(container)
  clipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard")
  address = window.location.href
  vi.spyOn(api, "integrationTokens").mockResolvedValue([kuma, homepage])
  vi.spyOn(api, "issueIntegrationToken").mockResolvedValue(issued)
  vi.spyOn(api, "revokeIntegrationToken").mockResolvedValue(undefined)
})

afterEach(() => {
  if (root) {
    act(() => root?.unmount())
    root = null
  }
  container.remove()
  if (clipboard) Object.defineProperty(navigator, "clipboard", clipboard)
  else Reflect.deleteProperty(navigator, "clipboard")
  page().happyDOM.setURL(address)
  vi.restoreAllMocks()
})

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
}

async function renderSection() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  root = createRoot(container)
  act(() => {
    root?.render(createElement(QueryClientProvider, { client: queryClient }, createElement(IntegrationsSection)))
  })
  await settle()
}

function click(element: Element) {
  act(() => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
  })
}

function button(label: string, scope: ParentNode = container): HTMLButtonElement {
  const found = Array.from(scope.querySelectorAll("button")).find((item) => item.textContent?.trim() === label)
  if (!found) throw new Error(`No button labelled ${label}`)
  return found
}

function rowOf(name: string): HTMLElement {
  const heading = Array.from(container.querySelectorAll(".settings-list h3")).find((item) => item.textContent === name)
  if (!heading) throw new Error(`No token named ${name}`)
  return heading.closest(".setting-row") as HTMLElement
}

async function issueToken(name: string) {
  const input = container.querySelector("#integration-name") as HTMLInputElement
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, name)
    input.dispatchEvent(new Event("input", { bubbles: true }))
  })
  const form = input.closest("form") as HTMLFormElement
  act(() => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }))
  })
  await settle()
}

describe("IntegrationsSection", () => {
  it("shows an issued token once and not again after leaving Settings", async () => {
    await renderSection()

    await issueToken("Claude Code")

    expect(api.issueIntegrationToken).toHaveBeenCalledWith("Claude Code")
    expect(container.textContent).toContain("Copy the token for Claude Code now")
    expect(container.querySelector(".token-reveal code")?.textContent).toBe(issued.token)
    expect((container.querySelector("#integration-name") as HTMLInputElement).value).toBe("")

    act(() => root?.unmount())
    root = null
    await renderSection()
    expect(container.textContent).not.toContain(issued.token)
  })

  it("asks to copy the token by hand when the clipboard is unavailable", async () => {
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true })
    await renderSection()
    await issueToken("Claude Code")

    click(button("Copy token"))
    await settle()

    expect(container.textContent).toContain("Select the token and copy it.")
    expect(container.querySelector(".token-reveal code")?.textContent).toBe(issued.token)
  })

  it("says the token was copied, then offers to copy it again", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true })
    await renderSection()
    await issueToken("Claude Code")
    vi.useFakeTimers({ shouldAdvanceTime: true })

    try {
      click(button("Copy token"))
      await settle()
      expect(writeText).toHaveBeenCalledWith(issued.token)
      expect(button("Copied")).toBeTruthy()

      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000)
      })
      expect(button("Copy token")).toBeTruthy()
    } finally {
      vi.useRealTimers()
    }
  })

  it("confirms a revoke and returns focus to that token's Revoke button on cancel", async () => {
    await renderSection()
    const revoke = button("Revoke", rowOf("Homepage"))

    click(revoke)
    const confirmation = container.querySelector("#revoke-token-homepage") as HTMLElement
    expect(confirmation).not.toBeNull()
    expect(confirmation.textContent).toContain("Revoke Homepage?")
    expect(revoke.getAttribute("aria-expanded")).toBe("true")

    click(button("Keep token", confirmation))

    expect(container.querySelector("#revoke-token-homepage")).toBeNull()
    expect(document.activeElement).toBe(revoke)
    expect(api.revokeIntegrationToken).not.toHaveBeenCalled()
  })

  it("warns before issuing a token over plain HTTP", async () => {
    page().happyDOM.setURL("http://calendar-ghost.lan:8000/settings")
    await renderSection()
    expect(container.textContent).toContain("This page uses plain HTTP")

    act(() => root?.unmount())
    root = null
    page().happyDOM.setURL("https://calendar-ghost.example.test/settings")
    await renderSection()
    expect(container.textContent).not.toContain("This page uses plain HTTP")
  })
})
