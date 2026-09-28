import { describe, expect, it } from "vitest"

import { previewSummary } from "./rule-preview"

describe("previewSummary", () => {
  it("keeps the single-event summary unchanged", () => {
    expect(previewSummary({ eligible_events: 3, excluded_events: 1, recurring_series: 0, occurrence_changes: 0 })).toBe(
      "Preview found 3 eligible and 1 excluded events.",
    )
  })

  it("mentions recurring series and occurrence changes", () => {
    expect(previewSummary({ eligible_events: 3, excluded_events: 0, recurring_series: 2, occurrence_changes: 1 })).toBe(
      "Preview found 3 eligible and 0 excluded events, including 2 recurring series and 1 changed occurrence.",
    )
  })
})
