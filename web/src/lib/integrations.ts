import type { IntegrationToken } from "@/lib/api"
import { relativeTime } from "@/lib/relative-time"

export type IntegrationExample = { title: string; description: string; code: string }

// Host names that only resolve inside a home network or on this machine.
const LOCAL_SUFFIXES = [".localhost", ".local", ".lan", ".home.arpa", ".internal"]

// Private and local IPv4 blocks: the first octet, then the lowest and highest second octet.
const PRIVATE_IPV4: readonly (readonly [number, number, number])[] = [
  [10, 0, 255],
  [127, 0, 255],
  [172, 16, 31],
  [192, 168, 168],
  [169, 254, 254],
  // Tailscale and other carrier-grade NAT addresses never cross the internet in the clear.
  [100, 64, 127],
]

function privateIpv4(host: string): boolean {
  const parts = host.split(".").map(Number)
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return false
  const [a, b = -1] = parts
  return PRIVATE_IPV4.some(([first, low, high]) => a === first && b >= low && b <= high)
}

function privateIpv6(host: string): boolean {
  const address = host.replace(/^\[|\]$/g, "").toLowerCase()
  return address === "::1" || /^f[cd][0-9a-f]{2}:/.test(address) || address.startsWith("fe80:")
}

/**
 * Whether to note that a token sent to this address travels in the clear across the internet.
 * Plain HTTP on this machine or a home network is the homelab norm and stays quiet.
 */
export function needsTransportNote(origin: string): boolean {
  const url = new URL(origin)
  if (url.protocol !== "http:") return false
  const host = url.hostname.toLowerCase()
  const local =
    host === "localhost" ||
    !host.includes(".") ||
    LOCAL_SUFFIXES.some((suffix) => host.endsWith(suffix)) ||
    privateIpv4(host) ||
    privateIpv6(host)
  return !local
}

/** Copy-ready examples for monitors, dashboards, and AI agents, addressed at this installation. */
export function integrationExamples(origin: string): IntegrationExample[] {
  const status = `${origin}/api/v1/status`
  const mcp = `${origin}/mcp`
  return [
    {
      title: "Uptime Kuma",
      description: "Add an HTTP(s) - Json Query monitor. Alert when the result is not false.",
      code: `URL: ${status}\nHeaders: {"Authorization": "Bearer <token>"}\nJson Query: $.needs_attention\nExpected Value: false`,
    },
    {
      title: "Homepage",
      description: "Add a customapi widget to the Calendar Ghost service.",
      code: `widget:\n  type: customapi\n  url: ${status}\n  headers:\n    Authorization: Bearer {{HOMEPAGE_VAR_CALENDAR_GHOST_TOKEN}}\n  mappings:\n    - field: status\n      label: Status\n    - field: summary\n      label: Summary`,
    },
    {
      title: "Claude Code",
      description: "Keep the token in an environment variable, then add the server.",
      code: `claude mcp add --transport http calendar-ghost ${mcp} \\\n  --header "Authorization: Bearer \${CALENDAR_GHOST_TOKEN}"`,
    },
    {
      title: "Codex",
      description: "Add this to ~/.codex/config.toml and set CALENDAR_GHOST_TOKEN.",
      code: `[mcp_servers.calendar-ghost]\nurl = "${mcp}"\nbearer_token_env_var = "CALENDAR_GHOST_TOKEN"`,
    },
    {
      title: "Claude Desktop and other apps",
      description:
        "Apps that start MCP servers on your computer connect through the mcp-remote bridge, which needs Node.js. In Claude Desktop, add this to the configuration file opened from Settings, Developer, Edit Config, then restart it.",
      code: JSON.stringify({ mcpServers: { "calendar-ghost": desktopBridge(mcp) } }, null, 2),
    },
  ]
}

// mcp-remote refuses plain HTTP except on this machine unless told otherwise.
const BRIDGE_LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"])

function desktopBridge(mcp: string) {
  const url = new URL(mcp)
  const allowHttp = url.protocol === "http:" && !BRIDGE_LOCAL_HOSTS.has(url.hostname)
  return {
    command: "npx",
    args: ["-y", "mcp-remote", mcp, ...(allowHttp ? ["--allow-http"] : []), "--header", "Authorization:${AUTH_HEADER}"],
    env: { AUTH_HEADER: "Bearer <token>" },
  }
}

/** When a token was last used and issued, so tokens with the same name can be told apart. */
export function tokenUsage(token: IntegrationToken, now: number): string {
  if (token.revoked_at) return `Revoked ${relativeTime(token.revoked_at, now)}`
  const used = token.last_used_at ? `Last used ${relativeTime(token.last_used_at, now)}` : "Never used"
  return `${used} · issued ${relativeTime(token.created_at, now)}`
}

/** One line for the collapsed Integrations group: how many tokens are in use, and the latest use. */
export function integrationSummary(tokens: IntegrationToken[], now: number): string {
  const active = tokens.filter((token) => !token.revoked_at)
  if (active.length === 0) return "No tokens yet"
  const count = `${active.length} ${active.length === 1 ? "token" : "tokens"}`
  const uses = active.flatMap((token) => (token.last_used_at ? [token.last_used_at] : []))
  if (uses.length === 0) return `${count} · never used`
  const latest = uses.reduce((a, b) => (Date.parse(a) >= Date.parse(b) ? a : b))
  return `${count} · last used ${relativeTime(latest, now)}`
}

export type ClipboardWriter = { writeText: (text: string) => Promise<void> }
export type CopyResult = "copied" | "unavailable"

/**
 * Copies a token with the Clipboard API, which exists only in secure contexts: on a plain-HTTP
 * LAN address `navigator.clipboard` is undefined, and even where it exists a write can still be
 * rejected. Either way this reports "unavailable" instead of throwing, so the caller can keep the
 * token visible and selectable.
 */
export async function copyToken(
  token: string,
  clipboard: ClipboardWriter | undefined,
): Promise<CopyResult> {
  if (!clipboard?.writeText) return "unavailable"
  try {
    await clipboard.writeText(token)
    return "copied"
  } catch {
    return "unavailable"
  }
}
