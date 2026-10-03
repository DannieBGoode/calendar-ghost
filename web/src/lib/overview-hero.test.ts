import { describe, expect, it } from "vitest"

import { overviewHeroCallouts } from "./overview-hero"

describe("overview hero", () => {
  it("gives the ghost a short reaction for every state", () => {
    expect(overviewHeroCallouts("healthy")).toEqual([{ title: "All good!", detail: "Your calendars are in sync." }])
    expect(overviewHeroCallouts("review")).toEqual([{ title: "Almost all good" }])
    expect(overviewHeroCallouts("waiting")).toEqual([{ title: "Hang tight…" }])
    expect(overviewHeroCallouts("paused")).toEqual([{ title: "Taking a break" }])
    expect(overviewHeroCallouts("setup")).toEqual([{ title: "Ready when you are!" }])
  })

  it("has a stopped ghost call for help, starting with the plainest line", () => {
    const calls = overviewHeroCallouts("stopped").map((callout) => callout.title)
    expect(calls[0]).toBe("Help!")
    expect(calls).toContain("I need a hand")
    expect(new Set(calls).size).toBe(calls.length)
  })
})
