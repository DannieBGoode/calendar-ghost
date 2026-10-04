import { describe, expect, it } from "vitest"
import { eventBox, fitsTwoLines } from "./layout"
import { SAM_WEEK, type DemoEvent } from "./week"

const FRAME = { heightPx: 380, headerPx: 36, gapPx: 3 }
const event = (overrides: Partial<DemoEvent>): DemoEvent => ({
  key: "standup",
  kind: "work",
  day: 0,
  start: 10,
  end: 11,
  ...overrides,
})

describe("eventBox", () => {
  it("places an hour-long Monday event by its time", () => {
    // (380 - 36) / 8 hours = 43px per hour.
    expect(eventBox(event({}), FRAME)).toEqual({ leftPct: 0, widthPct: 20, topPx: 79, heightPx: 40 })
  })

  it("places Friday in the last fifth", () => {
    expect(eventBox(event({ day: 4, start: 9, end: 9.5 }), FRAME)).toMatchObject({
      leftPct: 80,
      topPx: 36,
    })
  })

  it("keeps every event of Sam's week inside the frame", () => {
    for (const item of SAM_WEEK) {
      const box = eventBox(item, FRAME)
      expect(box.topPx).toBeGreaterThanOrEqual(FRAME.headerPx)
      expect(box.topPx + box.heightPx).toBeLessThanOrEqual(FRAME.heightPx)
    }
  })
})

describe("fitsTwoLines", () => {
  it("shows the detail line only when an event is tall enough", () => {
    expect(fitsTwoLines({ leftPct: 0, widthPct: 20, topPx: 0, heightPx: 40 })).toBe(true)
    expect(fitsTwoLines({ leftPct: 0, widthPct: 20, topPx: 0, heightPx: 20 })).toBe(false)
  })
})

describe("Sam's week", () => {
  it("has work events that stay and personal or family events that cross over", () => {
    expect(SAM_WEEK.filter((item) => item.kind === "work")).toHaveLength(5)
    expect(SAM_WEEK.filter((item) => item.kind !== "work")).toHaveLength(5)
  })

  it("never overlaps two events on the same day", () => {
    for (const a of SAM_WEEK) {
      for (const b of SAM_WEEK) {
        if (a !== b && a.day === b.day) expect(a.end <= b.start || b.end <= a.start).toBe(true)
      }
    }
  })
})
