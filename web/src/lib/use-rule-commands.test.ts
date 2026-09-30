import { describe, expect, it } from "vitest"

import detailsSource from "../features/rule-details.tsx?raw"
import commandsSource from "./use-rule-commands.ts?raw"
import { RULE_CHANGE_QUERIES } from "@/lib/use-rule-commands"

describe("rule change refresh", () => {
  it("refetches incidents, which runs resolve and recovery previews move to another account", () => {
    expect(RULE_CHANGE_QUERIES).toContainEqual(["incidents"])
  })

  it("is shared by rule commands, rule changes, and leaving a removed rule", () => {
    expect(commandsSource.match(/\.\.\.RULE_CHANGE_QUERIES/g)).toHaveLength(1)
    // Rule Details refreshes after a policy change or replacement, and after a removal.
    expect(detailsSource.match(/RULE_CHANGE_QUERIES/g)?.length).toBeGreaterThanOrEqual(3)
    expect(detailsSource).not.toMatch(/\[\["rules"\]/)
  })
})
