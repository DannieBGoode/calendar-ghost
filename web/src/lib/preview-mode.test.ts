import { describe, expect, it } from "vitest"

import { isPreviewMode, previewPathForView, previewSearchForView } from "./preview-mode"

describe("preview mode", () => {
  it("only enables for explicit preview query parameters", () => {
    expect(isPreviewMode("")).toBe(false)
    expect(isPreviewMode("?preview=1")).toBe(true)
    expect(isPreviewMode("?dashboardPreview=1")).toBe(true)
    expect(isPreviewMode("?preview=0")).toBe(false)
  })

  it("keeps the dashboard hero controls available and carries preview across routes", () => {
    expect(previewSearchForView("overview")).toBe("?preview=1&dashboardPreview=1&heroPreview=1")
    expect(previewPathForView("activity")).toBe("/activity?preview=1")
    expect(previewSearchForView("activity", "?rule=preview-rule-work&show=blocked")).toBe(
      "?rule=preview-rule-work&show=blocked&preview=1",
    )
  })
})
