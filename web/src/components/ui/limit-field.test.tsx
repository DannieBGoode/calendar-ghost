/* @vitest-environment happy-dom */

import { act, useState } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, describe, expect, it, vi } from "vitest"

import { untranslatedText } from "@/i18n/testing"

import { LimitField, type LimitValue } from "./limit-field"

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

const LABELS = { noLimit: "No limit", upTo: "Up to", fewer: "Fewer", more: "More" }

function Harness({
  initial,
  tokens = false,
  pending = false,
  onChange = vi.fn(),
}: {
  initial: LimitValue
  tokens?: boolean
  pending?: boolean
  onChange?: (value: LimitValue) => void
}) {
  const [value, setValue] = useState(initial)
  return (
    <LimitField
      legend={tokens ? "Maximum Integration Tokens" : "Maximum active rules"}
      hint={tokens ? "Revoked tokens don't count." : "Paused rules and drafts don't count."}
      labels={tokens ? { ...LABELS, none: "None" } : LABELS}
      unit={tokens ? undefined : "rules"}
      min={1}
      max={10_000}
      value={value}
      pending={pending}
      onChange={(next) => {
        onChange(next)
        setValue(next)
      }}
    >
      <p id="rules-warning">1 person on Pro has more active rules than this.</p>
    </LimitField>
  )
}

function radios(container: HTMLElement): HTMLInputElement[] {
  return [...container.querySelectorAll<HTMLInputElement>("input[type='radio']")]
}

function labelOf(input: HTMLInputElement): string {
  return [...(input.labels ?? [])].map((label) => label.textContent).join(" ")
}

/** The option named `label`. */
function option(container: HTMLElement, label: string): HTMLInputElement {
  return radios(container).find((radio) => labelOf(radio) === label)!
}

function amount(container: HTMLElement): HTMLInputElement {
  return container.querySelector<HTMLInputElement>("[role='spinbutton']")!
}

function button(container: HTMLElement, name: string): HTMLButtonElement {
  return container.querySelector<HTMLButtonElement>(`button[aria-label='${name}']`)!
}

function press(target: HTMLElement, key: string) {
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }))
  })
}

function type(input: HTMLInputElement, value: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set?.call(input, value)
    input.dispatchEvent(new Event("input", { bubbles: true }))
  })
}

function chosen(container: HTMLElement): string {
  return labelOf(radios(container).find((radio) => radio.checked)!)
}

