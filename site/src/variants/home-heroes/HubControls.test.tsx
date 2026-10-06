import { act } from "react"
import { createRoot } from "react-dom/client"
import { renderToString } from "react-dom/server"
import { afterEach, describe, expect, it, vi } from "vitest"
import { en } from "../../i18n/en"
import { HubControls, holdRun, replayRun } from "./HubControls"

const m = {
  views: { work: en.demo.workSees, you: en.demo.youSee },
  viewLabel: en.variants.homeHeroes.hub.viewLabel,
  replay: en.variants.homeHeroes.hub.replay,
  motion: en.motion,
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

/** A stand-in for a CSS animation: its name, its state, and a `finished` promise a test resolves. */
function fakeAnimation(animationName: string, playState: AnimationPlayState = "running") {
  let finish = () => {}
  const animation = {
    animationName,
    playState,
    currentTime: 1800 as number | null,
    played: false,
    finished: Promise.resolve() as Promise<unknown>,
    play() {
      this.played = true
      this.playState = "running"
      this.finished = new Promise((resolve) => (finish = () => resolve(undefined)))
    },
    pause() {
      this.playState = "paused"
    },
    finish: () => finish(),
  }
  animation.finished = new Promise((resolve) => (finish = () => resolve(undefined)))
  return animation
}

/** Hero E3's figure as the page renders it, with the controls inside. */
async function mount(animations: ReturnType<typeof fakeAnimation>[] = []) {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const figure = document.createElement("figure")
  figure.className = "hb"
  figure.dataset.playing = "true"
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

describe("hero E3's controls", () => {
  it("are hidden until JavaScript has run, since the diagram rests on its final state, as work sees it, without it", () => {
    expect(renderToString(<HubControls m={m} />)).toContain('hidden=""')
  })

  it("switch Work's day between what work sees and what Sam sees, through data-view and aria-pressed", async () => {
    const { figure, button, done } = await mount()
    expect(figure.hasAttribute("data-enhanced")).toBe(true)
    expect(figure.dataset.view).toBe("work")
    expect(button(m.views.work).getAttribute("aria-pressed")).toBe("true")
    await act(async () => button(m.views.you).click())
    expect(figure.dataset.view).toBe("you")
    expect(button(m.views.you).getAttribute("aria-pressed")).toBe("true")
    expect(button(m.views.work).getAttribute("aria-pressed")).toBe("false")
    await act(async () => button(m.views.work).click())
    expect(figure.dataset.view).toBe("work")
    await done()
  })

  it("pause the run, then play it, through data-playing and the animations themselves", async () => {
    const run = fakeAnimation("hb-travel-in")
    const { figure, button, done } = await mount([run])
    await act(async () => button(en.motion.pause).click())
    expect(figure.dataset.playing).toBe("false")
    expect(run.playState).toBe("paused")
    await act(async () => button(en.motion.play).click())
    expect(figure.dataset.playing).toBe("true")
    expect(run.playState).toBe("running")
    await done()
  })

  it("keep Replay beside Pause; once the run has rested Pause has nothing to hold, and Replay starts it over", async () => {
    const run = fakeAnimation("hb-travel-in")
    const { button, done } = await mount([run])
    expect(button(m.replay)).toBeDefined()
    await act(async () => {
      run.playState = "finished"
      run.finish()
    })
    expect(button(en.motion.pause).disabled).toBe(true)
    await act(async () => button(m.replay).click())
    expect(run).toMatchObject({ currentTime: 0, played: true, playState: "running" })
    expect(button(en.motion.pause).disabled).toBe(false)
    await done()
  })

  it("hold the run while the diagram is off screen", async () => {
    vi.stubGlobal("IntersectionObserver", FakeObserver)
    const run = fakeAnimation("hb-land")
    const { figure, done } = await mount([run])
    act(() => report!([{ isIntersecting: false }]))
    expect(figure.hasAttribute("data-offscreen")).toBe(true)
    expect(run.playState).toBe("paused")
    act(() => report!([{ isIntersecting: true }]))
    expect(figure.hasAttribute("data-offscreen")).toBe(false)
    expect(run.playState).toBe("running")
    await done()
  })

  it("touch only the diagram's own animations, and never start a finished one over by holding", () => {
    const own = fakeAnimation("hb-travel-in")
    const finished = fakeAnimation("hb-land", "finished")
    const other = fakeAnimation("ghost-blink")
    const figure = { getAnimations: () => [own, finished, other] } as unknown as Element
    holdRun(figure, true)
    expect(own.playState).toBe("paused")
    expect(other.playState).toBe("running")
    holdRun(figure, false)
    expect(own.playState).toBe("running")
    expect(finished).toMatchObject({ playState: "finished", played: false })
    replayRun(figure)
    expect(own).toMatchObject({ currentTime: 0, played: true })
    expect(other).toMatchObject({ currentTime: 1800, played: false })
  })
})
