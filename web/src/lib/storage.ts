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
  const reclaimable =
    usage.reclaimable_bytes > 0 ? ` · ${formatBytes(usage.reclaimable_bytes)} can be reclaimed` : ""
  if (usage.activity_entries === 0 || !usage.oldest_activity_at)
    return `${size} · No Activity yet${reclaimable}`
  const count = usage.activity_entries.toLocaleString(locale ?? "en-US")
  const noun = usage.activity_entries === 1 ? "Activity entry" : "Activity entries"
  return `${size} · ${count} ${noun} since ${day(usage.oldest_activity_at, locale)}${reclaimable}`
}

// Clearing compacts the database even when nothing is old enough, so space left by an earlier
// clear (one answered 409 while a rule was synchronizing) can still be reclaimed.
export function canClearActivity(usage: DatabaseUsage): boolean {
  return usage.activity_entries > 0 || usage.reclaimable_bytes > 0
}

export function logSummary(usage: LogUsage | null, locale?: string): string {
  if (usage === null) return "File logging is off. Recent lines are still in the container logs, which rotate."
  if (usage.files === 0 || !usage.oldest_at || !usage.newest_at) return "No log lines yet"
  const sameYear = usage.oldest_at.slice(0, 4) === usage.newest_at.slice(0, 4)
  return `${formatBytes(usage.bytes)} · ${day(usage.oldest_at, locale, !sameYear)} – ${day(usage.newest_at, locale)}`
}

export type ClearActivityConfirmation = {
  body: string
  confirmLabel: string
  pendingLabel: string
  canConfirm: boolean
}

export function clearActivityConfirmation(
  entries: number,
  days: number,
  reclaimableBytes: number,
): ClearActivityConfirmation {
  const clearing = { confirmLabel: "Clear Activity", pendingLabel: "Clearing…" }
  if (entries > 0) {
    const count = entries.toLocaleString("en-US")
    const noun = entries === 1 ? "Activity entry" : "Activity entries"
    return {
      ...clearing,
      body: `${count} ${noun} older than ${days} days will be removed. Each event's latest entry is kept. This cannot be undone.`,
      canConfirm: true,
    }
  }
  if (reclaimableBytes > 0) {
    return {
      body: `Nothing is older than ${days} days. ${formatBytes(reclaimableBytes)} left by earlier clearing can still be reclaimed.`,
      confirmLabel: "Reclaim space",
      pendingLabel: "Reclaiming…",
      canConfirm: true,
    }
  }
  return { ...clearing, body: `Nothing is older than ${days} days.`, canConfirm: false }
}

export function countFailedConfirmation(message: string): ClearActivityConfirmation {
  return {
    body: `The entries to remove could not be counted: ${message}`,
    confirmLabel: "Count again",
    pendingLabel: "Counting…",
    canConfirm: true,
  }
}

export function clearedActivityMessage(removed: number, reclaimableBefore: number): string {
  if (removed === 0) {
    return reclaimableBefore > 0
      ? "The space left by earlier clearing was reclaimed."
      : "Nothing was old enough to clear."
  }
  const noun = removed === 1 ? "Activity entry was" : "Activity entries were"
  return `${removed.toLocaleString("en-US")} ${noun} cleared.`
}
