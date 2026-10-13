import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"

type Frequency = "DAILY" | "WEEKLY" | "MONTHLY" | "YEARLY"
type WeekdayRule = { weekday: number; ordinal: number | null }

/** The parts of an iCalendar RRULE this interface can put into words and step through. */
export type Repeat = {
  frequency: Frequency
  interval: number
  byDay: WeekdayRule[]
  byMonthDay: number[]
  count: number | null
  until: Date | null
  /** Days the series skips (EXDATE), as "YYYYMMDD" in the series' own calendar. */
  skipped: ReadonlySet<string>
}

/** A calendar day; `month` counts from 0, as Date does. */
type Day = { year: number; month: number; day: number }
type WallTime = Day & { hour: number; minute: number; second: number }

const FREQUENCIES: readonly string[] = ["DAILY", "WEEKLY", "MONTHLY", "YEARLY"]
const WEEKDAYS = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]
/** Parts that narrow a rule in ways it would be wrong to ignore; such a rule just "repeats". */
const UNSUPPORTED = ["BYSETPOS", "BYWEEKNO", "BYYEARDAY", "BYMONTH", "BYHOUR", "BYMINUTE", "BYSECOND"]
/** Day filters each frequency steps through; any other one would be ignored, so it is refused. */
const DAY_FILTERS: Record<Frequency, readonly string[]> = {
  DAILY: [],
  WEEKLY: ["BYDAY"],
  MONTHLY: ["BYDAY", "BYMONTHDAY"],
  YEARLY: [],
}
/** Lines that add dates to a series; this interface cannot place those, so it does not try. */
const ADDING_LINES = ["RDATE", "EXRULE"]
const ORDINALS: Record<string, MessageKey> = {
  "1": "rulePreview.repeat.ordinal.first",
  "2": "rulePreview.repeat.ordinal.second",
  "3": "rulePreview.repeat.ordinal.third",
  "4": "rulePreview.repeat.ordinal.fourth",
  "-1": "rulePreview.repeat.ordinal.last",
}
/** Enough steps for a daily series over decades; a rule that needs more is shown as it began. */
const STEP_LIMIT = 20_000

function weekdayRule(value: string): WeekdayRule | null {
  const match = /^([+-]?\d{1,2})?(SU|MO|TU|WE|TH|FR|SA)$/.exec(value)
  if (!match?.[2]) return null
  return { weekday: WEEKDAYS.indexOf(match[2]), ordinal: match[1] ? Number(match[1]) : null }
}

function untilDate(value: string): Date | null {
  const match = /^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})(Z)?)?$/.exec(value)
  if (!match) return null
  const [, year, month, day, hour = "23", minute = "59", second = "59", utc] = match
  const parts = [Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute), Number(second)] as const
  return utc ? new Date(Date.UTC(...parts)) : new Date(...parts)
}

function ruleParts(line: string): Map<string, string> {
  return new Map(
    line.slice("RRULE:".length).split(";").map((part) => {
      const [name = "", value = ""] = part.split("=")
      return [name.toUpperCase(), value.toUpperCase()] as const
    }),
  )
}

function list(parts: Map<string, string>, name: string): string[] {
  return parts.get(name)?.split(",") ?? []
}

function limits(parts: Map<string, string>): Pick<Repeat, "count" | "until"> {
  const count = parts.get("COUNT")
  const until = parts.get("UNTIL")
  return { count: count ? Number(count) : null, until: until ? untilDate(until) : null }
}

/** "YYYYMMDD" for every EXDATE value, whatever its time or zone parameter. */
function skippedDays(lines: readonly string[]): Set<string> {
  return new Set(
    lines
      .filter((line) => line.toUpperCase().startsWith("EXDATE"))
      .flatMap((line) => (line.split(":")[1] ?? "").split(","))
      .map((value) => value.slice(0, 8))
      .filter((value) => /^\d{8}$/.test(value)),
  )
}

/** Whether the rule uses only parts the stepping below honors; anything else would misplace it. */
function supported(lines: readonly string[], frequency: string, parts: Map<string, string>): frequency is Frequency {
  if (!FREQUENCIES.includes(frequency)) return false
  if (lines.some((line) => ADDING_LINES.some((name) => line.toUpperCase().startsWith(name)))) return false
  if (UNSUPPORTED.some((name) => parts.has(name))) return false
  const filters = ["BYDAY", "BYMONTHDAY"].filter((name) => parts.has(name))
  const allowed = new Set(DAY_FILTERS[frequency as Frequency])
  if (filters.length > 1 || filters.some((name) => !allowed.has(name))) return false
  return !parts.has("WKST") || parts.get("WKST") === "MO"
}

