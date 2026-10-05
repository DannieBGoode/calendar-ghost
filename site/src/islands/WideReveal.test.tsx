import { act } from "react"
import { createRoot } from "react-dom/client"
import { renderToString } from "react-dom/server"
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { en } from "../i18n/en"
import { WideReveal } from "./WideReveal"

describe("WideReveal", () => {
  it("renders at rest with both views when JavaScript has not run", () => {
    const html = renderToString(<WideReveal m={en.demo} motion={en.motion} />)
    expect(html).toContain("--split:55%")
    expect(html).toContain(en.demo.youSee)
    expect(html).toContain(en.demo.workSees)
    // Work sees every personal plan only as Busy, and every work meeting by name.
    expect(html.split(`>${en.demo.busy}<`).length - 1).toBe(5)
    expect(html.split(`>${en.demo.events.standup.title}<`).length - 1).toBe(2)
    expect(html.split(`>${en.demo.events.dentist.title}<`).length - 1).toBe(1)
  })

  it("keeps the default size unless a page asks for another", () => {
    const plain = renderToString(<WideReveal m={en.demo} motion={en.motion} />)
    expect(plain).not.toContain("--reveal-week-h")
    expect(plain).not.toContain("--handle-size")
    const big = renderToString(<WideReveal m={en.demo} motion={en.motion} weekHeight={520} handleSize={184} />)
    expect(big).toContain("--reveal-week-h:520px")
    expect(big).toContain("--handle-size:184px")
    // The week's events are laid out for the taller week: the Standup (10:00) sits lower.
    const standupTop = (html: string) => Number(html.match(/top:(\d+)px[^>]*><span>Standup/)?.[1])
    expect(standupTop(big)).toBeGreaterThan(standupTop(plain))
  })

  it("lays the week out a second time for phones when a page asks for a shorter one there", () => {
    const plain = renderToString(<WideReveal m={en.demo} motion={en.motion} weekHeight={520} />)
    expect(plain).not.toContain("--top-phone")
    expect(plain).not.toContain("--reveal-week-h-phone")
    const html = renderToString(
      <WideReveal m={en.demo} motion={en.motion} weekHeight={520} phoneWeekHeight={360} handleSize={184} phoneHandleSize={120} />,
    )
    expect(html).toContain("--reveal-week-h-phone:360px")
    expect(html).toContain("--handle-size-phone:120px")
    // The Standup (10:00) sits higher in the shorter phone week than in the wide one.
    const [, wide, phone] = html.match(/--top:(\d+)px;--h:\d+px;--top-phone:(\d+)px[^>]*><span>Standup/) ?? []
    expect(Number(phone)).toBeLessThan(Number(wide))
  })

  it("rests where a page asks, so the page reads right before it sweeps and without JavaScript", () => {
    const html = renderToString(<WideReveal m={en.demo} motion={en.motion} sweep={{ rest: 40, direction: "left", swing: 30 }} />)
    expect(html).toContain("--split:40%")
  })

  it("keeps its labels in the corners and its controls under the frame unless a page pins them to the divider", () => {
    const plain = renderToString(<WideReveal m={en.demo} motion={en.motion} />)
    expect(plain).toContain("reveal-tag-you")
    expect(plain).toContain("demo-foot")
    expect(plain).not.toContain("reveal-pins")
    expect(plain).not.toContain("data-labels")

    const hint = { mouse: "Move over the week", touch: "Drag the ghost" }
    const pinned = renderToString(<WideReveal m={en.demo} motion={en.motion} labels="divider" handleHint={hint} />)
    expect(pinned).toContain('data-labels="divider"')
    expect(pinned).not.toContain("reveal-tag")
    expect(pinned).not.toContain("demo-foot")
    // Both labels ride the divider, and the hint sits with the handle in both wordings.
    expect(pinned).toMatch(new RegExp(`reveal-pins.*${en.demo.youSee}.*${en.demo.workSees}`))
    expect(pinned).toMatch(new RegExp(`reveal-handle.*${hint.mouse}.*${hint.touch}`))
    // The pause control is an icon button inside the frame, still named in words.
    expect(pinned).toMatch(/class="reveal-frame".*class="motion-toggle is-compact".*<\/div><figcaption/)
    expect(pinned).toContain(`<span class="sr-only">${en.motion.pause}</span>`)
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
      await act(async () => root.render(<WideReveal m={en.demo} motion={en.motion} />))
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

    it("pins the position when the slider gains focus, so it does not drift for a keyboard user", async () => {
      const root = createRoot(container)
      await act(async () => root.render(<WideReveal m={en.demo} motion={en.motion} />))
      const slider = container.querySelector<HTMLInputElement>("input[type=range]")!
      const frame = container.querySelector<HTMLElement>(".reveal-frame")!

      await act(async () => {
        slider.focus()
      })

      const pinnedSplit = frame.style.getPropertyValue("--split")
      expect(pinnedSplit).toBe(`${slider.value}%`)
      expect(slider.getAttribute("aria-valuetext")).toBe(`${slider.value}% of the week shows your view`)

      // A later tick (where an in-progress sweep would otherwise move the value) must not move it.
      await act(async () => {})

      expect(frame.style.getPropertyValue("--split")).toBe(pinnedSplit)
      expect(slider.getAttribute("aria-valuetext")).toBe(`${slider.value}% of the week shows your view`)
      await act(async () => root.unmount())
    })

    it("startles the ghost when a visitor takes hold of it, then lets it enjoy the ride", async () => {
      const root = createRoot(container)
      await act(async () => root.render(<WideReveal m={en.demo} motion={en.motion} />))
      const ghost = () => container.querySelector(".reveal-handle .ghost")!.getAttribute("data-face")
      expect(ghost()).toBe("neutral")

      await act(async () => container.querySelector<HTMLInputElement>("input[type=range]")!.focus())
      expect(ghost()).toBe("surprised")

      await act(async () => new Promise((resolve) => setTimeout(resolve, 500)))
      expect(ghost()).toBe("happy")
      await act(async () => root.unmount())
    })

    it("says its line only while a visitor holds it", async () => {
      const root = createRoot(container)
      await act(async () => root.render(<WideReveal m={en.demo} motion={en.motion} heldSays="Wheee!" />))
      const bubble = () => container.querySelector(".reveal-says")?.textContent
      expect(bubble()).toBeUndefined()
      const slider = container.querySelector<HTMLInputElement>("input[type=range]")!
      await act(async () => slider.focus())
      expect(bubble()).toBe("Wheee!")
      await act(async () => slider.blur())
      expect(bubble()).toBeUndefined()
      await act(async () => root.unmount())
    })
  })
})
