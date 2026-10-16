/* @vitest-environment happy-dom */

import { act, useState } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, describe, expect, it, vi } from "vitest"

import { Checkbox } from "./checkbox"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: Root | null = null

afterEach(() => {
  act(() => root?.unmount())
  root = null
  document.body.innerHTML = ""
})

function render(element: React.ReactElement): HTMLInputElement {
  const container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
  act(() => root?.render(element))
  return container.querySelector("input")!
}

function Harness({
  initial = false,
  indeterminate = false,
  pending = false,
  onChange = vi.fn(),
}: {
  initial?: boolean
  indeterminate?: boolean
  pending?: boolean
  onChange?: (checked: boolean) => void
}) {
  const [checked, setChecked] = useState(initial)
  return (
    <Checkbox
      aria-label="Select robin@example.test"
      checked={checked}
      indeterminate={indeterminate}
      pending={pending}
      onCheckedChange={(next) => {
        onChange(next)
        setChecked(next)
      }}
    />
  )
}

describe("Checkbox", () => {
  it("is a native checkbox named by its label, in the tab sequence, so Space toggles it", () => {
    const box = render(<Harness />)
    expect(box.type).toBe("checkbox")
    expect(box.getAttribute("aria-label")).toBe("Select robin@example.test")
    expect(box.checked).toBe(false)
    expect(box.tabIndex).toBe(0)
  })

  it("reports each change and shows the new state", () => {
    const onChange = vi.fn()
    const box = render(<Harness onChange={onChange} />)
    act(() => box.click())
    expect(onChange).toHaveBeenCalledWith(true)
    expect(box.checked).toBe(true)
    act(() => box.click())
    expect(onChange).toHaveBeenLastCalledWith(false)
    expect(box.checked).toBe(false)
  })

  it("is mixed when only some of what it selects are selected, and selects all when pressed", () => {
    const onChange = vi.fn()
    const box = render(<Harness indeterminate onChange={onChange} />)
    expect(box.indeterminate).toBe(true)
    act(() => box.click())
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it("is not mixed unless asked", () => {
    expect(render(<Harness initial />).indeterminate).toBe(false)
  })

  it("keeps focus and ignores changes while a command is on its way", () => {
    const onChange = vi.fn()
    const box = render(<Harness pending onChange={onChange} />)
    act(() => box.focus())
    act(() => box.click())
    expect(onChange).not.toHaveBeenCalled()
    expect(box.checked).toBe(false)
    expect(box.getAttribute("aria-disabled")).toBe("true")
    expect(box.disabled).toBe(false)
    expect(document.activeElement).toBe(box)
  })
})
