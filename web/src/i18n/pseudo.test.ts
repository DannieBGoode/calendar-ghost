import { describe, expect, it } from "vitest"

import { pseudoize } from "./pseudo"

describe("pseudoize", () => {
  it("accents letters, keeps punctuation, and lengthens", () => {
    expect(pseudoize("Rules.")).toBe("[Ŕüļéš.···]")
  })
  it("keeps rich-text tags", () => {
    expect(pseudoize("Delete <strong>now</strong>")).toBe("[Ðéļéţé <strong>ñóŵ</strong>··········]")
  })
  it("leaves empty text alone", () => expect(pseudoize("")).toBe(""))
})
