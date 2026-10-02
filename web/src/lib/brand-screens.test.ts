import { readFileSync } from "node:fs"

import { describe, expect, it } from "vitest"

import authSource from "../features/auth-screen.tsx?raw"
import rulesSource from "../features/rules.tsx?raw"
import activitySource from "../features/activity.tsx?raw"
import settingsSource from "../features/settings.tsx?raw"

const stylesheet = readFileSync(new URL("../index.css", import.meta.url), "utf8")

describe("brand screens", () => {
  it("introduces sign-in and setup with the mark, name, and tagline", () => {
    expect(authSource).toContain('<GhostMark className="brand-mark" />')
    expect(authSource).toContain("{PRODUCT_NAME}")
    expect(authSource).toContain("{TAGLINE}")
    expect(authSource).not.toContain("CalendarCheck2")
  })

  it("keeps the auth intro twilight in both appearances", () => {
    expect(stylesheet).toMatch(/\.auth-intro \{[^}]*background: var\(--twilight-canvas\)/)
    expect(stylesheet).toMatch(/\.auth-intro \{[^}]*color: var\(--twilight-ink\)/)
  })

  it("shows the ghost in empty Rules and Activity", () => {
    expect(rulesSource).toContain('<GhostMark className="empty-ghost" />')
    expect(activitySource).toContain('<GhostMark className="empty-ghost" />')
  })

  it("uses attention, not destructive, for missing configuration", () => {
    expect(settingsSource).toContain('<div className="inline-attention" role="status">')
    expect(stylesheet).toMatch(/\.inline-attention \{[^}]*background: var\(--warning-surface\)/)
  })
})
