import { act } from "react"
import { createRoot } from "react-dom/client"
import { renderToString } from "react-dom/server"
import { afterEach, describe, expect, it, vi } from "vitest"
import { en } from "../../i18n/en"
import { ConsolidationControls, holdRun, replayRun } from "./ConsolidationControls"

const m = { replay: en.variants.homeHeroes.consolidation.replay, motion: en.motion }

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

/** Hero E2's figure as the page renders it, with the controls inside. */
async function mount(animations: ReturnType<typeof fakeAnimation>[] = []) {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const figure = document.createElement("figure")
  figure.className = "cn"
  figure.dataset.playing = "true"
  Object.assign(figure, { getAnimations: () => animations })
  const container = document.createElement("div")
  figure.append(container)
  document.body.append(figure)
  const root = createRoot(container)
  await act(async () => root.render(<ConsolidationControls m={m} />))
  const done = async () => {
    await act(async () => root.unmount())
    figure.remove()
  }
  return { figure, button: container.querySelector<HTMLButtonElement>("button")!, done }
}

afterEach(() => {
  vi.unstubAllGlobals()
  report = undefined
})

describe("hero E2's control", () => {
  it("is hidden until JavaScript has run, since the diagram rests on its final state without it", () => {
    expect(renderToString(<ConsolidationControls m={m} />)).toContain('hidden=""')
  })

  it("pauses the run, then plays it, through data-playing and the animations themselves", async () => {
    const run = fakeAnimation("cn-travel")
    const { figure, button, done } = await mount([run])
    expect(button.hidden).toBe(false)
    expect(button.textContent).toBe(en.motion.pause)
    await act(async () => button.click())
    expect(figure.dataset.playing).toBe("false")
    expect(run.playState).toBe("paused")
    expect(button.textContent).toBe(en.motion.play)
    await act(async () => button.click())
    expect(figure.dataset.playing).toBe("true")
    expect(run.playState).toBe("running")
    await done()
  })

  it("turns into Replay once the run has rested, and Replay starts it over", async () => {
    const run = fakeAnimation("cn-travel")
    const { button, done } = await mount([run])
    await act(async () => {
      run.playState = "finished"
      run.finish()
    })
    expect(button.textContent).toBe(m.replay)
    await act(async () => button.click())
    expect(run).toMatchObject({ currentTime: 0, played: true, playState: "running" })
    expect(button.textContent).toBe(en.motion.pause)
    await done()
  })

  it("holds the run while the diagram is off screen", async () => {
    vi.stubGlobal("IntersectionObserver", FakeObserver)
    const run = fakeAnimation("cn-appear")
    const { figure, done } = await mount([run])
    act(() => report!([{ isIntersecting: false }]))
    expect(figure.hasAttribute("data-offscreen")).toBe(true)
    expect(run.playState).toBe("paused")
    act(() => report!([{ isIntersecting: true }]))
    expect(figure.hasAttribute("data-offscreen")).toBe(false)
    expect(run.playState).toBe("running")
    await done()
  })

  it("touches only the diagram's own animations, and never starts a finished one over by holding", () => {
    const own = fakeAnimation("cn-travel")
    const finished = fakeAnimation("cn-appear", "finished")
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
