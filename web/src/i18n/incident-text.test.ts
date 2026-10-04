import { describe, expect, it } from "vitest"

import { incidentText } from "./incident-text"
import { testI18n } from "./testing"

describe("incidentText", () => {
  it("shows the stored summary", () => {
    expect(incidentText(testI18n(), { summary: "Stored English summary" })).toBe("Stored English summary")
  })
})
