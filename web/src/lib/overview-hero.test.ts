import { describe, expect, it } from "vitest"

import { testI18n } from "../i18n/testing"
import { overviewHeroCallouts } from "./overview-hero"

describe("overview hero", () => {
  it("gives the ghost a short reaction for every state", () => {
    const i18n = testI18n()
    expect(overviewHeroCallouts(i18n, "healthy")).toEqual([
      { title: "All good!", detail: "Your calendars are in sync." },
    ])
    expect(overviewHeroCallouts(i18n, "review")).toEqual([{ title: "Almost all good" }])
    expect(overviewHeroCallouts(i18n, "waiting")).toEqual([{ title: "Hang tight…" }])
    expect(overviewHeroCallouts(i18n, "paused")).toEqual([{ title: "Taking a break" }])
    expect(overviewHeroCallouts(i18n, "setup")).toEqual([{ title: "Ready when you are!" }])
  })

  it("has a stopped ghost call for help, starting with the plainest line", () => {
    const calls = overviewHeroCallouts(testI18n(), "stopped").map((callout) => callout.title)
    expect(calls[0]).toBe("Help!")
    expect(calls).toContain("I need a hand")
    expect(new Set(calls).size).toBe(calls.length)
  })
})
