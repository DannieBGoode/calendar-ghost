import { describe, expect, it } from "vitest"

import {
  SETTINGS_TABS,
  accountSearch,
  appLocationFromPathname,
  appLocationFromUrl,
  appPathForActivityTab,
  appPathForIncident,
  appPathForLocation,
  appPathForPeopleTab,
  appPathForPerson,
  appPathForRule,
  appPathForRulePreview,
  appPathForSettingsTab,
  appPathForView,
  connectionsPath,
  defaultSettingsTab,
  isKnownAppPath,
  isPlainLeftClick,
  isViewingRule,
  yourPlanPath,
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

describe("Activity tab URLs", () => {
  it("opens Incidents at its own address, and history at /activity", () => {
    expect(appPathForActivityTab("incidents")).toBe("/activity/incidents")
    expect(appPathForActivityTab("history")).toBe("/activity")
    expect(appLocationFromPathname("/activity/incidents/")).toEqual({
      view: "activity",
      ruleId: null,
      activityTab: "incidents",
    })
    expect(appPathForLocation({ view: "activity", ruleId: null, activityTab: "incidents" })).toBe("/activity/incidents")
    expect(isKnownAppPath("/activity/incidents")).toBe(true)
    expect(isKnownAppPath("/activity/elsewhere")).toBe(false)
  })

  it("opens one Incident at its own address under Incidents", () => {
    expect(appPathForIncident("incident 1")).toBe("/activity/incidents/incident%201")
    expect(appLocationFromPathname("/activity/incidents/incident%201")).toEqual({
      view: "activity",
      ruleId: null,
      activityTab: "incidents",
      incidentId: "incident 1",
    })
    expect(appPathForLocation({ view: "activity", ruleId: null, activityTab: "incidents", incidentId: "a" })).toBe(
      "/activity/incidents/a",
    )
    expect(isKnownAppPath("/activity/incidents/a")).toBe(true)
  })
})

describe("People tab URLs", () => {
  it("opens Invitations at its own address, and People at /people", () => {
    expect(appPathForPeopleTab("invitations")).toBe("/people/invitations")
    expect(appPathForPeopleTab("everyone")).toBe("/people")
    expect(appLocationFromPathname("/people/invitations")).toEqual({
      view: "people",
      ruleId: null,
      peopleTab: "invitations",
    })
    expect(appPathForLocation({ view: "people", ruleId: null, peopleTab: "invitations" })).toBe("/people/invitations")
    expect(isKnownAppPath("/people/invitations")).toBe(true)
  })

  it("opens Plans at its own address, never as a person named plans", () => {
    expect(appPathForPeopleTab("plans")).toBe("/people/plans")
    for (const path of ["/people/plans", "/people/plans/"]) {
      expect(appLocationFromPathname(path)).toEqual({ view: "people", ruleId: null, peopleTab: "plans" })
    }
    expect(appPathForLocation({ view: "people", ruleId: null, peopleTab: "plans" })).toBe("/people/plans")
    expect(isKnownAppPath("/people/plans")).toBe(true)
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

  it.each([
    "?oauth=connected&provider=google&account=acct-a&resumed=0",
    "?oauth=authorization_failed",
    "?oauth=account_limit_reached&provider=google&limit=1",
    "?account=acct-a",
    "?resumed=2",
    "?limit=1",
  ])(
    "shows Connections when a provider returns or an account is named (%s)",
    (search) => {
      expect(defaultSettingsTab(search)).toBe("connections")
    },
  )

  it("resolves the tab Settings opens at from the whole address", () => {
    expect(appLocationFromUrl("/settings", "")).toEqual({ view: "settings", ruleId: null, settingsTab: "account" })
    expect(appLocationFromUrl("/settings", "?oauth=connected")).toEqual({
      view: "settings",
      ruleId: null,
      settingsTab: "connections",
    })
    expect(appLocationFromUrl("/settings/administration", "?account=a").settingsTab).toBe("administration")
    expect(appLocationFromUrl("/rules", "?account=a")).toEqual({ view: "rules", ruleId: null })
  })

  it("links calendar accounts to Connections", () => {
    expect(connectionsPath()).toBe("/settings/connections")
    expect(connectionsPath(accountSearch("acct a"))).toBe("/settings/connections?account=acct%20a")
  })

  it("links to Your plan on the Your account tab", () => {
    expect(yourPlanPath()).toBe("/settings/account#your-plan")
    expect(appLocationFromUrl("/settings/account", "")).toEqual({ view: "settings", ruleId: null, settingsTab: "account" })
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

describe("rule preview URLs", () => {
  it("round-trips a rule's preview page under its details", () => {
    expect(appPathForRulePreview("rule 1")).toBe("/rules/rule%201/preview")
    expect(appLocationFromPathname("/rules/rule%201/preview")).toEqual({ view: "rules", ruleId: "rule 1", rulePreview: true })
    expect(appPathForLocation({ view: "rules", ruleId: "rule 1", rulePreview: true })).toBe("/rules/rule%201/preview")
    expect(isKnownAppPath("/rules/rule-1/preview/")).toBe(true)
    expect(appLocationFromPathname("/rules/rule-1")).toEqual({ view: "rules", ruleId: "rule-1" })
  })
})
