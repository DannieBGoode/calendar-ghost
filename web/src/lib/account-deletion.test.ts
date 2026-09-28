import { describe, expect, it } from "vitest"

import settingsSource from "../features/settings.tsx?raw"
import apiSource from "./api.ts?raw"

describe("permanent Connected Account deletion", () => {
  it("keeps disconnect and permanent deletion as separate confirmed actions", () => {
    expect(apiSource).toContain("/disconnect")
    expect(apiSource).toContain("deleteAccount")
    expect(settingsSource).toContain("Delete account")
    expect(settingsSource).toContain("Delete permanently")
    expect(settingsSource).toContain("Managed Projections in Google Calendar will not be deleted")
  })
})
