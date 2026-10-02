/* @vitest-environment happy-dom */

import { act, createElement } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { renderToStaticMarkup } from "react-dom/server"

import { AccountSelect } from "../components/account-select"
import accountSelectSource from "../components/account-select.tsx?raw"
import rulesSource from "../features/rules.tsx?raw"
import type { ConnectedAccount } from "./api"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const accounts: ConnectedAccount[] = [
  {
    id: "personal",
    display_name: "Daniel Calatayud",
    email: "daniel@example.com",
    avatar_url: null,
    state: "connected",
    rule_count: 0,
    authorized_at: "2026-10-02T00:00:00Z",
  },
  {
    id: "work",
    display_name: "Work Calendar",
    email: "work@example.com",
    avatar_url: "https://images.example.invalid/work.png",
    state: "connected",
    rule_count: 0,
    authorized_at: "2026-10-02T00:00:00Z",
  },
]

const typeaheadAccounts: ConnectedAccount[] = [
  {
    id: "personal",
    display_name: "Personal Calendar",
    email: "personal@example.com",
    avatar_url: null,
    state: "connected",
    rule_count: 0,
    authorized_at: "2026-10-02T00:00:00Z",
  },
  {
    id: "project",
    display_name: "Project Calendar",
    email: "project@example.com",
    avatar_url: null,
    state: "connected",
    rule_count: 0,
    authorized_at: "2026-10-02T00:00:00Z",
  },
  {
    id: "work",
    display_name: "Work Calendar",
    email: "work@example.com",
    avatar_url: null,
    state: "connected",
    rule_count: 0,
    authorized_at: "2026-10-02T00:00:00Z",
  },
]

function renderAccountSelect(value: string, accountList = accounts) {
  return renderToStaticMarkup(
    createElement(AccountSelect, {
      id: "account",
      labelId: "account-label",
      value,
      accounts: accountList,
      onChange: () => undefined,
    }),
  )
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
  vi.useRealTimers()
})

function mountInteractive(
  value: string,
  accountList = accounts,
  onChange = vi.fn<(value: string) => void>(),
) {
  root = createRoot(container)
  act(() => {
    root?.render(
      createElement(AccountSelect, {
        id: "account",
        labelId: "account-label",
        value,
        accounts: accountList,
        onChange,
      }),
    )
  })
  return {
    trigger: container.querySelector('[role="combobox"]') as HTMLButtonElement,
    onChange,
  }
}

function press(
  trigger: HTMLButtonElement,
  key: string,
  options: KeyboardEventInit = {},
) {
  const event = new KeyboardEvent("keydown", {
    key,
    bubbles: true,
    cancelable: true,
    ...options,
  })
  act(() => trigger.dispatchEvent(event))
  return event
}

function click(element: Element) {
  act(() => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
  })
}

function mouseDown(element: Element) {
  const event = new MouseEvent("mousedown", { bubbles: true, cancelable: true })
  act(() => element.dispatchEvent(event))
  return event
}

function mouseMove(element: Element) {
  act(() => element.dispatchEvent(new MouseEvent("mousemove", { bubbles: true })))
}

function listbox() {
  return container.querySelector('[role="listbox"]') as HTMLDivElement
}

function options() {
  return Array.from(container.querySelectorAll('[role="option"]')) as HTMLDivElement[]
}

