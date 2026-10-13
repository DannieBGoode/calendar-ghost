import type { ChangeMark } from "@/lib/activity"
import type { RulePreview } from "@/lib/api"
import { nextOccurrence, readRepeat } from "@/lib/recurrence"

export type PreviewItem = RulePreview["items"][number]

/** What starting the rule does to the destination for one event. */
export type PreviewOutcome = "add" | "update" | "remove" | "current" | "blocked" | "skipped"
export const PREVIEW_OUTCOMES: readonly PreviewOutcome[] = ["add", "update", "remove", "current", "blocked", "skipped"]

/** Activity's sign for each outcome, so a preview and the history it becomes read alike. */
export const OUTCOME_MARKS: Record<PreviewOutcome, ChangeMark> = {
  add: "added",
  update: "changed",
  remove: "removed",
  current: "current",
  blocked: "blocked",
  skipped: "skipped",
}

export function previewOutcome(item: PreviewItem): PreviewOutcome {
  switch (item.planned_action) {
    case "create":
      return "add"
    case "update":
      return "update"
    case "delete":
      return "remove"
    case "conflict":
      return "blocked"
    case "ignore":
      return item.projection ? "current" : "skipped"
  }
}

/** The kinds of event the Kind filter offers, in its order. */
export type PreviewKind = "allDay" | "birthday" | "recurring" | "declined" | "maybe" | "unanswered"
export const PREVIEW_KINDS: readonly PreviewKind[] = ["allDay", "birthday", "recurring", "declined", "maybe", "unanswered"]

const RESPONSE_KINDS: Partial<Record<PreviewItem["response"], PreviewKind>> = {
  declined: "declined",
  tentative: "maybe",
  needs_action: "unanswered",
}

export function previewKinds(item: PreviewItem): PreviewKind[] {
  const response = RESPONSE_KINDS[item.response]
  return [
    ...(item.starts_on !== null ? (["allDay"] as const) : []),
    ...(item.birthday ? (["birthday"] as const) : []),
    ...(item.kind !== "single" ? (["recurring"] as const) : []),
    ...(response ? [response] : []),
  ]
}

/** All, what the destination will hold, or what it will not. */
export type PreviewShow = "all" | "sync" | "out"
export type PreviewFilters = { show: PreviewShow; kinds: readonly PreviewKind[] }
export const NO_FILTERS: PreviewFilters = { show: "all", kinds: [] }

/** A row matches its Show choice and, when kinds are chosen, any one of them. */
export function matchesFilters(item: PreviewItem, filters: PreviewFilters): boolean {
  if (filters.show === "sync" && !item.projection) return false
  if (filters.show === "out" && item.projection) return false
  if (!filters.kinds.length) return true
  const kinds = new Set(previewKinds(item))
  return filters.kinds.some((kind) => kinds.has(kind))
}

export function isFiltered(filters: PreviewFilters): boolean {
  return filters.show !== "all" || filters.kinds.length > 0
}

/** How many items fall under each key; an item may count under several. */
export function tally<K extends string>(items: readonly PreviewItem[], keys: (item: PreviewItem) => readonly K[]): Map<K, number> {
  const counts = new Map<K, number>()
  for (const item of items) for (const key of keys(item)) counts.set(key, (counts.get(key) ?? 0) + 1)
  return counts
}

export const outcomeCounts = (items: readonly PreviewItem[]) => tally(items, (item) => [previewOutcome(item)])

/**
 * One row in its place on the calendar; `at` is null for a deleted event the provider no longer
 * dates. `since` is a series' first date when it began earlier.
 */
export type PlacedItem = { item: PreviewItem; at: Date | null; allDay: boolean; since: Date | null }
type DatedItem = PlacedItem & { at: Date }
export type PreviewDay = { key: string; date: Date; items: PlacedItem[] }
/** Deleted events without a date, days before today (collapsed under Earlier), and today onward. */
export type PreviewLayout = { undated: PlacedItem[]; earlier: PreviewDay[]; upcoming: PreviewDay[] }

/** A local calendar day from an ISO date such as "2026-10-13", without a time zone shift. */
export function localDay(isoDate: string): Date {
  const [year = 1970, month = 1, day = 1] = isoDate.split("-").map(Number)
  return new Date(year, month - 1, day)
}

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

function dayKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`
}

/** When the event begins, or for a cancelled occurrence when it would have. */
export function itemStart(item: PreviewItem): { at: Date; allDay: boolean } | null {
  if (item.starts_at) return { at: new Date(item.starts_at), allDay: false }
  if (item.starts_on) return { at: localDay(item.starts_on), allDay: true }
  if (!item.original_start) return null
  const allDay = !item.original_start.includes("T")
  return { at: allDay ? localDay(item.original_start) : new Date(item.original_start), allDay }
}

/**
 * Where a row sits: a series at its next date from today, so a weekly event that began weeks ago
 * is not hidden among earlier events; a series that has ended, or any other event, at its start.
 */
function place(item: PreviewItem, today: Date): PlacedItem {
  const start = itemStart(item)
  if (!start) return { item, at: null, allDay: false, since: null }
  if (item.kind !== "series" || start.at >= today) return { item, ...start, since: null }
  const next = nextOccurrence(readRepeat(item.recurrence), start.at, today, item.time_zone)
  if (next === "ended") return { item, ...start, since: null }
  // A rule this interface cannot step through still runs, so it shows under today.
  return { item, at: next ?? today, allDay: start.allDay, since: start.at }
}

function byStart(a: DatedItem, b: DatedItem): number {
  if (a.allDay !== b.allDay) return a.allDay ? -1 : 1
  return a.at.getTime() - b.at.getTime() || a.item.title.localeCompare(b.item.title)
}

function groupByDay(placed: readonly DatedItem[]): PreviewDay[] {
  const days = new Map<string, PreviewDay & { items: DatedItem[] }>()
  for (const each of placed) {
    const date = startOfDay(each.at)
    const key = dayKey(date)
    const day = days.get(key) ?? { key, date, items: [] }
    day.items.push(each)
    days.set(key, day)
  }
  return [...days.values()]
    .sort((a, b) => a.date.getTime() - b.date.getTime())
    .map((day) => ({ ...day, items: day.items.sort(byStart) }))
}

/** The rows in calendar order, split at the start of `now`'s day. */
export function layOut(items: readonly PreviewItem[], now: Date): PreviewLayout {
  const today = startOfDay(now)
  const placed = items.map((item) => place(item, today))
  const days = groupByDay(placed.filter((each): each is DatedItem => each.at !== null))
  return {
    undated: placed.filter((each) => each.at === null),
    earlier: days.filter((day) => day.date < today),
    upcoming: days.filter((day) => day.date >= today),
  }
}

export function isTomorrow(date: Date, now: Date): boolean {
  return dayKey(date) === dayKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1))
}

export function isToday(date: Date, now: Date): boolean {
  return dayKey(date) === dayKey(now)
}
