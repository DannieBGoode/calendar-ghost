import { describe, expect, it } from "vitest"
import { en } from "./en"
import { format } from "./format"
import { SAM_WEEK } from "../demo/week"
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
    expect(strings(en).filter(([, text]) => text.includes("\u2014"))).toEqual([])
  })

  it("states the approved headline, one sentence per line", () => {
    expect(en.hero.titleLines).toEqual(["Sync your calendars.", "Keep your privacy."])
  })

  it("never calls the app pre-alpha", () => {
    expect(strings(en).filter(([, text]) => /pre-?alpha/i.test(text))).toEqual([])
  })

  it("distinguishes website analytics from the installed application's no-telemetry promise", () => {
    expect(en.meta.description).toContain("with no app telemetry")
    expect(en.meta.description).not.toContain("no trackers")
    expect(en.footer.privacy).toBe("Website analytics, no app telemetry.")
    expect(en.footer.privacyBody).toBe(
      "calendarghost.com uses cookieless Umami Cloud to count visits, referrers, campaigns, and selected clicks. The tracker runs through calendarghost.com and does not follow you across sites. The installed application sends no analytics or telemetry.",
    )
    expect(en.trust.cards).toContainEqual({
      title: "No app telemetry",
      body: "The installed application talks only to Google, Microsoft, and the notification targets you set up.",
    })
  })

  it("says in the With details bubble what crossed over and what stayed home", () => {
    expect(en.ghost.crossingBusy).toBe("Dentist? What dentist?")
    expect(en.ghost.crossingDetails).toBe("Title and place came along. The guest list stayed home.")
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

describe("the Activity mockup", () => {
  const clock = (hours: number) => `${String(Math.floor(hours)).padStart(2, "0")}:${hours % 1 ? "30" : "00"}`

  it("tells Sam's week as the rest of the page does: each event of the week at its own day and time", () => {
    const titles = new Map(Object.entries(en.demo.events).map(([key, event]) => [event.title, key]))
    const fromWeek = en.app.activity.rows.filter((row) => titles.has(row.title))
    expect(fromWeek.map((row) => row.title)).toEqual(["Dentist", "Gym", "School drop-off"])
    for (const row of fromWeek) {
      const event = SAM_WEEK.find((item) => item.key === titles.get(row.title))!
      expect(row.when).toBe(`${en.demo.days[event.day]} ${clock(event.start)}–${clock(event.end)}`)
    }
  })

  it("names no event the week shows during working hours as removed or skipped", () => {
    // A removed or skipped event is not on Work, so it must not be one the week shows there.
    const weekTitles = new Set(Object.values(en.demo.events).map((event) => event.title))
    for (const row of en.app.activity.rows.filter((item) => /^(Removed|Skipped)/.test(item.outcome))) {
      expect(weekTitles.has(row.title)).toBe(false)
    }
  })
})
