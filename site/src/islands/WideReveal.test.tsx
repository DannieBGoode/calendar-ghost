import { act } from "react"
import { createRoot } from "react-dom/client"
import { renderToString } from "react-dom/server"
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { en } from "../i18n/en"
import { WideReveal } from "./WideReveal"

describe("WideReveal", () => {
  it("renders at rest with both views when JavaScript has not run", () => {
    const html = renderToString(<WideReveal m={en.demo} />)
    expect(html).toContain("--split:55%")
    expect(html).toContain(en.demo.youSee)
    expect(html).toContain(en.demo.workSees)
    // Work sees every personal plan only as Busy, and every work meeting by name.
    expect(html.split(`>${en.demo.busy}<`).length - 1).toBe(5)
    expect(html.split(`>${en.demo.events.standup.title}<`).length - 1).toBe(2)
    expect(html.split(`>${en.demo.events.dentist.title}<`).length - 1).toBe(1)
  })

  describe("in the browser", () => {
    let container: HTMLDivElement
    beforeEach(() => {
      container = document.createElement("div")
      document.body.append(container)
      ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    })
    afterEach(() => container.remove())

    it("holds the position a visitor picks with the slider", async () => {
      const root = createRoot(container)
      await act(async () => root.render(<WideReveal m={en.demo} />))
      const slider = container.querySelector<HTMLInputElement>("input[type=range]")!
      expect(slider.getAttribute("aria-label")).toBe(en.demo.sliderLabel)

      await act(async () => {
        const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!
        setValue.call(slider, "30")
        slider.dispatchEvent(new Event("input", { bubbles: true }))
      })

      const frame = container.querySelector<HTMLElement>(".reveal-frame")!
      expect(frame.style.getPropertyValue("--split")).toBe("30%")
      expect(slider.getAttribute("aria-valuetext")).toBe("30% of the week shows your view")
      await act(async () => root.unmount())
    })
  })
})
