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

/** The kinds of event the preview can be narrowed to, in their order. */
export type PreviewKind = "allDay" | "birthday" | "recurring" | "declined" | "maybe" | "unanswered"
const PREVIEW_KINDS: readonly PreviewKind[] = ["allDay", "birthday", "recurring", "declined", "maybe", "unanswered"]

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

/**
 * One way to look at the preview, chosen one at a time: everything, what the destination will or
 * will not hold, or one kind of event.
 */
export type PreviewView = "all" | "sync" | "out" | PreviewKind
const OUTCOME_VIEWS = ["all", "sync", "out"] as const

export function matchesView(item: PreviewItem, view: PreviewView): boolean {
  switch (view) {
    case "all":
      return true
    case "sync":
      return item.projection !== null
    case "out":
      return item.projection === null
    default:
      return previewKinds(item).includes(view)
  }
}

/**
 * The views this preview offers, each with how many rows it shows: the three outcome views always,
 * and a kind only when some row has it. One view applies at a time, so the counts never move.
 */
export function previewViews(items: readonly PreviewItem[]): { view: PreviewView; count: number }[] {
  const kinds = tally(items, previewKinds)
  return [
    ...OUTCOME_VIEWS.map((view) => ({ view, count: items.filter((item) => matchesView(item, view)).length })),
    ...PREVIEW_KINDS.flatMap((view) => {
      const count = kinds.get(view) ?? 0
      return count ? [{ view, count }] : []
    }),
  ]
}

/** How many items fall under each key; an item may count under several. */
function tally<K extends string>(items: readonly PreviewItem[], keys: (item: PreviewItem) => readonly K[]): Map<K, number> {
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
/** One finished preview: what it found, and when, which every date on the page is read against. */
export type PreviewRun = { items: PreviewItem[]; completedAt: Date }
/** The two calendars' names, as the page shows them. */
export type PreviewNames = { source: string; destination: string }
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

/** The layout with only the items that pass, dropping days left empty; nothing is placed again. */
export function narrowLayout(layout: PreviewLayout, keep: (item: PreviewItem) => boolean): PreviewLayout {
  const days = (list: readonly PreviewDay[]) =>
    list.map((day) => ({ ...day, items: day.items.filter((placed) => keep(placed.item)) })).filter((day) => day.items.length > 0)
  return {
    undated: layout.undated.filter((placed) => keep(placed.item)),
    earlier: days(layout.earlier),
    upcoming: days(layout.upcoming),
  }
}

export function isTomorrow(date: Date, now: Date): boolean {
  return dayKey(date) === dayKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1))
}

export function isToday(date: Date, now: Date): boolean {
  return dayKey(date) === dayKey(now)
}
