import { describe, expect, it } from "vitest"
import { en } from "../../i18n/en"
import {
  CYCLE_S,
  DESTINATIONS,
  PARTS,
  SEGMENT,
  SPEED,
  arcLength,
  buildDiagram,
  dashFor,
  pointAt,
  reaches,
  splitAt,
  tAtLength,
  tWhere,
  type Box,
  type Cubic,
  type LayoutKind,
} from "./node-diagram"

const line: Cubic = { p0: { x: 0, y: 0 }, p1: { x: 10, y: 0 }, p2: { x: 20, y: 0 }, p3: { x: 30, y: 0 } }

/** The last point of an SVG path made of absolute commands. */
function endOf(d: string) {
  const numbers = d.match(/-?\d+(\.\d+)?/g)!.map(Number)
  return { x: numbers.at(-2)!, y: numbers.at(-1)! }
}

const overlaps = (a: Box, b: Box) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height

describe("the rule the diagram draws", () => {
  it("lists an event's parts in order, each with its words", () => {
    expect(PARTS.map((part) => part.key)).toEqual(["time", "title", "place", "description", "guests", "organizer", "link", "attachments", "invitations"])
    for (const part of PARTS) expect(en.variants.homeHeroes.nodeDiagram.parts[part.key]).toBeTruthy()
  })

  it("sends Busy only the time, details the title, place, and description too, and never the rest", () => {
    const into = (projection: "busy" | "details") => PARTS.filter((part) => reaches(part, projection)).map((part) => part.key)
    expect(into("busy")).toEqual(["time"])
    expect(into("details")).toEqual(["time", "title", "place", "description"])
    expect(PARTS.filter((part) => part.reach === "never").map((part) => part.key)).toEqual(["guests", "organizer", "link", "attachments", "invitations"])
  })

  it("has Work and Family get Busy, and Personal get the details", () => {
    expect(DESTINATIONS).toEqual([
      { key: "work", projection: "busy" },
      { key: "family", projection: "busy" },
      { key: "personal", projection: "details" },
    ])
  })
})

describe("the curve geometry", () => {
  it("measures, cuts, and finds points along a curve", () => {
    expect(arcLength(line)).toBeCloseTo(30, 5)
    expect(tAtLength(line, 15)).toBeCloseTo(0.5, 3)
    expect(tWhere(line, "x", 12)).toBeCloseTo(0.4, 5)
    const [head, tail] = splitAt(line, 0.25)
    expect(head.p3).toEqual(pointAt(line, 0.25))
    expect(arcLength(head) + arcLength(tail)).toBeCloseTo(30, 5)
  })
})

for (const kind of ["wide", "tall"] as LayoutKind[]) {
  describe(`the ${kind} diagram`, () => {
    const diagram = buildDiagram(kind)
    const legsOf = (part: string) => diagram.legs.filter((leg) => leg.part === part)

    it("draws one pill and one hairline per part and per calendar, all inside it and apart", () => {
      expect(diagram.parts.map((pill) => pill.key)).toEqual(PARTS.map((part) => part.key))
      expect(diagram.destinations.map((pill) => pill.key)).toEqual(["work", "family", "personal"])
      expect(diagram.curves).toHaveLength(PARTS.length + DESTINATIONS.length)
      const boxes = [...diagram.parts, ...diagram.destinations]
      for (const box of boxes) {
        expect(box.x).toBeGreaterThanOrEqual(0)
        expect(box.y).toBeGreaterThanOrEqual(0)
        expect(box.x + box.width).toBeLessThanOrEqual(diagram.width)
        expect(box.y + box.height).toBeLessThanOrEqual(diagram.height)
      }
      for (const [index, box] of boxes.entries()) for (const other of boxes.slice(index + 1)) expect(overlaps(box, other)).toBe(false)
    })

    it("runs the time through the ghost to every calendar", () => {
      const legs = legsOf("time")
      expect(legs.map((leg) => leg.to)).toEqual([undefined, "work", "family", "personal"])
      // It leaves for the calendars after it has reached the ghost.
      const [into, ...out] = legs
      for (const leg of out) expect(leg.delay).toBeGreaterThan(into!.delay + into!.length / SPEED)
      // The still diagram shows it on its own curve and on every calendar's.
      for (const leg of legs) expect(leg.still).not.toBeNull()
    })

    it("runs the title, place, and description only to Personal", () => {
      for (const part of ["title", "place", "description"]) {
        expect(legsOf(part).map((leg) => leg.to)).toEqual([undefined, "personal"])
      }
      expect(diagram.legs.filter((leg) => leg.to === "personal" && leg.role === "details" && leg.still !== null)).toHaveLength(1)
    })

    it("stops every part that never crosses over short of the ghost, with a cap", () => {
      const never = PARTS.filter((part) => part.reach === "never").map((part) => part.key)
      expect(diagram.stops.map((stop) => stop.part)).toEqual(never)
      for (const part of never) {
        const [leg, ...rest] = legsOf(part)
        expect(rest).toEqual([])
        expect(leg!.to).toBeUndefined()
        expect(leg!.role).toBe("stays")
        // Its path ends where its stub ends, at the cap, well before the hairline does.
        const stop = diagram.stops.find((item) => item.part === part)!
        expect(endOf(leg!.d)).toEqual(endOf(stop.stub))
        const full = diagram.curves.find((curve) => curve.id === `from-${part}`)!
        const [stopped, hub] = [endOf(leg!.d), endOf(full.d)]
        expect(Math.hypot(hub.x - stopped.x, hub.y - stopped.y)).toBeGreaterThan(SEGMENT)
        expect(stop.delay).toBeCloseTo(leg!.delay + leg!.length / SPEED, 1)
      }
      // Nothing else stops.
      expect(diagram.stops).toHaveLength(never.length)
    })

    it("starts every segment within one loop, and its dash hides it before and after its run", () => {
      for (const leg of diagram.legs) {
        expect(leg.delay).toBeGreaterThanOrEqual(0)
        expect(leg.delay).toBeLessThan(CYCLE_S)
        const dash = dashFor(leg)
        const [segment, gap] = dash.dasharray.split(" ").map(Number)
        expect(segment).toBe(SEGMENT)
        // The gap outlasts the whole run, so a second segment never shows in the same loop.
        expect(gap! + dash.to).toBeGreaterThan(leg.length)
        expect(dash.from).toBe(SEGMENT)
        if (leg.still === null) expect(dash.still).toBe(SEGMENT)
        else {
          expect(-dash.still).toBeGreaterThanOrEqual(0)
          expect(-dash.still + SEGMENT).toBeLessThanOrEqual(leg.length)
        }
      }
    })

    it("draws the ghost as the mark's outline: a page, two tabs, and a hem", () => {
      expect(diagram.node.body).toMatch(/^M.*a.*h.*a.*V(.*q){5}.*Z$/)
      expect(diagram.node.tabs.match(/M/g)).toHaveLength(2)
    })
  })
}
