import { describe, expect, it } from "vitest"
import { SAM_WEEK } from "../../demo/week"
import { en } from "../../i18n/en"
import {
  DEPARTS,
  HOURS,
  SEGMENT,
  SOURCES,
  SPEED,
  THROUGH_S,
  WORK_MEETINGS,
  buildDiagram,
  clock,
  dashFor,
  inWeekHours,
  type Diagram,
  type Leg,
} from "./consolidation"
import type { Box } from "./node-diagram"

const overlaps = (a: Box, b: Box) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
const inside = (box: Box, diagram: Diagram) =>
  box.x >= 0 && box.y >= 0 && box.x + box.width <= diagram.width && box.y + box.height <= diagram.height

/** Where a path starts and ends, read from its "M x y C ... x y" data. */
function ends(d: string) {
  const numbers = d.match(/-?\d+(\.\d+)?/g)!.map(Number)
  return { start: { x: numbers[0]!, y: numbers[1]! }, end: { x: numbers.at(-2)!, y: numbers.at(-1)! } }
}

describe("Sam's calendars and their one day", () => {
  it("are five calendars, each with one event, and portraits only where none repeats", () => {
    expect(SOURCES).toHaveLength(5)
    expect(SOURCES.map((source) => source.key)).toEqual(["personal", "family", "kidsSchool", "runningClub", "sideProject"])
    const portraits = SOURCES.flatMap((source) => (source.avatar ? [source.avatar] : []))
    expect(portraits).toEqual(["personal", "family"])
    expect(new Set(portraits).size).toBe(portraits.length)
  })

  it("agree with Sam's week: Monday's Dentist and Standup, and nothing else inside the week's hours", () => {
    const monday = SAM_WEEK.filter((event) => event.day === 0)
    const shown = [...SOURCES.map((source) => source.event), ...WORK_MEETINGS]
    for (const event of monday) {
      expect(shown.find((item) => item.key === event.key), event.key).toMatchObject({ start: event.start, end: event.end })
    }
    // The events the rest of the page does not show fall outside the hours its week shows.
    const extra = shown.filter((event) => !monday.some((item) => item.key === event.key))
    expect(extra).toHaveLength(4)
    for (const event of extra) expect(inWeekHours(event), event.key).toBe(false)
    expect(WORK_MEETINGS.map((event) => event.key)).toEqual(["standup"])
  })

  it("never overlap one another, and fit the hours the column shows", () => {
    const events = [...SOURCES.map((source) => source.event), ...WORK_MEETINGS].sort((a, b) => a.start - b.start)
    for (const [index, event] of events.entries()) {
      expect(event.start).toBeGreaterThanOrEqual(HOURS.start)
      expect(event.end).toBeLessThanOrEqual(HOURS.end)
      if (index > 0) expect(event.start).toBeGreaterThanOrEqual(events[index - 1]!.end)
    }
  })

  it("name every calendar and event in the copy", () => {
    const copy = en.variants.homeHeroes.consolidation
    for (const source of SOURCES) {
      const name = source.key === "personal" || source.key === "family" ? en.demo.calendars[source.key] : copy.calendars[source.key]
      expect(name, source.key).toBeTruthy()
      expect(copy.fact).toContain(name)
      const key = source.event.key
      expect(key === "dentist" || key === "standup" ? en.demo.events[key].title : copy.events[key], key).toBeTruthy()
    }
  })

  it("writes clock times as the rest of the page does", () => {
    expect(clock(7.5)).toBe("07:30")
    expect(clock(15)).toBe("15:00")
    expect(clock(18.5)).toBe("18:30")
  })
})

