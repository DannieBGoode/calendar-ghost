/* @vitest-environment happy-dom */

import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, describe, expect, it, vi } from "vitest"

import { DestructiveConfirmation } from "@/components/destructive-confirmation"

let root: Root | undefined
let container: HTMLDivElement

afterEach(() => {
  act(() => root?.unmount())
  root = undefined
  container.remove()
  vi.restoreAllMocks()
})

/** Whether the reader asks for reduced motion. */
function motion(reduced: boolean) {
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query) => ({ matches: reduced && query === "(prefers-reduced-motion: reduce)", media: query }) as MediaQueryList,
  )
}

function open() {
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
  act(() =>
    root?.render(
      <DestructiveConfirmation
        id="remove-pro"
        title="Remove Pro?"
        body="People who join later cannot get it."
        cancelLabel="Keep plan"
        confirmLabel="Remove plan"
        pendingLabel="Removing"
        pending={false}
        onConfirm={() => undefined}
        onCancel={() => undefined}
      />,
    ),
  )
  return container.querySelector<HTMLElement>("#remove-pro")!
}

describe("DestructiveConfirmation", () => {
  it("scrolls fully into view as it opens, smoothly, with focus on its title", () => {
    motion(false)
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined)
    const group = open()
    expect(scrolled).toHaveBeenCalledOnce()
    expect(scrolled.mock.contexts[0]).toBe(group)
    // Nearest, within the page's scroll padding: below the top bar and above a toast.
    expect(scrolled).toHaveBeenCalledWith({ block: "nearest", behavior: "smooth" })
    expect(document.activeElement).toBe(group.querySelector("h3"))
  })

  it("scrolls at once when the reader asks for reduced motion", () => {
    motion(true)
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined)
    open()
    expect(scrolled).toHaveBeenCalledWith({ block: "nearest", behavior: "instant" })
  })

  it("puts its start under the top bar when it is taller than the window", () => {
    motion(false)
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, 600, window.innerHeight + 1))
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined)
    open()
    expect(scrolled).toHaveBeenCalledWith({ block: "start", behavior: "smooth" })
  })
})
