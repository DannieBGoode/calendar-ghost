import { act } from "react"
import { createRoot } from "react-dom/client"
import { renderToString } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { en } from "../../i18n/en"
import { SameEventControls, holdSequence, replaySequence } from "./SameEventControls"

const m = { replay: en.variants.homeHeroes.sameEvent.replay, motion: en.motion }

/** Hero D's figure as the page renders it, with the controls inside. */
async function mount() {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const figure = document.createElement("figure")
  figure.className = "se"
  figure.dataset.playing = "true"
  const container = document.createElement("div")
  figure.append(container)
  document.body.append(figure)
  const root = createRoot(container)
  await act(async () => root.render(<SameEventControls m={m} />))
  const done = async () => {
    await act(async () => root.unmount())
    figure.remove()
  }
  return { figure, container, done }
}

/** A stand-in for a CSS animation: its name, and whether it was started over. */
function fakeAnimation(animationName: string, playState: AnimationPlayState = "finished") {
  return {
    animationName,
    playState,
    currentTime: 1800 as number | null,
    played: false,
    play() {
      this.played = true
      this.playState = "running"
    },
    pause() {
      this.playState = "paused"
    },
  }
}

describe("hero D's controls", () => {
  it("are hidden until JavaScript has run, since the sequence rests without it", () => {
    const html = renderToString(<SameEventControls m={m} />)
    expect(html.match(/hidden=""/g)).toHaveLength(2)
  })

  it("pause the figure, then play it, through data-playing", async () => {
    const { figure, container, done } = await mount()
    const pause = container.querySelector<HTMLButtonElement>(".motion-toggle")!
    expect(pause.hidden).toBe(false)
    await act(async () => pause.click())
    expect(figure.dataset.playing).toBe("false")
    expect(pause.textContent).toBe(en.motion.play)
    await act(async () => pause.click())
    expect(figure.dataset.playing).toBe("true")
    await done()
  })

  it("replay plays again, even after a pause", async () => {
    const { figure, container, done } = await mount()
    await act(async () => container.querySelector<HTMLButtonElement>(".motion-toggle")!.click())
    const replay = container.querySelector<HTMLButtonElement>(".se-replay")!
    expect(replay.hidden).toBe(false)
    expect(replay.textContent).toBe(m.replay)
    await act(async () => replay.click())
    expect(figure.dataset.playing).toBe("true")
    expect(container.querySelector(".motion-toggle")!.textContent).toBe(en.motion.pause)
    await done()
  })

  it("starts only the sequence's own animations over, not the ghost's blinking", () => {
    const sequence = fakeAnimation("se-gone")
    const blink = fakeAnimation("ghost-blink")
    const figure = { getAnimations: () => [sequence, blink] } as unknown as Element
    replaySequence(figure)
    expect(sequence).toMatchObject({ currentTime: 0, played: true })
    expect(blink).toMatchObject({ currentTime: 1800, played: false })
  })

  it("hold the running sequence and let it go on, but never start a finished part over", () => {
    const running = fakeAnimation("se-busy", "running")
    const finished = fakeAnimation("se-tick")
    const blink = fakeAnimation("ghost-blink", "running")
    const figure = { getAnimations: () => [running, finished, blink] } as unknown as Element
    holdSequence(figure, true)
    expect(running.playState).toBe("paused")
    expect(blink.playState).toBe("running")
    holdSequence(figure, false)
    expect(running.playState).toBe("running")
    expect(finished).toMatchObject({ playState: "finished", played: false })
  })
})
