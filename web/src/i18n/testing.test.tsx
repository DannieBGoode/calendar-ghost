/* @vitest-environment happy-dom */
import { describe, expect, it } from "vitest"

import { dateWords, untranslatedText } from "./testing"

function html(markup: string): Element {
  const root = document.createElement("div")
  root.innerHTML = markup
  return root
}

describe("untranslatedText", () => {
  it("accepts pseudo text, interpolated fixtures, and split rich text", () => {
    expect(untranslatedText(html("<p>[Ŕüļéš···]</p><p>[Ðéļéţé ···]Work A[ ñóŵ··]</p><p>[Ðéļéţé <b>··]Work[</b>··]</p>"), ["Work A", "Work"])).toEqual([])
  })
  it("reports English text and English accessible labels", () => {
    expect(untranslatedText(html('<p>[status] Failed</p><button aria-label="Open menu">[Ŕ]</button>'))).toEqual(["[status] Failed", "Open menu"])
  })
})

describe("dateWords", () => {
  it("lists the month, weekday, and day-period names formatted dates contain", () => {
    expect(dateWords()).toEqual(expect.arrayContaining(["Sep", "September", "Wed", "Wednesday", "AM", "PM"]))
    const formatted = new Date(2026, 8, 30, 22).toLocaleString("en-US", { weekday: "short", month: "short", day: "numeric", hour: "numeric" })
    expect(untranslatedText(html(`<p>${formatted}</p>`), dateWords())).toEqual([])
  })
})
