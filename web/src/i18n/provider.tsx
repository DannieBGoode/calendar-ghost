import { createContext, useContext, useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from "react"

import { GhostMark } from "@/components/ghost-mark"
import { PRODUCT_NAME } from "@/lib/brand"

import { LOCALES, type LocaleEntry } from "./locales"
import english from "./locales/en"
import { PSEUDO_LOCALE, readLocalePreference, resolveFormatLocale, resolveLocale } from "./locale"
import { createI18n, type I18n } from "./translator"
import type { Catalog } from "./types"

const I18nContext = createContext<I18n | null>(null)

function browserLanguages(): readonly string[] {
  if (typeof navigator === "undefined") return []
  // Some browsers report an empty list; `navigator.language` still names the UI language.
  if (navigator.languages.length) return navigator.languages
  return navigator.language ? [navigator.language] : []
}

const pseudoRequested = () => typeof window !== "undefined" && new URLSearchParams(window.location.search).get("locale") === PSEUDO_LOCALE

export function I18nProvider({ children, locales = LOCALES }: { children: ReactNode; locales?: readonly LocaleEntry[] }) {
  const tags = useMemo(() => locales.map((entry) => entry.tag), [locales])
  const [preference] = useState(() => readLocalePreference(tags))
  const locale = resolveLocale(preference, browserLanguages(), tags)
  // `tag` is the language asked for; `language` is the one shown, English after a failed load.
  const [loaded, setLoaded] = useState<{ tag: string; language: string; catalog: Catalog }>({ tag: "en", language: "en", catalog: english })
  const [transform, setTransform] = useState<((text: string) => string) | undefined>(undefined)

  useEffect(() => {
    if (loaded.tag === locale) return
    const entry = locales.find((candidate) => candidate.tag === locale)
    let current = true
    void (entry ? entry.load() : Promise.resolve(english as Catalog))
      .then((catalog) => ({ tag: locale, language: locale, catalog }))
      .catch((error: unknown) => {
        // A missing chunk after an upgrade must not leave the page blank.
        console.warn(`i18n: could not load "${locale}"; showing English`, error)
        return { tag: locale, language: "en", catalog: english }
      })
      .then((next) => current && setLoaded(next))
    return () => {
      current = false
    }
  }, [locale, locales, loaded.tag])

  useEffect(() => {
    // `import.meta.env.DEV` is a build-time constant, so production drops the import and its chunk.
    if (import.meta.env.DEV && pseudoRequested()) {
      import("./pseudo")
        .then(({ pseudoize }) => setTransform(() => pseudoize))
        // The pseudo-locale is a development check; without it the page stays in its language.
        .catch((error: unknown) => console.warn("i18n: could not load the pseudo-locale", error))
    }
  }, [])

  const i18n = useMemo(
    () => createI18n({ locale: loaded.language, formatLocale: resolveFormatLocale(loaded.language, browserLanguages()), catalog: loaded.catalog, transform }),
    [loaded, transform],
  )

  useLayoutEffect(() => {
    document.documentElement.lang = i18n.locale
  }, [i18n.locale])

  if (loaded.tag !== locale) {
    return (
      <div className="startup-loading" role="status" aria-busy="true" aria-label={PRODUCT_NAME}>
        <GhostMark className="startup-ghost" />
      </div>
    )
  }
  return <I18nContext.Provider value={i18n}>{children}</I18nContext.Provider>
}

/** Provides a fixed translator, for tests and isolated renders. */
export function StaticI18nProvider({ i18n, children }: { i18n: I18n; children: ReactNode }) {
  return <I18nContext.Provider value={i18n}>{children}</I18nContext.Provider>
}

// The hook and providers intentionally share their private context boundary, as useTheme does.
// eslint-disable-next-line react-refresh/only-export-components
export function useI18n(): I18n {
  const i18n = useContext(I18nContext)
  if (!i18n) throw new Error("useI18n needs an I18nProvider")
  return i18n
}
