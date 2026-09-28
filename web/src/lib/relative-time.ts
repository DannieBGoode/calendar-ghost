const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
]

const format = new Intl.RelativeTimeFormat("en", { numeric: "auto" })

/** A short, human distance from now, such as "5 minutes ago" or "yesterday". */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000)
  if (Number.isNaN(seconds)) return "at an unknown time"
  if (Math.abs(seconds) < 60) return "just now"
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size || unit === "minute") {
      const value = Math.trunc(seconds / size)
      if (unit === "day" && Math.abs(value) > 6) {
        return `on ${new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" })}`
      }
      return format.format(value, unit)
    }
  }
  return "just now"
}
