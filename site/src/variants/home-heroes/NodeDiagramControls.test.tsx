import { act } from "react"
import { createRoot } from "react-dom/client"
import { renderToString } from "react-dom/server"
import { afterEach, describe, expect, it, vi } from "vitest"
import { en } from "../../i18n/en"
import { NodeDiagramControls } from "./NodeDiagramControls"

/** Stands in for the browser's IntersectionObserver, so a test can move the figure on and off screen. */
let report: ((entries: { isIntersecting: boolean }[]) => void) | undefined
class FakeObserver {
  constructor(callback: (entries: { isIntersecting: boolean }[]) => void) {
    report = callback
  }
  observe() {}
  disconnect() {}
}

/** Hero E's figure as the page renders it, with the controls inside. */
async function mount() {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const figure = document.createElement("figure")
  figure.className = "nd"
  figure.dataset.playing = "true"
  const container = document.createElement("div")
  figure.append(container)
  document.body.append(figure)
  const root = createRoot(container)
  await act(async () => root.render(<NodeDiagramControls m={en.motion} />))
  const done = async () => {
    await act(async () => root.unmount())
    figure.remove()
  }
  return { figure, container, done }
}

afterEach(() => {
  vi.unstubAllGlobals()
  report = undefined
})

describe("hero E's controls", () => {
  it("are hidden until JavaScript has run, since nothing moves without it", () => {
    expect(renderToString(<NodeDiagramControls m={en.motion} />)).toContain('hidden=""')
  })

  it("pause the diagram, then play it, through data-playing", async () => {
    const { figure, container, done } = await mount()
    const toggle = container.querySelector<HTMLButtonElement>(".motion-toggle")!
    expect(toggle.hidden).toBe(false)
    await act(async () => toggle.click())
    expect(figure.dataset.playing).toBe("false")
    expect(toggle.textContent).toBe(en.motion.play)
    await act(async () => toggle.click())
    expect(figure.dataset.playing).toBe("true")
    await done()
  })

  it("mark the diagram while it is off screen, so its loop holds", async () => {
    vi.stubGlobal("IntersectionObserver", FakeObserver)
    const { figure, done } = await mount()
    expect(report).toBeDefined()
    act(() => report!([{ isIntersecting: false }]))
    expect(figure.hasAttribute("data-offscreen")).toBe(true)
    act(() => report!([{ isIntersecting: true }]))
    expect(figure.hasAttribute("data-offscreen")).toBe(false)
    await done()
  })
})
