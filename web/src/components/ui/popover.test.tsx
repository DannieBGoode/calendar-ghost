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
