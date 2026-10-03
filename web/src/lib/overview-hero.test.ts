import { describe, expect, it } from "vitest"

import { overviewHeroCallout } from "./overview-hero"

describe("overview hero", () => {
  it("provides a complete, self-contained presentation for every state", () => {
    for (const tone of ["setup", "healthy", "attention"] as const) {
      const callout = overviewHeroCallout(tone)
      expect(callout.title).toBeTruthy()
      expect(callout.detail).toBeTruthy()
    }
  })

  it("uses readable labels for every connectivity state", () => {
    expect(overviewHeroCallout("setup").title).toBe("Ready when you are")
    expect(overviewHeroCallout("healthy").title).toBe("All good!")
    expect(overviewHeroCallout("attention").title).toBe("Needs attention")
  })
})
