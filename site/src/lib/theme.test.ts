import { describe, expect, it } from "vitest"
import {
  applyThemePreference,
  nextThemePreference,
  parseThemePreference,
  readThemePreference,
  resolveTheme,
  THEME_COLORS,
  THEME_STORAGE_KEY,
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
  it("accepts only the three known preferences", () => {
    expect(parseThemePreference("device")).toBe("device")
    expect(parseThemePreference("light")).toBe("light")
    expect(parseThemePreference("dark")).toBe("dark")
    expect(parseThemePreference("system")).toBeNull()
    expect(parseThemePreference(null)).toBeNull()
    expect(parseThemePreference(undefined)).toBeNull()
  })
})

describe("nextThemePreference", () => {
  it("cycles Device, Light, Dark, Device", () => {
    expect(nextThemePreference("device")).toBe("light")
    expect(nextThemePreference("light")).toBe("dark")
    expect(nextThemePreference("dark")).toBe("device")
  })
})

describe("resolveTheme", () => {
  it("follows the device only when the preference is Device", () => {
    expect(resolveTheme("device", true)).toBe("dark")
    expect(resolveTheme("device", false)).toBe("light")
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

  it("clears data-theme and widens color-scheme for Device", () => {
    document.documentElement.dataset.theme = "dark"
    applyThemePreference("device")
    expect(document.documentElement.dataset.theme).toBeUndefined()
    expect(document.documentElement.style.colorScheme).toBe("light dark")
  })

  it("creates the theme-color meta if the page has none", () => {
    document.head.innerHTML = ""
    applyThemePreference("light")
    expect(document.querySelector('meta[name="theme-color"]')?.getAttribute("content")).toBe(THEME_COLORS.light)
  })
})
