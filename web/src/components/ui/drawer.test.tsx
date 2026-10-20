/* @vitest-environment happy-dom */

import { act, useState } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, describe, expect, it, vi } from "vitest"

import { Drawer } from "./drawer"
import { ToastProvider } from "./toast"
import { useToast } from "./toast-context"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root | null = null

afterEach(() => {
  act(() => root?.unmount())
  root = null
  document.body.replaceChildren()
  document.body.style.overflow = ""
  vi.restoreAllMocks()
})

function render() {
  const close = vi.fn()
  const undo = vi.fn()
  function Content() {
    const toast = useToast()
    const [open, setOpen] = useState(true)
    if (!open) return <button onClick={() => setOpen(true)}>Original row</button>
    return (
      <Drawer aria-labelledby="drawer-title" onClose={() => { close(); setOpen(false) }}>
        <h2 id="drawer-title" tabIndex={-1}>Details</h2>
        <input aria-label="Search" onKeyDown={(event) => event.preventDefault()} />
        <button onClick={() => toast.show({ message: "Plan changed", action: { label: "Undo", onSelect: undo } })}>Change plan</button>
      </Drawer>
    )
  }
  const container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
  act(() => root?.render(<ToastProvider closeLabel="Close result"><Content /></ToastProvider>))
  return { container, close, undo, dialog: container.querySelector<HTMLDialogElement>("dialog")! }
}

describe("Drawer", () => {
  it("uses a named native modal, locks scrolling, and restores the previous overflow on close", () => {
    document.body.style.overflow = "auto"
    const { dialog, close } = render()
    expect(dialog.open).toBe(true)
    expect(document.activeElement).toBe(dialog.querySelector("h2"))
    expect(dialog.getAttribute("aria-labelledby")).toBe("drawer-title")
    expect(document.body.style.overflow).toBe("hidden")
    act(() => { dialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })) })
    expect(close).toHaveBeenCalledOnce()
    expect(document.body.style.overflow).toBe("auto")
  })

  it("lets an inner search handle Escape before the drawer", () => {
    const { dialog, close } = render()
    act(() => { dialog.querySelector("input")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })) })
    expect(close).not.toHaveBeenCalled()
    expect(dialog.open).toBe(true)
  })

  it("routes backdrop dismissal through the close guard, without dismissing for an inner pointer", () => {
    const { dialog, close } = render()
    act(() => { dialog.querySelector("h2")!.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true })) })
    expect(close).not.toHaveBeenCalled()
    act(() => { dialog.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true })) })
    expect(close).toHaveBeenCalledOnce()
  })

  it("remeasures a visible result when it moves between the drawer and page", () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const top = this.isConnected ? window.innerHeight - (this.closest("dialog") ? 120 : 60) : 0
      return new DOMRect(0, top, 100, 60)
    })
    const { container, dialog } = render()
    const space = () => document.documentElement.style.getPropertyValue("--toast-space")
    act(() => dialog.querySelector<HTMLButtonElement>("button")!.click())
    expect(space()).toBe("128px")
    act(() => { dialog.dispatchEvent(new Event("cancel", { cancelable: true })) })
    expect(space()).toBe("68px")
    act(() => { window.dispatchEvent(new Event("resize")) })
    expect(space()).toBe("68px")
    act(() => container.querySelector<HTMLButtonElement>("button")!.click())
    expect(space()).toBe("128px")
    act(() => { window.dispatchEvent(new Event("resize")) })
    expect(space()).toBe("128px")
  })

  it("keeps results and Undo inside the modal and returns the result to the page when closed", () => {
    const { container, dialog, undo } = render()
    act(() => dialog.querySelector<HTMLButtonElement>("button")!.click())
    expect(dialog.querySelector('[role="status"]')?.textContent).toBe("Plan changed")
    const action = [...dialog.querySelectorAll("button")].find((button) => button.textContent === "Undo")!
    act(() => action.click())
    expect(undo).toHaveBeenCalledOnce()
    expect(dialog.open).toBe(true)
    act(() => dialog.querySelector<HTMLButtonElement>("button")!.click())
    act(() => { dialog.dispatchEvent(new Event("cancel", { cancelable: true })) })
    expect(container.querySelector("dialog")).toBeNull()
    expect(container.querySelector('[role="status"]')?.textContent).toBe("Plan changed")
  })
})
