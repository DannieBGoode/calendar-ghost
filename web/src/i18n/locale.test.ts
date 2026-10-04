import { describe, expect, it } from "vitest"

import {
  LOCALE_STORAGE_KEY,
  readLocalePreference,
  resolveFormatLocale,
  resolveLocale,
} from "./locale"
import { createFormatters } from "./format"
import { testI18n } from "./testing"

function memoryStorage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial))
  return { getItem: (key: string) => values.get(key) ?? null }
}
const failingStorage = {
  getItem: () => {
    throw new Error("blocked")
  },
}

describe("resolveLocale", () => {
  const available = ["en", "de", "pt-BR"]
  it("prefers a saved choice", () => expect(resolveLocale("de", ["en-US"], available)).toBe("de"))
  it("ignores a saved choice that is no longer shipped", () => expect(resolveLocale("fr", ["de-AT"], available)).toBe("de"))
  it("matches a full browser tag before its base language", () => expect(resolveLocale(null, ["pt-BR"], available)).toBe("pt-BR"))
  it("matches a browser base language", () => expect(resolveLocale(null, ["de-CH", "en"], available)).toBe("de"))
  it("matches case-insensitively", () => expect(resolveLocale(null, ["PT-br"], available)).toBe("pt-BR"))
  it("falls back to English", () => expect(resolveLocale(null, ["ja-JP"], available)).toBe("en"))
  it("falls back to English without browser languages", () => expect(resolveLocale(null, [], available)).toBe("en"))
})

describe("resolveFormatLocale", () => {
  it("uses the first browser tag of the same language", () => expect(resolveFormatLocale("en", ["de-DE", "en-GB"])).toBe("en-GB"))
  it("uses the UI language in the browser's region when no browser tag shares the language", () => {
    expect(resolveFormatLocale("en", ["de-DE"])).toBe("en-DE")
    expect(resolveFormatLocale("en", ["fr-FR", "de-DE"])).toBe("en-FR")
  })
  it("uses the UI language when the browser names no region", () => expect(resolveFormatLocale("en", ["de"])).toBe("en"))
  it("uses the UI language when Intl has no formats for that region", () => {
    expect(resolveFormatLocale("en", ["xx-ZZ"])).toBe("en")
  })
  it("uses the UI language without browser languages", () => expect(resolveFormatLocale("en", [])).toBe("en"))
  it("ignores an invalid browser tag", () => expect(resolveFormatLocale("en", ["en-!!"])).toBe("en"))
  it("gives an English UI in a German browser a 24-hour clock and the day before the month", () => {
    const formatLocale = resolveFormatLocale("en", ["de-DE"])
    const format = createFormatters(formatLocale, testI18n().t)
    const afternoon = new Date(2026, 9, 4, 14, 30)
    expect(format.time(afternoon)).toBe("14:30")
    expect(format.date(afternoon, { day: "numeric", month: "short" })).toBe("4 Oct")
  })
})

describe("locale preference storage", () => {
  it("reads only shipped languages", () => {
    expect(readLocalePreference(["en"], memoryStorage({ [LOCALE_STORAGE_KEY]: "en" }))).toBe("en")
    expect(readLocalePreference(["en"], memoryStorage({ [LOCALE_STORAGE_KEY]: "xx" }))).toBeNull()
  })
  it("survives blocked storage", () => {
    expect(readLocalePreference(["en"], failingStorage)).toBeNull()
  })
  it("tolerates no storage at all", () => expect(readLocalePreference(["en"], null)).toBeNull())
})
