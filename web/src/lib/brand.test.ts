import { readFileSync } from "node:fs"

import { describe, expect, it } from "vitest"

import { APP_VERSION, PRODUCT_NAME, TAGLINE, documentTitle } from "./brand"

const stylesheet = readFileSync(new URL("../index.css", import.meta.url), "utf8")
const html = readFileSync(new URL("../../index.html", import.meta.url), "utf8")
const themeSource = readFileSync(new URL("./theme.ts", import.meta.url), "utf8")
const pkg = JSON.parse(readFileSync(new URL("../../package.json", import.meta.url), "utf8")) as { version: string }

describe("brand", () => {
  it("names the product and its pages", () => {
    expect(PRODUCT_NAME).toBe("Calendar Ghost")
    expect(TAGLINE).toBe("Your busy time, everywhere it needs to be.")
    expect(documentTitle("Rules")).toBe("Rules – Calendar Ghost")
  })

  it("shows the version the bundle was built from", () => {
    expect(APP_VERSION).toBe(pkg.version)
  })

  it("keeps the saved appearance across the rename", () => {
    expect(themeSource).toContain('"calendar-sync-theme"')
    expect(html).toContain('const storageKey = "calendar-sync-theme"')
  })

  it("keeps the loading ghost still under reduced motion", () => {
    expect(stylesheet).toMatch(/\.startup-ghost \{[^}]*animation: ghost-breath/)
    expect(stylesheet).toMatch(/@media \(prefers-reduced-motion: reduce\) \{\s*\.startup-ghost \{\s*animation: none;/)
  })
})
