import { en, type Messages } from "./en"

export type { Messages }

export const LOCALES = { en } satisfies Record<string, Messages>
export type Locale = keyof typeof LOCALES
const DEFAULT_LOCALE: Locale = "en"

export function messagesFor(locale: string | undefined): Messages {
  return locale && locale in LOCALES ? LOCALES[locale as Locale] : LOCALES[DEFAULT_LOCALE]
}

export function hasLanguagePicker(): boolean {
  return Object.keys(LOCALES).length > 1
}

/** English has no prefix; every other language lives under `/<locale>`. */
export function localePath(locale: Locale, pathname: string): string {
  return locale === DEFAULT_LOCALE ? pathname : `/${locale}${pathname}`
}

/**
 * Removes a leading `/<locale>` segment (exact match only, not a prefix of a longer word) for any
 * non-default locale, so a pathname already under `/es/...` can be handed to `localePath` for
 * another locale without doubling the prefix into `/es/es/...`.
 */
export function stripLocale(pathname: string, locales: readonly string[] = Object.keys(LOCALES)): string {
  for (const locale of locales) {
    if (locale === DEFAULT_LOCALE) continue
    if (pathname === `/${locale}`) return "/"
    if (pathname.startsWith(`/${locale}/`)) return pathname.slice(locale.length + 1)
  }
  return pathname
}
