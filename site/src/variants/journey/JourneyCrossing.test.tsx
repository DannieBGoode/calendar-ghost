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

  it("can show its pause control as an icon button, still named in words", () => {
    const compact = renderToString(<JourneyCrossing m={copy} plan={journeyDentist(en)} avatars={avatars} compactToggle />)
    expect(compact).toMatch(/class="motion-toggle is-compact" hidden=""/)
    expect(compact).toContain(`<span class="sr-only">${en.motion.pause}</span>`)
  })

  it("shows Work from 13:00 to 17:00 and the full card unless a page asks for less", () => {
    expect(html.match(/class="jc-hour"/g)).toHaveLength(4)
    expect(html).not.toContain("--jc-hours")
    expect(html).toContain(journeyDentist(en).description)
    expect(html).toContain("speech-bubble")

    const calm = renderToString(
      <JourneyCrossing m={copy} plan={journeyDentist(en)} avatars={avatars} hours={{ from: 14, to: 17 }} rows={["time", "place"]} says={false} once />,
    )
    // Three hours around the Dentist (15:00 to 16:30), the slot an hour down from the top.
    expect(calm.match(/class="jc-hour"/g)).toHaveLength(3)
    expect(calm).toContain("--jc-hours:3")
    expect(calm).toContain("--from:1;")
    expect(calm).not.toContain(">13:00<")
    // Sam's card keeps its time and place and drops the description (which still lands on Work
    // with details, as Details Projection says); the ghost says nothing.
    const card = calm.slice(calm.indexOf('class="jc-source"'), calm.indexOf('class="jc-cal jc-to"'))
    expect(card).toContain("Mon 15:00–16:30")
    expect(card).toContain(en.demo.events.dentist.detail)
    expect(card).not.toContain(journeyDentist(en).description)
    expect(calm).not.toContain("speech-bubble")
    // The guest and the meeting link still hang under Sam's card.
    expect(card).toContain(en.crossing.guests)
    expect(card).toContain(en.crossing.link)
  })
})
