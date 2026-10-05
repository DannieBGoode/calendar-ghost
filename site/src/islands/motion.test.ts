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

  it("can head left first from where it rests", () => {
    const left = sweepTimeFor(40, { direction: "left" })
    expect(sweepPercent(left)).toBeCloseTo(40)
    expect(sweepPercent(left + 100)).toBeLessThan(40)
    expect(sweepPercent(sweepTimeFor(40) + 100)).toBeGreaterThan(40)
  })

  it("can swing less far each way", () => {
    expect(sweepPercent(SWEEP_PERIOD_MS / 4, SWEEP_PERIOD_MS, 30)).toBeCloseTo(80)
    expect(sweepPercent((SWEEP_PERIOD_MS * 3) / 4, SWEEP_PERIOD_MS, 30)).toBeCloseTo(20)
    const start = sweepTimeFor(40, { swing: 30, direction: "left" })
    expect(sweepPercent(start, SWEEP_PERIOD_MS, 30)).toBeCloseTo(40)
  })

  it("from 40% heading left, nears the left end of a 30-point swing within 2.5 seconds", () => {
    const start = sweepTimeFor(40, { swing: 30, direction: "left" })
    expect(sweepPercent(start + 2000, SWEEP_PERIOD_MS, 30)).toBeLessThan(22)
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
