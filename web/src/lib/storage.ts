import type { DatabaseUsage, LogUsage } from "@/lib/api"

const UNITS = ["KB", "MB", "GB", "TB"]

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${Math.round(bytes)} B`
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(1)} ${UNITS[unit]}`
}

// A fixed 3-letter table, because some locales (e.g. en-GB) spell September "Sept" in CLDR's
// short-month data; this keeps the abbreviation consistent regardless of locale.
const SHORT_MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
]

function day(value: string, locale?: string, withYear = true): string {
  const date = new Date(value)
  const parts = new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    ...(withYear ? { year: "numeric" } : {}),
    timeZone: "UTC",
  }).formatToParts(date)
  return parts
    .map((part) => (part.type === "month" ? SHORT_MONTHS[date.getUTCMonth()] : part.value))
    .join("")
}

export function activitySummary(usage: DatabaseUsage, locale?: string): string {
  const size = formatBytes(usage.bytes)
  if (usage.activity_entries === 0 || !usage.oldest_activity_at) return `${size} · No Activity yet`
  const count = usage.activity_entries.toLocaleString(locale ?? "en-US")
  const noun = usage.activity_entries === 1 ? "Activity entry" : "Activity entries"
  return `${size} · ${count} ${noun} since ${day(usage.oldest_activity_at, locale)}`
}

export function logSummary(usage: LogUsage | null, locale?: string): string {
  if (usage === null) return "File logging is off. Container logs are still available."
  if (usage.files === 0 || !usage.oldest_at || !usage.newest_at) return "No log lines yet"
  const sameYear = usage.oldest_at.slice(0, 4) === usage.newest_at.slice(0, 4)
  return `${formatBytes(usage.bytes)} · ${day(usage.oldest_at, locale, !sameYear)} – ${day(usage.newest_at, locale)}`
}

export function clearActivityBody(entries: number, days: number): string {
  if (entries === 0) return `Nothing is older than ${days} days.`
  const count = entries.toLocaleString("en-US")
  const noun = entries === 1 ? "Activity entry" : "Activity entries"
  return `${count} ${noun} older than ${days} days will be removed. Each event's latest entry is kept. This cannot be undone.`
}
