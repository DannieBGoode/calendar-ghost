import { describe, expect, it } from "vitest"

import calendarReplacementSource from "../features/calendar-replacement.tsx?raw"
import projectionChoiceSource from "../features/projection-choice.tsx?raw"
import factsSource from "../features/rule-details-facts.tsx?raw"
import pageSource from "../features/rule-details.tsx?raw"
import policyEditorSource from "../features/rule-policy-editor.tsx?raw"
import removalSource from "../features/rule-removal.tsx?raw"
import refreshSource from "./use-rule-refresh.ts?raw"
import commandsSource from "./use-rule-commands.ts?raw"
import { clearCompletedWork, RULE_CHANGE_QUERIES } from "@/lib/use-rule-commands"
import { ruleWork } from "@/lib/rule-work"

// Rule Details spans the page and the sections and hooks it composes.
const detailsSource = [
  pageSource,
  factsSource,
  policyEditorSource,
  calendarReplacementSource,
  removalSource,
  projectionChoiceSource,
  refreshSource,
].join("\n")

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

  it("clears a completed command from the cached rule work", () => {
    const commandStartedAt = Date.parse("2026-10-02T00:00:00Z")
    const running = {
      kind: "reconciliation" as const,
      started_at: "2026-10-02T00:00:00Z",
      handling: null,
      total: null,
      done: 0,
      stage: "reconciliation" as const,
    }
    const completed = clearCompletedWork({ id: "rule-1", running }, "reconcile", commandStartedAt)
    expect(completed).toEqual({ id: "rule-1", running: null })
    expect(ruleWork({ pending: undefined, running: completed?.running })).toBeNull()
    expect(clearCompletedWork({ id: "rule-1", running }, "sync", commandStartedAt)).toEqual({ id: "rule-1", running })
    expect(
      clearCompletedWork(
        { id: "rule-1", running: { ...running, started_at: "2026-10-02T00:01:00Z" } },
        "reconcile",
        commandStartedAt,
      ),
    ).toEqual({ id: "rule-1", running: { ...running, started_at: "2026-10-02T00:01:00Z" } })
    expect(clearCompletedWork(undefined, "reconcile", commandStartedAt)).toBeUndefined()
    expect(commandsSource).toContain('queryClient.setQueryData<RuleSummary[]>(["rules"]')
    expect(commandsSource).toContain('queryClient.setQueryData<RuleDetail>(["rule", ruleId]')
  })
})
