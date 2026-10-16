/* @vitest-environment happy-dom */

import { Clock, Zap } from "lucide-react"
import { act, useState } from "react"
import { createRoot, type Root } from "react-dom/client"
import { afterEach, describe, expect, it, vi } from "vitest"

import { untranslatedText } from "@/i18n/testing"

import { RadioCards } from "./radio-cards"

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Speed = "instant" | "5m"

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

const SPEEDS = [
  {
    value: "instant",
    title: "Instant",
    description: "Changes sync soon after the calendar provider reports them.",
    icon: <Zap aria-hidden="true" />,
  },
  {
    value: "5m",
    title: "Every 5 minutes",
    description: "Calendars are checked for changes every 5 minutes.",
    icon: <Clock aria-hidden="true" />,
  },
] as const

function Harness({ pending = false, onChange = vi.fn() }: { pending?: boolean; onChange?: (value: Speed) => void }) {
  const [value, setValue] = useState<Speed>("instant")
  return (
    <>
      <h3 id="speed-label">Sync speed</h3>
      <RadioCards
        aria-labelledby="speed-label"
        value={value}
        options={SPEEDS}
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

/** The option whose title is `title`. */
function option(container: HTMLElement, title: string): HTMLInputElement {
  return radios(container).find((radio) => labelOf(radio).startsWith(title))!
}

/** The text of the elements an element's `attribute` names by id, in order. */
function referenced(element: Element, attribute: string): string[] {
  const ids = element.getAttribute(attribute)?.split(" ").filter(Boolean) ?? []
  return ids.map((id) => document.getElementById(id)?.textContent ?? "")
}

/** The text of the labels an input is labelled by. */
function labelOf(input: HTMLInputElement): string {
  return [...(input.labels ?? [])].map((label) => label.textContent).join(" ")
}

describe("RadioCards", () => {
  it("is one radio group named by its label, each card a native radio named by its title and described by its sentence", () => {
    const container = render(<Harness />)
    const group = container.querySelector("[role='radiogroup']")!
    expect(referenced(group, "aria-labelledby")).toEqual(["Sync speed"])
    const instant = option(container, "Instant")
    const fiveMinutes = option(container, "Every 5 minutes")
    expect(radios(container)).toEqual([instant, fiveMinutes])
    expect(labelOf(instant)).toBe("Instant")
    expect(referenced(instant, "aria-describedby")).toEqual(["Changes sync soon after the calendar provider reports them."])
    expect(labelOf(fiveMinutes)).toBe("Every 5 minutes")
    expect(instant.checked).toBe(true)
    expect(fiveMinutes.checked).toBe(false)
  })

  it("shares one name, so the arrow keys move the choice and Tab stops once, as a native radio group does", () => {
    const container = render(<Harness />)
    const instant = option(container, "Instant")
    const fiveMinutes = option(container, "Every 5 minutes")
    expect(instant.name).not.toBe("")
    expect(fiveMinutes.name).toBe(instant.name)
  })

  it("chooses the card that is pressed", () => {
    const onChange = vi.fn()
    const container = render(<Harness onChange={onChange} />)
    act(() => option(container, "Every 5 minutes").click())
    expect(onChange).toHaveBeenCalledWith("5m")
    expect(option(container, "Every 5 minutes").checked).toBe(true)
    expect(option(container, "Instant").checked).toBe(false)
  })

  it("keeps a choice that cannot be made visible, with why, and out of reach", () => {
    const onChange = vi.fn()
    const container = render(
      <RadioCards
        aria-label="Change plan"
        value={null}
        options={[
          { value: "free", title: "Free", description: "1 active rule", unavailable: "Current" },
          { value: "pro", title: "Pro", description: "No limits" },
        ]}
        onValueChange={onChange}
      />,
    )
    const free = option(container, "Free")
    const pro = option(container, "Pro")
    expect(free.disabled).toBe(true)
    expect(labelOf(free)).toBe("Free Current")
    expect(pro.disabled).toBe(false)
    expect(free.checked || pro.checked).toBe(false)
    act(() => free.click())
    expect(onChange).not.toHaveBeenCalledWith("free")
  })

  it("keeps focus and ignores choices while a command is on its way", () => {
    const onChange = vi.fn()
    const container = render(<Harness pending onChange={onChange} />)
    const instant = option(container, "Instant")
    const fiveMinutes = option(container, "Every 5 minutes")
    expect(instant.getAttribute("aria-disabled")).toBe("true")
    act(() => fiveMinutes.focus())
    act(() => fiveMinutes.click())
    expect(onChange).not.toHaveBeenCalled()
    expect(option(container, "Instant").checked).toBe(true)
    expect(document.activeElement).toBe(option(container, "Every 5 minutes"))
  })

  it("shows only the words it is given", () => {
    const container = render(
      <RadioCards
        aria-label="[Ŝýñç šþééð]"
        value="a"
        options={[
          { value: "a", title: "[Îñšţåñţ]", description: "[Çĥåñĝéš]" },
          { value: "b", title: "[Éṽéŕý 5 ɱîñûţéš]", unavailable: "[Çûŕŕéñţ]" },
        ]}
        onValueChange={vi.fn()}
      />,
    )
    expect(untranslatedText(container)).toEqual([])
  })
})
