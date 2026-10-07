import { describe, expect, it } from "vitest"
import {
  HOURS,
  LAND_S,
  PASSES,
  REST_S,
  SOURCES,
  SPEED,
  THROUGH_S,
  arcLength,
  buildHub,
  chipStops,
  clock,
  cubicPath,
  dropStops,
  faceStops,
  keyframes,
  lineStops,
  pointAt,
  showsOnWork,
  stayStops,
  type Box,
  type Cubic,
  type Hub,
  type Stop,
} from "./hub"
import { DAY_END, SAM_WEEK } from "./week"

const overlaps = (a: Box, b: Box) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
const inside = (box: Box, hub: Hub) => box.x >= 0 && box.y >= 0 && box.x + box.width <= hub.width && box.y + box.height <= hub.height

/** A path's cubic, read from its "M x y C x y x y x y" data. */
function cubicOf(d: string): Cubic {
  const [x0, y0, x1, y1, x2, y2, x3, y3] = d.match(/-?\d+(\.\d+)?/g)!.map(Number) as number[]
  return { p0: { x: x0!, y: y0! }, p1: { x: x1!, y: y1! }, p2: { x: x2!, y: y2! }, p3: { x: x3!, y: y3! } }
}

/** Stops must run from 0 to 100 in order. */
function expectOrdered(stops: Stop[]) {
  expect(stops[0]![0]).toBe(0)
  expect(stops.at(-1)![0]).toBe(100)
  for (const [index, [at]] of stops.entries()) if (index > 0) expect(at).toBeGreaterThanOrEqual(stops[index - 1]![0])
}

describe("the curve geometry", () => {
  it("measures a curve, finds points along it, and writes it as path data", () => {
    const line: Cubic = { p0: { x: 0, y: 0 }, p1: { x: 10, y: 0 }, p2: { x: 20, y: 0 }, p3: { x: 30, y: 0 } }
    expect(arcLength(line)).toBeCloseTo(30, 5)
    expect(pointAt(line, 0.5)).toEqual({ x: 15, y: 0 })
    expect(cubicPath({ ...line, p3: { x: 30.123, y: 0 } })).toBe("M0 0C10 0 20 0 30.12 0")
  })
})

describe("Sam's Tuesday", () => {
  it("is Sam's three calendars, in the order of their events, inside a short day", () => {
    expect(SOURCES.map((source) => source.key)).toEqual(["personal", "work", "family"])
    const events = SOURCES.map((source) => source.event)
    for (const [index, event] of events.entries()) {
      expect(event.start).toBeGreaterThan(HOURS.start)
      expect(event.end).toBeLessThan(HOURS.end)
      if (index > 0) expect(event.start).toBeGreaterThanOrEqual(events[index - 1]!.end)
    }
    expect(HOURS.end - HOURS.start).toBeLessThanOrEqual(8)
  })

  it("agrees with Sam's week: Tuesday's gym session on Personal and client call on Work, and the family dinner after the week's hours", () => {
    for (const [calendar, key] of [
      ["personal", "gym"],
      ["work", "clientCall"],
    ] as const) {
      const week = SAM_WEEK.find((event) => event.key === key && event.day === 1)!
      expect(SOURCES.find((source) => source.key === calendar)!.event).toEqual({ key, start: week.start, end: week.end })
    }
    expect(SOURCES.find((source) => source.key === "family")!.event.start).toBeGreaterThanOrEqual(DAY_END)
  })

  it("shows on Work as Busy, except Work's own client call", () => {
    expect(SOURCES.map(showsOnWork)).toEqual(["busy", "own", "busy"])
    expect(clock(11.5)).toBe("11:30")
  })
})

