export type ThemePreference = "system" | "light" | "dark"
export type ResolvedTheme = Exclude<ThemePreference, "system">
/** The colors used whenever the interface is dark, by choice or by following the device. */
export type DarkPalette = "twilight" | "midnight"

export const THEME_STORAGE_KEY = "calendar-sync-theme"
export const DARK_PALETTE_STORAGE_KEY = "calendar-sync-dark-palette"
export const DEFAULT_DARK_PALETTE: DarkPalette = "twilight"
export const SYSTEM_DARK_MODE_QUERY = "(prefers-color-scheme: dark)"

/** Browser chrome colors, matching each appearance's `--background`. */
export const THEME_COLORS: Record<"light" | DarkPalette, string> = {
  light: "#fbfbfe",
  twilight: "#0d0e19",
  midnight: "#05101c",
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

export function parseDarkPalette(value: unknown): DarkPalette | null {
  return value === "twilight" || value === "midnight" ? value : null
}

function readStored(storage: ThemeStorage | null, key: string): string | null {
  if (!storage) return null

  try {
    return storage.getItem(key)
  } catch {
    return null
  }
}

function writeStored(storage: ThemeStorage | null, key: string, value: string): boolean {
  if (!storage) return false

  try {
    storage.setItem(key, value)
    return true
  } catch {
    return false
  }
}

export function readThemePreference(
  storage: ThemeStorage | null = browserStorage(),
): ThemePreference | null {
  return parseThemePreference(readStored(storage, THEME_STORAGE_KEY))
}

export function writeThemePreference(
  preference: ThemePreference,
  storage: ThemeStorage | null = browserStorage(),
): boolean {
  return writeStored(storage, THEME_STORAGE_KEY, preference)
}

export function readDarkPalette(
  storage: ThemeStorage | null = browserStorage(),
): DarkPalette | null {
  return parseDarkPalette(readStored(storage, DARK_PALETTE_STORAGE_KEY))
}

export function writeDarkPalette(
  palette: DarkPalette,
  storage: ThemeStorage | null = browserStorage(),
): boolean {
  return writeStored(storage, DARK_PALETTE_STORAGE_KEY, palette)
}

export function resolveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ResolvedTheme {
  if (preference !== "system") return preference
  return systemPrefersDark ? "dark" : "light"
}

export function themeColor(theme: ResolvedTheme, palette: DarkPalette): string {
  return THEME_COLORS[theme === "light" ? "light" : palette]
}

export function applyTheme(
  theme: ResolvedTheme,
  palette: DarkPalette,
  targetDocument: Document | undefined = typeof document === "undefined" ? undefined : document,
): void {
  if (!targetDocument) return

  const root = targetDocument.documentElement
  root.dataset.theme = theme
  // Stylesheets apply the palette only under the dark theme.
  root.dataset.palette = palette
  root.style.colorScheme = theme

  let meta = targetDocument.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (!meta) {
    meta = targetDocument.createElement("meta")
    meta.name = "theme-color"
    targetDocument.head.append(meta)
  }
  meta.content = themeColor(theme, palette)
}
