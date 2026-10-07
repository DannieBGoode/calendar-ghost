import { act } from "react"
import { createRoot } from "react-dom/client"
import { renderToString } from "react-dom/server"
import { afterEach, describe, expect, it, vi } from "vitest"
import { en } from "../i18n/en"
import { HubControls, replayLoop } from "./HubControls"

const m = {
  views: { work: en.demo.workSees, you: en.demo.youSee },
  viewLabel: en.hero.diagram.viewLabel,
  motion: en.motion,
  replay: en.hero.diagram.replay,
}

/** Stands in for the browser's IntersectionObserver, so a test can move the figure on and off screen. */
let report: ((entries: { isIntersecting: boolean }[]) => void) | undefined
class FakeObserver {
  constructor(callback: (entries: { isIntersecting: boolean }[]) => void) {
    report = callback
  }
  observe() {}
  disconnect() {}
}

/** A stand-in for a CSS animation: its name and its clock. */
const fakeAnimation = (animationName: string) => ({ animationName, currentTime: 1800 as number | null })

/** The hero's figure as the page renders it, with the controls inside. */
async function mount(animations: ReturnType<typeof fakeAnimation>[] = []) {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const figure = document.createElement("figure")
  figure.className = "hc"
  figure.dataset.playing = "true"
  figure.dataset.view = "work"
  Object.assign(figure, { getAnimations: () => animations })
  const container = document.createElement("div")
  figure.append(container)
  document.body.append(figure)
  const root = createRoot(container)
  await act(async () => root.render(<HubControls m={m} />))
  const done = async () => {
    await act(async () => root.unmount())
    figure.remove()
  }
  const button = (name: string) => [...container.querySelectorAll("button")].find((item) => item.textContent === name)!
  return { figure, button, done }
}

afterEach(() => {
  vi.unstubAllGlobals()
  report = undefined
})

describe("the home hero diagram's controls", () => {
  it("are hidden until JavaScript has run, since the diagram rests on its final state, as work sees it, without it", () => {
    expect(renderToString(<HubControls m={m} />)).toContain('hidden=""')
  })

  it("switch the day between what work sees and what Sam sees, through data-view and aria-pressed", async () => {
    const { figure, button, done } = await mount()
    expect(figure.hasAttribute("data-enhanced")).toBe(true)
    expect(button(m.views.work).getAttribute("aria-pressed")).toBe("true")
    await act(async () => button(m.views.you).click())
    expect(figure.dataset.view).toBe("you")
    expect(button(m.views.you).getAttribute("aria-pressed")).toBe("true")
    expect(button(m.views.work).getAttribute("aria-pressed")).toBe("false")
    await act(async () => button(m.views.work).click())
    expect(figure.dataset.view).toBe("work")
    await done()
  })

  it("pause the loop and play it again through data-playing, with short words and full names", async () => {
    const { figure, button, done } = await mount()
    const pause = button(en.motion.pauseShort)
    expect(pause.getAttribute("aria-label")).toBe(en.motion.pause)
    await act(async () => pause.click())
    expect(figure.dataset.playing).toBe("false")
    expect(button(en.motion.playShort).getAttribute("aria-label")).toBe(en.motion.play)
    await act(async () => button(en.motion.playShort).click())
    expect(figure.dataset.playing).toBe("true")
    await done()
  })

  it("start the cycle over with Replay, and play it if it was paused", async () => {
    const own = fakeAnimation("hc-wide-chip-0")
    const { figure, button, done } = await mount([own])
    await act(async () => button(en.motion.pauseShort).click())
    await act(async () => button(m.replay).click())
    expect(own.currentTime).toBe(0)
    expect(figure.dataset.playing).toBe("true")
    await done()
  })

  it("hold the loop while the diagram is off screen", async () => {
    vi.stubGlobal("IntersectionObserver", FakeObserver)
    const { figure, done } = await mount()
    act(() => report!([{ isIntersecting: false }]))
    expect(figure.hasAttribute("data-offscreen")).toBe(true)
    act(() => report!([{ isIntersecting: true }]))
    expect(figure.hasAttribute("data-offscreen")).toBe(false)
    await done()
  })

  it("start over only the diagram's own animations", () => {
    const own = fakeAnimation("hc-tall-block-1")
    const other = fakeAnimation("ghost-blink")
    replayLoop({ getAnimations: () => [own, other] } as unknown as Element)
    expect(own.currentTime).toBe(0)
    expect(other.currentTime).toBe(1800)
  })
})
