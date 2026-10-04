import { describe, expect, it } from "vitest"

const sources = import.meta.glob(["../**/*.{ts,tsx}", "!../**/product-name.test.ts"], {
  query: "?raw",
  import: "default",
  eager: true,
})

describe("product name", () => {
  it("never shows the retired name", () => {
    const stale = Object.entries(sources)
      .filter(([, text]) => /Calendar Sync\b/.test(text))
      .map(([path]) => path)
    expect(stale).toEqual([])
  })
})
