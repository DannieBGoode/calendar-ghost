import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"
import { describeRepeat, readRepeat } from "@/lib/recurrence"
import {
  PREVIEW_OUTCOMES,
  itemStart,
  localDay,
  previewOutcome,
  type PlacedItem,
  type PreviewItem,
  type PreviewOutcome,
} from "@/lib/rule-preview"

/** Why an event stays out of the destination, or leaves it, in a few calendar words. */
const REASON_WORDS: Record<string, MessageKey> = {
  all_day_excluded: "rulePreview.reason.allDay",
  all_day_excluded_removed: "rulePreview.reason.allDay",
  birthday: "rulePreview.reason.birthday",
  birthday_removed: "rulePreview.reason.birthday",
  declined: "rulePreview.reason.declined",
  declined_removed: "rulePreview.reason.declined",
  tentative_excluded: "rulePreview.reason.maybe",
  tentative_excluded_removed: "rulePreview.reason.maybe",
  awaiting_response: "rulePreview.reason.unanswered",
  awaiting_response_removed: "rulePreview.reason.unanswered",
  managed_projection_source: "rulePreview.reason.managed",
  series_without_occurrences: "rulePreview.reason.noDatesLeft",
  series_without_occurrences_removed: "rulePreview.reason.noDatesLeft",
  cancelled_without_projection: "rulePreview.reason.cancelled",
  source_cancelled: "rulePreview.reason.cancelled",
  occurrence_cancelled: "rulePreview.reason.cancelled",
  occurrence_already_cancelled: "rulePreview.reason.cancelled",
  before_sync_window: "rulePreview.reason.beforeWindow",
}

const OUTCOME_WORDS: Record<PreviewOutcome, MessageKey> = {
  add: "rulePreview.outcome.add",
  update: "rulePreview.outcome.update",
  remove: "rulePreview.outcome.remove",
  current: "rulePreview.outcome.current",
  blocked: "rulePreview.outcome.blocked",
  skipped: "rulePreview.outcome.skipped",
}

const COUNT_WORDS: Record<PreviewOutcome, MessageKey> = {
  add: "rulePreview.counts.add",
  update: "rulePreview.counts.update",
  remove: "rulePreview.counts.remove",
  current: "rulePreview.counts.current",
  blocked: "rulePreview.counts.blocked",
  skipped: "rulePreview.counts.skipped",
}

const RESPONSE_WORDS: Partial<Record<PreviewItem["response"], MessageKey>> = {
  declined: "rulePreview.row.declined",
  tentative: "rulePreview.row.maybe",
  needs_action: "rulePreview.row.unanswered",
}

/** "Add", or "Not synced: birthday" when the outcome has a reason worth naming. */
export function outcomeText(i18n: I18n, item: PreviewItem): string {
  const outcome = i18n.t(OUTCOME_WORDS[previewOutcome(item)])
  const reason = REASON_WORDS[item.reason]
  return reason ? i18n.t("rulePreview.outcome.withReason", { outcome, reason: i18n.t(reason) }) : outcome
}

/** The outcomes that occur, in their order, each with its count and words. */
export function outcomeParts(i18n: I18n, counts: ReadonlyMap<PreviewOutcome, number>) {
  return PREVIEW_OUTCOMES.flatMap((outcome) => {
    const count = counts.get(outcome) ?? 0
    return count ? [{ outcome, text: i18n.t(COUNT_WORDS[outcome], { count: i18n.format.number(count) }) }] : []
  })
}

const SHORT_DAY: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" }

/** One day, or the days it spans from where it is placed, as a series' next date is. */
function allDayText(i18n: I18n, item: PreviewItem, at: Date): string {
  if (!item.starts_on || !item.ends_before) return i18n.t("rulePreview.row.allDay")
  const span = Math.round((localDay(item.ends_before).getTime() - localDay(item.starts_on).getTime()) / 86_400_000)
  if (span <= 1) return i18n.t("rulePreview.row.allDay")
  const first = at
  const last = new Date(at.getFullYear(), at.getMonth(), at.getDate() + span - 1)
  const range = i18n.t("rulePreview.row.timeRange", { start: i18n.format.date(first, SHORT_DAY), end: i18n.format.date(last, SHORT_DAY) })
  return i18n.t("rulePreview.row.allDayDays", { range })
}

function durationMs(item: PreviewItem): number | null {
  if (!item.starts_at || !item.ends_at) return null
  return new Date(item.ends_at).getTime() - new Date(item.starts_at).getTime()
}

/** "09:00–10:00", "22:00–01:00 Tue" when it ends on another day, or "All day". */
export function whenText(i18n: I18n, placed: PlacedItem): string {
  if (!placed.at) return i18n.t("rulePreview.row.noDate")
  if (placed.allDay) return allDayText(i18n, placed.item, placed.at)
  const start = i18n.format.time(placed.at)
  const duration = durationMs(placed.item)
  if (duration === null || duration <= 0) return start
  const ends = new Date(placed.at.getTime() + duration)
  const end = i18n.format.time(ends)
  if (ends.toDateString() === placed.at.toDateString()) return i18n.t("rulePreview.row.timeRange", { start, end })
  return i18n.t("rulePreview.row.endsNextDay", { start, end, day: i18n.format.date(ends, { weekday: "short" }) })
}

function occurrenceNote(i18n: I18n, item: PreviewItem): string {
  if (item.cancelled) return i18n.t("rulePreview.row.cancelledOnce")
  const regular = item.original_start
  const start = itemStart(item)
  if (!regular || !start) return i18n.t("rulePreview.row.changedOnce")
  const allDay = !regular.includes("T")
  const was = allDay ? localDay(regular) : new Date(regular)
  if (was.getTime() === start.at.getTime()) return i18n.t("rulePreview.row.changedOnce")
  const sameDay = was.toDateString() === start.at.toDateString()
  const time = allDay
    ? i18n.format.date(was, SHORT_DAY)
    : sameDay
      ? i18n.format.time(was)
      : i18n.format.dateTime(was, { ...SHORT_DAY, hour: "numeric", minute: "2-digit" })
  return i18n.t("rulePreview.row.moved", { time })
}

/** What else the source row says: its recurrence, a change to one date, or your response. */
export function sourceNotes(i18n: I18n, placed: PlacedItem): string[] {
  const { item, since } = placed
  const notes: string[] = []
  if (item.kind === "series") {
    const first = itemStart(item)?.at ?? placed.at ?? new Date()
    notes.push(describeRepeat(i18n, readRepeat(item.recurrence), first, item.time_zone))
    if (since) notes.push(i18n.t("rulePreview.row.since", { date: i18n.format.date(since, SHORT_DAY) }))
  }
  if (item.kind === "occurrence") notes.push(occurrenceNote(i18n, item))
  const response = RESPONSE_WORDS[item.response]
  if (response) notes.push(i18n.t(response))
  // An excluded birthday already says so in its outcome.
  if (item.birthday && item.projection) notes.push(i18n.t("rulePreview.row.birthday"))
  return notes
}

/** What else the destination row says: its recurrence, and the details it copies. */
export function destinationNotes(i18n: I18n, placed: PlacedItem): string[] {
  const projection = placed.item.projection
  if (!projection) return []
  const first = itemStart(placed.item)?.at ?? placed.at ?? new Date()
  return [
    ...(projection.recurrence ? [describeRepeat(i18n, readRepeat(projection.recurrence), first, placed.item.time_zone)] : []),
    ...(projection.carries_details ? [i18n.t("rulePreview.privacy.withDetails")] : []),
  ]
}