/** The rule in an event's recurrence lines, or null when it has none this interface can read. */
export function readRepeat(lines: readonly string[] | null | undefined): Repeat | null {
  const line = lines?.find((each) => each.toUpperCase().startsWith("RRULE:"))
  if (!lines || !line) return null
  const parts = ruleParts(line)
  const frequency = parts.get("FREQ") ?? ""
  if (!supported(lines, frequency, parts)) return null
  const byDay = list(parts, "BYDAY").map(weekdayRule)
  if (byDay.some((rule) => rule === null)) return null
  return {
    frequency,
    interval: Math.max(1, Number(parts.get("INTERVAL") ?? 1) || 1),
    byDay: byDay as WeekdayRule[],
    byMonthDay: list(parts, "BYMONTHDAY").map(Number).filter((day) => Number.isInteger(day) && day !== 0),
    ...limits(parts),
    skipped: skippedDays(lines),
  }
}

/** Reads and builds instants as wall times in one place: the series' zone, or the browser's. */
type Zone = { wall: (date: Date) => WallTime; at: (wall: WallTime) => Date }

const LOCAL: Zone = {
  wall: (date) => ({
    year: date.getFullYear(),
    month: date.getMonth(),
    day: date.getDate(),
    hour: date.getHours(),
    minute: date.getMinutes(),
    second: date.getSeconds(),
  }),
  at: (wall) => new Date(wall.year, wall.month, wall.day, wall.hour, wall.minute, wall.second),
}

function namedZone(timeZone: string): Zone {
  const format = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "numeric",
    second: "numeric",
  })
  const wall = (date: Date): WallTime => {
    const parts = format.formatToParts(date)
    const value = (type: string) => Number(parts.find((part) => part.type === type)?.value ?? 0)
    return { year: value("year"), month: value("month") - 1, day: value("day"), hour: value("hour"), minute: value("minute"), second: value("second") }
  }
  const utcOf = (time: WallTime) => Date.UTC(time.year, time.month, time.day, time.hour, time.minute, time.second)
  return {
    wall,
    at: (time) => {
      // The zone's offset at a guess, applied twice, settles across a DST change.
      const guess = utcOf(time)
      const first = guess - (utcOf(wall(new Date(guess))) - guess)
      return new Date(guess - (utcOf(wall(new Date(first))) - first))
    },
  }
}

/** The series' zone when the browser knows it, otherwise the browser's own. */
/** One Zone per name, since building its formatter costs far more than using it. */
const ZONES = new Map<string, Zone>()

function zoneOf(timeZone: string | null | undefined): Zone {
  if (!timeZone) return LOCAL
  const known = ZONES.get(timeZone)
  if (known) return known
  try {
    const zone = namedZone(timeZone)
    ZONES.set(timeZone, zone)
    return zone
  } catch {
    return LOCAL
  }
}

function dayOf(year: number, month: number, day: number): Day {
  const date = new Date(Date.UTC(year, month, day))
  return { year: date.getUTCFullYear(), month: date.getUTCMonth(), day: date.getUTCDate() }
}

function weekdayOf(day: Day): number {
  return new Date(Date.UTC(day.year, day.month, day.day)).getUTCDay()
}

/** The day in that very month, or null when the month has no such day, as 31 April. */
function inMonth(year: number, month: number, day: number): Day | null {
  const found = dayOf(year, month, day)
  return found.month === ((month % 12) + 12) % 12 ? found : null
}

function weekdayName(i18n: I18n, weekday: number): string {
  // 4 January 1970 was a Sunday.
  return i18n.format.date(new Date(1970, 0, 4 + weekday), { weekday: "long" })
}

function weekdays(repeat: Repeat, first: Day): number[] {
  const days = repeat.byDay.length ? repeat.byDay.map((rule) => rule.weekday) : [weekdayOf(first)]
  // Monday first, as iCalendar weeks begin.
  return [...new Set(days)].sort((a, b) => ((a + 6) % 7) - ((b + 6) % 7))
}

function monthlyDay(i18n: I18n, repeat: Repeat, first: Day): string {
  const [byDay] = repeat.byDay
  const ordinal = byDay?.ordinal != null ? ORDINALS[String(byDay.ordinal)] : undefined
  if (byDay && ordinal) {
    return i18n.t("rulePreview.repeat.nthWeekday", { ordinal: i18n.t(ordinal), weekday: weekdayName(i18n, byDay.weekday) })
  }
  return i18n.t("rulePreview.repeat.dayOfMonth", { day: repeat.byMonthDay[0] ?? first.day })
}

/** "Weekly on Tuesday", "Every 2 weeks on Monday and Thursday", "Monthly on the last Friday". */
export function describeRepeat(i18n: I18n, repeat: Repeat | null, first: Date, timeZone?: string | null): string {
  if (!repeat) return i18n.t("rulePreview.repeat.unknown")
  const day = zoneOf(timeZone).wall(first)
  const count = repeat.interval
  switch (repeat.frequency) {
    case "DAILY":
      return i18n.t("rulePreview.repeat.daily", { count })
    case "WEEKLY": {
      const days = weekdays(repeat, day)
      if (count === 1 && days.join() === "1,2,3,4,5") return i18n.t("rulePreview.repeat.weekdays")
      return i18n.t("rulePreview.repeat.weekly", { count, days: i18n.format.list(days.map((each) => weekdayName(i18n, each))) })
    }
    case "MONTHLY":
      return i18n.t("rulePreview.repeat.monthly", { count, day: monthlyDay(i18n, repeat, day) })
    case "YEARLY":
      return i18n.t("rulePreview.repeat.yearly", {
        count,
        date: i18n.format.date(new Date(2000, day.month, day.day), { month: "long", day: "numeric" }),
      })
  }
}

