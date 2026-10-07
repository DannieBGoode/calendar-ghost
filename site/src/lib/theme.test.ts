import { describe, expect, it } from "vitest"
import {
  applyThemePreference,
  parseThemePreference,
  readThemePreference,
  resolveTheme,
  THEME_COLORS,
  THEME_STORAGE_KEY,
  toggledTheme,
  writeThemePreference,
} from "./theme"

function fakeStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial))
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      data.set(key, value)
    },
  }
}

describe("parseThemePreference", () => {
  it("accepts only Light and Dark; anything else, the old Device included, means none saved", () => {
    expect(parseThemePreference("light")).toBe("light")
    expect(parseThemePreference("dark")).toBe("dark")
    expect(parseThemePreference("device")).toBeNull()
    expect(parseThemePreference("system")).toBeNull()
    expect(parseThemePreference(null)).toBeNull()
    expect(parseThemePreference(undefined)).toBeNull()
  })
})

describe("toggledTheme", () => {
  it("saves the opposite of the theme on screen", () => {
    expect(toggledTheme("light")).toBe("dark")
    expect(toggledTheme("dark")).toBe("light")
  })
})

describe("resolveTheme", () => {
  it("follows the device only when nothing is saved", () => {
    expect(resolveTheme(null, true)).toBe("dark")
    expect(resolveTheme(null, false)).toBe("light")
    expect(resolveTheme("light", true)).toBe("light")
    expect(resolveTheme("dark", false)).toBe("dark")
  })
})

describe("reading and writing the preference", () => {
  it("round-trips through storage under the site's own key", () => {
    const storage = fakeStorage()
    expect(readThemePreference(storage)).toBeNull()
    writeThemePreference("dark", storage)
    expect(storage.getItem(THEME_STORAGE_KEY)).toBe("dark")
    expect(readThemePreference(storage)).toBe("dark")
  })

  it("ignores a stored value from something else", () => {
    const storage = fakeStorage({ [THEME_STORAGE_KEY]: "midnight" })
    expect(readThemePreference(storage)).toBeNull()
  })

  it("returns null without throwing when storage is unavailable", () => {
    expect(readThemePreference(null)).toBeNull()
    expect(writeThemePreference("light", null)).toBe(false)
  })
})

describe("applyThemePreference", () => {
  it("sets data-theme and locks color-scheme for an explicit choice", () => {
    document.head.innerHTML = '<meta name="theme-color" content="#fbfbfe">'
    applyThemePreference("dark")
    expect(document.documentElement.dataset.theme).toBe("dark")
    expect(document.documentElement.style.colorScheme).toBe("dark")
    expect(document.querySelector('meta[name="theme-color"]')?.getAttribute("content")).toBe(THEME_COLORS.dark)
  })

  it("clears data-theme and widens color-scheme when nothing is saved", () => {
    document.documentElement.dataset.theme = "dark"
    applyThemePreference(null)
    expect(document.documentElement.dataset.theme).toBeUndefined()
    expect(document.documentElement.style.colorScheme).toBe("light dark")
  })

  it("creates the theme-color meta if the page has none", () => {
    document.head.innerHTML = ""
    applyThemePreference("light")
    expect(document.querySelector('meta[name="theme-color"]')?.getAttribute("content")).toBe(THEME_COLORS.light)
  })
})
