import { describe, expect, it } from "vitest"

import dashboardSource from "../features/dashboard.tsx?raw"
import rulesSource from "../features/rules.tsx?raw"
import detailsSource from "../features/rule-details.tsx?raw"

describe("Rule Details presentation", () => {
  it("defaults Rule Removal to deleting mapped projections and names the effect on its button", () => {
    expect(detailsSource).toContain('useState<ProjectionHandling>("delete")')
    expect(detailsSource).toContain("removalConfirmLabel(effective, detail.mapping_count)")
    expect(detailsSource).toContain("aria-describedby={`${name}-consequence`}")
    expect(detailsSource).toContain("Removal incomplete")
  })

  it("shows consequences before saving a Material Rule Change", () => {
    expect(detailsSource).toContain("policyChangeConsequences(")
    expect(detailsSource).toContain("disabled={!changed || update.isPending}")
  })

  it("confirms a Rule Replacement separately and names its destructive effect", () => {
    expect(detailsSource).toContain('id="replace-confirmation"')
    expect(detailsSource).toContain("replacementConfirmLabel(")
    expect(detailsSource).toContain("Review replacement")
  })

  it("keeps keyboard focus inside destructive confirmations", () => {
    expect(detailsSource).toContain("heading.current?.focus()")
    expect(detailsSource).toContain("returnFocus.current?.focus()")
  })

  it("reports the removal outcome on the rules list, including events left in place", () => {
    expect(detailsSource).toContain("const outcome = removalOutcome(result, destinationName)")
    expect(detailsSource).toContain('noticeTone: outcome.attention ? "attention" : undefined')
    expect(rulesSource).toContain("notice.attention")
    expect(rulesSource).toContain("Review in Activity")
  })

  it("does not refetch a removed rule before leaving its page", () => {
    expect(detailsSource).toContain('removeQueries({ queryKey: ["rule", ruleId] })')
  })

  it("links every rule row to its details and renders the details route", () => {
    expect(rulesSource).toContain("appPathForRule(rule.id)")
    expect(dashboardSource).toContain("<RuleDetailsView")
    expect(rulesSource).toContain("Preview required")
  })
})
