import { describe, expect, it } from "vitest"
import {
  applyMotionPaused,
  MOTION_ATTRIBUTE,
  MOTION_STORAGE_KEY,
  motionStopped,
  pagePaused,
  readMotionPaused,
  writeMotionPaused,
} from "./motion-preference"

function fakeStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial))
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
    data,
  }
}

describe("the site-wide Pause animations choice", () => {
  it("is saved under the site's own key, and cleared rather than saved as a second value", () => {
    const storage = fakeStorage()
    expect(readMotionPaused(storage)).toBe(false)
    expect(writeMotionPaused(true, storage)).toBe(true)
    expect(storage.data.get(MOTION_STORAGE_KEY)).toBe("paused")
    expect(readMotionPaused(storage)).toBe(true)
    writeMotionPaused(false, storage)
    expect(storage.data.has(MOTION_STORAGE_KEY)).toBe(false)
    expect(readMotionPaused(fakeStorage({ [MOTION_STORAGE_KEY]: "yes" }))).toBe(false)
  })

  it("survives storage that throws or is missing", () => {
    const broken = {
      getItem: () => {
        throw new Error("denied")
      },
      setItem: () => {
        throw new Error("denied")
      },
      removeItem: () => {
        throw new Error("denied")
      },
    }
    expect(readMotionPaused(broken)).toBe(false)
    expect(writeMotionPaused(true, broken)).toBe(false)
    expect(readMotionPaused(null)).toBe(false)
  })

  it("is on whenever the device asks for reduced motion", () => {
    expect(motionStopped(false, false)).toBe(false)
    expect(motionStopped(true, false)).toBe(true)
    expect(motionStopped(false, true)).toBe(true)
  })

  it("stops the page through one attribute on <html>", () => {
    applyMotionPaused(true)
    expect(document.documentElement.getAttribute(MOTION_ATTRIBUTE)).toBe("paused")
    expect(pagePaused()).toBe(true)
    applyMotionPaused(false)
    expect(document.documentElement.hasAttribute(MOTION_ATTRIBUTE)).toBe(false)
    expect(pagePaused()).toBe(false)
  })
})
