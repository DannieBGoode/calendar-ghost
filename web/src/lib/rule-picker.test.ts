import { describe, expect, it } from "vitest"

import { movedIndex, openingIndex, typeaheadIndex } from "./rule-picker"

describe("rule picker keyboard", () => {
  it("opens on the selected option, or at either end with Home and End", () => {
    expect(openingIndex("ArrowDown", false, 2, 4)).toBe(2)
    expect(openingIndex("Enter", false, -1, 4)).toBe(0)
    expect(openingIndex(" ", false, 1, 4)).toBe(1)
    expect(openingIndex("Home", false, 2, 4)).toBe(0)
    expect(openingIndex("End", false, 0, 4)).toBe(3)
    expect(openingIndex("a", false, 0, 4)).toBeNull()
    expect(openingIndex("ArrowDown", false, 0, 0)).toBeNull()
  })

  it("moves within the list without wrapping", () => {
    expect(movedIndex("ArrowDown", 3, 4)).toBe(3)
    expect(movedIndex("ArrowUp", 0, 4)).toBe(0)
    expect(movedIndex("ArrowDown", 1, 4)).toBe(2)
    expect(movedIndex("End", 0, 4)).toBe(3)
    expect(movedIndex("PageUp", 3, 30)).toBe(0)
    expect(movedIndex("Tab", 1, 4)).toBeNull()
  })

  it("finds options by the start of their name and cycles on a repeated letter", () => {
    const labels = ["All rules", "Family to Work", "Personal to Work", "Personal to Family"]

    expect(typeaheadIndex(labels, "p", 0)).toBe(2)
    expect(typeaheadIndex(labels, "pp", 2)).toBe(3)
    expect(typeaheadIndex(labels, "pe", 3)).toBe(3)
    expect(typeaheadIndex(labels, "fam", 0)).toBe(1)
    expect(typeaheadIndex(labels, "z", 0)).toBe(-1)
  })
})
