import { describe, expect, it } from "vitest"

import { isTypeaheadKey, listCommand, movedIndex, openingIndex, typeaheadIndex } from "./rule-picker"

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

  it("closes, chooses, or chooses and moves on from the open list", () => {
    expect(listCommand("Escape", false)).toBe("close")
    expect(listCommand("Enter", false)).toBe("choose")
    expect(listCommand(" ", false)).toBe("choose")
    expect(listCommand("ArrowUp", true)).toBe("choose")
    expect(listCommand("Tab", false)).toBe("chooseAndLeave")
    expect(listCommand("ArrowUp", false)).toBeNull()
    expect(listCommand("a", false)).toBeNull()
  })

  it("searches only on printable keys typed without a shortcut modifier", () => {
    expect(isTypeaheadKey({ key: "p", ctrlKey: false, metaKey: false })).toBe(true)
    expect(isTypeaheadKey({ key: " ", ctrlKey: false, metaKey: false })).toBe(false)
    expect(isTypeaheadKey({ key: "ArrowDown", ctrlKey: false, metaKey: false })).toBe(false)
    expect(isTypeaheadKey({ key: "p", ctrlKey: true, metaKey: false })).toBe(false)
    expect(isTypeaheadKey({ key: "p", ctrlKey: false, metaKey: true })).toBe(false)
  })

  it("finds options by the start of their name and cycles on a repeated letter", () => {
    const labels = ["All rules", "Family to Work", "Personal to Work", "Personal to Family"]

    expect(typeaheadIndex(labels, "p", 0, "en")).toBe(2)
    expect(typeaheadIndex(labels, "pp", 2, "en")).toBe(3)
    expect(typeaheadIndex(labels, "pe", 3, "en")).toBe(3)
    expect(typeaheadIndex(labels, "fam", 0, "en")).toBe(1)
    expect(typeaheadIndex(labels, "z", 0, "en")).toBe(-1)
  })
})