for (const kind of ["wide", "tall"] as const) {
  describe(`the ${kind} diagram`, () => {
    const diagram = buildDiagram(kind)
    const busy = diagram.slots.filter((slot) => slot.source)

    it("keeps every calendar inside the drawing, apart from the others", () => {
      expect(diagram.sources).toHaveLength(SOURCES.length)
      for (const [index, pill] of diagram.sources.entries()) {
        expect(inside(pill, diagram), pill.key).toBe(true)
        for (const other of diagram.sources.slice(index + 1)) expect(overlaps(pill, other), `${pill.key} ${other.key}`).toBe(false)
      }
      expect(inside(diagram.work, diagram)).toBe(true)
    })

    it("puts one Busy block in the Work column per calendar, at its event's time, beside Work's own meeting", () => {
      expect(busy.map((slot) => slot.source)).toEqual(SOURCES.map((source) => source.key))
      expect(diagram.slots.filter((slot) => !slot.source).map((slot) => slot.event.key)).toEqual(["standup"])
      const column = { top: diagram.work.y + diagram.work.header, bottom: diagram.work.y + diagram.work.height }
      for (const slot of diagram.slots) {
        expect(slot.x).toBeGreaterThan(diagram.work.x)
        expect(slot.x + slot.width).toBeLessThan(diagram.work.x + diagram.work.width)
        expect(slot.y).toBeGreaterThan(column.top)
        expect(slot.y + slot.height).toBeLessThan(column.bottom)
      }
      // Earlier is higher, and blocks never overlap.
      const byTime = [...diagram.slots].sort((a, b) => a.event.start - b.event.start)
      for (let index = 1; index < byTime.length; index += 1) expect(byTime[index]!.y).toBeGreaterThanOrEqual(byTime[index - 1]!.y + byTime[index - 1]!.height)
      // One hour is the same height everywhere in the column.
      const perHour = byTime.map((slot) => (slot.height + 2) / (slot.event.end - slot.event.start))
      for (const height of perHour) expect(height).toBeCloseTo(perHour[0]!, 5)
    })

    it("runs each calendar's segment into the ghost, then out as Busy to its block, which appears as it lands", () => {
      for (const source of SOURCES) {
        const [into, out] = [diagram.legs.find((leg) => leg.source === source.key && leg.side === "in")!, diagram.legs.find((leg) => leg.source === source.key && leg.side === "out")!]
        expect(into.delay).toBe(DEPARTS[source.key])
        expect(out.delay).toBeCloseTo(into.delay + into.length / SPEED + THROUGH_S, 5)
        const slot = busy.find((item) => item.source === source.key)!
        expect(slot.appears).toBeCloseTo(out.delay + out.length / SPEED, 2)
        for (const leg of [into, out]) expect(leg.duration).toBeCloseTo((leg.length + SEGMENT) / SPEED, 5)
      }
      expect(diagram.legs).toHaveLength(SOURCES.length * 2)
    })

    it("lands the first Busy block within three seconds (the visitor's first read), and keeps only a few segments in flight", () => {
      expect(Math.min(...busy.map((slot) => slot.appears!))).toBeLessThan(3)
      const inFlight = (time: number) => diagram.legs.filter((leg: Leg) => time >= leg.delay && time < leg.delay + leg.duration).length
      for (let time = 0; time < 12; time += 0.05) expect(inFlight(time), `${time.toFixed(2)}s`).toBeLessThanOrEqual(3)
    })

    it("keeps each segment out of sight before and after its run", () => {
      for (const leg of diagram.legs) {
        const dash = dashFor(leg)
        const [length, gap] = dash.dasharray.split(" ").map(Number)
        expect(length).toBe(SEGMENT)
        expect(gap).toBeGreaterThan(leg.length + SEGMENT)
        expect(dash.from).toBe(SEGMENT)
        expect(dash.to).toBeCloseTo(-leg.length, 1)
      }
    })

    it("draws one hairline from each calendar into the ghost", () => {
      for (const pill of diagram.sources) {
        const curve = diagram.curves.find((item) => item.id === `from-${pill.key}`)!
        const { start } = ends(curve.d)
        expect(start.y).toBeGreaterThan(pill.y)
        expect(start.y).toBeLessThan(pill.y + pill.height)
      }
    })
  })
}

describe("the out side", () => {
  it("on wide screens, fans out from the ghost to each Busy block's place on Work's edge", () => {
    const diagram = buildDiagram("wide")
    for (const slot of diagram.slots.filter((item) => item.source)) {
      const { end } = ends(diagram.curves.find((curve) => curve.id === `to-${slot.source}`)!.d)
      expect(end.x).toBeCloseTo(diagram.work.x, 1)
      expect(end.y).toBeCloseTo(slot.y + slot.height / 2, 1)
    }
  })

  it("on phones, is one hairline from the ghost down into Work", () => {
    const diagram = buildDiagram("tall")
    const out = diagram.curves.filter((curve) => curve.id.startsWith("to-"))
    expect(out.map((curve) => curve.id)).toEqual(["to-work"])
    expect(ends(out[0]!.d).end.y).toBeCloseTo(diagram.work.y, 1)
    for (const leg of diagram.legs.filter((item) => item.side === "out")) expect(leg.d).toBe(out[0]!.d)
  })
})
