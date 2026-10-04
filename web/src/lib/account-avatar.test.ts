import { describe, expect, it } from "vitest"

import avatarSource from "../components/account-avatar.tsx?raw"
import ruleEndpointSource from "../components/rule-endpoint.tsx?raw"
import ruleBuilderSource from "../features/rule-builder.tsx?raw"
import rulesViewSource from "../features/rules.tsx?raw"
import settingsAccountRowSource from "../features/settings-account-row.tsx?raw"
import settingsAccountsSource from "../features/settings-accounts.tsx?raw"
import settingsGoogleReturnSource from "../features/settings-google-return.tsx?raw"
import settingsStorageSource from "../features/settings-storage.tsx?raw"
import settingsPageSource from "../features/settings.tsx?raw"
import { accountInitials } from "./account-avatar"

// The rules page and the rule builder it opens.
const rulesSource = `${rulesViewSource}\n${ruleBuilderSource}`

// The Settings page and the sections it is split into.
const settingsSource = [
  settingsPageSource,
  settingsAccountsSource,
  settingsAccountRowSource,
  settingsStorageSource,
  settingsGoogleReturnSource,
].join("\n")

describe("accountInitials", () => {
  it("uses the first and last words of a full display name", () => {
    expect(accountInitials("Daniel Calatayud", "daniel@example.com", "en")).toBe("DC")
  })

  it("uses a structured email name when the display name is only a calendar label", () => {
    expect(accountInitials("Personal", "daniel.calatayud@example.com", "en")).toBe("DC")
  })

  it("falls back safely when identity fields are sparse", () => {
    expect(accountInitials("", "daniel@example.com", "en")).toBe("DA")
    expect(accountInitials("", "", "en")).toBe("?")
  })

  it("uppercases by the UI language's rules", () => {
    expect(accountInitials("", "ilker@example.com", "tr")).toBe("İL")
    expect(accountInitials("", "ilker@example.com", "en")).toBe("IL")
  })
})

describe("AccountAvatar", () => {
  it("shows the Google profile photo without leaking the page as a referrer", () => {
    expect(avatarSource).toContain("referrerPolicy=\"no-referrer\"")
    expect(avatarSource).toContain('alt=""')
  })

  it("falls back to initials when there is no photo or it fails to load", () => {
    expect(avatarSource).toContain("onError={() => setFailedUrl(photo)}")
    expect(avatarSource).toContain("accountInitials(displayName, email, locale)")
  })

  it("is used for every account identity in the dashboard", () => {
    expect(settingsSource).not.toContain("accountInitials(")
    expect(rulesSource).not.toContain("accountInitials(")
    expect(ruleEndpointSource).not.toContain("accountInitials(")
    // The collapsed accounts summary and each account row.
    expect(settingsSource.match(/<AccountAvatar/g)).toHaveLength(2)
    expect(ruleEndpointSource.match(/<AccountAvatar/g)).toHaveLength(1)
  })
})
