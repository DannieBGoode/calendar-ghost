import { act, useState } from "react"
import { createRoot } from "react-dom/client"
import { renderToString } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { en } from "../i18n/en"
import { MotionToggle } from "./MotionToggle"

function Harness() {
  const [paused, setPaused] = useState(false)
  return <MotionToggle paused={paused} onToggle={() => setPaused((value) => !value)} m={en.motion} />
}

describe("MotionToggle", () => {
  it("is hidden until JavaScript has run, since nothing loops before", () => {
    expect(renderToString(<Harness />)).toContain("hidden")
  })

  it("as an icon button, keeps its words as its name and its tooltip", () => {
    const html = renderToString(<MotionToggle paused={false} onToggle={() => {}} m={en.motion} compact />)
    expect(html).toContain("is-compact")
    expect(html).toContain(`title="${en.motion.pause}"`)
    expect(html).toContain(`<span class="sr-only">${en.motion.pause}</span>`)
  })

  it("pauses, then plays", async () => {
    ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    const container = document.createElement("div")
    document.body.append(container)
    const root = createRoot(container)
    await act(async () => root.render(<Harness />))
    const button = container.querySelector("button")!
    expect(button.hidden).toBe(false)
    expect(button.textContent).toBe(en.motion.pause)
    await act(async () => button.click())
    expect(button.textContent).toBe(en.motion.play)
    await act(async () => button.click())
    expect(button.textContent).toBe(en.motion.pause)
    await act(async () => root.unmount())
    container.remove()
  })
})
