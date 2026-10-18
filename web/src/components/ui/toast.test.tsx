/* @vitest-environment happy-dom */

import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, describe, expect, it, vi } from "vitest"

import { untranslatedText } from "@/i18n/testing"

import { ToastProvider } from "./toast"
import { useToast } from "./toast-context"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: Root | null = null

afterEach(() => {
  act(() => root?.unmount())
  root = null
  document.body.innerHTML = ""
  vi.useRealTimers()
})

type Show = ReturnType<typeof useToast>["show"]

/**
 * Renders a page with one control inside the provider. `show` shows a toast as a test step;
 * `showNow` is the provider's own, for a toast's action to call while it runs.
 */
function render(closeLabel = "Close"): { container: HTMLElement; show: Show; showNow: Show } {
  const container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
  const shown: { show?: Show } = {}
  function Page() {
    const toasts = useToast()
    shown.show = toasts.show
    return (
      <button id="plans-switch" type="button">
        Plans
      </button>
    )
  }
  act(() =>
    root?.render(
      <ToastProvider closeLabel={closeLabel}>
        <Page />
      </ToastProvider>,
    ),
  )
  return {
    container,
    show: (toast) => act(() => shown.show?.(toast)),
    showNow: (toast) => shown.show?.(toast),
  }
}

function liveRegions(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>("[role='status'], [aria-live]")]
}

/** The one live region; the tests above check that there is only one. */
function liveRegion(container: HTMLElement): HTMLElement {
  return liveRegions(container)[0]!
}

function buttonNamed(container: HTMLElement, name: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find(
    (button) => button.getAttribute("aria-label") === name || button.textContent === name,
  )
}

/** The toast itself: its icon, its result, and its buttons. */
function card(container: HTMLElement): HTMLElement {
  return liveRegion(container).parentElement!
}

function control(container: HTMLElement): HTMLButtonElement {
  return container.querySelector<HTMLButtonElement>("#plans-switch")!
}

