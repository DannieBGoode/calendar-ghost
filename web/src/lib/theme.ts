export type ThemePreference = "system" | "light" | "dark"
export type ResolvedTheme = Exclude<ThemePreference, "system">

export const THEME_STORAGE_KEY = "calendar-sync-theme"
export const SYSTEM_DARK_MODE_QUERY = "(prefers-color-scheme: dark)"

const THEME_COLORS: Record<ResolvedTheme, string> = {
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

export function parseThemePreference(value: unknown): ThemePreference | null {
  return value === "system" || value === "light" || value === "dark" ? value : null
}

export function readThemePreference(
  storage: ThemeStorage | null = browserStorage(),
): ThemePreference | null {
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

export function resolveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ResolvedTheme {
  if (preference !== "system") return preference
  return systemPrefersDark ? "dark" : "light"
}

export function applyTheme(
  theme: ResolvedTheme,
  targetDocument: Document | undefined = typeof document === "undefined" ? undefined : document,
): void {
  if (!targetDocument) return

  const root = targetDocument.documentElement
  root.dataset.theme = theme
  root.style.colorScheme = theme

  let themeColor = targetDocument.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (!themeColor) {
    themeColor = targetDocument.createElement("meta")
    themeColor.name = "theme-color"
    targetDocument.head.append(themeColor)
  }
  themeColor.content = THEME_COLORS[theme]
}
