import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"

import settingsAccountRowSource from "../features/settings-account-row.tsx?raw"
import settingsAccountsSource from "../features/settings-accounts.tsx?raw"
import settingsGoogleReturnSource from "../features/settings-google-return.tsx?raw"
import settingsStorageSource from "../features/settings-storage.tsx?raw"
import settingsPageSource from "../features/settings.tsx?raw"
import apiSource from "./api.ts?raw"

// The Settings page and the sections it is split into.
const settingsSource = [
  settingsPageSource,
  settingsAccountsSource,
  settingsAccountRowSource,
  settingsStorageSource,
  settingsGoogleReturnSource,
].join("\n")

describe("permanent Connected Account deletion", () => {
  it("keeps disconnect and permanent deletion as separate confirmed actions", () => {
    const { t } = testI18n()
    expect(apiSource).toContain("/disconnect")
    expect(apiSource).toContain("deleteAccount")
    expect(settingsSource).toContain('t("settings.accounts.actions.delete")')
    expect(settingsSource).toContain('t("settings.accounts.delete.confirm")')
    expect(settingsSource).toContain('"settings.accounts.delete.bodyWithRules"')
    expect(t("settings.accounts.actions.delete")).toBe("Delete account")
    expect(t("settings.accounts.delete.confirm")).toBe("Delete permanently")
    expect(t("settings.accounts.delete.bodyWithRules", { count: 2 })).toContain(
      "Managed Projections in Google Calendar will not be deleted",
    )
  })
})
