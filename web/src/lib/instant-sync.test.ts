import { describe, expect, it } from "vitest"

import { instantSyncBlock, instantSyncHelpUrl, ruleCadence } from "./instant-sync"

const GUIDE = "https://calendarghost.com/docs/instant-sync"

describe("instantSyncBlock", () => {
  it("leaves the switch to the User when instant sync is on or they turned it off", () => {
    expect(instantSyncBlock("on")).toBeNull()
    expect(instantSyncBlock("off_by_user")).toBeNull()
  })

  it("names what keeps it from running otherwise, and a reason this version does not know as unknown", () => {
    expect(instantSyncBlock("not_in_plan")).toBe("not_in_plan")
    expect(instantSyncBlock("no_public_address")).toBe("no_public_address")
    expect(instantSyncBlock("not_reaching")).toBe("not_reaching")
    expect(instantSyncBlock("a_reason_from_a_later_server")).toBe("unknown")
  })
})

describe("instantSyncHelpUrl", () => {
  it("opens the guide's section the server names, and nothing without one", () => {
    expect(instantSyncHelpUrl("not-in-your-plan")).toBe(`${GUIDE}#not-in-your-plan`)
    expect(instantSyncHelpUrl(null)).toBeNull()
    expect(instantSyncHelpUrl(undefined)).toBeNull()
  })
})

describe("ruleCadence", () => {
  it("says a watched rule syncs instantly, and how often it also checks", () => {
    expect(ruleCadence({ effective_cadence: "instant", poll_every_minutes: 5 })).toEqual({
      instant: true,
      reason: null,
      minutes: 5,
      helpUrl: null,
    })
  })

  it("gives a rule on its schedule its reason and the guide's section on it", () => {
    expect(ruleCadence({ effective_cadence: "waiting_for_provider", poll_every_minutes: 5 })).toEqual({
      instant: false,
      reason: "waiting_for_provider",
      minutes: 5,
      helpUrl: `${GUIDE}#waiting-for-the-provider`,
    })
    const sections = (reason: string) => ruleCadence({ effective_cadence: reason, poll_every_minutes: 5 }).helpUrl
    expect(sections("not_watchable")).toBe(`${GUIDE}#this-calendar-cannot-be-watched`)
    expect(sections("not_in_plan")).toBe(`${GUIDE}#not-in-your-plan`)
    expect(sections("no_public_address")).toBe(`${GUIDE}#no-public-https-address`)
    expect(sections("not_reaching")).toBe(`${GUIDE}#providers-cannot-reach-the-installation`)
  })

  it("links nowhere for the User's own choice, or for a reason this version does not know", () => {
    expect(ruleCadence({ effective_cadence: "off_by_user", poll_every_minutes: 5 })).toEqual({
      instant: false,
      reason: "off_by_user",
      minutes: 5,
      helpUrl: null,
    })
    expect(ruleCadence({ effective_cadence: "a_reason_from_a_later_server", poll_every_minutes: 10 })).toEqual({
      instant: false,
      reason: null,
      minutes: 10,
      helpUrl: null,
    })
  })
})
