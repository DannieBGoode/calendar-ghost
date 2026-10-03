import { describe, expect, it } from "vitest"

import overviewSource from "../features/overview.tsx?raw"

describe("Overview onboarding", () => {
  it("counts only an authorized account as the first completed step", () => {
    expect(overviewSource).toContain("const done = [dashboard.connected_accounts > 0,")
    expect(overviewSource).toContain("Reauthorize your Google account")
  })

  it("does not promise a first sync while the account needs attention", () => {
    expect(overviewSource).toContain('health.tone === "attention"')
    expect(overviewSource).toContain('"Waiting for recovery"')
  })
})
