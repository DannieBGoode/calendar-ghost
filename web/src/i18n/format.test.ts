import { describe, expect, it } from "vitest"

import { testI18n } from "./testing"

describe("formatters", () => {
  const { format } = testI18n()

  it("formats bytes like the storage summary did", () => {
    expect(format.bytes(0)).toBe("0 B")
    expect(format.bytes(512)).toBe("512 B")
    expect(format.bytes(1536)).toBe("1.5 KB")
    expect(format.bytes(5 * 1024 * 1024)).toBe("5.0 MB")
    expect(format.bytes(48.2 * 1024 * 1024)).toBe("48.2 MB")
    expect(format.bytes(3 * 1024 ** 3)).toBe("3.0 GB")
  })

  it("formats bytes with the locale's decimal separator", () => {
    expect(testI18n({ formatLocale: "de-DE" }).format.bytes(1536)).toBe("1,5 KB")
  })

  it("joins lists in the locale's words", () => {
    expect(format.list(["Title", "description", "location"])).toBe("Title, description, and location")
  })

  it("joins lists in the UI language, whatever the browser's region", () => {
    // en-GB would drop the serial comma; the English UI keeps it, as it did before translation.
    const british = testI18n({ formatLocale: "en-GB" }).format
    expect(british.list(["Title", "description", "location"])).toBe("Title, description, and location")
    expect(british.unitList(["a@example.test", "b@example.test"])).toBe("a@example.test, b@example.test")
  })

  it("keeps a three-letter September in English short days", () => {
    expect(testI18n({ formatLocale: "en-GB" }).format.shortDay("2026-09-03T12:00:00Z")).toBe("3 Sep 2026")
    expect(format.shortDay("2026-09-03T12:00:00Z", false)).toBe("Sep 3")
  })

  it("describes relative times", () => {
    const now = Date.parse("2026-10-03T12:00:00Z")
    expect(format.relative("2026-10-03T11:59:30Z", now)).toBe("just now")
    expect(format.relative("2026-10-03T11:55:00Z", now)).toBe("5 minutes ago")
    expect(format.relative("2026-10-03T09:00:00Z", now)).toBe("3 hours ago")
    expect(format.relative("2026-10-02T12:00:00Z", now)).toBe("yesterday")
    expect(format.relative("not a date", now)).toBe("at an unknown time")
    expect(format.relative("2026-09-20T12:00:00Z", now)).toBe("on Sep 20")
  })

  it("formats clock times", () => {
    // ICU separates the day period with a narrow no-break space (U+202F), which \s matches.
    expect(format.time(new Date(2026, 9, 3, 14, 5))).toMatch(/^2:05\sPM$/)
    expect(testI18n({ formatLocale: "en-GB" }).format.time(new Date(2026, 9, 3, 14, 5))).toBe("14:05")
  })
})
