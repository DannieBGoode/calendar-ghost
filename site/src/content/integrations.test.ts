import { readFileSync } from "node:fs"
import { describe, expect, it } from "vitest"
import { STATUS_CHECK_COMMAND } from "./integrations"

// The indirection through `here` keeps Vite's static `new URL(url, import.meta.url)` asset
// rewrite (which serves the path over http://, not file://) from matching this call.
const here = import.meta.url
const GUIDE = readFileSync(new URL("../../../docs/self-hosting.md", here), "utf8")

describe("status check command", () => {
  it("matches the self-hosting guide, so the page never drifts from it", () => {
    expect(GUIDE).toContain(STATUS_CHECK_COMMAND)
  })

  it("sends the token only in the Authorization header", () => {
    expect(STATUS_CHECK_COMMAND).toContain('-H "Authorization: Bearer ')
    expect(STATUS_CHECK_COMMAND).not.toMatch(/[?&]token=/)
  })
})
