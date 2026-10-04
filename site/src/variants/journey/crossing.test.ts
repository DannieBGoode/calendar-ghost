import { describe, expect, it } from "vitest"
import { PARTS, RUN, clock, crosses, momentAt, peelWindow, progress, staysBehind } from "./crossing"

describe("what crosses over", () => {
  it("with Busy only, only the time crosses; everything else stays with Sam", () => {
    expect(PARTS.filter((part) => crosses(part, "busy"))).toEqual(["time"])
    expect(staysBehind("busy")).toEqual(["title", "place", "description", "guests", "link"])
  })

  it("with details, title, place, and description cross too; guests and links never do", () => {
    expect(PARTS.filter((part) => crosses(part, "details"))).toEqual(["title", "time", "place", "description"])
    expect(staysBehind("details")).toEqual(["guests", "link"])
  })
})

describe("clock", () => {
  it("writes clock times with two digits", () => {
    expect(clock(15.5)).toBe("15:30")
    expect(clock(9)).toBe("09:00")
  })
})

describe("the carry", () => {
  it("goes fetch, take, peel, carry, set, settle, then rests until the next run", () => {
    const moments = [0, RUN.take[0], RUN.peel[0], RUN.carry[0], RUN.set[0], RUN.settle[0], RUN.settle[1]].map(momentAt)
    expect(moments).toEqual(["fetch", "take", "peel", "carry", "set", "settle", "rest"])
    expect(momentAt(RUN.total - 1)).toBe("rest")
  })

  it("sends every part home before the ghost leaves with the rest", () => {
    const lastHome = peelWindow(staysBehind("busy").length - 1)[1]
    expect(lastHome).toBeLessThanOrEqual(RUN.carry[0])
    expect(peelWindow(0)[0]).toBe(RUN.peel[0])
  })

  it("measures progress through a stretch of the run", () => {
    expect(progress(50, [100, 200])).toBe(0)
    expect(progress(150, [100, 200])).toBe(0.5)
    expect(progress(250, [100, 200])).toBe(1)
  })
})
