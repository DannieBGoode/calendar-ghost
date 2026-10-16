/* @vitest-environment happy-dom */

import { act, useState } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, describe, expect, it, vi } from "vitest"

import { untranslatedText } from "@/i18n/testing"

import { Switch } from "./switch"

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

function Harness({ pending = false, onChange = vi.fn() }: { pending?: boolean; onChange?: (checked: boolean) => void }) {
  const [checked, setChecked] = useState(false)
  return (
    <Switch
      aria-label="Plans"
      checked={checked}
      pending={pending}
      stateLabels={{ on: "On", off: "Off" }}
      onCheckedChange={(next) => {
        onChange(next)
        setChecked(next)
      }}
    />
  )
}

function control(container: HTMLElement): HTMLButtonElement {
  return container.querySelector<HTMLButtonElement>("[role='switch']")!
}

/** The state text a sighted person reads beside the track; the other is kept only for width. */
function shownState(button: HTMLElement): string | undefined {
  return [...button.querySelectorAll("[data-state-label]")].find((label) => !label.classList.contains("invisible"))?.textContent
}

describe("Switch", () => {
  it("is a switch named by its label, its state in aria-checked and as visible text", () => {
    const button = control(render(<Harness />))
    expect(button.tagName).toBe("BUTTON")
    expect(button.getAttribute("type")).toBe("button")
    expect(button.getAttribute("aria-label")).toBe("Plans")
    expect(button.getAttribute("aria-checked")).toBe("false")
    expect(shownState(button)).toBe("Off")
    // The state is announced from aria-checked, so the visible words are not read a second time.
    for (const label of button.querySelectorAll("[data-state-label]")) {
      expect(label.closest("[aria-hidden='true']")).not.toBeNull()
    }
  })

  it("applies at once when pressed and says its new state", () => {
    const onChange = vi.fn()
    const button = control(render(<Harness onChange={onChange} />))
    act(() => button.click())
    expect(onChange).toHaveBeenCalledWith(true)
    expect(button.getAttribute("aria-checked")).toBe("true")
    expect(shownState(button)).toBe("On")
    act(() => button.click())
    expect(onChange).toHaveBeenLastCalledWith(false)
    expect(button.getAttribute("aria-checked")).toBe("false")
  })

  it("is one stop in the tab sequence that Enter and Space press, as a native button", () => {
    const button = control(render(<Harness />))
    expect(button.tabIndex).toBe(0)
    act(() => button.focus())
    expect(document.activeElement).toBe(button)
  })

  it("keeps focus and ignores presses while its change is on its way", () => {
    const onChange = vi.fn()
    const button = control(render(<Harness pending onChange={onChange} />))
    act(() => button.focus())
    act(() => button.click())
    expect(onChange).not.toHaveBeenCalled()
    expect(button.getAttribute("aria-disabled")).toBe("true")
    expect(button.hasAttribute("disabled")).toBe(false)
    expect(document.activeElement).toBe(button)
  })

  it("can be named by the heading it switches", () => {
    const container = render(
      <>
        <h2 id="plans-title">Plans are off</h2>
        <Switch aria-labelledby="plans-title" checked={false} stateLabels={{ on: "On", off: "Off" }} onCheckedChange={vi.fn()} />
      </>,
    )
    expect(control(container).getAttribute("aria-labelledby")).toBe("plans-title")
  })

  it("shows only the words it is given", () => {
    const container = render(
      <Switch aria-label="[Þļåñš]" checked stateLabels={{ on: "[Óñ]", off: "[Óƒƒ]" }} onCheckedChange={vi.fn()} />,
    )
    expect(untranslatedText(container)).toEqual([])
  })
})
