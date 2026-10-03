import { describe, expect, it } from "vitest"

import { HERO_PREVIEW_TONES, HERO_TONE_LABELS, heroPreviewCopy } from "./overview-hero"

describe("hero preview", () => {
  it("keeps the preview order aligned with the available connectivity states", () => {
    expect(HERO_PREVIEW_TONES).toEqual(["setup", "healthy", "attention"])
  })

  it("provides a complete, self-contained presentation for every state", () => {
    for (const tone of HERO_PREVIEW_TONES) {
      const copy = heroPreviewCopy(tone)
      expect(copy.badge).toBeTruthy()
      expect(copy.headline).toBeTruthy()
      expect(copy.detail).toBeTruthy()
      expect(copy.firstFact).toBeTruthy()
      expect(copy.secondFact).toBeTruthy()
      expect(copy.callout.title).toBeTruthy()
      expect(copy.callout.detail).toBeTruthy()
    }
  })

  it("uses readable labels for the preview control", () => {
    expect(HERO_TONE_LABELS).toEqual({ setup: "Setup", healthy: "Healthy", attention: "Attention" })
  })
})
