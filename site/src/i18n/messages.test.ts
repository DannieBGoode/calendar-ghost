import { describe, expect, it } from "vitest"
import { en } from "./en"
import { format } from "./format"
import { hasLanguagePicker, localePath, messagesFor } from "./index"

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
    expect(en.hero.chip).toBe("Pre-alpha · Open source (AGPL) · Google Calendar")
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
})

describe("format", () => {
  it("fills placeholders and leaves unknown ones", () => {
    expect(format("{percent}% of {thing}", { percent: 40 })).toBe("40% of {thing}")
  })
})
