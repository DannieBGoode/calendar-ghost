import { describe, expect, it } from "vitest"

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
    expect(apiSource).toContain("/disconnect")
    expect(apiSource).toContain("deleteAccount")
    expect(settingsSource).toContain("Delete account")
    expect(settingsSource).toContain("Delete permanently")
    expect(settingsSource).toContain("Managed Projections in Google Calendar will not be deleted")
  })
})
