/** How Activity writes times: run times, day headers, and recorded event times. */

/** The Time column: the clock time alone, since day headers name the day. */
export function formatClockTime(value: string): string {
  return new Date(value).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
}

export function formatDay(value: string, now: Date = new Date()): string {
  const date = new Date(value)
  const days = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000)
  if (days === 0) return "Today"
  if (days === 1) return "Yesterday"
  return date.toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  })
}

export function formatRunTime(value: string, now: Date = new Date()): string {
  const date = new Date(value)
  const time = date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
  const days = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000)
  if (days === 0) return `Today at ${time}`
  if (days === 1) return `Yesterday at ${time}`
  const day = date.toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  })
  return `${day} at ${time}`
}

export function formatEventTime(
  event: { all_day: boolean; starts: string | null; ends: string | null },
  now: Date = new Date(),
): string {
  if (!event.starts || !event.ends) return ""
  // The year is noise for this year's events, which are most of them.
  const sameYear = new Date(event.all_day ? `${event.starts}T00:00:00` : event.starts).getFullYear() === now.getFullYear()
  const dayFormat: Intl.DateTimeFormatOptions = {
    weekday: "short",
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
  }
  if (event.all_day) {
    const start = new Date(`${event.starts}T00:00:00`)
    const lastDay = new Date(`${event.ends}T00:00:00`)
    lastDay.setDate(lastDay.getDate() - 1)
    const first = start.toLocaleDateString(undefined, dayFormat)
    if (lastDay.getTime() <= start.getTime()) return `${first}, all day`
    return `${first} – ${lastDay.toLocaleDateString(undefined, dayFormat)}, all day`
  }
  const start = new Date(event.starts)
  const end = new Date(event.ends)
  const timeFormat: Intl.DateTimeFormatOptions = { hour: "numeric", minute: "2-digit" }
  const sameDay = start.toDateString() === end.toDateString()
  return sameDay
    ? `${start.toLocaleDateString(undefined, dayFormat)}, ${start.toLocaleTimeString(undefined, timeFormat)} – ${end.toLocaleTimeString(undefined, timeFormat)}`
    : `${start.toLocaleString(undefined, { ...dayFormat, ...timeFormat })} – ${end.toLocaleString(undefined, { ...dayFormat, ...timeFormat })}`
}

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}