describe("LimitField", () => {
  it("is a group named by its legend and described by its hint, with No limit first and Up to a number", () => {
    const container = render(<Harness initial={{ choice: "noLimit", amount: "3" }} />)
    const group = container.querySelector("fieldset")!
    expect(group.querySelector("legend")?.textContent).toBe("Maximum active rules")
    const hint = document.getElementById(group.getAttribute("aria-describedby")!)
    expect(hint?.textContent).toBe("Paused rules and drafts don't count.")
    expect(radios(container).map(labelOf)).toEqual(["No limit", "Up to"])
    expect(chosen(container)).toBe("No limit")
    expect(container.textContent).toContain("rules")
    expect(container.textContent).toContain("1 person on Pro has more active rules than this.")
  })

  it("offers None first and No limit last where none is a real choice", () => {
    const container = render(<Harness tokens initial={{ choice: "none", amount: "2" }} />)
    expect(radios(container).map(labelOf)).toEqual(["None", "Up to", "No limit"])
    expect(chosen(container)).toBe("None")
  })

  it("puts its options in one native radio group, so the arrow keys move the choice and Tab stops once", () => {
    const options = radios(render(<Harness tokens initial={{ choice: "none", amount: "2" }} />))
    expect(new Set(options.map((option) => option.name)).size).toBe(1)
    expect(options[0]!.name).not.toBe("")
  })

  it("is a text field with a numeric keyboard and spin button semantics, so a scroll wheel never changes a limit", () => {
    const number = amount(render(<Harness initial={{ choice: "upTo", amount: "3" }} />))
    expect(number.type).toBe("text")
    expect(number.inputMode).toBe("numeric")
    expect(number.getAttribute("aria-valuemin")).toBe("1")
    expect(number.getAttribute("aria-valuemax")).toBe("10000")
    expect(number.getAttribute("aria-valuenow")).toBe("3")
    expect(document.getElementById(number.getAttribute("aria-labelledby")!)?.textContent).toBe("Maximum active rules")
  })

  it("keeps the number visible and dimmed while No limit is chosen, so choosing Up to again keeps it", () => {
    const onChange = vi.fn()
    const container = render(<Harness initial={{ choice: "upTo", amount: "3" }} onChange={onChange} />)
    act(() => option(container, "No limit").click())
    expect(onChange).toHaveBeenLastCalledWith({ choice: "noLimit", amount: "3" })
    expect(amount(container).value).toBe("3")
    expect(container.querySelector("[data-stepper]")?.hasAttribute("data-inactive")).toBe(true)
    act(() => option(container, "Up to").click())
    expect(onChange).toHaveBeenLastCalledWith({ choice: "upTo", amount: "3" })
    expect(container.querySelector("[data-stepper]")?.hasAttribute("data-inactive")).toBe(false)
  })

  it("steps by one with the arrow keys, by ten with Page Up and Page Down, and to its bounds with Home and End", () => {
    const container = render(<Harness initial={{ choice: "upTo", amount: "3" }} />)
    const number = amount(container)
    press(number, "ArrowUp")
    expect(number.value).toBe("4")
    press(number, "ArrowDown")
    press(number, "ArrowDown")
    expect(number.value).toBe("2")
    press(number, "PageUp")
    expect(number.value).toBe("12")
    press(number, "PageDown")
    press(number, "PageDown")
    expect(number.value).toBe("1")
    press(number, "End")
    expect(number.value).toBe("10000")
    press(number, "ArrowUp")
    expect(number.value).toBe("10000")
    press(number, "Home")
    expect(number.value).toBe("1")
    press(number, "ArrowDown")
    expect(number.value).toBe("1")
    expect(number.getAttribute("aria-valuenow")).toBe("1")
  })

  it("starts an empty number at its least", () => {
    const container = render(<Harness initial={{ choice: "upTo", amount: "" }} />)
    expect(amount(container).hasAttribute("aria-valuenow")).toBe(false)
    press(amount(container), "ArrowUp")
    expect(amount(container).value).toBe("1")
  })

  it("keeps only digits as the number is typed", () => {
    const onChange = vi.fn()
    const container = render(<Harness initial={{ choice: "upTo", amount: "3" }} onChange={onChange} />)
    type(amount(container), "1,2a5")
    expect(onChange).toHaveBeenLastCalledWith({ choice: "upTo", amount: "125" })
    expect(amount(container).maxLength).toBe(5)
  })

  it("leaves the number and its buttons out of the tab sequence while another option is chosen", () => {
    const container = render(<Harness initial={{ choice: "noLimit", amount: "3" }} />)
    expect(amount(container).tabIndex).toBe(-1)
    expect(button(container, "Fewer").tabIndex).toBe(-1)
    expect(button(container, "More").tabIndex).toBe(-1)
    act(() => option(container, "Up to").click())
    expect(amount(container).tabIndex).toBe(0)
    // The arrow keys step the number, so its buttons are only for a pointer, as in a spin button.
    expect(button(container, "More").tabIndex).toBe(-1)
  })

  it("chooses Up to when the dimmed number is focused or stepped with a pointer", () => {
    const onChange = vi.fn()
    const container = render(<Harness initial={{ choice: "noLimit", amount: "3" }} onChange={onChange} />)
    act(() => amount(container).focus())
    expect(onChange).toHaveBeenLastCalledWith({ choice: "upTo", amount: "3" })
    expect(chosen(container)).toBe("Up to")
    act(() => option(container, "No limit").click())
    act(() => button(container, "More").click())
    expect(onChange).toHaveBeenLastCalledWith({ choice: "upTo", amount: "4" })
    act(() => button(container, "Fewer").click())
    expect(onChange).toHaveBeenLastCalledWith({ choice: "upTo", amount: "3" })
  })

  it("names the number's buttons and the number they change", () => {
    const container = render(<Harness initial={{ choice: "upTo", amount: "3" }} />)
    const number = amount(container)
    expect(button(container, "Fewer").getAttribute("aria-controls")).toBe(number.id)
    expect(button(container, "More").getAttribute("aria-controls")).toBe(number.id)
    expect(button(container, "More").type).toBe("button")
  })

  it("passes the number field's own attributes, so a refusal can name and describe it", () => {
    const container = render(
      <LimitField
        legend="Maximum active rules"
        labels={LABELS}
        min={1}
        max={10_000}
        value={{ choice: "upTo", amount: "0" }}
        inputProps={{ id: "plan-free-rules", "aria-invalid": true, "aria-describedby": "plan-free-rules-error" }}
        onChange={vi.fn()}
      />,
    )
    const number = amount(container)
    expect(number.id).toBe("plan-free-rules")
    expect(number.getAttribute("aria-invalid")).toBe("true")
    expect(number.getAttribute("aria-describedby")).toBe("plan-free-rules-error")
  })

  it("keeps focus and ignores changes while a save is on its way", () => {
    const onChange = vi.fn()
    const container = render(<Harness pending initial={{ choice: "upTo", amount: "3" }} onChange={onChange} />)
    const number = amount(container)
    act(() => number.focus())
    press(number, "ArrowUp")
    type(number, "7")
    act(() => button(container, "More").click())
    act(() => option(container, "No limit").click())
    expect(onChange).not.toHaveBeenCalled()
    expect(chosen(container)).toBe("Up to")
    expect(number.readOnly).toBe(true)
    expect(number.getAttribute("aria-disabled")).toBe("true")
    expect(option(container, "No limit").getAttribute("aria-disabled")).toBe("true")
    expect(document.activeElement).toBe(number)
  })

  it("shows only the words it is given", () => {
    const container = render(
      <LimitField
        legend="[Ṁåẋîɱûɱ]"
        hint="[Ŕéṽöķéð]"
        labels={{ none: "[Ñöñé]", upTo: "[Úþ ţö]", noLimit: "[Ñö ļîɱîţ]", fewer: "[Ƒéŵéŕ]", more: "[Ṁöŕé]" }}
        unit="[ŕûļéš]"
        min={1}
        max={10_000}
        value={{ choice: "upTo", amount: "2" }}
        onChange={vi.fn()}
      />,
    )
    expect(untranslatedText(container)).toEqual([])
  })
})
