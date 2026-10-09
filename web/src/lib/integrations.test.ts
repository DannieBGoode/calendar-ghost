import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"
import type { IntegrationToken } from "@/lib/api"
import {
  copyToken,
  integrationExamples,
  integrationSummary,
  needsTransportNote,
  tokenUsage,
} from "@/lib/integrations"

const i18n = testI18n()
const now = Date.parse("2026-10-03T12:00:00Z")
const token: IntegrationToken = {
  id: "t1",
  name: "Uptime Kuma",
  scopes: ["status:read"],
  created_at: "2026-10-01T09:00:00Z",
  last_used_at: "2026-10-03T11:57:00Z",
  revoked_at: null,
}

describe("integrationExamples", () => {
  it("fills each example with this installation's address and reads the token from the environment", () => {
    const examples = integrationExamples(i18n, "https://ghost.example.lan")
    expect(examples.map((example) => example.title)).toEqual([
      "Uptime Kuma",
      "Homepage",
      "Claude Code",
      "Codex",
      "Claude Desktop and other apps",
    ])
    const text = examples.map((example) => example.code).join("\n")
    expect(text).toContain("https://ghost.example.lan/api/v1/status")
    expect(text).toContain("https://ghost.example.lan/mcp")
    expect(text).toContain("$.needs_attention")
    expect(text).toContain("${CALENDAR_GHOST_TOKEN}")
    expect(text).toContain('bearer_token_env_var = "CALENDAR_GHOST_TOKEN"')
    expect(text).not.toContain("cgs_")
  })

  it("connects desktop apps through the mcp-remote bridge, allowing plain HTTP only where needed", () => {
    const desktop = (origin: string) => {
      const example = integrationExamples(i18n, origin).find((item) => item.title === "Claude Desktop and other apps")
      const config = JSON.parse(example?.code ?? "{}") as { mcpServers: Record<string, { args: string[] }> }
      return config.mcpServers["calendar-ghost"]
    }

    expect(desktop("https://ghost.example.lan")).toEqual({
      command: "npx",
      args: ["-y", "mcp-remote", "https://ghost.example.lan/mcp", "--header", "Authorization:${AUTH_HEADER}"],
      env: { AUTH_HEADER: "Bearer <token>" },
    })
    expect(desktop("http://localhost:8000")?.args).not.toContain("--allow-http")
    expect(desktop("http://ghost.lan:8000")?.args).toEqual([
      "-y",
      "mcp-remote",
      "http://ghost.lan:8000/mcp",
      "--allow-http",
      "--header",
      "Authorization:${AUTH_HEADER}",
    ])
  })
})

describe("needsTransportNote", () => {
  it.each([
    "http://localhost:8000",
    "http://app.localhost:8000",
    "http://127.0.0.1:8000",
    "http://[::1]:8000",
    "http://192.168.1.20:8000",
    "http://10.0.0.5",
    "http://172.16.0.9",
    "http://172.31.255.1",
    "http://100.101.102.103",
    "http://169.254.10.10",
    "http://raspberrypi",
    "http://raspberrypi.local:8000",
    "http://ghost.lan",
    "http://ghost.home.arpa",
    "http://ghost.internal",
    "http://[fd12:3456::1]:8000",
    "https://ghost.example.com",
  ])("stays quiet for %s, where a token does not cross the internet in the clear", (origin) => {
    expect(needsTransportNote(origin)).toBe(false)
  })

  it.each(["http://ghost.example.com", "http://203.0.113.7:8000", "http://172.32.0.1", "http://100.128.0.1"])(
    "notes that %s sends tokens in the clear",
    (origin) => {
      expect(needsTransportNote(origin)).toBe(true)
    },
  )
})

describe("tokenUsage", () => {
  it("says when a token was issued and last used, or that it was revoked", () => {
    expect(tokenUsage(i18n, token, now)).toBe("Last used 3 minutes ago · issued 2 days ago")
    expect(tokenUsage(i18n, { ...token, last_used_at: null }, now)).toBe("Never used · issued 2 days ago")
    expect(tokenUsage(i18n, { ...token, revoked_at: "2026-10-02T12:00:00Z" }, now)).toBe("Revoked yesterday")
  })
})

describe("integrationSummary", () => {
  it("says there are no tokens until the first one is issued", () => {
    expect(integrationSummary(i18n, [], now)).toBe("No tokens yet")
    expect(integrationSummary(i18n, [{ ...token, revoked_at: "2026-10-02T12:00:00Z" }], now)).toBe("No tokens yet")
  })

  it("counts the tokens in use and names the most recent use", () => {
    expect(integrationSummary(i18n, [token], now)).toBe("1 token · last used 3 minutes ago")
    expect(
      integrationSummary(i18n, [token, { ...token, id: "t2", last_used_at: "2026-10-03T09:00:00Z" }], now),
    ).toBe("2 tokens · last used 3 minutes ago")
    expect(integrationSummary(i18n, [{ ...token, last_used_at: null }], now)).toBe("1 token · never used")
  })
})

describe("copyToken", () => {
  it("copies with the Clipboard API when it is available and succeeds", async () => {
    const writeText = () => Promise.resolve()
    expect(await copyToken("secret", { writeText })).toBe("copied")
  })

  it("falls back when the Clipboard API is unavailable", async () => {
    expect(await copyToken("secret", undefined)).toBe("unavailable")
  })

  it("falls back when the Clipboard API rejects, such as on a plain HTTP origin", async () => {
    const writeText = () => Promise.reject(new Error("The request is not allowed by the user agent."))
    expect(await copyToken("secret", { writeText })).toBe("unavailable")
  })
})
