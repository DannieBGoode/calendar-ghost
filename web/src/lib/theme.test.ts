import { describe, expect, it } from "vitest"

import bootstrapHtml from "../../index.html?raw"
import {
  applyTheme,
  parseThemePreference,
  readThemePreference,
  resolveTheme,
  THEME_STORAGE_KEY,
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

    applyTheme("dark", targetDocument)

    expect(root.dataset).toEqual({ theme: "dark" })
    expect(root.style.colorScheme).toBe("dark")
    expect(meta.content).toBe("#0d0e19")
  })
})

describe("pre-paint theme bootstrap", () => {
  function runBootstrap(
    storedTheme: string | null,
    systemPrefersDark: boolean,
    storageUnavailable = false,
  ) {
    const script = bootstrapHtml.match(/<script>([\s\S]*?)<\/script>/)?.[1]
    if (!script) throw new Error("Theme bootstrap script was not found")

    const root = { dataset: { theme: "light" }, style: { colorScheme: "light" } }
    const meta = {
      content: "#fbfbfe",
      setAttribute: (name: string, value: string) => {
        if (name === "content") meta.content = value
      },
    }
    const storage = {
      getItem: () => {
        if (storageUnavailable) throw new Error("storage unavailable")
        return storedTheme
      },
    }
    const targetDocument = { documentElement: root, querySelector: () => meta }
    const execute = new Function("localStorage", "matchMedia", "document", script)

    execute(storage, () => ({ matches: systemPrefersDark }), targetDocument)
    return { root, meta }
  }

  it("stays aligned with the runtime storage key and theme colors", () => {
    expect(bootstrapHtml).toContain(`const storageKey = "${THEME_STORAGE_KEY}"`)
    expect(bootstrapHtml).toContain('root.dataset.theme = theme')
    expect(bootstrapHtml).toContain('theme === "dark" ? "#0d0e19" : "#fbfbfe"')
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
