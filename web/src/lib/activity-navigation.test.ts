import { describe, expect, it } from "vitest"

import appSource from "../App.tsx?raw"
import dashboardSource from "../features/dashboard.tsx?raw"

describe("Activity navigation", () => {
  it("starts Activity fresh from the address on every arrival, including back and forward", () => {
    expect(dashboardSource).toContain("<ActivityView key={visit} onViewChange={onViewChange} onOpenRule={onOpenRule} />")
    expect(appSource.match(/setVisit\(\(count\) => count \+ 1\)/g)).toHaveLength(2)
  })
})
