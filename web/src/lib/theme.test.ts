import { describe, expect, it } from "vitest"

import bootstrapHtml from "../../index.html?raw"
import {
  applyTheme,
  DARK_PALETTE_STORAGE_KEY,
  parseDarkPalette,
  parseThemePreference,
  readDarkPalette,
  readThemePreference,
  resolveTheme,
  THEME_COLORS,
  THEME_STORAGE_KEY,
  themeColor,
  writeDarkPalette,
  writeThemePreference,
} from "./theme"

describe("parseThemePreference", () => {
  it.each(["system", "light", "dark"] as const)("accepts %s", (preference) => {
    expect(parseThemePreference(preference)).toBe(preference)
  })

  it.each([null, undefined, "", "sepia", 1, {}])("rejects %j", (value) => {
    expect(parseThemePreference(value)).toBeNull()
  })
})

describe("theme preference storage", () => {
  it("reads a valid stored preference", () => {
    const storage = { getItem: () => "dark", setItem: () => undefined }

    expect(readThemePreference(storage)).toBe("dark")
  })

  it("ignores invalid or inaccessible stored preferences", () => {
    const invalidStorage = { getItem: () => "sepia", setItem: () => undefined }
    const inaccessibleStorage = {
      getItem: () => {
        throw new Error("storage unavailable")
      },
      setItem: () => undefined,
    }

    expect(readThemePreference(invalidStorage)).toBeNull()
    expect(readThemePreference(inaccessibleStorage)).toBeNull()
    expect(readThemePreference(null)).toBeNull()
  })

  it("writes the preference under the application storage key", () => {
    const values = new Map<string, string>()
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    }

    expect(writeThemePreference("system", storage)).toBe(true)
    expect(values.get(THEME_STORAGE_KEY)).toBe("system")
  })

  it("reports storage write failures without throwing", () => {
    const inaccessibleStorage = {
      getItem: () => null,
      setItem: () => {
        throw new Error("storage unavailable")
      },
    }

    expect(writeThemePreference("light", inaccessibleStorage)).toBe(false)
    expect(writeThemePreference("light", null)).toBe(false)
  })
})

describe("dark palette", () => {
  it.each(["twilight", "midnight"] as const)("accepts %s", (palette) => {
    expect(parseDarkPalette(palette)).toBe(palette)
  })

  it.each([null, undefined, "", "dark", "blue", 1])("rejects %j", (value) => {
    expect(parseDarkPalette(value)).toBeNull()
  })

  it("is stored under its own key beside the theme preference", () => {
    const values = new Map<string, string>()
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    }

    expect(writeDarkPalette("midnight", storage)).toBe(true)
    expect(values.get(DARK_PALETTE_STORAGE_KEY)).toBe("midnight")
    expect(values.has(THEME_STORAGE_KEY)).toBe(false)
    expect(readDarkPalette(storage)).toBe("midnight")
  })

  it("ignores invalid or inaccessible stored palettes", () => {
    const inaccessibleStorage = {
      getItem: () => {
        throw new Error("storage unavailable")
      },
      setItem: () => {
        throw new Error("storage unavailable")
      },
    }

    expect(readDarkPalette({ getItem: () => "sepia", setItem: () => undefined })).toBeNull()
    expect(readDarkPalette(inaccessibleStorage)).toBeNull()
    expect(writeDarkPalette("midnight", inaccessibleStorage)).toBe(false)
  })

  it("colors the browser chrome by appearance, then palette", () => {
    expect(themeColor("light", "midnight")).toBe(THEME_COLORS.light)
    expect(themeColor("dark", "twilight")).toBe(THEME_COLORS.twilight)
    expect(themeColor("dark", "midnight")).toBe(THEME_COLORS.midnight)
  })
})

describe("resolveTheme", () => {
  it("keeps an explicit light or dark preference", () => {
    expect(resolveTheme("light", true)).toBe("light")
    expect(resolveTheme("dark", false)).toBe("dark")
  })

  it("resolves the system preference from the device color scheme", () => {
    expect(resolveTheme("system", true)).toBe("dark")
    expect(resolveTheme("system", false)).toBe("light")
  })
})

