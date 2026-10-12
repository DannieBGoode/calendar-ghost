import { describe, expect, it } from "vitest"

import { testI18n } from "../i18n/testing"
import type { CalendarProvider } from "./api"
import { accountNoun, providerDisplayName, providerWords } from "./providers"

const i18n = testI18n()

// A provider a later server describes that this version has no words for.
const later: CalendarProvider = {
  kind: "a-later-provider",
  display_name: "Later",
  connect_url: "/api/v1/oauth/later/start",
  redirect_uri: "http://localhost:8000/api/v1/oauth/later/callback",
  cause_anchors: {},
}

describe("providerDisplayName and accountNoun", () => {
  it("name each provider and its accounts as CONTEXT.md does", () => {
    expect(providerDisplayName(i18n, "google")).toBe("Google")
    expect(providerDisplayName(i18n, "outlook")).toBe("Microsoft")
    expect(accountNoun(i18n, "google")).toBe("Google account")
    expect(accountNoun(i18n, "outlook")).toBe("Microsoft account")
  })

  it("use a provider's own name when the catalog has none, and neutral words when nothing is known", () => {
    expect(providerDisplayName(i18n, later.kind, [later])).toBe("Later")
    expect(accountNoun(i18n, later.kind, [later])).toBe("Later account")
    expect(accountNoun(i18n, null)).toBe("calendar account")
  })
})

describe("providerWords", () => {
  it("gives a message every way it names one provider", () => {
    expect(providerWords(i18n, "outlook")).toEqual({
      provider: "Microsoft",
      Provider: "Microsoft",
      calendar: "Outlook",
      Calendar: "Outlook",
      account: "Microsoft account",
      api: "Microsoft Graph",
      console: "the Microsoft Entra admin center",
      status: "the Microsoft 365 service status page",
    })
    expect(providerWords(i18n, "google").console).toBe("Google Cloud")
  })

  it("is neutral when no one provider is meant", () => {
    expect(providerWords(i18n, null)).toEqual({
      provider: "the calendar provider",
      Provider: "The calendar provider",
      calendar: "the calendar provider",
      Calendar: "The calendar provider",
      account: "calendar account",
      api: "the calendar provider's API",
      console: "the calendar provider's developer console",
      status: "the calendar provider's status page",
    })
  })
})
