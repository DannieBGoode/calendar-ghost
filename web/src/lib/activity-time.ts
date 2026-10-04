import { CLOCK } from "@/i18n/format"
import type { I18n } from "@/i18n/translator"

/** How Activity writes times: run times, day headers, and recorded event times. */

/** The Time column: the clock time alone, since day headers name the day. */
export function formatClockTime(i18n: I18n, value: string): string {
  return i18n.format.time(value)
}

function daysBefore(now: Date, date: Date): number {
  return Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000)
}

export function formatDay(i18n: I18n, value: string, now: Date = new Date()): string {
  const date = new Date(value)
  const days = daysBefore(now, date)
  if (days === 0) return i18n.t("activity.day.today")
  if (days === 1) return i18n.t("activity.day.yesterday")
  return i18n.format.date(date, {
    weekday: "long",
    day: "numeric",
    month: "long",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  })
}

export function formatRunTime(i18n: I18n, value: string, now: Date = new Date()): string {
  const date = new Date(value)
  const time = i18n.format.time(date)
  const days = daysBefore(now, date)
  if (days === 0) return i18n.t("activity.runTime.today", { time })
  if (days === 1) return i18n.t("activity.runTime.yesterday", { time })
  const day = i18n.format.date(date, {
    weekday: "short",
    day: "numeric",
    month: "short",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  })
  return i18n.t("activity.runTime.day", { day, time })
}

export function formatEventTime(
  i18n: I18n,
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
  const { t, format } = i18n
  if (event.all_day) {
    const start = new Date(`${event.starts}T00:00:00`)
    const lastDay = new Date(`${event.ends}T00:00:00`)
    lastDay.setDate(lastDay.getDate() - 1)
    const first = format.date(start, dayFormat)
    if (lastDay.getTime() <= start.getTime()) return t("common.range.allDay", { day: first })
    return t("common.range.allDaySpan", { first, last: format.date(lastDay, dayFormat) })
  }
  const start = new Date(event.starts)
  const end = new Date(event.ends)
  if (start.toDateString() === end.toDateString()) {
    return t("common.range.sameDay", { day: format.date(start, dayFormat), start: format.time(start), end: format.time(end) })
  }
  return t("common.range.span", {
    start: format.dateTime(start, { ...dayFormat, ...CLOCK }),
    end: format.dateTime(end, { ...dayFormat, ...CLOCK }),
  })
}

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}