describe("account select", () => {
  it("renders the selected account and every avatar-enabled option", () => {
    const markup = renderAccountSelect("work")

    expect(markup).toContain('src="https://images.example.invalid/work.png"')
    expect(markup).toContain("Work Calendar")
    expect(markup).toContain("work@example.com")
    expect(markup.match(/role="option"/g)).toHaveLength(2)
    expect(markup).toContain('aria-selected="true"')
  })

  it("falls back to the first account or an empty-state label", () => {
    const fallbackMarkup = renderAccountSelect("unknown")
    expect(fallbackMarkup).toContain("Daniel Calatayud")
    expect(fallbackMarkup).toContain(">DC</span>")
    expect(renderAccountSelect("", [])).toContain("No Google accounts")
  })

  it("keeps the account avatar and combobox structure in the component", () => {
    expect(accountSelectSource.match(/<AccountOptionContent/g)).toHaveLength(2)
    expect(accountSelectSource.match(/<AccountAvatar/g)).toHaveLength(1)
    expect(accountSelectSource).toContain('role="combobox"')
    expect(accountSelectSource).toContain('role="listbox"')
    expect(accountSelectSource).toContain("avatarUrl={account.avatar_url}")
  })

  it("uses the avatar-enabled control for both new-rule endpoints", () => {
    expect(rulesSource.match(/<AccountSelect/g)).toHaveLength(2)
    expect(rulesSource).toContain('labelId="source-account-label"')
    expect(rulesSource).toContain('labelId="destination-account-label"')
    expect(rulesSource).toContain('setSourceCalendar("")')
    expect(rulesSource).toContain('setDestinationCalendar("")')
    expect(rulesSource).toContain('const resolvedSourceAccount = sourceAccount || accounts[0]?.id || ""')
    expect(rulesSource).toContain('const resolvedDestinationAccount = destinationAccount || accounts[1]?.id || accounts[0]?.id || ""')
    expect(rulesSource).toContain('queryKey: ["calendars", resolvedSourceAccount]')
    expect(rulesSource).toContain('queryKey: ["calendars", resolvedDestinationAccount]')
    expect(rulesSource).toContain('enabled: Boolean(resolvedSourceAccount)')
    expect(rulesSource).toContain('enabled: Boolean(resolvedDestinationAccount)')
    expect(rulesSource).not.toContain('<NativeSelect id="source-account"')
    expect(rulesSource).not.toContain('<NativeSelect id="destination-account"')
  })

  it("opens and closes from pointer input, selects a hovered option, and ignores the current value", () => {
    const first = mountInteractive("personal")

    click(first.trigger)
    expect(first.trigger.getAttribute("aria-expanded")).toBe("true")
    expect(listbox().hidden).toBe(false)
    click(first.trigger)
    expect(first.trigger.getAttribute("aria-expanded")).toBe("false")
    expect(listbox().hidden).toBe(true)

    click(first.trigger)
    const accountOptions = options()
    mouseMove(accountOptions[1])
    expect(first.trigger.getAttribute("aria-activedescendant")).toContain("option-1")
    click(accountOptions[1])
    expect(first.onChange).toHaveBeenCalledWith("work")
    expect(first.trigger.getAttribute("aria-expanded")).toBe("false")

    click(first.trigger)
    click(options()[0])
    expect(first.onChange).toHaveBeenCalledTimes(1)
  })

  it.each([
    ["ArrowDown", false, 1],
    ["ArrowUp", false, 1],
    ["Enter", false, 1],
    [" ", false, 1],
    ["ArrowDown", true, 1],
    ["Home", false, 0],
    ["End", false, 1],
  ] as const)("opens the closed list with %s", (key, altKey, activeIndex) => {
    const { trigger } = mountInteractive("work")

    const event = press(trigger, key, { altKey })
    expect(event.defaultPrevented).toBe(true)
    expect(trigger.getAttribute("aria-expanded")).toBe("true")
    expect(trigger.getAttribute("aria-activedescendant")).toContain(`option-${activeIndex}`)
  })

  it("leaves the closed list alone for unmatched typeahead and empty accounts", () => {
    const first = mountInteractive("personal")

    expect(press(first.trigger, "z").defaultPrevented).toBe(false)
    expect(first.trigger.getAttribute("aria-expanded")).toBe("false")

    act(() => root?.unmount())
    root = null
    const empty = mountInteractive("", [])
    expect(press(empty.trigger, "ArrowDown").defaultPrevented).toBe(false)
    expect(empty.trigger.getAttribute("aria-expanded")).toBe("false")
    click(empty.trigger)
    expect(empty.trigger.getAttribute("aria-expanded")).toBe("false")
  })

  it("clamps the active option when the account list shrinks", () => {
    const { trigger } = mountInteractive("personal", typeaheadAccounts)
    click(trigger)
    press(trigger, "End")
    expect(trigger.getAttribute("aria-activedescendant")).toContain("option-2")

    act(() => {
      root?.render(
        createElement(AccountSelect, {
          id: "account",
          labelId: "account-label",
          value: "personal",
          accounts: typeaheadAccounts.slice(0, 2),
          onChange: () => undefined,
        }),
      )
    })
    expect(trigger.getAttribute("aria-activedescendant")).toContain("option-1")
  })

  it("moves through the open list and prevents navigation keys", () => {
    const { trigger } = mountInteractive("personal")
    click(trigger)

    for (const [key, activeIndex] of [
      ["ArrowDown", 1],
      ["ArrowUp", 0],
      ["End", 1],
      ["PageDown", 1],
      ["PageUp", 0],
      ["Home", 0],
    ] as const) {
      expect(press(trigger, key).defaultPrevented).toBe(true)
      expect(trigger.getAttribute("aria-activedescendant")).toContain(`option-${activeIndex}`)
    }
  })

  it.each(["Enter", " "])("chooses the active option with %s", (key) => {
    const { trigger, onChange } = mountInteractive("personal")
    click(trigger)
    press(trigger, "ArrowDown")

    const event = press(trigger, key)
    expect(event.defaultPrevented).toBe(true)
    expect(onChange).toHaveBeenCalledWith("work")
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
  })

  it("uses Alt+ArrowUp and Tab to commit the active option", () => {
    const altUp = mountInteractive("personal")
    click(altUp.trigger)
    press(altUp.trigger, "ArrowDown")
    expect(press(altUp.trigger, "ArrowUp", { altKey: true }).defaultPrevented).toBe(true)
    expect(altUp.onChange).toHaveBeenCalledWith("work")
    expect(altUp.trigger.getAttribute("aria-expanded")).toBe("false")

    act(() => root?.unmount())
    root = null
    const tab = mountInteractive("personal")
    click(tab.trigger)
    press(tab.trigger, "ArrowDown")
    expect(press(tab.trigger, "Tab").defaultPrevented).toBe(false)
    expect(tab.onChange).toHaveBeenCalledWith("work")
    expect(tab.trigger.getAttribute("aria-expanded")).toBe("false")
  })

  it("closes on Escape without selecting and supports typeahead cycling and timeout reset", () => {
    vi.useFakeTimers()
    const { trigger, onChange } = mountInteractive("personal", typeaheadAccounts)
    click(trigger)
    expect(press(trigger, "Escape").defaultPrevented).toBe(true)
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
    expect(onChange).not.toHaveBeenCalled()

    press(trigger, "p")
    expect(trigger.getAttribute("aria-activedescendant")).toContain("option-1")
    vi.advanceTimersByTime(200)
    press(trigger, "p")
    expect(trigger.getAttribute("aria-activedescendant")).toContain("option-0")
    vi.advanceTimersByTime(600)
    press(trigger, "w")
    expect(trigger.getAttribute("aria-activedescendant")).toContain("option-2")
    expect(press(trigger, "z").defaultPrevented).toBe(false)
    expect(trigger.getAttribute("aria-activedescendant")).toContain("option-2")
  })

  it("prevents pointer blur, closes on trigger blur, and scrolls the active option", () => {
    const originalScrollIntoView = Element.prototype.scrollIntoView
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView

    try {
      const { trigger } = mountInteractive("personal")
      click(trigger)
      expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" })

      const accountOptions = options()
      expect(mouseDown(accountOptions[1]).defaultPrevented).toBe(true)
      mouseMove(accountOptions[1])
      expect(scrollIntoView).toHaveBeenCalledTimes(2)

      act(() => {
        trigger.focus()
        trigger.blur()
      })
      expect(trigger.getAttribute("aria-expanded")).toBe("false")
    } finally {
      Element.prototype.scrollIntoView = originalScrollIntoView
    }
  })
})
