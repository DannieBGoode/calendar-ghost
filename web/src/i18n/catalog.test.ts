import { describe, expect, it } from "vitest"

import { VERDICTS } from "@/lib/operator-overview"

import { catalogProblems, unusedKeys, type TemplateValues } from "./catalog-check"
import { LOCALES } from "./locales"
import english from "./locales/en"
import type { Catalog } from "./types"

const base = {
  title: "Calendar Ghost settings",
  rules: { one: "{count} rule", other: "{count} rules" },
  group: { hello: "Hello {name}" },
} satisfies Catalog

describe("catalogProblems", () => {
  it("accepts a faithful translation", () => {
    const french: Catalog = {
      title: "Réglages de Calendar Ghost",
      rules: { one: "{count} règle", many: "{count} de règles", other: "{count} règles" },
      group: { hello: "Bonjour {name}" },
    }
    expect(catalogProblems(base, french, "fr")).toEqual([])
  })

  it("reports missing and extra keys", () => {
    const other: Catalog = { title: "Calendar Ghost", rules: base.rules, extra: "x" }
    expect(catalogProblems(base, other, "en")).toEqual(["group.hello: missing", "extra: not in English"])
  })

  it("reports placeholder differences", () => {
    const other: Catalog = { ...base, group: { hello: "Hallo {nom}" } }
    expect(catalogProblems(base, other, "de")).toEqual(["group.hello: placeholders {nom} differ from English {name}"])
  })

  it("reports plural categories the language needs", () => {
    const other: Catalog = { ...base, rules: { one: "{count} règle", other: "{count} règles" } }
    expect(catalogProblems(base, other, "fr")).toEqual(["rules: missing plural forms many"])
  })

  it("reports empty strings, a dropped product name, and em dashes", () => {
    const other: Catalog = { title: "Réglages \u2014 ", rules: base.rules, group: { hello: "" } }
    expect(catalogProblems(base, other, "en")).toEqual([
      "title: drops Calendar Ghost",
      "title: uses an em dash",
      "group.hello: empty",
    ])
  })

  it("reports a group that uses the key other", () => {
    const bad: Catalog = { group: { other: "x", more: "y" } }
    expect(catalogProblems(bad, bad, "en")).toEqual(["group: a group may not use the key other"])
  })
})

describe("unusedKeys", () => {
  const catalog = { page: { title: "Rules", empty: "None" }, verdict: { healthy: "Fine", stopped: "Stopped" } } satisfies Catalog

  it("accepts keys a source names, literally or through a template's known values", () => {
    const sources = ['t("page.title")', "t('page.empty')", "t(`verdict.${status}`)"]
    expect(unusedKeys(catalog, sources, { "verdict.*": ["healthy", "stopped"] })).toEqual([])
  })

  it("reports keys no source names", () => {
    expect(unusedKeys(catalog, ['t("page.title")', "t(`verdict.${status}`)"], { "verdict.*": ["healthy"] })).toEqual([
      "page.empty: unused",
      "verdict.stopped: unused",
    ])
  })

  it("does not count a longer string that only contains a key", () => {
    expect(unusedKeys({ page: { title: "Rules" } }, ['t("page.title.extra")'], {})).toEqual(["page.title: unused"])
  })

  it("counts every key a server-named template matches", () => {
    const errors = { apiError: { not_found: "Gone", conflict: "Taken" } } satisfies Catalog
    expect(unusedKeys(errors, ["t(`apiError.${error.code}`)"], { "apiError.*": "server" })).toEqual([])
  })

  it("reports a template without known values and known values no source uses", () => {
    expect(unusedKeys(catalog, ['t("page.title")', 't("page.empty")', "t(`verdict.${status}`)"], { "page.*": ["title"] })).toEqual([
      "verdict.healthy: unused",
      "verdict.stopped: unused",
      "verdict.*: a key template without known values",
      "page.*: known values for a key template no source builds",
    ])
  })
})

/** The source the Web UI ships, without tests. */
const SOURCES = Object.values(
  import.meta.glob<string>(["/src/**/*.{ts,tsx}", "!/src/**/*.test.{ts,tsx}"], { query: "?raw", import: "default", eager: true }),
)

/**
 * The values each key template in the source takes, with each `${...}` written as `*`. "server"
 * marks a template the server's codes complete; tests/adapters/test_api_problems.py checks that
 * every message under it names a code the server sends.
 */
const TEMPLATE_VALUES: TemplateValues = {
  "people.*.title": ["empty", "beyond"],
  "people.*.body": ["empty", "beyond"],
  "people.roles.*": ["installation_administrator", "user"],
  "people.verdicts.*": VERDICTS,
  "people.health.summary.*": ["paused", "setup"],
  "people.overview.verdict.*": VERDICTS,
  "people.overview.problem.*": ["stalled", "stopped", "overdue"],
  "people.overview.go.*": ["connections", "rule"],
  "people.overview.next.*.self": ["reauthorize", "preview", "activity", "overdue", "calendar"],
  "people.overview.ifTheyAsk.*": ["reauthorize", "preview", "activity", "overdue", "calendar"],
  "people.cause.*": [
    "api_disabled",
    "quota_exceeded",
    "oauth_client_invalid",
    "access_revoked",
    "calendar_forbidden",
    "calendar_not_found",
    "rate_limited",
    "temporary",
    "unknown",
  ],
  "common.provider.*": ["google"],
  "common.apiError.*": "server",
  "common.apiError.*_*": "server",
}

describe("shipped catalogs", () => {
  it("names every English key somewhere in the source", () => {
    expect(SOURCES.length).toBeGreaterThan(50)
    expect(unusedKeys(english, SOURCES, TEMPLATE_VALUES)).toEqual([])
  })

  it.each(LOCALES.map((entry) => [entry.tag, entry] as const))("%s matches English", async (tag, entry) => {
    expect(catalogProblems(english, await entry.load(), tag)).toEqual([])
  })
})