describe("ToastProvider", () => {
  it("has one polite live region, there before any result, so the first one is announced", () => {
    const { container } = render()
    expect(liveRegions(container)).toHaveLength(1)
    expect(liveRegion(container).getAttribute("role")).toBe("status")
    expect(liveRegion(container).getAttribute("aria-live")).toBe("polite")
    expect(liveRegion(container).textContent).toBe("")
  })

  it("says a result in the live region with its Undo and Close, and never takes focus", () => {
    const { container, show } = render()
    act(() => control(container).focus())
    show({ message: "Plans are on. They limit 2 people.", action: { label: "Undo", onSelect: vi.fn() } })
    expect(liveRegions(container)).toHaveLength(1)
    expect(liveRegion(container).textContent).toBe("Plans are on. They limit 2 people.")
    expect(buttonNamed(container, "Undo")).toBeDefined()
    expect(buttonNamed(container, "Close")).toBeDefined()
    // The buttons sit outside the live region, so they are not read out with the result.
    expect(liveRegion(container).querySelector("button")).toBeNull()
    expect(document.activeElement).toBe(control(container))
  })

  it("shows the icon of a next step in place of Undo's, and keeps it until it is closed", () => {
    vi.useFakeTimers()
    const { container, show } = render()
    const next = vi.fn()
    show({
      message: "Free was added.",
      action: { label: "Assign people", icon: <svg className="next-step" aria-hidden="true" />, onSelect: next },
    })
    const button = buttonNamed(container, "Assign people")!
    expect(button.querySelector(".next-step")).not.toBeNull()
    expect(button.querySelectorAll("svg")).toHaveLength(1)
    act(() => {
      vi.advanceTimersByTime(10 * 60 * 1000)
    })
    act(() => button.click())
    expect(next).toHaveBeenCalledTimes(1)
    expect(liveRegion(container).textContent).toBe("")
  })

  it("shows one result at a time: the next replaces it", () => {
    const { container, show } = render()
    show({ message: "Plans are on. They limit 2 people.", action: { label: "Undo", onSelect: vi.fn() } })
    show({ message: "Free is the default plan now." })
    expect(liveRegions(container)).toHaveLength(1)
    expect(liveRegion(container).textContent).toBe("Free is the default plan now.")
    expect(buttonNamed(container, "Undo")).toBeUndefined()
  })

  it("announces the same result again when it arrives again", () => {
    const { container, show } = render()
    show({ message: "Plans are on." })
    const first = liveRegion(container).firstElementChild
    show({ message: "Plans are on." })
    expect(liveRegion(container).firstElementChild).not.toBe(first)
  })

  it("stays with Undo until it is closed, so Undo is still there when a keyboard reaches it", () => {
    vi.useFakeTimers()
    const { container, show } = render()
    show({ message: "Plans are off. Nobody is limited.", action: { label: "Undo", onSelect: vi.fn() } })
    act(() => {
      vi.advanceTimersByTime(10 * 60 * 1000)
    })
    expect(liveRegion(container).textContent).toBe("Plans are off. Nobody is limited.")
    expect(buttonNamed(container, "Undo")).toBeDefined()
  })

  it("closes a result with no Undo on its own after six seconds", () => {
    vi.useFakeTimers()
    const { container, show } = render()
    show({ message: "Free was saved." })
    act(() => {
      vi.advanceTimersByTime(5_900)
    })
    expect(liveRegion(container).textContent).toBe("Free was saved.")
    act(() => {
      vi.advanceTimersByTime(200)
    })
    expect(liveRegion(container).textContent).toBe("")
    expect(buttonNamed(container, "Close")).toBeUndefined()
  })

  it("gives the next result six seconds of its own", () => {
    vi.useFakeTimers()
    const { container, show } = render()
    show({ message: "Free was saved." })
    act(() => {
      vi.advanceTimersByTime(4_000)
    })
    show({ message: "Family was saved." })
    act(() => {
      vi.advanceTimersByTime(4_000)
    })
    expect(liveRegion(container).textContent).toBe("Family was saved.")
  })

  it("waits while the pointer is on it, then gives six seconds more", () => {
    vi.useFakeTimers()
    const { container, show } = render()
    show({ message: "Free was saved." })
    act(() => {
      card(container).dispatchEvent(new PointerEvent("pointerover", { bubbles: true, relatedTarget: document.body }))
    })
    act(() => {
      vi.advanceTimersByTime(60_000)
    })
    expect(liveRegion(container).textContent).toBe("Free was saved.")
    act(() => {
      card(container).dispatchEvent(new PointerEvent("pointerout", { bubbles: true, relatedTarget: document.body }))
    })
    act(() => {
      vi.advanceTimersByTime(5_900)
    })
    expect(liveRegion(container).textContent).toBe("Free was saved.")
    act(() => {
      vi.advanceTimersByTime(200)
    })
    expect(liveRegion(container).textContent).toBe("")
  })

  it("waits while focus is in it, so a keyboard can still reach Close", () => {
    vi.useFakeTimers()
    const { container, show } = render()
    act(() => control(container).focus())
    show({ message: "Free was saved." })
    act(() => buttonNamed(container, "Close")!.focus())
    act(() => {
      vi.advanceTimersByTime(60_000)
    })
    expect(liveRegion(container).textContent).toBe("Free was saved.")
    act(() => control(container).focus())
    act(() => {
      vi.advanceTimersByTime(6_100)
    })
    expect(liveRegion(container).textContent).toBe("")
  })

  it("reserves its height at the foot of the page while it shows, so nothing has to stay under it", () => {
    const { container, show } = render()
    const space = () => document.documentElement.style.getPropertyValue("--toast-space")
    expect(space()).toBe("")
    show({ message: "Plans are on.", action: { label: "Undo", onSelect: vi.fn() } })
    expect(space()).toMatch(/^\d+px$/)
    act(() => buttonNamed(container, "Close")!.click())
    expect(space()).toBe("")
  })

  it("runs Undo once, closes, and returns focus to the control that was focused when it appeared", () => {
    const { container, show } = render()
    const undo = vi.fn()
    act(() => control(container).focus())
    show({ message: "Plans are on.", action: { label: "Undo", onSelect: undo } })
    const button = buttonNamed(container, "Undo")!
    act(() => button.focus())
    act(() => button.click())
    expect(undo).toHaveBeenCalledTimes(1)
    expect(liveRegion(container).textContent).toBe("")
    expect(buttonNamed(container, "Undo")).toBeUndefined()
    expect(document.activeElement).toBe(control(container))
  })

  it("keeps the result Undo shows, and still returns focus to the control", () => {
    const { container, show, showNow } = render()
    act(() => control(container).focus())
    show({
      message: "Plans are on.",
      action: { label: "Undo", onSelect: () => showNow({ message: "Plans are off." }) },
    })
    const button = buttonNamed(container, "Undo")!
    act(() => button.focus())
    act(() => button.click())
    expect(liveRegion(container).textContent).toBe("Plans are off.")
    expect(document.activeElement).toBe(control(container))
  })

  it("closes with its Close button or Escape, returning focus that was inside it", () => {
    const { container, show } = render()
    act(() => control(container).focus())
    show({ message: "Free was removed." })
    act(() => buttonNamed(container, "Close")!.click())
    expect(liveRegion(container).textContent).toBe("")

    show({ message: "Free was removed.", action: { label: "Undo", onSelect: vi.fn() } })
    const undo = buttonNamed(container, "Undo")!
    act(() => undo.focus())
    act(() => {
      undo.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }))
    })
    expect(liveRegion(container).textContent).toBe("")
    expect(document.activeElement).toBe(control(container))
  })

  it("needs its provider", () => {
    function Orphan() {
      useToast()
      return null
    }
    const container = document.createElement("div")
    root = createRoot(container)
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined)
    expect(() => act(() => root?.render(<Orphan />))).toThrow()
    error.mockRestore()
  })

  it("shows only the words it is given", () => {
    const { container, show } = render("[Çļöšé]")
    show({ message: "[Þļåñš åŕé öñ.]", action: { label: "[Úñðö]", onSelect: vi.fn() } })
    // The page's own control is fixture text; the toast's words are all pseudo-translated.
    expect(untranslatedText(container, ["Plans"])).toEqual([])
  })
})
