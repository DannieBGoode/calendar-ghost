import { describe, expect, it } from "vitest"
import { en } from "./en"
import { codeParts } from "./code"

describe("codeParts", () => {
  it("marks the text between backticks as code", () => {
    expect(codeParts("Alert when `needs_attention` is `true`")).toEqual([
      { text: "Alert when ", code: false },
      { text: "needs_attention", code: true },
      { text: " is ", code: false },
      { text: "true", code: true },
    ])
  })

  it("leaves plain text alone", () => {
    expect(codeParts("Healthy")).toEqual([{ text: "Healthy", code: false }])
  })

  it("finds every backtick paired in the integrations copy", () => {
    const strings = JSON.stringify(en.integrations).match(/"(?:[^"\\]|\\.)*"/g) ?? []
    for (const text of strings) expect((text.match(/`/g) ?? []).length % 2, text).toBe(0)
  })
})
