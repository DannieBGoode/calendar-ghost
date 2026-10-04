import { readFileSync } from "node:fs"

import { describe, expect, it } from "vitest"

import authSource from "../features/auth-screen.tsx?raw"
import rulesSource from "../features/rules.tsx?raw"
import activitySource from "../features/activity.tsx?raw"
import settingsAccountRowSource from "../features/settings-account-row.tsx?raw"
import settingsAccountsSource from "../features/settings-accounts.tsx?raw"
import settingsGoogleReturnSource from "../features/settings-google-return.tsx?raw"
import settingsStorageSource from "../features/settings-storage.tsx?raw"
import settingsPageSource from "../features/settings.tsx?raw"

// The Settings page and the sections it is split into.
const settingsSource = [
  settingsPageSource,
  settingsAccountsSource,
  settingsAccountRowSource,
  settingsStorageSource,
  settingsGoogleReturnSource,
].join("\n")

const stylesheet = readFileSync(new URL("../index.css", import.meta.url), "utf8")

describe("brand screens", () => {
  it("introduces sign-in and setup with the mark, name, and tagline", () => {
    expect(authSource).toContain('<GhostMark className="brand-mark" />')
    expect(authSource).toContain("{PRODUCT_NAME}")
    expect(authSource).toContain('t("auth.tagline")')
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

  it("keeps missing configuration a quiet note rather than an error", () => {
    expect(settingsSource).toContain('<p className="settings-note" role="status">')
    expect(settingsSource).not.toMatch(/className="inline-error" role="status">\s*Add the master key/)
  })
})
