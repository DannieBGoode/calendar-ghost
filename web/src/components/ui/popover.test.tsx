/* @vitest-environment happy-dom */

import { act, useRef, useState } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, describe, expect, it, vi } from "vitest"

import { Popover } from "./popover"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: Root | null = null

afterEach(() => {
  act(() => root?.unmount())
  root = null
  document.body.innerHTML = ""
  document.documentElement.style.removeProperty("scroll-padding-top")
  document.documentElement.style.removeProperty("scroll-padding-bottom")
  vi.restoreAllMocks()
})

function render(element: React.ReactElement): HTMLElement {
  const container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
  act(() => root?.render(element))
  return container
}

/**
 * A control that opens a popover holding a short choice, as Change plan does: a title that takes
 * focus, a radio, and Cancel, with a button elsewhere on the page. `focusTitle` false leaves the
 * popover to take focus itself.
 */
function Harness({ onClose = vi.fn(), focusTitle = true }: { onClose?: () => void; focusTitle?: boolean }) {
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const close = () => {
    onClose()
    setOpen(false)
  }
  return (
    <div>
      <button type="button">Elsewhere</button>
      <div className="relative">
        <button
          ref={trigger}
          type="button"
          aria-haspopup="dialog"
          aria-expanded={open}
          aria-controls={open ? "change" : undefined}
          onClick={() => setOpen(!open)}
        >
          Change plan
        </button>
        <Popover id="change" open={open} aria-labelledby="change-title" returnFocus={() => trigger.current} onClose={close}>
          <h3 id="change-title" tabIndex={-1} ref={(heading) => (focusTitle ? heading?.focus() : undefined)}>
            Change plan for 2 people
          </h3>
          <label>
            <input type="radio" name="plan" /> Pro
          </label>
          <button type="button" onClick={close}>
            Cancel
          </button>
        </Popover>
      </div>
    </div>
  )
}

function button(container: HTMLElement, label: string): HTMLButtonElement {
  return [...container.querySelectorAll("button")].find((item) => item.textContent.trim() === label)!
}

function dialog(container: HTMLElement): HTMLElement | null {
  return container.querySelector<HTMLElement>("dialog")
}

function press(target: Element, key: string) {
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }))
  })
}

describe("Popover", () => {
  it("shows nothing while closed", () => {
    const container = render(<Harness />)
    expect(dialog(container)).toBeNull()
  })

  it("is a dialog that never blocks the page, named by its title", () => {
    const container = render(<Harness />)
    act(() => button(container, "Change plan").click())
    const layer = dialog(container)!
    expect(layer.id).toBe("change")
    expect(layer.getAttribute("aria-labelledby")).toBe("change-title")
    expect(layer.hasAttribute("aria-modal")).toBe(false)
    expect(button(container, "Change plan").getAttribute("aria-controls")).toBe("change")
  })

  it("leaves focus where its content put it, and takes focus itself when the content puts it nowhere", () => {
    const container = render(<Harness />)
    act(() => button(container, "Change plan").click())
    expect(document.activeElement?.id).toBe("change-title")

    act(() => root?.unmount())
    const other = render(<Harness focusTitle={false} />)
    act(() => button(other, "Change plan").click())
    expect(document.activeElement).toBe(dialog(other))
    expect(dialog(other)?.getAttribute("tabindex")).toBe("-1")
  })

  it("closes on Escape and returns focus to its control", () => {
    const onClose = vi.fn()
    const container = render(<Harness onClose={onClose} />)
    act(() => button(container, "Change plan").click())
    press(container.querySelector("input")!, "Escape")
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(dialog(container)).toBeNull()
    expect(document.activeElement).toBe(button(container, "Change plan"))
  })

  it("leaves Escape to a control inside that handles it first", () => {
    const onClose = vi.fn()
    const container = render(<Harness onClose={onClose} />)
    act(() => button(container, "Change plan").click())
    const input = container.querySelector("input")!
    input.addEventListener("keydown", (event) => event.preventDefault())
    press(input, "Escape")
    expect(onClose).not.toHaveBeenCalled()
  })

  it("returns focus to its control when its own Cancel closes it", () => {
    const container = render(<Harness />)
    act(() => button(container, "Change plan").click())
    act(() => button(container, "Cancel").click())
    expect(dialog(container)).toBeNull()
    expect(document.activeElement).toBe(button(container, "Change plan"))
  })

  it("closes on a press outside it, but not on its control or inside it", () => {
    const onClose = vi.fn()
    const container = render(<Harness onClose={onClose} />)
    act(() => button(container, "Change plan").click())
    act(() => {
      container.querySelector("input")!.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }))
      button(container, "Change plan").dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }))
    })
    expect(onClose).not.toHaveBeenCalled()
    act(() => {
      button(container, "Elsewhere").dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }))
    })
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(dialog(container)).toBeNull()
  })

  it("keeps focus where it went when it closes after focus moved on", () => {
    const container = render(<Harness />)
    act(() => button(container, "Change plan").click())
    const elsewhere = button(container, "Elsewhere")
    act(() => {
      elsewhere.focus()
      elsewhere.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }))
    })
    expect(dialog(container)).toBeNull()
    expect(document.activeElement).toBe(elsewhere)
  })
})

/** A box as `getBoundingClientRect` gives it, with no width, so only the vertical place is tested. */
function box(top: number, height: number): DOMRect {
  return { top, bottom: top + height, height, left: 0, right: 0, width: 0, x: 0, y: top, toJSON: () => ({}) }
}

