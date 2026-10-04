import { describe, expect, it } from "vitest"
import { HAUNTED_PERIOD_MS, HAUNTED_STILL_MS, hauntedFrame } from "./haunted"

const DAYS = [0, 1, 2, 3, 4]

describe("hauntedFrame", () => {
  it("starts empty, with the ghost out of sight", () => {
    const frame = hauntedFrame(0, DAYS)
    expect(frame.shown).toEqual([false, false, false, false, false])
    expect(frame.busy).toEqual([false, false, false, false, false])
    expect(frame.ghost.visible).toBe(false)
  })

  it("slides every event in before the ghost arrives", () => {
    const frame = hauntedFrame(1000, DAYS)
    expect(frame.shown).toEqual([true, true, true, true, true])
    expect(frame.busy.some(Boolean)).toBe(false)
  })

  it("turns an event into Busy once the ghost has passed its day", () => {
    const frame = hauntedFrame(4000, DAYS)
    expect(frame.ghost.visible).toBe(true)
    expect(frame.busy).toEqual([true, true, false, false, false])
  })

  it("rests with every event Busy and nothing fading", () => {
    const frame = hauntedFrame(HAUNTED_STILL_MS, DAYS)
    expect(frame.busy).toEqual([true, true, true, true, true])
    expect(frame.fading).toBe(false)
    expect(frame.ghost.visible).toBe(false)
  })

  it("fades out at the end and repeats", () => {
    expect(hauntedFrame(8600, DAYS).fading).toBe(true)
    expect(hauntedFrame(HAUNTED_PERIOD_MS + 1000, DAYS)).toEqual(hauntedFrame(1000, DAYS))
  })
})
