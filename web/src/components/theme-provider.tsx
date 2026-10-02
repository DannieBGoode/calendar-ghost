import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react"

import {
  applyTheme,
  DARK_PALETTE_STORAGE_KEY,
  DEFAULT_DARK_PALETTE,
  parseDarkPalette,
  parseThemePreference,
  readDarkPalette,
  readThemePreference,
  resolveTheme,
  SYSTEM_DARK_MODE_QUERY,
  THEME_STORAGE_KEY,
  writeDarkPalette,
  writeThemePreference,
  type DarkPalette,
  type ResolvedTheme,
  type ThemePreference,
} from "@/lib/theme"

type ThemeContextValue = {
  preference: ThemePreference
  resolvedTheme: ResolvedTheme
  setPreference: (preference: ThemePreference) => void
  darkPalette: DarkPalette
  setDarkPalette: (palette: DarkPalette) => void
}

type ThemeProviderProps = {
  children: ReactNode
  defaultPreference?: ThemePreference
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function systemPrefersDark(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(SYSTEM_DARK_MODE_QUERY).matches
  )
}

function subscribeToSystemPreference(onChange: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {}

  const mediaQuery = window.matchMedia(SYSTEM_DARK_MODE_QUERY)
  mediaQuery.addEventListener("change", onChange)
  return () => mediaQuery.removeEventListener("change", onChange)
}

export function ThemeProvider({ children, defaultPreference = "system" }: ThemeProviderProps) {
  const [preference, setPreferenceState] = useState<ThemePreference>(
    () => readThemePreference() ?? defaultPreference,
  )
  const prefersDark = useSyncExternalStore(
    subscribeToSystemPreference,
    systemPrefersDark,
    () => false,
  )
  const [darkPalette, setDarkPaletteState] = useState<DarkPalette>(
    () => readDarkPalette() ?? DEFAULT_DARK_PALETTE,
  )
  const resolvedTheme = resolveTheme(preference, prefersDark)

  const setPreference = useCallback((nextPreference: ThemePreference) => {
    setPreferenceState(nextPreference)
    writeThemePreference(nextPreference)
  }, [])

  const setDarkPalette = useCallback((nextPalette: DarkPalette) => {
    setDarkPaletteState(nextPalette)
    writeDarkPalette(nextPalette)
  }, [])

  useLayoutEffect(() => {
    applyTheme(resolvedTheme, darkPalette)
  }, [resolvedTheme, darkPalette])

  useEffect(() => {
    if (typeof window === "undefined") return

    const handleStorage = (event: StorageEvent) => {
      // A null key means another tab cleared storage, which resets both choices.
      if (event.key === THEME_STORAGE_KEY || event.key === null) {
        setPreferenceState(parseThemePreference(event.newValue) ?? defaultPreference)
      }
      if (event.key === DARK_PALETTE_STORAGE_KEY || event.key === null) {
        setDarkPaletteState(parseDarkPalette(event.newValue) ?? DEFAULT_DARK_PALETTE)
      }
    }

    window.addEventListener("storage", handleStorage)
    return () => window.removeEventListener("storage", handleStorage)
  }, [defaultPreference])

  const value = useMemo(
    () => ({ preference, resolvedTheme, setPreference, darkPalette, setDarkPalette }),
    [preference, resolvedTheme, setPreference, darkPalette, setDarkPalette],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

// The hook and provider intentionally share their private context boundary.
// eslint-disable-next-line react-refresh/only-export-components
export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext)
  if (!context) throw new Error("useTheme must be used within a ThemeProvider")
  return context
}
