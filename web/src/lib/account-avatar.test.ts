import { describe, expect, it } from "vitest"

import avatarSource from "../components/account-avatar.tsx?raw"
import ruleEndpointSource from "../components/rule-endpoint.tsx?raw"
import rulesSource from "../features/rules.tsx?raw"
import settingsSource from "../features/settings.tsx?raw"
import { accountInitials } from "./account-avatar"

describe("accountInitials", () => {
  it("uses the first and last words of a full display name", () => {
    expect(accountInitials("Daniel Calatayud", "daniel@example.com")).toBe("DC")
  })

  it("uses a structured email name when the display name is only a calendar label", () => {
    expect(accountInitials("Personal", "daniel.calatayud@example.com")).toBe("DC")
  })

  it("falls back safely when identity fields are sparse", () => {
    expect(accountInitials("", "daniel@example.com")).toBe("DA")
    expect(accountInitials("", "")).toBe("?")
  })
})

describe("AccountAvatar", () => {
  it("shows the Google profile photo without leaking the page as a referrer", () => {
    expect(avatarSource).toContain("referrerPolicy=\"no-referrer\"")
    expect(avatarSource).toContain('alt=""')
  })

  it("falls back to initials when there is no photo or it fails to load", () => {
    expect(avatarSource).toContain("onError={() => setFailedUrl(photo)}")
    expect(avatarSource).toContain("accountInitials(displayName, email)")
  })

  it("is used for every account identity in the dashboard", () => {
    expect(settingsSource).not.toContain("accountInitials(")
    expect(rulesSource).not.toContain("accountInitials(")
    expect(ruleEndpointSource).not.toContain("accountInitials(")
    expect(settingsSource.match(/<AccountAvatar/g)).toHaveLength(1)
    expect(ruleEndpointSource.match(/<AccountAvatar/g)).toHaveLength(1)
  })
})