for (const kind of ["wide", "tall"] as const) {
  describe(`the ${kind} layout`, () => {
    const hub = buildHub(kind)

    it("draws the pills, the ghost, and the day inside the drawing and apart, reading in one direction", () => {
      const boxes = [...hub.pills, hub.ghost, hub.day]
      for (const box of boxes) expect(inside(box, hub)).toBe(true)
      for (const [index, a] of boxes.entries()) for (const b of boxes.slice(index + 1)) expect(overlaps(a, b)).toBe(false)
      const along = kind === "wide" ? "x" : "y"
      const size = kind === "wide" ? "width" : "height"
      expect(Math.max(...hub.pills.map((item) => item[along] + item[size]))).toBeLessThan(hub.ghost[along])
      expect(hub.ghost[along] + hub.ghost[size]).toBeLessThan(hub.day[along])
    })

    if (kind === "wide") {
      it("keeps it compact: the pills close together and the day not much taller, both centred on the ghost's line, the labels on one line", () => {
        const middle = hub.ghost.y + hub.ghost.height / 2
        const stackTop = hub.pills[0]!.y
        const stackBottom = hub.pills.at(-1)!.y + hub.pills.at(-1)!.height
        expect((stackTop + stackBottom) / 2).toBeCloseTo(hub.day.y + hub.day.height / 2, 0)
        expect(Math.abs(middle - (hub.day.y + hub.day.height / 2))).toBeLessThan(hub.ghost.height * 0.15)
        expect(hub.day.height).toBeLessThan((stackBottom - stackTop) * 1.5)
        expect(hub.labels.calendars.y).toBe(hub.labels.day.y)
      })
    }

    it("labels each whole hour of the day and places each event at its time", () => {
      expect(hub.hours.map((item) => item.hour)).toEqual([12, 13, 14, 15, 16, 17, 18, 19])
      for (const block of hub.blocks) {
        expect(block.y).toBeCloseTo(hub.day.dayTop + (block.event.start - HOURS.start) * hub.day.hour + 1)
        expect(block.height).toBeCloseTo((block.event.end - block.event.start) * hub.day.hour - 2)
        expect(block.x).toBe(hub.day.x + hub.day.gutter)
      }
    })

    it("runs every hairline through the ghost and through no pill or day", () => {
      const ghostMiddle = { x: hub.ghost.x + hub.ghost.width / 2, y: hub.ghost.y + hub.ghost.height / 2 }
      const nearGhost = (point: { x: number; y: number }) => Math.hypot(point.x - ghostMiddle.x, point.y - ghostMiddle.y) < hub.ghost.width * 0.6
      for (const curve of hub.curves) {
        const cubic = cubicOf(curve.d)
        expect(nearGhost(curve.id.startsWith("from-") ? cubic.p3 : cubic.p0), curve.id).toBe(true)
        for (let step = 1; step < 40; step += 1) {
          const point = pointAt(cubic, step / 40)
          for (const box of [...hub.pills, hub.day]) {
            const within = point.x > box.x + 1 && point.x < box.x + box.width - 1 && point.y > box.y + 1 && point.y < box.y + box.height - 1
            expect(within, curve.id).toBe(false)
          }
        }
      }
      for (const leg of hub.legs) expect(hub.curves.find((curve) => curve.id === leg.curve), leg.curve).toBeDefined()
    })

    it("sends every event through the ghost; titles bound for Busy drop there and the ghost keeps them", () => {
      for (const source of SOURCES) {
        const [into, out] = hub.legs.filter((leg) => leg.source === source.key)
        const pass = PASSES[source.key]
        const shows = showsOnWork(source)
        expect(into).toMatchObject({ side: "in", drops: shows === "busy" })
        expect(out).toMatchObject({ side: "out", shows })
        expect(into!.delay).toBeGreaterThanOrEqual(0)
        expect(into!.delay + into!.duration).toBeCloseTo(pass, 1)
        expect(into!.duration).toBeCloseTo(into!.length / SPEED, 1)
        expect(out!.delay).toBeCloseTo(pass + THROUGH_S, 1)
        expect(hub.blocks.find((block) => block.source === source.key)!.lands).toBeCloseTo(out!.delay + out!.duration, 1)
      }
      expect(hub.kept.titles.map((title) => title.event)).toEqual(["gym", "familyDinner"])
      expect(hub.cycle).toBeCloseTo(Math.max(...hub.blocks.map((block) => block.lands)) + LAND_S + REST_S, 1)
    })

    it("turns every moving part into keyframes for one cycle, in order, ending as it began", () => {
      for (const leg of hub.legs) {
        const chip = chipStops(hub, leg)
        expectOrdered(chip)
        expect(chip[0]![1].opacity).toBe(0)
        expect(chip.at(-1)![1].opacity).toBe(0)
        expectOrdered(lineStops(hub, leg.delay, leg.duration))
        if (leg.drops) expect(dropStops(hub, leg).at(-1)![1].opacity).toBe(1)
      }
      for (const block of hub.blocks) {
        const stay = stayStops(hub, block.lands)
        expectOrdered(stay)
        expect(stay.some(([, values]) => values.opacity === 1)).toBe(true)
        expect(stay.at(-1)![1].opacity).toBe(0)
      }
      const face = faceStops(hub)
      expectOrdered(face)
      expect(face.filter(([, values], index) => values.opacity === 1 && face[index - 1]?.[1].opacity === 0)).toHaveLength(hub.passes.length)
      expect(keyframes("hc-x", [[0, { opacity: 0 }], [100, { opacity: 1, "offset-distance": "100%" }]])).toBe("@keyframes hc-x{0%{opacity:0}100%{opacity:1;offset-distance:100%}}")
    })
  })
}
