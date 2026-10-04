import { act } from "react"
import { createRoot } from "react-dom/client"
import { renderToString } from "react-dom/server"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { en } from "../i18n/en"
import { LoopStage } from "./LoopStage"

describe("LoopStage", () => {
  it("rests without JavaScript: not playing, and no pause control to show", () => {
    const html = renderToString(
      <LoopStage motion={en.motion} className="scenes">
        <p>scene</p>
      </LoopStage>,
    )
    expect(html).toContain('class="loop-stage scenes"')
    expect(html).toContain('data-hydrated="false"')
    expect(html).toContain('data-playing="false"')
    expect(html).toContain("<p>scene</p>")
    expect(html).toMatch(/<button[^>]*hidden/)
  })

  describe("in the browser", () => {
    beforeEach(() => {
      ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
      // The stage is always in view here.
      vi.stubGlobal(
        "IntersectionObserver",
        class {
          constructor(private readonly callback: IntersectionObserverCallback) {}
          observe() {
            this.callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver)
          }
          disconnect() {}
        },
      )
    })
    afterEach(() => vi.unstubAllGlobals())

    it("plays once hydrated and in view, and its control pauses and resumes it", async () => {
      const container = document.createElement("div")
      document.body.append(container)
      const root = createRoot(container)
      await act(async () => root.render(<LoopStage motion={en.motion} />))
      const stage = container.querySelector<HTMLElement>(".loop-stage")!
      const button = container.querySelector("button")!
      expect(stage.dataset.hydrated).toBe("true")
      expect(stage.dataset.playing).toBe("true")
      expect(button.hidden).toBe(false)
      await act(async () => button.click())
      expect(stage.dataset.playing).toBe("false")
      expect(button.textContent).toBe(en.motion.play)
      await act(async () => button.click())
      expect(stage.dataset.playing).toBe("true")
      await act(async () => root.unmount())
      container.remove()
    })
  })
})
