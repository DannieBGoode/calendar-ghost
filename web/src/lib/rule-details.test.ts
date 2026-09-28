import { describe, expect, it } from "vitest"

import dashboardSource from "../features/dashboard.tsx?raw"
import detailsSource from "../features/rule-details.tsx?raw"

describe("Rule Details presentation", () => {
  it("defaults Rule Removal to deleting mapped projections and confirms separately", () => {
    expect(detailsSource).toContain('useState<ProjectionHandling>("delete")')
    expect(detailsSource).toContain("removalConfirmLabel(")
    expect(detailsSource).toContain('role="radiogroup"')
    expect(detailsSource).toContain("Removal incomplete")
  })

  it("shows consequences before saving a Material Rule Change", () => {
    expect(detailsSource).toContain("policyChangeConsequences(")
    expect(detailsSource).toContain("disabled={!changed || update.isPending}")
  })

  it("links every rule row to its details and renders the details route", () => {
    expect(dashboardSource).toContain("appPathForRule(rule.id)")
    expect(dashboardSource).toContain("<RuleDetailsView")
    expect(dashboardSource).toContain("Preview required")
  })
})
