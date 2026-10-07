import { describe, expect, it } from "vitest"
import { HAUNTED_PERIOD_MS, HAUNTED_STILL_MS, hauntedFrame, phoneCell, PHONE_COLUMNS, pointOnPath, waypoints, type PathPoint } from "./haunted"
import { SAM_WEEK } from "./week"

const INCOMING = SAM_WEEK.filter((event) => event.kind !== "work")
const PHONE_INCOMING = INCOMING.filter((event) => event.day < PHONE_COLUMNS)
const COUNT = INCOMING.length

/** The moment the ghost reaches waypoint `index` (0 is the way in, the last is the way out). */
const reachMs = (index: number) => 1700 + (5400 * index) / (COUNT + 1)

function expectNear(actual: PathPoint, expected: PathPoint) {
  expect(actual.x).toBeCloseTo(expected.x, 6)
  expect(actual.row).toBeCloseTo(expected.row, 6)
  expect(actual.y).toBeCloseTo(expected.y, 6)
}

describe("hauntedFrame", () => {
  it("starts empty, with the ghost out of sight", () => {
    const frame = hauntedFrame(0, COUNT)
    expect(frame.incoming).toEqual(["away", "away", "away", "away", "away"])
    expect(frame.run).toBeNull()
  })

  it("brings every event in, in transit, before the ghost arrives", () => {
    const frame = hauntedFrame(1500, COUNT)
    expect(frame.incoming).toEqual(["transit", "transit", "transit", "transit", "transit"])
    expect(frame.run).toBeNull()
  })

  it("turns each event into Busy the moment the ghost touches it, in order", () => {
    expect(hauntedFrame(reachMs(1) - 10, COUNT).incoming[0]).toBe("transit")
    expect(hauntedFrame(reachMs(1) + 10, COUNT).incoming).toEqual(["busy", "transit", "transit", "transit", "transit"])
    const middle = hauntedFrame(reachMs(3) + 10, COUNT)
    expect(middle.run).toBeGreaterThan(0)
    expect(middle.incoming).toEqual(["busy", "busy", "busy", "transit", "transit"])
  })

  it("rests with every event Busy, the ghost gone, and nothing fading", () => {
    const frame = hauntedFrame(HAUNTED_STILL_MS, COUNT)
    expect(frame.incoming.every((state) => state === "busy")).toBe(true)
    expect(frame.fading).toBe(false)
    expect(frame.run).toBeNull()
  })

  it("fades out at the end and repeats", () => {
    expect(hauntedFrame(8600, COUNT).fading).toBe(true)
    expect(hauntedFrame(HAUNTED_PERIOD_MS + 1000, COUNT)).toEqual(hauntedFrame(1000, COUNT))
  })
})

describe("the ghost's path", () => {
  it("enters and leaves beyond the week's edges, in both layouts", () => {
    for (const layout of ["wide", "phone"] as const) {
      const points = waypoints(INCOMING, layout)
      expect(pointOnPath(points, 0).x).toBeLessThan(0)
      expect(pointOnPath(points, 1).x).toBeGreaterThan(layout === "wide" ? 5 : 3)
    }
  })

  it("reaches each visible event when its Busy state changes", () => {
    const wide = waypoints(INCOMING, "wide")
    const phone = waypoints(PHONE_INCOMING, "phone", COUNT)
    INCOMING.forEach((event, index) => {
      const u = (index + 1) / (COUNT + 1)
      expectNear(pointOnPath(wide, u), { x: event.day + 0.5, row: 0, y: event.start - 9 })
      if (index < PHONE_INCOMING.length) {
        const cell = phoneCell(event.day)
        expectNear(pointOnPath(phone, u), { x: cell.col + 0.5, row: cell.row, y: event.start - 9 })
      }
      expect(hauntedFrame(reachMs(index + 1) + 1, COUNT).incoming[index]).toBe("busy")
    })
  })

  it("moves smoothly: no jump between two nearby moments", () => {
    const points = waypoints(PHONE_INCOMING, "phone", COUNT)
    for (let step = 0; step < 1000; step += 1) {
      const a = pointOnPath(points, step / 1000)
      const b = pointOnPath(points, (step + 1) / 1000)
      expect(Math.hypot(b.x - a.x, b.row - a.row, (b.y - a.y) / 8)).toBeLessThan(0.05)
    }
  })

  it("maps the phone's visible Monday-to-Wednesday events onto one row", () => {
    expect(PHONE_INCOMING.map((event) => event.day)).toEqual([0, 1, 2])
    expect([0, 1, 2].map(phoneCell)).toEqual([
      { col: 0, row: 0 },
      { col: 1, row: 0 },
      { col: 2, row: 0 },
    ])
  })
})
