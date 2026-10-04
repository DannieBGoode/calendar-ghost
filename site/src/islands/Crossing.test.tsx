import { act } from "react"
import { createRoot } from "react-dom/client"
import { describe, expect, it } from "vitest"
import { en } from "../i18n/en"
import { Crossing } from "./Crossing"

describe("Crossing", () => {
  it("switches between Busy only and With details", async () => {
    ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    const container = document.createElement("div")
    document.body.append(container)
    const root = createRoot(container)
    await act(async () => root.render(<Crossing m={{ crossing: en.crossing, demo: en.demo }} />))

    const [busy, details] = Array.from(container.querySelectorAll("button"))
    expect(busy?.getAttribute("aria-pressed")).toBe("true")
    expect(container.textContent).toContain(en.crossing.busyOnlyBody)

    await act(async () => details?.click())
    expect(details?.getAttribute("aria-pressed")).toBe("true")
    expect(container.querySelector(".crossing")?.getAttribute("data-mode")).toBe("details")
    expect(container.textContent).toContain(en.crossing.withDetailsBody)

    await act(async () => root.unmount())
    container.remove()
  })
})
