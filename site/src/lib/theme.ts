// Light or Dark for the landing page. With nothing saved the page follows the device; the nav's
// toggle saves an explicit Light or Dark. Mirrors the app's own pattern (web/src/lib/theme.ts), but
// with the site's own localStorage key: the two are different origins with unrelated audiences, so
// a choice on one must never read as a choice on the other.
export type ThemePreference = "light" | "dark"
export type ResolvedTheme = ThemePreference

export const THEME_STORAGE_KEY = "calendar-ghost-site-theme"
export const SYSTEM_DARK_MODE_QUERY = "(prefers-color-scheme: dark)"

/** Browser chrome colors, matching tokens.css's `--background` in each appearance. */
export const THEME_COLORS: Record<ResolvedTheme, string> = {
  light: "#fbfbfe",
  dark: "#0d0e19",
}

type ThemeStorage = Pick<Storage, "getItem" | "setItem">

function browserStorage(): ThemeStorage | null {
  if (typeof window === "undefined") return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

/** A saved choice, or null for none (which includes the old "device" value): follow the device. */
export function parseThemePreference(value: unknown): ThemePreference | null {
  return value === "light" || value === "dark" ? value : null
}

export function readThemePreference(storage: ThemeStorage | null = browserStorage()): ThemePreference | null {
  if (!storage) return null
  try {
    return parseThemePreference(storage.getItem(THEME_STORAGE_KEY))
  } catch {
    return null
  }
}

export function writeThemePreference(
  preference: ThemePreference,
  storage: ThemeStorage | null = browserStorage(),
): boolean {
  if (!storage) return false
  try {
    storage.setItem(THEME_STORAGE_KEY, preference)
    return true
  } catch {
    return false
  }
}

/** The theme on screen: the saved choice, or the device's with none. */
export function resolveTheme(preference: ThemePreference | null, systemPrefersDark: boolean): ResolvedTheme {
  return preference ?? (systemPrefersDark ? "dark" : "light")
}

/** What the toggle saves when pressed: the opposite of the theme on screen. */
export function toggledTheme(shown: ResolvedTheme): ThemePreference {
  return shown === "dark" ? "light" : "dark"
}

export function systemPrefersDark(): boolean {
  return typeof matchMedia === "function" && matchMedia(SYSTEM_DARK_MODE_QUERY).matches
}

/**
 * Applies a preference to the page: an explicit choice sets `data-theme` (so the stylesheets'
 * `:root[data-theme="dark"]` rules win over the media query) and locks `color-scheme` to it, so
 * `light-dark()` follows the choice regardless of the device. None (null) clears both, falling
 * back to `color-scheme: light dark` and the `@media (prefers-color-scheme: dark)` rules. Either
 * way the `theme-color` meta tracks the resolved appearance.
 *
 * Layout.astro's inline head script runs this same logic before first paint, so there is no
 * flash; it is duplicated there in plain JS because it must stay a same-origin inline script
 * (`is:inline`), which cannot import a module.
 */
export function applyThemePreference(
  preference: ThemePreference | null,
  targetDocument: Document | undefined = typeof document === "undefined" ? undefined : document,
): void {
  if (!targetDocument) return

  const root = targetDocument.documentElement
  if (preference === null) {
    delete root.dataset.theme
    root.style.colorScheme = "light dark"
  } else {
    root.dataset.theme = preference
    root.style.colorScheme = preference
  }

  const resolved = resolveTheme(preference, systemPrefersDark())
  let meta = targetDocument.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (!meta) {
    meta = targetDocument.createElement("meta")
    meta.name = "theme-color"
    targetDocument.head.append(meta)
  }
  meta.content = THEME_COLORS[resolved]
}
