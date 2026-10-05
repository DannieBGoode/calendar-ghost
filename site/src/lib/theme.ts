// Device, Light, or Dark for the landing page. Mirrors the app's own pattern
// (web/src/lib/theme.ts), but with the site's own localStorage key: the two are different
// origins with unrelated audiences, so a choice on one must never read as a choice on the other.
export type ThemePreference = "device" | "light" | "dark"
export type ResolvedTheme = Exclude<ThemePreference, "device">

export const THEME_STORAGE_KEY = "calendar-ghost-site-theme"
export const SYSTEM_DARK_MODE_QUERY = "(prefers-color-scheme: dark)"

/** Browser chrome colors, matching tokens.css's `--background` in each appearance. */
export const THEME_COLORS: Record<ResolvedTheme, string> = {
  light: "#fbfbfe",
  dark: "#0d0e19",
}

/** The order the toggle button cycles through on each click. */
const PREFERENCE_ORDER: readonly ThemePreference[] = ["device", "light", "dark"]

type ThemeStorage = Pick<Storage, "getItem" | "setItem">

function browserStorage(): ThemeStorage | null {
  if (typeof window === "undefined") return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function parseThemePreference(value: unknown): ThemePreference | null {
  return value === "device" || value === "light" || value === "dark" ? value : null
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

/** The next state in the Device, Light, Dark cycle the toggle button steps through. */
export function nextThemePreference(preference: ThemePreference): ThemePreference {
  return PREFERENCE_ORDER[(PREFERENCE_ORDER.indexOf(preference) + 1) % PREFERENCE_ORDER.length]!
}

export function resolveTheme(preference: ThemePreference, systemPrefersDark: boolean): ResolvedTheme {
  if (preference !== "device") return preference
  return systemPrefersDark ? "dark" : "light"
}

function systemPrefersDark(): boolean {
  return typeof matchMedia === "function" && matchMedia(SYSTEM_DARK_MODE_QUERY).matches
}

/**
 * Applies a preference to the page: an explicit choice sets `data-theme` (so the stylesheets'
 * `:root[data-theme="dark"]` rules win over the media query) and locks `color-scheme` to it, so
 * `light-dark()` follows the choice regardless of the device. Device clears both, falling back to
 * `color-scheme: light dark` and the `@media (prefers-color-scheme: dark)` rules. Either way the
 * `theme-color` meta tracks the resolved appearance.
 *
 * Layout.astro's inline head script runs this same logic before first paint, so there is no
 * flash; it is duplicated there in plain JS because it must stay a same-origin inline script
 * (`is:inline`), which cannot import a module.
 */
export function applyThemePreference(
  preference: ThemePreference,
  targetDocument: Document | undefined = typeof document === "undefined" ? undefined : document,
): void {
  if (!targetDocument) return

  const root = targetDocument.documentElement
  if (preference === "device") {
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
