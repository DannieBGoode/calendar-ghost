import type { MessageKey, MessageParams } from "./types"

type DateInput = Date | string
export type Formatters = {
  number: (value: number) => string
  bytes: (bytes: number) => string
  list: (items: readonly string[]) => string
  /** A list in the format language's short unit-list style, such as counts ("2 created, 1 deleted") or addresses. */
  unitList: (items: readonly string[]) => string
  date: (value: DateInput, options: Intl.DateTimeFormatOptions) => string
  time: (value: DateInput) => string
  dateTime: (value: DateInput, options?: Intl.DateTimeFormatOptions) => string
  /** A UTC calendar day such as "3 Sep 2026", for storage ranges. */
  shortDay: (value: string, withYear?: boolean) => string
  /** A short distance from now, such as "5 minutes ago" or "yesterday". */
  relative: (iso: string, now?: number) => string
}

type Translate = (key: MessageKey, params?: MessageParams) => string

const BYTE_UNITS: readonly [MessageKey, ...MessageKey[]] = ["common.bytes.kb", "common.bytes.mb", "common.bytes.gb", "common.bytes.tb"]
const RELATIVE_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
]
// CLDR spells September "Sept" for some English locales; the storage summary keeps three letters.
const ENGLISH_SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
/** Hour and minute, in the format language's clock. */
export const CLOCK: Intl.DateTimeFormatOptions = { hour: "numeric", minute: "2-digit" }

const toDate = (value: DateInput) => (value instanceof Date ? value : new Date(value))

/**
 * Dates, times, numbers, and sizes follow `locale`, the browser's region. Lists join the words of
 * a sentence, so they follow `listLocale`, the UI language, and keep its punctuation: an English UI
 * keeps the serial comma ("a, b, and c") in an en-GB browser too.
 */
export function createFormatters(locale: string, t: Translate, listLocale: string = locale): Formatters {
  const english = locale.split("-")[0] === "en"
  const decimal = new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
  const whole = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 })
  const relativeFormat = new Intl.RelativeTimeFormat(locale, { numeric: "auto" })
  const numberFormat = new Intl.NumberFormat(locale)
  const listFormat = new Intl.ListFormat(listLocale, { style: "long", type: "conjunction" })
  const unitListFormat = new Intl.ListFormat(listLocale, { style: "short", type: "unit" })

  function bytes(value: number): string {
    if (value < 1024) return t("common.bytes.b", { value: whole.format(value) })
    let scaled = value / 1024
    let unit = 0
    while (scaled >= 1024 && unit < BYTE_UNITS.length - 1) {
      scaled /= 1024
      unit += 1
    }
    return t(BYTE_UNITS[unit] ?? BYTE_UNITS[0], { value: decimal.format(scaled) })
  }

  function shortDay(value: string, withYear = true): string {
    const date = new Date(value)
    const parts = new Intl.DateTimeFormat(locale, {
      day: "numeric",
      month: "short",
      ...(withYear ? { year: "numeric" } : {}),
      timeZone: "UTC",
    }).formatToParts(date)
    return parts
      .map((part) => (english && part.type === "month" ? ENGLISH_SHORT_MONTHS[date.getUTCMonth()] : part.value))
      .join("")
  }

  function relative(iso: string, now: number = Date.now()): string {
    const seconds = Math.round((new Date(iso).getTime() - now) / 1000)
    if (Number.isNaN(seconds)) return t("common.time.unknown")
    if (Math.abs(seconds) < 60) return t("common.time.justNow")
    for (const [unit, size] of RELATIVE_UNITS) {
      if (Math.abs(seconds) >= size || unit === "minute") {
        const value = Math.trunc(seconds / size)
        if (unit === "day" && Math.abs(value) > 6) {
          return t("common.time.onDay", { day: new Date(iso).toLocaleDateString(locale, { month: "short", day: "numeric" }) })
        }
        return relativeFormat.format(value, unit)
      }
    }
    return t("common.time.justNow")
  }

  return {
    number: (value) => numberFormat.format(value),
    bytes,
    list: (items) => listFormat.format(items),
    unitList: (items) => unitListFormat.format(items),
    date: (value, options) => toDate(value).toLocaleDateString(locale, options),
    time: (value) => toDate(value).toLocaleTimeString(locale, CLOCK),
    dateTime: (value, options) => toDate(value).toLocaleString(locale, options),
    shortDay,
    relative,
  }
}
