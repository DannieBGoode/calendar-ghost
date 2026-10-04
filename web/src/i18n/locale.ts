export const LOCALE_STORAGE_KEY = "calendar-sync-locale"
/** Dev-only query value (`?locale=pseudo`) that shows every message accented and lengthened. */
export const PSEUDO_LOCALE = "pseudo"

type LocaleStorage = Pick<Storage, "getItem">

function browserStorage(): LocaleStorage | null {
  if (typeof window === "undefined") return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

const base = (tag: string) => (tag.split("-")[0] ?? tag).toLowerCase()

export function readLocalePreference(available: readonly string[], storage: LocaleStorage | null = browserStorage()): string | null {
  if (!storage) return null
  try {
    const value = storage.getItem(LOCALE_STORAGE_KEY)
    return value !== null && available.includes(value) ? value : null
  } catch {
    return null
  }
}

/** The saved language, then the browser's full tags, then their base languages, then English. */
export function resolveLocale(preference: string | null, browser: readonly string[], available: readonly string[]): string {
  if (preference !== null && available.includes(preference)) return preference
  for (const tag of browser) {
    const exact = available.find((candidate) => candidate.toLowerCase() === tag.toLowerCase())
    if (exact) return exact
    const sameLanguage = available.find((candidate) => candidate.toLowerCase() === base(tag))
    if (sameLanguage) return sameLanguage
  }
  return "en"
}

/**
 * Whether `Intl` has formats for exactly this tag. `supportedLocalesOf` alone also accepts a tag
 * it can only serve through its base language, such as "en-ZZ"; the resolved locale tells them apart.
 */
function formatsFor(tag: string): boolean {
  try {
    return Intl.DateTimeFormat.supportedLocalesOf([tag]).length > 0 && new Intl.DateTimeFormat(tag).resolvedOptions().locale === tag
  } catch {
    // An invalid tag throws a RangeError.
    return false
  }
}

/** The region of a browser tag, such as "DE" for "de-DE"; null for a bare language or an invalid tag. */
function regionOf(tag: string): string | null {
  try {
    return new Intl.Locale(tag).region ?? null
  } catch {
    return null
  }
}

/**
 * The tag dates and numbers use, so they follow the browser's region as they did before the UI
 * was translatable:
 * - the first browser tag in the UI language, so an English UI in an en-GB browser keeps day-month
 *   dates and a 24-hour clock;
 * - otherwise the UI language in the first browser tag's region, so an English UI in a de-DE
 *   browser formats as en-DE (24-hour clock, day before month);
 * - otherwise the UI language itself.
 */
export function resolveFormatLocale(locale: string, browser: readonly string[]): string {
  const sameLanguage = browser.find((tag) => base(tag) === base(locale) && formatsFor(tag))
  if (sameLanguage) return sameLanguage
  const [first] = browser
  const region = first === undefined ? null : regionOf(first)
  const regional = region ? `${base(locale)}-${region}` : null
  return regional && formatsFor(regional) ? regional : locale
}
