import { renderToString } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { en } from "../../i18n/en"
import { JourneyCrossing } from "./JourneyCrossing"
import { journeyDentist } from "./plans"

const avatars = { personal: "/p.webp", family: "/f.webp", work: "/w.webp" }
const copy = {
  switchLabel: en.crossing.switchLabel,
  busyOnly: en.crossing.busyOnly,
  withDetails: en.crossing.withDetails,
  busyOnlyBody: en.crossing.busyOnlyBody,
  withDetailsBody: en.crossing.withDetailsBody,
  peel: en.variants.journey.crossing.peel,
  busySays: en.ghost.crossingBusy,
  detailsSays: en.ghost.crossingDetails,
  busy: en.demo.busy,
  summary: en.crossing.summary,
  day: en.demo.days[0],
  calendars: en.demo.calendars,
  motion: en.motion,
}

describe("JourneyCrossing before JavaScript runs", () => {
  const html = renderToString(<JourneyCrossing m={copy} plan={journeyDentist(en)} avatars={avatars} />)

  it("offers what crosses over as real radio buttons, Busy only picked", () => {
    expect(html.match(/type="radio" name="jc-mode"/g)).toHaveLength(2)
    expect(html).toMatch(/name="jc-mode" checked="" value="busy"/)
  })

  it("shows the Dentist from 15:00 to 16:30, as the home page's Crossing does", () => {
    expect(html).toContain("Mon 15:00–16:30")
  })

  it("renders both landed results, for CSS to show the one picked", () => {
    expect(html).toContain('data-mode="busy"><span>Busy</span>')
    expect(html).toContain(`data-mode="details"><span>${en.demo.events.dentist.title}</span>`)
  })

  it("says what happens in words for screen readers", () => {
    expect(html).toContain("moves from the Personal calendar to the Work calendar")
  })

  it("has no pause control until it has hydrated", () => {
    expect(html).toMatch(/class="motion-toggle" hidden=""/)
  })
})
