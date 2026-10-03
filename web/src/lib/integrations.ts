import type { IntegrationToken } from "@/lib/api"

export type IntegrationExample = { title: string; description: string; code: string }

/** Whether this installation is reachable only over plain HTTP, where a bearer token travels in the clear. */
export function isPlainHttp(origin: string): boolean {
  return origin.startsWith("http://")
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
  ]
}

const USAGE_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
]

// Unlike the Overview's relativeTime(), this always states the number ("1 day ago", never
// "yesterday"), because a revoked or last-used timestamp here is a precise audit fact, not a
// casual status line.
const usageFormat = new Intl.RelativeTimeFormat("en", { numeric: "always" })

function ageOf(iso: string, now: number): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000)
  if (Number.isNaN(seconds)) return "at an unknown time"
  if (Math.abs(seconds) < 60) return "just now"
  for (const [unit, size] of USAGE_UNITS) {
    if (Math.abs(seconds) >= size || unit === "minute") {
      const value = Math.trunc(seconds / size)
      if (unit === "day" && Math.abs(value) > 6) {
        return `on ${new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" })}`
      }
      return usageFormat.format(value, unit)
    }
  }
  return "just now"
}

/** When a token was last used, that it was never used, or that it was revoked. */
export function tokenUsage(token: IntegrationToken, now: number): string {
  if (token.revoked_at) return `Revoked ${ageOf(token.revoked_at, now)}`
  if (!token.last_used_at) return "Never used"
  return `Last used ${ageOf(token.last_used_at, now)}`
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
