import { en, type Messages } from "./en"

export type { Messages }

export const LOCALES = { en } satisfies Record<string, Messages>
export type Locale = keyof typeof LOCALES
export const DEFAULT_LOCALE: Locale = "en"

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