function weeklyPeriod(repeat: Repeat, first: Day, step: number): Day[] {
  const monday = first.day - ((weekdayOf(first) + 6) % 7)
  return weekdays(repeat, first).map((weekday) =>
    dayOf(first.year, first.month, monday + step * 7 * repeat.interval + ((weekday + 6) % 7)),
  )
}

function nthWeekdays(year: number, month: number, rule: WeekdayRule): Day[] {
  const days: Day[] = []
  for (let day = 1; day <= 31; day += 1) {
    const date = inMonth(year, month, day)
    if (date && weekdayOf(date) === rule.weekday) days.push(date)
  }
  if (rule.ordinal === null) return days
  const picked = rule.ordinal > 0 ? days[rule.ordinal - 1] : days[days.length + rule.ordinal]
  return picked ? [picked] : []
}

function monthlyPeriod(repeat: Repeat, first: Day, step: number): Day[] {
  const { year } = first
  const month = first.month + step * repeat.interval
  if (repeat.byDay.length) return repeat.byDay.flatMap((rule) => nthWeekdays(year, month, rule))
  const days = repeat.byMonthDay.length ? repeat.byMonthDay : [first.day]
  return days.flatMap((day) => {
    // A negative day counts back from the month's end: -1 is its last day.
    const date = inMonth(year, month, day > 0 ? day : new Date(Date.UTC(year, month + 1, 0)).getUTCDate() + day + 1)
    return date ? [date] : []
  })
}

/** The days one step of the rule covers: a day, a week, a month, or a year. */
function period(repeat: Repeat, first: Day, step: number): Day[] {
  switch (repeat.frequency) {
    case "DAILY":
      return [dayOf(first.year, first.month, first.day + step * repeat.interval)]
    case "WEEKLY":
      return weeklyPeriod(repeat, first, step)
    case "MONTHLY":
      return monthlyPeriod(repeat, first, step)
    case "YEARLY": {
      const date = inMonth(first.year + step * repeat.interval, first.month, first.day)
      return date ? [date] : []
    }
  }
}

function dayKey(day: Day): string {
  return `${day.year}${String(day.month + 1).padStart(2, "0")}${String(day.day).padStart(2, "0")}`
}

/**
 * The series' first date on or after `from`, "ended" when it has none left, or null when the rule
 * cannot be stepped through. Dates are stepped in the series' own zone, so a weekly 18:00 stays
 * 18:00 there across a DST change. Changed occurrences are listed on their own; skipped ones
 * (EXDATE) still count toward COUNT, as iCalendar counts them.
 */
export function nextOccurrence(repeat: Repeat | null, first: Date, from: Date, timeZone?: string | null): Date | "ended" | null {
  if (!repeat) return null
  const zone = zoneOf(timeZone)
  const wall = zone.wall(first)
  let seen = 0
  for (let step = firstStep(repeat, wall, zone.wall(from)); step < STEP_LIMIT; step += 1) {
    const instants = period(repeat, wall, step)
      .map((day) => ({ day, at: zone.at({ ...wall, ...day }) }))
      .filter(({ at }) => at >= first)
      .sort((a, b) => a.at.getTime() - b.at.getTime())
    for (const { day, at } of instants) {
      if (pastEnd(repeat, at, seen)) return "ended"
      seen += 1
      if (at >= from && !repeat.skipped.has(dayKey(day))) return at
    }
  }
  return null
}

/**
 * The step to start from: one before the step that holds `from`, so an old series is not walked
 * from its first date. A COUNT is counted from the first date, so such a series starts at 0.
 */
function firstStep(repeat: Repeat, first: Day, from: Day): number {
  if (repeat.count !== null) return 0
  const days = (Date.UTC(from.year, from.month, from.day) - Date.UTC(first.year, first.month, first.day)) / 86_400_000
  const units = {
    DAILY: days,
    WEEKLY: Math.floor(days / 7),
    MONTHLY: (from.year - first.year) * 12 + from.month - first.month,
    YEARLY: from.year - first.year,
  }[repeat.frequency]
  return Math.max(0, Math.floor(units / repeat.interval) - 1)
}

/** Whether a date falls after the series' UNTIL, or past its COUNT of `seen` dates so far. */
function pastEnd(repeat: Repeat, at: Date, seen: number): boolean {
  return (repeat.until !== null && at > repeat.until) || (repeat.count !== null && seen >= repeat.count)
}
