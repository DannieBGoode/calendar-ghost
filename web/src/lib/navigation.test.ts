import { describe, expect, it } from "vitest"

import {
  appLocationFromPathname,
  appPathForLocation,
  appPathForRule,
  appPathForView,
  appViewFromPathname,
  isKnownAppPath,
  isPlainLeftClick,
} from "./navigation"

describe("application section URLs", () => {
  it.each([
    ["overview", "/overview"],
    ["rules", "/rules"],
    ["activity", "/activity"],
    ["settings", "/settings"],
  ] as const)("maps %s to %s", (view, path) => {
    expect(appPathForView(view)).toBe(path)
    expect(appViewFromPathname(path)).toBe(view)
    expect(isKnownAppPath(path)).toBe(true)
  })

  it("normalizes trailing slashes and falls back to Overview", () => {
    expect(appViewFromPathname("/rules/")).toBe("rules")
    expect(appViewFromPathname("/")).toBe("overview")
    expect(appViewFromPathname("/unknown")).toBe("overview")
    expect(isKnownAppPath("/unknown")).toBe(false)
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
    expect(appViewFromPathname("/rules/rule-1")).toBe("rules")
    expect(appPathForLocation({ view: "settings", ruleId: null })).toBe(appPathForView("settings"))
  })

  it("only intercepts plain left clicks", () => {
    const plain = { button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false }
    expect(isPlainLeftClick(plain)).toBe(true)
    expect(isPlainLeftClick({ ...plain, metaKey: true })).toBe(false)
    expect(isPlainLeftClick({ ...plain, button: 1 })).toBe(false)
  })
})
