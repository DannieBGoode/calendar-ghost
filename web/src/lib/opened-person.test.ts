import { describe, expect, it } from "vitest"

import { peopleReturnSearch, rememberOpenedPerson, takeOpenedPerson } from "./use-people"

describe("the person opened from People", () => {
  it("is focused once on return, while their page keeps its way back to the filtered list", () => {
    rememberOpenedPerson("user-robin", "?state=active&sort=email")

    // Back to People restores focus to their row, once.
    expect(takeOpenedPerson()).toBe("user-robin")
    expect(takeOpenedPerson()).toBeNull()

    // Forward to their page again still leads back to the same filtered list (review on PR 68).
    expect(peopleReturnSearch("user-robin")).toBe("?state=active&sort=email")
    expect(peopleReturnSearch("user-sam")).toBe("")
  })
})
