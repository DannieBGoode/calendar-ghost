/* @vitest-environment happy-dom */

import { act, useState } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, describe, expect, it, vi } from "vitest"

import { untranslatedText } from "@/i18n/testing"

import { RadioRows, type RadioRowOption } from "./radio-rows"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Plan = "free" | "pro" | "family"

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

const PLANS: readonly RadioRowOption<Plan>[] = [
  { value: "free", title: "Free", summary: "1 rule, 1 account", badges: [{ text: "Default", variant: "outline" }] },
  { value: "pro", title: "Pro", summary: "Unlimited, Instant", badges: [{ text: "Current" }] },
  { value: "family", title: "Family" },
]

function Harness({
  pending = false,
  onChange = vi.fn(),
  notes = {},
}: {
  pending?: boolean
  onChange?: (value: Plan) => void
  notes?: Partial<Record<Plan, RadioRowOption<Plan>["note"]>>
}) {
  const [value, setValue] = useState<Plan>("pro")
  return (
    <>
      <h3 id="plan-label">Change plan</h3>
      <RadioRows
        aria-labelledby="plan-label"
        value={value}
        options={PLANS.map((option) => ({ ...option, note: notes[option.value] ?? null }))}
        pending={pending}
        onValueChange={(next) => {
          onChange(next)
          setValue(next)
        }}
      />
    </>
  )
}

function radios(container: HTMLElement): HTMLInputElement[] {
  return [...container.querySelectorAll<HTMLInputElement>("input[type='radio']")]
}

function option(container: HTMLElement, title: string): HTMLInputElement {
  return radios(container).find((radio) => labelOf(radio).startsWith(title))!
}

function referenced(element: Element, attribute: string): string[] {
  const ids = element.getAttribute(attribute)?.split(" ").filter(Boolean) ?? []
  return ids.map((id) => document.getElementById(id)?.textContent ?? "")
}

function labelOf(input: HTMLInputElement): string {
  return [...(input.labels ?? [])].map((label) => label.textContent).join(" ")
}

describe("RadioRows", () => {
  it("is one radio group named by its label, each row a native radio named by its title and badges, described by its summary", () => {
    const container = render(<Harness />)
    const group = container.querySelector("[role='radiogroup']")!
    expect(referenced(group, "aria-labelledby")).toEqual(["Change plan"])
    expect(radios(container).map(labelOf)).toEqual(["Free Default", "Pro Current", "Family"])
    expect(referenced(option(container, "Free"), "aria-describedby")).toEqual(["1 rule, 1 account"])
    expect(option(container, "Family").hasAttribute("aria-describedby")).toBe(false)
    expect(option(container, "Pro").checked).toBe(true)
    expect(radios(container).every((radio) => !radio.disabled)).toBe(true)
    // One name, so the arrow keys move the choice and Tab stops once, as a native radio group does.
    expect(new Set(radios(container).map((radio) => radio.name)).size).toBe(1)
    expect(option(container, "Free").name).not.toBe("")
  })

  it("chooses the row that is pressed", () => {
    const onChange = vi.fn()
    const container = render(<Harness onChange={onChange} />)
    act(() => option(container, "Family").click())
    expect(onChange).toHaveBeenCalledWith("family")
    expect(option(container, "Family").checked).toBe(true)
    expect(option(container, "Pro").checked).toBe(false)
  })

  it("says under a row what choosing it would do, in a live region there before it speaks, which describes its radio", () => {
    const container = render(<Harness />)
    // Every row has its region from the start, empty, so a screen reader announces what fills it.
    const regions = [...container.querySelectorAll("[role='status']")]
    expect(regions).toHaveLength(3)
    expect(regions.every((region) => region.textContent === "")).toBe(true)

    act(() => root?.render(<Harness notes={{ free: { text: "Would be over: 2 calendar accounts, 1 allowed", tone: "attention" } }} />))
    const free = option(container, "Free")
    expect(referenced(free, "aria-describedby")).toEqual(["1 rule, 1 account", "Would be over: 2 calendar accounts, 1 allowed"])
    const note = container.querySelector<HTMLElement>("[role='status'][data-tone='attention']")!
    expect(note.textContent).toBe("Would be over: 2 calendar accounts, 1 allowed")
    expect(note.querySelector("svg[aria-hidden='true']")).not.toBeNull()

    act(() => root?.render(<Harness notes={{ family: { text: "Within every limit" } }} />))
    expect(referenced(option(container, "Family"), "aria-describedby")).toEqual(["Within every limit"])
    expect(container.querySelector("[role='status'][data-tone]")).toBeNull()
    expect(referenced(option(container, "Free"), "aria-describedby")).toEqual(["1 rule, 1 account"])
  })

  it("says on the group what describes the choice, and that it is missing", () => {
    const container = render(
      <>
        <p id="plan-error">Choose a plan first.</p>
        <RadioRows aria-label="Change plan" aria-describedby="plan-error" aria-invalid value={null} options={PLANS} onValueChange={vi.fn()} />
      </>,
    )
    const group = container.querySelector("[role='radiogroup']")!
    expect(group.getAttribute("aria-invalid")).toBe("true")
    expect(referenced(group, "aria-describedby")).toEqual(["Choose a plan first."])
    expect(radios(container).some((radio) => radio.checked)).toBe(false)
  })

  it("keeps focus and ignores choices while a command is on its way", () => {
    const onChange = vi.fn()
    const container = render(<Harness pending onChange={onChange} />)
    const family = option(container, "Family")
    expect(radios(container).every((radio) => radio.getAttribute("aria-disabled") === "true")).toBe(true)
    act(() => family.focus())
    act(() => family.click())
    expect(onChange).not.toHaveBeenCalled()
    expect(option(container, "Pro").checked).toBe(true)
    expect(document.activeElement).toBe(option(container, "Family"))
  })

  it("shows only the words it is given", () => {
    const container = render(
      <RadioRows
        aria-label="[Çĥåñĝé þļåñ]"
        value="a"
        options={[
          { value: "a", title: "[Ƒŕéé]", summary: "[1 ŕûļé]", badges: [{ text: "[Ðéƒåûļţ]" }], note: { text: "[Ŵîţĥîñ]" } },
          { value: "b", title: "[Þŕö]" },
        ]}
        onValueChange={vi.fn()}
      />,
    )
    expect(untranslatedText(container)).toEqual([])
  })
})