describe("applyTheme", () => {
  it("updates the root color scheme and browser theme color", () => {
    const root = { dataset: {}, style: { colorScheme: "" } }
    const meta = { content: "" }
    const targetDocument = {
      documentElement: root,
      querySelector: () => meta,
    } as unknown as Document

    applyTheme("dark", "twilight", targetDocument)

    expect(root.dataset).toEqual({ theme: "dark", palette: "twilight" })
    expect(root.style.colorScheme).toBe("dark")
    expect(meta.content).toBe("#0d0e19")
  })

  it("marks the dark palette and colors the browser chrome to match", () => {
    const root = { dataset: {}, style: { colorScheme: "" } }
    const meta = { content: "" }
    const targetDocument = {
      documentElement: root,
      querySelector: () => meta,
    } as unknown as Document

    applyTheme("dark", "midnight", targetDocument)

    expect(root.dataset).toEqual({ theme: "dark", palette: "midnight" })
    expect(meta.content).toBe(THEME_COLORS.midnight)
  })
})

describe("pre-paint theme bootstrap", () => {
  function runBootstrap(
    storedTheme: string | null,
    systemPrefersDark: boolean,
    storageUnavailable = false,
    storedPalette: string | null = null,
  ) {
    const script = /<script>([\s\S]*?)<\/script>/.exec(bootstrapHtml)?.[1]
    if (!script) throw new Error("Theme bootstrap script was not found")

    const root = { dataset: { theme: "light" }, style: { colorScheme: "light" } }
    const meta = {
      content: "#fbfbfe",
      setAttribute: (name: string, value: string) => {
        if (name === "content") meta.content = value
      },
    }
    const storage = {
      getItem: (key: string) => {
        if (storageUnavailable) throw new Error("storage unavailable")
        return key === DARK_PALETTE_STORAGE_KEY ? storedPalette : storedTheme
      },
    }
    const targetDocument = { documentElement: root, querySelector: () => meta }
    // Runs the inline script index.html ships, exactly as the browser would before React loads.
    // eslint-disable-next-line @typescript-eslint/no-implied-eval
    const execute = new Function("localStorage", "matchMedia", "document", script) as (
      storage: unknown,
      matchMedia: () => { matches: boolean },
      document: unknown,
    ) => void

    execute(storage, () => ({ matches: systemPrefersDark }), targetDocument)
    return { root, meta }
  }

  it("stays aligned with the runtime storage key and theme colors", () => {
    expect(bootstrapHtml).toContain(`const storageKey = "${THEME_STORAGE_KEY}"`)
    expect(bootstrapHtml).toContain(`const paletteKey = "${DARK_PALETTE_STORAGE_KEY}"`)
    expect(bootstrapHtml).toContain("root.dataset.theme = theme")
    expect(bootstrapHtml).toContain("root.dataset.palette = palette")
    for (const color of Object.values(THEME_COLORS)) expect(bootstrapHtml).toContain(color)
  })

  it.each([
    ["saved Midnight while dark", "dark", "midnight", "midnight", THEME_COLORS.midnight],
    ["saved Twilight while dark", "dark", "twilight", "twilight", THEME_COLORS.twilight],
    ["no saved palette", "dark", null, "twilight", THEME_COLORS.twilight],
    ["invalid saved palette", "dark", "sepia", "twilight", THEME_COLORS.twilight],
    ["saved Midnight while light", "light", "midnight", "midnight", THEME_COLORS.light],
  // eslint-disable-next-line max-params -- debt: split this before adding to it
  ] as const)("applies %s before paint", (_case, storedTheme, storedPalette, palette, color) => {
    const { root, meta } = runBootstrap(storedTheme, false, false, storedPalette)

    expect((root.dataset as Record<string, string>).palette).toBe(palette)
    expect(meta.content).toBe(color)
  })

  it.each([
    ["device dark", null, true, "dark"],
    ["device light", null, false, "light"],
    ["saved dark", "dark", false, "dark"],
    ["saved light", "light", true, "light"],
    ["saved device setting", "system", true, "dark"],
    ["invalid saved value", "sepia", true, "dark"],
  ] as const)("resolves %s before paint", (_case, storedTheme, systemDark, expected) => {
    const { root, meta } = runBootstrap(storedTheme, systemDark)

    expect(root.dataset.theme).toBe(expected)
    expect(root.style.colorScheme).toBe(expected)
    expect(meta.content).toBe(expected === "dark" ? "#0d0e19" : "#fbfbfe")
  })

  it("falls back to the device when storage is unavailable", () => {
    const { root } = runBootstrap(null, true, true)

    expect(root.dataset.theme).toBe("dark")
  })
})
