import { describe, expect, it } from "vitest"
import { SAM_WEEK } from "../../demo/week"
import { HOURS, LAND_S, PASSES, SOURCES, SPEED, THROUGH_S, buildHub, clock, faceStops, inWeekHours, showsOnWork, type Hub } from "./hub"
import { pointAt, type Box, type Cubic } from "./node-diagram"

const overlaps = (a: Box, b: Box) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
const inside = (box: Box, hub: Hub) => box.x >= 0 && box.y >= 0 && box.x + box.width <= hub.width && box.y + box.height <= hub.height

/** A path's cubic, read from its "M x y C x y x y x y" data. */
function cubicOf(d: string): Cubic {
  const [x0, y0, x1, y1, x2, y2, x3, y3] = d.match(/-?\d+(\.\d+)?/g)!.map(Number) as number[]
  return { p0: { x: x0!, y: y0! }, p1: { x: x1!, y: y1! }, p2: { x: x2!, y: y2! }, p3: { x: x3!, y: y3! } }
}

describe("Sam's calendars and their day", () => {
  it("are Sam's three calendars, Work among them, in the order of their events", () => {
    expect(SOURCES.map((source) => source.key)).toEqual(["work", "personal", "family"])
    const events = SOURCES.map((source) => source.event)
    for (const [index, event] of events.entries()) {
      expect(event.start).toBeGreaterThanOrEqual(HOURS.start)
      expect(event.end).toBeLessThanOrEqual(HOURS.end)
      if (index > 0) expect(event.start).toBeGreaterThanOrEqual(events[index - 1]!.end)
    }
  })

  it("agree with Sam's week: Monday's Standup on Work and Dentist on Personal, and the family dinner after the week's hours", () => {
    for (const [calendar, key] of [
      ["work", "standup"],
      ["personal", "dentist"],
    ] as const) {
      const week = SAM_WEEK.find((event) => event.key === key && event.day === 0)!
      expect(SOURCES.find((source) => source.key === calendar)!.event).toEqual({ key, start: week.start, end: week.end })
    }
    expect(inWeekHours(SOURCES.find((source) => source.key === "family")!.event)).toBe(false)
  })

  it("show on Work as Busy, except Work's own Standup, which keeps its title", () => {
    expect(SOURCES.map(showsOnWork)).toEqual(["own", "busy", "busy"])
  })

  it("writes clock times", () => {
    expect([clock(9), clock(10), clock(15), clock(16.5), clock(18.5)]).toEqual(["09:00", "10:00", "15:00", "16:30", "18:30"])
  })
})

