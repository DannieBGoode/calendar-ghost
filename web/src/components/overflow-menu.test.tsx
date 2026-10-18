/* @vitest-environment happy-dom */

import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, describe, expect, it, vi } from "vitest"

import { OverflowMenu, type OverflowMenuItem } from "./overflow-menu"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: Root | null = null

afterEach(() => {
  act(() => root?.unmount())
  root = null
  document.body.innerHTML = ""
  vi.restoreAllMocks()
})

const ITEMS: OverflowMenuItem[] = [
  { id: "edit", label: "Edit", onSelect: vi.fn() },
  { id: "remove", label: "Remove", description: "Make another plan the default first.", disabled: true, onSelect: vi.fn() },
]

function render(): HTMLElement {
  const container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
  act(() => root?.render(<OverflowMenu label="More actions for Free" items={ITEMS} />))
  return container
}

/** A box as `getBoundingClientRect` gives it, with no width, so only the vertical place is tested. */
function box(top: number, height: number): DOMRect {
  return { top, bottom: top + height, height, left: 0, right: 0, width: 0, x: 0, y: top, toJSON: () => ({}) }
}

/**
 * Lays the page out as a browser would: the window's height, where the menu's trigger sits, and
 * how tall the menu's items are, which its max-height caps.
 */
function layout({ window: height, trigger, content }: { window: number; trigger: number; content: number }) {
  vi.spyOn(window, "innerHeight", "get").mockReturnValue(height)
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    if (this.getAttribute("role") === "menu") return box(0, Math.min(content, Number.parseFloat(this.style.maxHeight) || Infinity))
    if (this.classList.contains("overflow-menu")) return box(trigger, 40)
    return box(0, 0)
  })
}

async function open(container: HTMLElement) {
  act(() => container.querySelector<HTMLButtonElement>("[aria-haspopup='menu']")!.click())
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 40))
  })
}

/** Which side of its trigger the menu opened on, and the most it may be tall, as its style says. */
function placement(container: HTMLElement): { side: string | undefined; maxHeight: string } {
  const menu = container.querySelector<HTMLElement>("[role='menu']")!
  return { side: menu.dataset.side, maxHeight: menu.style.maxHeight }
}

describe("OverflowMenu in the window", () => {
  it("opens under its trigger when the window has room for it", async () => {
    layout({ window: 900, trigger: 100, content: 300 })
    const container = render()
    await open(container)
    expect(placement(container)).toEqual({ side: "bottom", maxHeight: "" })
    expect(document.activeElement?.textContent).toBe("Edit")
  })

  it("caps its height at the room it has, so its items scroll inside it", async () => {
    layout({ window: 600, trigger: 150, content: 500 })
    const container = render()
    await open(container)
    // Under the trigger: 600 - 16 - (190 + 4) = 390. Above it: 150 - 4 - 16 = 130.
    expect(placement(container)).toEqual({ side: "bottom", maxHeight: "390px" })
  })
})
