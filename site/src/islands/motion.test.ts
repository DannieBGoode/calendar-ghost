import { describe, expect, it } from "vitest"
import { eyeOffset, shouldAnimate } from "./motion"

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
