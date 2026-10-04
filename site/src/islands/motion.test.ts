import { describe, expect, it } from "vitest"
import {
  REVEAL_REST,
  SWEEP_PERIOD_MS,
  clampPercent,
  eyeOffset,
  shouldAnimate,
  sweepPercent,
  sweepTimeFor,
} from "./motion"

describe("sweep", () => {
  it("swings between 12% and 88% around the middle", () => {
    expect(sweepPercent(0)).toBeCloseTo(50)
    expect(sweepPercent(SWEEP_PERIOD_MS / 4)).toBeCloseTo(88)
    expect(sweepPercent((SWEEP_PERIOD_MS * 3) / 4)).toBeCloseTo(12)
  })

  it("resumes from where the visitor left the slider", () => {
    for (const percent of [REVEAL_REST, 20, 70]) {
      expect(sweepPercent(sweepTimeFor(percent))).toBeCloseTo(percent)
    }
  })

  it("resumes from the nearest edge of the swing when left outside it", () => {
    expect(sweepPercent(sweepTimeFor(97))).toBeCloseTo(88)
    expect(sweepPercent(sweepTimeFor(3))).toBeCloseTo(12)
  })

  it("keeps the handle inside the frame", () => {
    expect(clampPercent(-10)).toBe(2)
    expect(clampPercent(140)).toBe(98)
    expect(clampPercent(40)).toBe(40)
  })
})

describe("eyeOffset", () => {
  it("looks straight ahead when the pointer is on the ghost", () => {
    expect(eyeOffset(0, 0)).toEqual({ x: 0, y: 0 })
  })

  it("looks toward the pointer by at most the eye's travel", () => {
    expect(eyeOffset(10, 0)).toEqual({ x: 1.3, y: 0 })
    expect(eyeOffset(0, -400)).toEqual({ x: 0, y: -1.1 })
  })
})

describe("shouldAnimate", () => {
  const running = { onScreen: true, pageVisible: true, reducedMotion: false, held: false }

  it("animates only when nothing stops it", () => {
    expect(shouldAnimate(running)).toBe(true)
    expect(shouldAnimate({ ...running, onScreen: false })).toBe(false)
    expect(shouldAnimate({ ...running, pageVisible: false })).toBe(false)
    expect(shouldAnimate({ ...running, reducedMotion: true })).toBe(false)
    expect(shouldAnimate({ ...running, held: true })).toBe(false)
  })
})
