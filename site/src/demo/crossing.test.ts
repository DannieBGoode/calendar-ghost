import { describe, expect, it } from "vitest"
import { crossingFields } from "./crossing"

describe("crossingFields", () => {
  it("lets only the time cross over with Busy only", () => {
    expect(crossingFields("busy")).toEqual({ title: false, location: false, guests: false, link: false })
  })

  it("adds title and place with details, never guests or meeting links", () => {
    expect(crossingFields("details")).toEqual({ title: true, location: true, guests: false, link: false })
  })
})
