import { describe, expect, it } from "vitest"

import {
  SETTINGS_TABS,
  accountSearch,
  appLocationFromPathname,
  appLocationFromUrl,
  appPathForLocation,
  appPathForPerson,
  appPathForRule,
  appPathForSettingsTab,
  appPathForView,
  connectionsPath,
  defaultSettingsTab,
  isKnownAppPath,
  isPlainLeftClick,
  isViewingRule,
} from "./navigation"

describe("application section URLs", () => {
  it.each([
    ["overview", "/overview"],
    ["rules", "/rules"],
    ["activity", "/activity"],
    ["people", "/people"],
    ["settings", "/settings"],
  ] as const)("maps %s to %s", (view, path) => {
    expect(appPathForView(view)).toBe(path)
    expect(appLocationFromPathname(path).view).toBe(view)
    expect(isKnownAppPath(path)).toBe(true)
  })

  it("normalizes trailing slashes and falls back to Overview", () => {
    expect(appLocationFromPathname("/rules/").view).toBe("rules")
    expect(appLocationFromPathname("/").view).toBe("overview")
    expect(appLocationFromPathname("/unknown").view).toBe("overview")
    expect(isKnownAppPath("/unknown")).toBe(false)
  })
})

describe("person URLs", () => {
  it("round-trips one person's page under People", () => {
    expect(appPathForPerson("user 1")).toBe("/people/user%201")
    expect(appLocationFromPathname("/people/user%201/")).toEqual({ view: "people", ruleId: null, personId: "user 1" })
    expect(appPathForLocation({ view: "people", ruleId: null, personId: "user 1" })).toBe("/people/user%201")
    expect(isKnownAppPath("/people/user%201")).toBe(true)
    expect(appLocationFromPathname("/people/%E0").view).toBe("overview")
  })
})

describe("Settings tab URLs", () => {
  it("lists the tabs in order: Your account, Connections, Administration", () => {
    expect(SETTINGS_TABS).toEqual(["account", "connections", "administration"])
  })

  it.each(["connections", "account", "administration"] as const)("round-trips the %s tab", (settingsTab) => {
    const path = appPathForSettingsTab(settingsTab)
    expect(path).toBe(`/settings/${settingsTab}`)
    expect(appLocationFromPathname(path)).toEqual({ view: "settings", ruleId: null, settingsTab })
    expect(appLocationFromPathname(`${path}/`).settingsTab).toBe(settingsTab)
    expect(appPathForLocation({ view: "settings", ruleId: null, settingsTab })).toBe(path)
    expect(isKnownAppPath(path)).toBe(true)
  })

  it("opens Settings without a tab at its own address", () => {
    expect(appLocationFromPathname("/settings")).toEqual({ view: "settings", ruleId: null })
    expect(appPathForLocation({ view: "settings", ruleId: null })).toBe("/settings")
  })

  it("shows Your account for Settings without a tab", () => {
    expect(defaultSettingsTab("")).toBe("account")
    expect(defaultSettingsTab("?unrelated=1")).toBe("account")
  })

  it.each(["?google=connected&account=acct-a&resumed=0", "?google=authorization_failed", "?account=acct-a", "?resumed=2"])(
    "shows Connections when Google returns or an account is named (%s)",
    (search) => {
      expect(defaultSettingsTab(search)).toBe("connections")
    },
  )

  it("resolves the tab Settings opens at from the whole address", () => {
    expect(appLocationFromUrl("/settings", "")).toEqual({ view: "settings", ruleId: null, settingsTab: "account" })
    expect(appLocationFromUrl("/settings", "?google=connected")).toEqual({
      view: "settings",
      ruleId: null,
      settingsTab: "connections",
    })
    expect(appLocationFromUrl("/settings/administration", "?account=a").settingsTab).toBe("administration")
    expect(appLocationFromUrl("/rules", "?account=a")).toEqual({ view: "rules", ruleId: null })
  })

  it("links Google accounts to Connections", () => {
    expect(connectionsPath()).toBe("/settings/connections")
    expect(connectionsPath(accountSearch("acct a"))).toBe("/settings/connections?account=acct%20a")
  })

  it.each(["/settings/unknown", "/settings/installation", "/settings/account/more", "/settingsx/account"])("falls back safely for %s", (path) => {
    expect(appLocationFromPathname(path)).toEqual({ view: "overview", ruleId: null })
    expect(isKnownAppPath(path)).toBe(false)
  })
})

describe("rule detail URLs", () => {
  it.each(["rule-1", "a/b", "ünï code", "550e8400-e29b-41d4-a716-446655440000"])(
    "round-trips rule id %s",
    (ruleId) => {
      const path = appPathForRule(ruleId)
      expect(appLocationFromPathname(path)).toEqual({ view: "rules", ruleId })
      expect(appPathForLocation({ view: "rules", ruleId })).toBe(path)
      expect(isKnownAppPath(path)).toBe(true)
    },
  )

  it("accepts a trailing slash", () => {
    expect(appLocationFromPathname("/rules/rule-1/")).toEqual({ view: "rules", ruleId: "rule-1" })
  })

  it.each(["/rules/x/y", "/rules/%E0%A4%A", "/rules/%20", "/rulesx/1"])(
    "falls back safely for %s",
    (path) => {
      expect(appLocationFromPathname(path).ruleId).toBeNull()
      expect(isKnownAppPath(path)).toBe(false)
    },
  )

  it("keeps section URLs working", () => {
    expect(appLocationFromPathname("/rules")).toEqual({ view: "rules", ruleId: null })
    expect(appLocationFromPathname("/rules/rule-1").view).toBe("rules")
    expect(appPathForLocation({ view: "settings", ruleId: null })).toBe(appPathForView("settings"))
  })

  it("only intercepts plain left clicks", () => {
    const plain = { button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false }
    expect(isPlainLeftClick(plain)).toBe(true)
    expect(isPlainLeftClick({ ...plain, metaKey: true })).toBe(false)
    expect(isPlainLeftClick({ ...plain, button: 1 })).toBe(false)
  })
})

describe("isViewingRule", () => {
  it("matches only that rule's details page", () => {
    expect(isViewingRule("rule-a", "/rules/rule-a")).toBe(true)
    expect(isViewingRule("rule-a", "/rules/rule-a/")).toBe(true)
    expect(isViewingRule("rule-a", "/rules/rule-b")).toBe(false)
    expect(isViewingRule("rule-a", "/rules")).toBe(false)
    expect(isViewingRule("rule-a", "/activity")).toBe(false)
  })
})
