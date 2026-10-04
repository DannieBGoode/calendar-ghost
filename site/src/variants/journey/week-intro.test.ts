import { describe, expect, it } from "vitest"
import { REVEAL_REST } from "../../islands/motion"
import { INTRO_FROM, INTRO_MS, INTRO_SWEEP_MS, INTRO_TURN, hasArrived, introSplit } from "./week-intro"

describe("the week's opening pass", () => {
  it("sweeps from the right edge to the left, then settles at rest", () => {
    expect(introSplit(0)).toBe(INTRO_FROM)
    expect(introSplit(INTRO_SWEEP_MS)).toBeCloseTo(INTRO_TURN)
    expect(introSplit(INTRO_MS)).toBe(REVEAL_REST)
    expect(introSplit(INTRO_SWEEP_MS / 2)).toBeLessThan(INTRO_FROM)
  })

  it("takes under five seconds", () => {
    expect(INTRO_MS).toBeLessThanOrEqual(5000)
  })

  it("brings a plan to work's side once the divider has passed its middle", () => {
    const friday = { leftPct: 80, widthPct: 20 }
    expect(hasArrived(friday, 95)).toBe(false)
    expect(hasArrived(friday, 90)).toBe(true)
  })

  it("passes every day of the week", () => {
    expect(hasArrived({ leftPct: 0, widthPct: 20 }, INTRO_TURN)).toBe(true)
  })
})
