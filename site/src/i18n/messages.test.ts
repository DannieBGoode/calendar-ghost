import { describe, expect, it } from "vitest"
import { en } from "./en"
import { format } from "./format"
import { hasLanguagePicker, localePath, messagesFor, stripLocale, type Locale } from "./index"

function strings(value: unknown, path = "en"): [string, string][] {
  if (typeof value === "string") return [[path, value]]
  if (Array.isArray(value)) return value.flatMap((item, index) => strings(item, `${path}[${index}]`))
  if (value && typeof value === "object") {
    return Object.entries(value).flatMap(([key, item]) => strings(item, `${path}.${key}`))
  }
  return []
}

describe("English copy", () => {
  it("has no empty or padded strings", () => {
    const bad = strings(en).filter(([, text]) => text.trim() === "" || text.trim() !== text)
    expect(bad).toEqual([])
  })

  it("never uses an em dash", () => {
    expect(strings(en).filter(([, text]) => text.includes("—"))).toEqual([])
  })

  it("states the approved headline and scope chip", () => {
    expect(en.hero.title).toBe("Sync your calendars. Keep your privacy.")
    expect(en.hero.chip).toBe("Open source (AGPL) · Self-hosted · Google Calendar")
  })

  it("never calls the app pre-alpha", () => {
    expect(strings(en).filter(([, text]) => /pre-?alpha/i.test(text))).toEqual([])
  })

  it("lists everything that never crosses over", () => {
    expect(en.crossing.alwaysStays).toEqual([
      "Guests",
      "Organizer",
      "Meeting links",
      "Attachments",
      "Invitations",
    ])
  })
})

describe("locales", () => {
  it("falls back to English for an unknown locale", () => {
    expect(messagesFor("xx")).toBe(en)
    expect(messagesFor(undefined)).toBe(en)
  })

  it("hides the language picker while English is the only language", () => {
    expect(hasLanguagePicker()).toBe(false)
  })

  it("serves English without a prefix", () => {
    expect(localePath("en", "/")).toBe("/")
    expect(localePath("en", "/404")).toBe("/404")
  })

  it("strips a locale prefix with an exact segment match, leaving English untouched", () => {
    const locales = ["en", "es"]
    expect(stripLocale("/es/", locales)).toBe("/")
    expect(stripLocale("/es", locales)).toBe("/")
    expect(stripLocale("/es/features", locales)).toBe("/features")
    // "esperanto" is not the "es" segment, so it is left alone.
    expect(stripLocale("/esperanto", locales)).toBe("/esperanto")
    // The default locale never carries a prefix, so nothing is stripped.
    expect(stripLocale("/en/features", locales)).toBe("/en/features")
    expect(stripLocale("/features", locales)).toBe("/features")
  })

  it("composes with localePath without doubling the prefix", () => {
    // "es" stands in for a second locale that does not exist yet; cast past the real, narrower
    // `Locale` union (today only "en") to exercise the composition `Layout.astro` and
    // `LanguagePicker.astro` use once one does.
    const locales = ["en", "es"]
    const fakeLocale = "es" as Locale
    expect(localePath(fakeLocale, stripLocale("/es/features", locales))).toBe("/es/features")
    expect(localePath("en", stripLocale("/es/features", locales))).toBe("/features")
  })
})

describe("format", () => {
  it("fills placeholders and leaves unknown ones", () => {
    expect(format("{percent}% of {thing}", { percent: 40 })).toBe("40% of {thing}")
  })
})