/**
 * Lays the page out as a browser would: the window's height, where the control's wrapper sits, and
 * how tall the popover's content is, which its max-height caps. `content` can change later, as
 * content that arrives does.
 */
function layout({ window: height, control, content }: { window: number; control: number; content: number }) {
  // `shift` moves the control once the popover's height is capped, as on a page scrolled to its end.
  const page = { content, control, shift: 0 }
  vi.spyOn(window, "innerHeight", "get").mockReturnValue(height)
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    if (this.tagName === "DIALOG") return box(0, Math.min(page.content, Number.parseFloat(this.style.maxHeight) || Infinity))
    const capped = document.querySelector<HTMLElement>("dialog")?.style.maxHeight
    if (this.classList.contains("relative")) return box(page.control + (capped ? page.shift : 0), 32)
    return box(0, 0)
  })
  return page
}

/** Which side of its control the popover opened on, and the most it may be tall, as its style says. */
function placement(container: HTMLElement): { side: string | undefined; maxHeight: string } {
  const layer = dialog(container)!
  // A popover is marked capped exactly when its height is.
  expect(layer.dataset.capped === "true").toBe(layer.style.maxHeight !== "")
  return { side: layer.dataset.side, maxHeight: layer.style.maxHeight }
}

/** Lets what waits for the next frame run, as placing again after a scroll does. */
async function nextFrames() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 40))
  })
}

async function open(container: HTMLElement) {
  act(() => button(container, "Change plan").click())
  await nextFrames()
}

describe("Popover in the window", () => {
  it("opens under its control when the window has room for it", async () => {
    layout({ window: 900, control: 100, content: 400 })
    const container = render(<Harness />)
    await open(container)
    expect(placement(container)).toEqual({ side: "bottom", maxHeight: "" })
    expect(dialog(container)!.style.bottom).toBe("")
  })

  it("opens above its control when there is more room there, and never past the window's edge", async () => {
    layout({ window: 900, control: 700, content: 400 })
    const container = render(<Harness />)
    await open(container)
    // Under the control 146 px are left, above it 678.
    expect(placement(container)).toEqual({ side: "top", maxHeight: "" })
    expect(dialog(container)!.style.top).toBe("auto")
    expect(dialog(container)!.style.bottom).not.toBe("")

    act(() => root?.unmount())
    layout({ window: 900, control: 700, content: 800 })
    const taller = render(<Harness />)
    await open(taller)
    expect(placement(taller)).toEqual({ side: "top", maxHeight: "678px" })
  })

  it("caps its height at the room under its control when that is larger, so its content scrolls inside it", async () => {
    layout({ window: 600, control: 100, content: 800 })
    const container = render(<Harness />)
    await open(container)
    expect(placement(container)).toEqual({ side: "bottom", maxHeight: "446px" })
  })

  it("keeps clear of the top bar and of a toast, which the page's scroll padding marks", async () => {
    document.documentElement.style.setProperty("scroll-padding-top", "80px")
    document.documentElement.style.setProperty("scroll-padding-bottom", "100px")
    layout({ window: 900, control: 400, content: 500 })
    const container = render(<Harness />)
    await open(container)
    // Under the control: 900 - 100 - 16 - (432 + 6) = 346. Above it: 400 - 6 - 80 - 16 = 298.
    expect(placement(container)).toEqual({ side: "bottom", maxHeight: "346px" })
  })

  it("scrolls its control up first when the window has little room on either side of it", async () => {
    document.documentElement.style.setProperty("scroll-padding-top", "80px")
    layout({ window: 300, control: 130, content: 400 })
    const scrolled = vi.spyOn(HTMLElement.prototype, "scrollIntoView").mockImplementation(() => undefined)
    const container = render(<Harness />)
    await open(container)
    expect(scrolled).toHaveBeenCalledTimes(1)
    expect(scrolled.mock.contexts[0]).toBe(dialog(container)!.parentElement)
    // Up to just under the top bar, which the page's scroll padding keeps clear.
    expect(scrolled.mock.calls[0]).toEqual([{ block: "start" }])
  })

  it("fits itself again when capping its height moved its control, as at the end of a page", async () => {
    const page = layout({ window: 600, control: 300, content: 800 })
    page.shift = 16
    const container = render(<Harness />)
    await open(container)
    // Capped at the 278 px above the control, the page moved it 16 px down: 294 px are above it now.
    expect(placement(container)).toEqual({ side: "top", maxHeight: "294px" })
  })

  it("places itself again when its content grows, and as the page scrolls", async () => {
    const page = layout({ window: 900, control: 300, content: 200 })
    const container = render(<Harness />)
    await open(container)
    expect(placement(container)).toEqual({ side: "bottom", maxHeight: "" })

    page.content = 700
    act(() => dialog(container)!.append(document.createElement("p")))
    await nextFrames()
    // Under the control 546 px are left, above it 278: it stays under, capped.
    expect(placement(container)).toEqual({ side: "bottom", maxHeight: "546px" })

    page.control = 600
    act(() => {
      window.dispatchEvent(new Event("scroll"))
    })
    await nextFrames()
    // Now 246 px are left under it and 578 above.
    expect(placement(container)).toEqual({ side: "top", maxHeight: "578px" })
  })
})
