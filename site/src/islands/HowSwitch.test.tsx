import { act } from "react"
import { createRoot } from "react-dom/client"
import { describe, expect, it } from "vitest"
import { en } from "../i18n/en"
import { HowSwitch } from "./HowSwitch"

const avatars = { personal: "/personal.webp", family: "/family.webp", work: "/work.webp" }

describe("HowSwitch", () => {
  it("defaults to Busy only, and switching to With details changes the preview", async () => {
    ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    const container = document.createElement("ol")
    document.body.append(container)
    const root = createRoot(container)
    await act(async () =>
      root.render(
        <HowSwitch m={{ crossing: en.crossing, demo: en.demo, how: en.how, howStrip: en.howStrip }} avatars={avatars} />,
      ),
    )

    const [busy, details] = Array.from(container.querySelectorAll("button"))
    expect(busy?.getAttribute("aria-pressed")).toBe("true")
    expect(details?.getAttribute("aria-pressed")).toBe("false")
    const previewText = () => Array.from(container.querySelectorAll(".how-preview-row")).map((row) => row.textContent)
    expect(previewText()).toEqual([
      `${en.demo.busy}Mon 3:00 PM`,
      `${en.demo.busy}Tue 12:00 PM`,
      `${en.demo.busy}Thu 1:00 PM`,
    ])

    await act(async () => details?.click())
    expect(details?.getAttribute("aria-pressed")).toBe("true")
    expect(busy?.getAttribute("aria-pressed")).toBe("false")
    expect(previewText()).toEqual([
      `${en.demo.events.dentist.title}Mon 3:00 PM`,
      `${en.demo.events.gym.title}Tue 12:00 PM`,
      `${en.demo.events.therapy.title}Thu 1:00 PM`,
    ])

    await act(async () => root.unmount())
    container.remove()
  })
})
