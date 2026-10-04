import { describe, expect, it } from "vitest"

import { catalogProblems } from "./catalog-check"
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

describe("shipped catalogs", () => {
  it.each(LOCALES.map((entry) => [entry.tag, entry] as const))("%s matches English", async (tag, entry) => {
    expect(catalogProblems(english, await entry.load(), tag)).toEqual([])
  })
})