for (const kind of ["wide", "tall"] as const) {
  describe(`the ${kind} layout`, () => {
    const hub = buildHub(kind)

    it("draws the pills, the ghost, and Work's day inside the drawing and apart", () => {
      const boxes = [...hub.pills, hub.ghost, hub.work]
      for (const box of boxes) expect(inside(box, hub)).toBe(true)
      for (const [index, a] of boxes.entries()) for (const b of boxes.slice(index + 1)) expect(overlaps(a, b)).toBe(false)
    })

    it("reads in one direction: the calendars, then the ghost, then Work", () => {
      const along = kind === "wide" ? "x" : "y"
      const size = kind === "wide" ? "width" : "height"
      expect(Math.max(...hub.pills.map((item) => item[along] + item[size]))).toBeLessThan(hub.ghost[along])
      expect(hub.ghost[along] + hub.ghost[size]).toBeLessThan(hub.work[along])
    })

    it("shows Work's day from 09:00 to 20:00, one hour the same height everywhere, each event at its time", () => {
      expect(hub.hours.map((item) => item.hour)).toEqual([9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19])
      for (const [index, item] of hub.hours.entries()) expect(item.y).toBeCloseTo(hub.work.dayTop + index * hub.work.hour)
      expect(hub.work.dayTop + (HOURS.end - HOURS.start) * hub.work.hour).toBeLessThan(hub.work.y + hub.work.height)
      expect(hub.blocks.map((block) => [block.source, block.shows])).toEqual(SOURCES.map((source) => [source.key, showsOnWork(source)]))
      for (const block of hub.blocks) {
        expect(block.y).toBeCloseTo(hub.work.dayTop + (block.event.start - HOURS.start) * hub.work.hour + 1)
        expect(block.height).toBeCloseTo((block.event.end - block.event.start) * hub.work.hour - 2)
        // Blocks leave the gutter to the hour labels.
        expect(block.x).toBe(hub.work.x + hub.work.gutter)
        expect(block.x + block.width).toBeLessThan(hub.work.x + hub.work.width)
      }
    })

    it("keeps the pills close together, centred on the ghost's line, with Personal on it", () => {
      const pitches = hub.pills.slice(1).map((item, index) => item.y - hub.pills[index]!.y)
      for (const pitch of pitches) expect(pitch).toBeLessThanOrEqual(hub.pills[0]!.height * 1.4)
      const middle = (hub.ghost.y + hub.ghost.height / 2)
      const personal = cubicOf(hub.curves.find((curve) => curve.id === "from-personal")!.d)
      if (kind === "wide") {
        expect(personal.p0.y).toBeCloseTo(personal.p3.y)
        expect(Math.abs(personal.p3.y - middle)).toBeLessThan(hub.ghost.height * 0.1)
        expect(hub.labels.calendars.y).toBeLessThan(hub.pills[0]!.y)
        expect(hub.pills[0]!.y - hub.labels.calendars.y).toBeLessThan(30)
      }
    })

    it("runs each hairline from a pill into the ghost, or from the ghost to the day, through no pill and not across the day", () => {
      const ghostMiddle = { x: hub.ghost.x + hub.ghost.width / 2, y: hub.ghost.y + hub.ghost.height / 2 }
      const nearGhost = (point: { x: number; y: number }) => Math.hypot(point.x - ghostMiddle.x, point.y - ghostMiddle.y) < hub.ghost.width * 0.6
      for (const curve of hub.curves) {
        const cubic = cubicOf(curve.d)
        if (curve.id.startsWith("from-")) expect(nearGhost(cubic.p3), curve.id).toBe(true)
        if (curve.id.startsWith("to-")) expect(nearGhost(cubic.p0), curve.id).toBe(true)
        for (let step = 1; step < 40; step += 1) {
          const point = pointAt(cubic, step / 40)
          for (const box of [...hub.pills, hub.work]) {
            const within = point.x > box.x + 1 && point.x < box.x + box.width - 1 && point.y > box.y + 1 && point.y < box.y + box.height - 1
            expect(within, curve.id).toBe(false)
          }
        }
      }
      expect(hub.curves.filter((curve) => curve.id.startsWith("from-"))).toHaveLength(SOURCES.length)
      if (kind === "wide") {
        for (const block of hub.blocks) {
          const end = cubicOf(hub.curves.find((curve) => curve.id === `to-${block.source}`)!.d).p3
          expect(end).toEqual({ x: hub.work.x, y: expect.closeTo(block.y + block.height / 2, 1) })
        }
      } else {
        expect(hub.curves.filter((curve) => curve.id.startsWith("to-")).map((curve) => curve.id)).toEqual(["to-work"])
      }
    })

    it("sends every event through the ghost: the Dentist and the family dinner lose their titles there (kept by the ghost), Work's Standup keeps its own", () => {
      for (const source of SOURCES) {
        const [into, out] = hub.legs.filter((leg) => leg.source === source.key)
        const block = hub.blocks.find((item) => item.source === source.key)!
        const pass = PASSES[source.key]
        const shows = showsOnWork(source)
        expect(into).toMatchObject({ side: "in", shows: "own", drops: shows === "busy" })
        expect(out).toMatchObject({ side: "out", shows, drops: false })
        expect(into!.delay + into!.duration).toBeCloseTo(pass, 1)
        expect(into!.duration).toBeCloseTo(into!.length / SPEED, 1)
        expect(out!.delay).toBeCloseTo(pass + THROUGH_S, 1)
        expect(block.lands).toBeCloseTo(out!.delay + out!.duration, 1)
        const trace = hub.traces.find((item) => item.source === source.key)
        if (shows === "busy") expect(trace).toMatchObject({ event: source.event.key, appears: pass })
        else expect(trace).toBeUndefined()
      }
      expect(hub.legs).toHaveLength(SOURCES.length * 2)
      expect(hub.passes).toEqual([PASSES.personal, PASSES.work, PASSES.family])
      // The Dentist goes first and lands within four seconds; the run rests once the last block is in.
      expect(Math.min(...Object.values(PASSES))).toBe(PASSES.personal)
      expect(hub.blocks.find((block) => block.source === "personal")!.lands).toBeLessThan(4)
      expect(hub.duration).toBeCloseTo(Math.max(...hub.blocks.map((block) => block.lands)) + LAND_S, 1)
      expect(hub.duration).toBeLessThan(10)
    })

    it("keeps the dropped titles by the ghost, apart from every pill and from Work", () => {
      const ghost = hub.ghost
      for (const trace of hub.traces) {
        expect(Math.hypot(trace.x - (ghost.x + ghost.width / 2), trace.y - (ghost.y + ghost.height / 2))).toBeLessThan(ghost.width * 1.2)
        for (const box of [...hub.pills, hub.work]) expect(overlaps({ x: trace.x - 2, y: trace.y - 2, width: 4, height: 4 }, box)).toBe(false)
      }
    })

    it("keeps the ghost neutral between chips, pleased as each passes through, and pleased at rest", () => {
      const stops = faceStops(hub)
      expect(stops[0]).toEqual([0, 0])
      expect(stops.at(-1)).toEqual([100, 1])
      for (const [index, [at]] of stops.entries()) if (index > 0) expect(at).toBeGreaterThanOrEqual(stops[index - 1]![0])
      expect(stops.filter(([, opacity], index) => opacity === 1 && stops[index - 1]?.[1] === 0)).toHaveLength(hub.passes.length)
    })
  })
}
