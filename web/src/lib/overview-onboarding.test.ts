import { describe, expect, it } from "vitest"

import overviewSource from "../features/overview.tsx?raw"

describe("Overview onboarding", () => {
  it("counts only an authorized account as the first completed step", () => {
    expect(overviewSource).toContain("const done = [dashboard.connected_accounts > 0,")
    expect(overviewSource).toContain("overview.onboarding.steps.reauthorize.title")
  })
})
