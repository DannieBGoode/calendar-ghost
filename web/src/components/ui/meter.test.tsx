/* @vitest-environment happy-dom */

import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { Meter } from "./meter"

/** The rendered meter: its native element, which carries the role, and the drawn bar beside it. */
function rendered(element: React.ReactElement): { meter: HTMLMeterElement; root: HTMLElement; fill: HTMLElement } {
  const container = document.createElement("div")
  container.innerHTML = renderToStaticMarkup(element)
  const root = container.firstElementChild as HTMLElement
  return {
    meter: root.querySelector("meter")!,
    root,
    fill: root.querySelector<HTMLElement>("[data-meter-fill]")!,
  }
}

describe("Meter", () => {
  it("is a native meter named by its label, with its numbers in words", () => {
    const { meter, fill } = rendered(<Meter aria-label="Active rules" value={1} max={3} valueText="1 of 3" />)
    expect(meter.getAttribute("aria-label")).toBe("Active rules")
    expect(meter.getAttribute("min")).toBe("0")
    expect(meter.getAttribute("max")).toBe("3")
    expect(meter.getAttribute("value")).toBe("1")
    expect(meter.getAttribute("aria-valuetext")).toBe("1 of 3")
    expect(fill.style.width).toBe("33.33%")
  })

  it("draws its bar for sight only, so the meter is announced once", () => {
    const { meter, fill } = rendered(<Meter aria-label="Active rules" value={1} max={3} valueText="1 of 3" />)
    expect(fill.closest("[aria-hidden='true']")).not.toBeNull()
    expect(meter.closest("[aria-hidden='true']")).toBeNull()
  })

  it("is full and neutral at the limit", () => {
    const { root, fill } = rendered(<Meter aria-label="Active rules" value={1} max={1} valueText="1 of 1, limit reached" />)
    expect(fill.style.width).toBe("100%")
    expect(root.getAttribute("data-tone")).toBe("neutral")
  })

  it("holds its value at the limit past it, and says the real count in its text", () => {
    const { meter, root, fill } = rendered(
      <Meter aria-label="Calendar accounts" value={2} max={1} tone="over" valueText="2 of 1, over the limit" />,
    )
    expect(meter.getAttribute("value")).toBe("1")
    expect(meter.getAttribute("max")).toBe("1")
    expect(meter.getAttribute("aria-valuetext")).toBe("2 of 1, over the limit")
    expect(root.getAttribute("data-tone")).toBe("over")
    expect(fill.style.width).toBe("100%")
  })

  it("stays neutral past a limit nobody enforces, as while Plans are off", () => {
    const { root } = rendered(<Meter aria-label="Calendar accounts" value={2} max={1} valueText="2 of 1, would be over" />)
    expect(root.getAttribute("data-tone")).toBe("neutral")
  })

  it("is empty with nothing in use, and never divides by a limit of zero", () => {
    expect(rendered(<Meter aria-label="Active rules" value={0} max={2} valueText="0 of 2" />).fill.style.width).toBe("0%")
    const none = rendered(<Meter aria-label="Integration Tokens" value={0} max={0} valueText="0 of 0" />)
    expect(none.fill.style.width).toBe("0%")
    expect(none.meter.getAttribute("max")).toBe("1")
    expect(none.meter.getAttribute("value")).toBe("0")
    const over = rendered(<Meter aria-label="Integration Tokens" value={1} max={0} valueText="1 of 0" />)
    expect(over.fill.style.width).toBe("100%")
    expect(over.meter.getAttribute("value")).toBe("1")
  })

  it("can be named by the row it measures", () => {
    const { meter } = rendered(<Meter aria-labelledby="rules-name" value={1} max={1} valueText="1 of 1" />)
    expect(meter.getAttribute("aria-labelledby")).toBe("rules-name")
  })
})
