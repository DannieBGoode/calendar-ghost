/* @vitest-environment happy-dom */

import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, describe, expect, it } from "vitest"

import { Button } from "./button"
import { Input } from "./input"
import { NativeSelect } from "./native-select"

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

/** The utilities an element is given on a coarse pointer, such as a finger on a touch screen. */
function coarse(element: Element): string[] {
  return [...element.classList].filter((name) => name.startsWith("pointer-coarse:"))
}

describe("Touch targets", () => {
  it.each([
    ["default", "pointer-coarse:h-11"],
    ["sm", "pointer-coarse:h-11"],
    ["icon", "pointer-coarse:size-11"],
  ] as const)("make a %s button 44 px tall on a coarse pointer, as DESIGN.md promises", (size, target) => {
    const container = render(<Button size={size}>Go</Button>)
    expect(coarse(container.querySelector("button")!)).toContain(target)
  })

  it("make a field and a select 44 px tall on a coarse pointer", () => {
    const container = render(
      <>
        <Input aria-label="Name" />
        <NativeSelect aria-label="Plan">
          <option>Free</option>
        </NativeSelect>
      </>,
    )
    expect(coarse(container.querySelector("input")!)).toContain("pointer-coarse:h-11")
    expect(coarse(container.querySelector("select")!)).toContain("pointer-coarse:h-11")
  })
})
