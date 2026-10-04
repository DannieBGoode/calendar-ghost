import english from "./locales/en"
import { pseudoize } from "./pseudo"
import { createI18n, type I18n } from "./translator"

/** English with US formats, matching what the existing tests assert. */
export function testI18n({ formatLocale = "en-US" }: { formatLocale?: string } = {}): I18n {
  return createI18n({ locale: "en", formatLocale, catalog: english })
}

export function pseudoI18n(): I18n {
  return createI18n({ locale: "en", formatLocale: "en-US", catalog: english, transform: pseudoize })
}

/**
 * Month, weekday, and day-period names (such as "Sep", "Wednesday", "PM") that `Intl` writes into
 * formatted dates and times. They come from locale data, not the catalog, so render checks allow them.
 */
export function dateWords(locale = "en-US"): string[] {
  const words = new Set<string>()
  const collect = (options: Intl.DateTimeFormatOptions, date: Date) => {
    for (const part of new Intl.DateTimeFormat(locale, options).formatToParts(date)) {
      if (part.type === "month" || part.type === "weekday" || part.type === "dayPeriod") words.add(part.value)
    }
  }
  for (let month = 0; month < 12; month += 1) {
    for (const style of ["short", "long"] as const) collect({ month: style, day: "numeric" }, new Date(2026, month, 1))
  }
  for (let day = 0; day < 7; day += 1) {
    for (const style of ["short", "long"] as const) collect({ weekday: style }, new Date(2026, 0, 4 + day))
  }
  for (const hour of [9, 21]) collect({ hour: "numeric" }, new Date(2026, 0, 1, hour))
  return [...words]
}

const ALWAYS_ALLOWED = ["Calendar Ghost"]
const ACCESSIBLE_ATTRIBUTES = ["aria-label", "aria-description", "title", "placeholder", "alt"]

/**
 * What is left of `text` after removing allowed fixture data and pseudo-translated segments. The
 * pseudo-locale brackets each literal segment, and rich text can split a segment across nodes, so
 * an unmatched `]` at the start or `[` at the end is a segment's remainder too. Fixture data goes
 * first because it may contain brackets itself, such as a configuration example; pseudo segments
 * hold no ASCII letters, so no fixture value can match inside one.
 */
function residue(text: string, allowed: readonly string[]): string {
  let rest = text
  for (const value of [...allowed].sort((a, b) => b.length - a.length)) rest = rest.split(value).join(" ")
  return rest.replace(/\[[^\]]*\]/g, " ").replace(/^[^[]*\]/, " ").replace(/\[[^\]]*$/, " ").trim()
}

/**
 * Visible and accessible text under `root` that did not come from a catalog when rendered with
 * `pseudoI18n()`: any ASCII letters left outside pseudo segments and allowed fixture data.
 */
export function untranslatedText(root: Element, allowed: readonly string[] = []): string[] {
  const permitted = [...ALWAYS_ALLOWED, ...allowed]
  const found: string[] = []
  const check = (text: string) => {
    if (/[A-Za-z]/.test(residue(text, permitted))) found.push(text.trim())
  }
  const walker = root.ownerDocument.createTreeWalker(root, 4 /* NodeFilter.SHOW_TEXT */)
  for (let node = walker.nextNode(); node; node = walker.nextNode()) check(node.textContent ?? "")
  for (const element of root.querySelectorAll("*")) {
    for (const name of ACCESSIBLE_ATTRIBUTES) {
      const value = element.getAttribute(name)
      if (value) check(value)
    }
  }
  return found
}
