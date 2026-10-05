import { act } from "react"
import { createRoot } from "react-dom/client"
import { renderToString } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { en } from "../i18n/en"
import { Crossing } from "./Crossing"

const m = { crossing: en.crossing, demo: en.demo, motion: en.motion }

describe("Crossing", () => {
  it("switches between Busy only and With details", async () => {
    ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    const container = document.createElement("div")
    document.body.append(container)
    const root = createRoot(container)
    await act(async () => root.render(<Crossing m={m} />))

    const [busy, details] = Array.from(container.querySelectorAll(".crossing-switch button"))
    expect(busy?.getAttribute("aria-pressed")).toBe("true")
    expect(container.textContent).toContain(en.crossing.busyOnlyBody)

    await act(async () => (details as HTMLButtonElement | undefined)?.click())
    expect(details?.getAttribute("aria-pressed")).toBe("true")
    expect(container.querySelector(".crossing")?.getAttribute("data-mode")).toBe("details")
    expect(container.textContent).toContain(en.crossing.withDetailsBody)
    // Details Projection: the title and place land on Work, and Busy does not.
    const landed = container.querySelector(".crossing-landed")!
    expect(landed.querySelector(".crossing-landed-title")?.getAttribute("data-crosses")).toBe("true")
    expect(landed.querySelector(".crossing-landed-place")?.getAttribute("data-crosses")).toBe("true")
    expect(landed.querySelector(".crossing-landed-busy")?.getAttribute("data-crosses")).toBe("false")

    await act(async () => root.unmount())
    container.remove()
  })

  it("lands Busy-Only on Work: only the time, titled Busy", () => {
    const html = document.createElement("div")
    html.innerHTML = renderToString(<Crossing m={m} />)
    const landed = html.querySelector(".crossing-landed")!
    expect(landed.querySelector(".crossing-landed-busy")?.textContent).toBe(en.demo.busy)
    expect(landed.querySelector(".crossing-landed-busy")?.getAttribute("data-crosses")).toBe("true")
    expect(landed.querySelector(".crossing-landed-title")?.getAttribute("data-crosses")).toBe("false")
    expect(landed.querySelector(".crossing-landed-place")?.getAttribute("data-crosses")).toBe("false")
    expect(landed.querySelector(".crossing-landed-time")?.textContent).toBe("15:00–16:30")
    // On the server there is no run yet: the CSS shows the landed state (or the run's first frame).
    expect(html.querySelector(".crossing")?.hasAttribute("data-run")).toBe(false)
  })

  it("keeps everything that never crosses over on the Personal card, each with its icon, for everyone to read", () => {
    const html = document.createElement("div")
    html.innerHTML = renderToString(<Crossing m={m} />)
    const stays = html.querySelector(".crossing-personal .crossing-stays")!
    expect(stays.closest("[aria-hidden]")).toBeNull()
    expect(stays.querySelector("h3")?.textContent).toBe(en.crossing.alwaysStaysTitle)
    const items = Array.from(stays.querySelectorAll("li"))
    expect(items.map((item) => item.textContent?.trim())).toEqual([...en.crossing.alwaysStays])
    for (const item of items) expect(item.querySelector("svg")).not.toBeNull()
    // None of them is on the copy that lands on Work.
    const landed = html.querySelector(".crossing-landed")!.textContent ?? ""
    for (const item of en.crossing.alwaysStays) expect(landed).not.toContain(item)
  })
})
