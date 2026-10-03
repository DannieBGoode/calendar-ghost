import { describe, expect, it } from "vitest"

import type { IntegrationToken } from "@/lib/api"
import {
  copyToken,
  integrationExamples,
  isPlainHttp,
  tokenUsage,
} from "@/lib/integrations"

const now = Date.parse("2026-10-03T12:00:00Z")
const token: IntegrationToken = {
  id: "t1",
  name: "Uptime Kuma",
  scope: "status:read",
  created_at: "2026-10-01T09:00:00Z",
  last_used_at: "2026-10-03T11:57:00Z",
  revoked_at: null,
}

describe("integrationExamples", () => {
  it("fills each example with this installation's address and reads the token from the environment", () => {
    const examples = integrationExamples("https://ghost.example.lan")
    expect(examples.map((example) => example.title)).toEqual(["Uptime Kuma", "Homepage", "Claude Code", "Codex"])
    const text = examples.map((example) => example.code).join("\n")
    expect(text).toContain("https://ghost.example.lan/api/v1/status")
    expect(text).toContain("https://ghost.example.lan/mcp")
    expect(text).toContain("$.needs_attention")
    expect(text).toContain("${CALENDAR_GHOST_TOKEN}")
    expect(text).toContain('bearer_token_env_var = "CALENDAR_GHOST_TOKEN"')
    expect(text).not.toContain("cgs_")
  })
})

describe("isPlainHttp", () => {
  it("warns only for plain HTTP", () => {
    expect(isPlainHttp("http://ghost.lan:8000")).toBe(true)
    expect(isPlainHttp("https://ghost.example.lan")).toBe(false)
  })
})

describe("tokenUsage", () => {
  it("says when a token was last used, never used, or revoked", () => {
    expect(tokenUsage(token, now)).toBe("Last used 3 minutes ago")
    expect(tokenUsage({ ...token, last_used_at: null }, now)).toBe("Never used")
    expect(tokenUsage({ ...token, revoked_at: "2026-10-02T12:00:00Z" }, now)).toBe("Revoked 1 day ago")
  })
})

describe("copyToken", () => {
  it("copies with the Clipboard API when it is available and succeeds", async () => {
    const writeText = async () => undefined
    expect(await copyToken("secret", { writeText })).toBe("copied")
  })

  it("falls back when the Clipboard API is unavailable", async () => {
    expect(await copyToken("secret", undefined)).toBe("unavailable")
  })

  it("falls back when the Clipboard API rejects, such as on a plain HTTP origin", async () => {
    const writeText = async () => {
      throw new Error("The request is not allowed by the user agent.")
    }
    expect(await copyToken("secret", { writeText })).toBe("unavailable")
  })
})
