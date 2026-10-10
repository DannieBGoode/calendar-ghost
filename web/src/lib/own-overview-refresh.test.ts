import { describe, expect, it } from "vitest"

import builderSource from "../features/rule-builder.tsx?raw"
import administratorViewSource from "../features/settings-administrator-view.tsx?raw"
import storageSource from "../features/settings-storage.tsx?raw"
import accountCommandsSource from "./use-account-commands.ts?raw"
import { OWN_OVERVIEW_QUERY } from "@/lib/operator-overview"
import { RULE_CHANGE_QUERIES } from "@/lib/use-rule-commands"

// Each mutation in a source that refreshes rules, accounts, or Activity.
function changesToWhatTheOverviewCounts(source: string): string[] {
  return source
    .split("useMutation(")
    .slice(1)
    .filter((mutation) => /queryKey: \["(rules|accounts|activity)"\]/.test(mutation))
}

describe("what your administrator can see", () => {
  it("is read under its own key", () => {
    expect(administratorViewSource).toContain("queryKey: OWN_OVERVIEW_QUERY")
  })

  it("is refreshed by every rule command and rule change", () => {
    expect(RULE_CHANGE_QUERIES).toContainEqual(OWN_OVERVIEW_QUERY)
  })

  it("is refreshed when a rule is created, an account changes, or Activity is cleared (review on PR 68)", () => {
    const changes = [builderSource, accountCommandsSource, storageSource].flatMap(changesToWhatTheOverviewCounts)

    expect(changes.length).toBeGreaterThanOrEqual(5)
    for (const change of changes) expect(change).toContain("OWN_OVERVIEW_QUERY")
  })
})
