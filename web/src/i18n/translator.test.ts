import { describe, expect, it, vi } from "vitest"

import { createI18n } from "./translator"
import type { Catalog, MessageKey } from "./types"

const english: Catalog = {
  greeting: "Hello {name}",
  rules: { one: "{count} rule", other: "{count} rules" },
  onlyEnglish: "Fallback",
}
const french: Catalog = {
  greeting: "Bonjour {name}",
  rules: { one: "{count} règle", many: "{count} de règles", other: "{count} règles" },
}
const key = (value: string) => value as MessageKey

describe("createI18n", () => {
  it("fills placeholders", () => {
    const i18n = createI18n({ locale: "en", catalog: english, fallback: english })
    expect(i18n.t(key("greeting"), { name: "Sam" })).toBe("Hello Sam")
  })

  it("selects English plural forms by count", () => {
    const i18n = createI18n({ locale: "en", catalog: english, fallback: english })
    expect(i18n.t(key("rules"), { count: 1 })).toBe("1 rule")
    expect(i18n.t(key("rules"), { count: 0 })).toBe("0 rules")
  })

  it("selects French plural forms, where zero is singular", () => {
    const i18n = createI18n({ locale: "fr", catalog: french, fallback: english })
    expect(i18n.t(key("rules"), { count: 0 })).toBe("0 règle")
    expect(i18n.t(key("rules"), { count: 2 })).toBe("2 règles")
  })

  it("formats numeric parameters for the locale", () => {
    const en = createI18n({ locale: "en", catalog: english, fallback: english })
    const de = createI18n({ locale: "de", catalog: english, fallback: english })
    expect(en.t(key("rules"), { count: 1234 })).toBe("1,234 rules")
    expect(de.t(key("rules"), { count: 1234 })).toBe("1.234 rules")
  })

  it("falls back to English for a key the catalog lacks", () => {
    const i18n = createI18n({ locale: "fr", catalog: french, fallback: english })
    expect(i18n.t(key("onlyEnglish"))).toBe("Fallback")
  })

  it("throws on a missing parameter under test", () => {
    const i18n = createI18n({ locale: "en", catalog: english, fallback: english })
    expect(() => i18n.t(key("greeting"))).toThrow("missing parameter {name}")
  })

  it("throws on an unknown key under test", () => {
    const i18n = createI18n({ locale: "en", catalog: english, fallback: english })
    expect(() => i18n.t(key("nope"))).toThrow("missing message")
  })

  it("reports whether a key built at runtime has a message", () => {
    const i18n = createI18n({ locale: "fr", catalog: french, fallback: english })
    expect(i18n.has("greeting")).toBe(true)
    expect(i18n.has("onlyEnglish")).toBe(true)
    expect(i18n.has("rules")).toBe(true)
    expect(i18n.has("absent")).toBe(false)
  })

  it("leaves the placeholder and warns once outside tests", () => {
    vi.stubEnv("MODE", "production")
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined)
    const i18n = createI18n({ locale: "en", catalog: english, fallback: english })
    expect(i18n.t(key("greeting"))).toBe("Hello {name}")
    i18n.t(key("greeting"))
    expect(warn).toHaveBeenCalledTimes(1)
    vi.unstubAllEnvs()
    warn.mockRestore()
  })

  it("applies a transform to templates but keeps placeholders", () => {
    const i18n = createI18n({ locale: "en", catalog: english, fallback: english, transform: (text) => text.toUpperCase() })
    expect(i18n.t(key("greeting"), { name: "Sam" })).toBe("HELLO Sam")
  })
})
