import type { ActivityShow } from "@/lib/activity-location"
import { ApiError, type ActivityCategory, type ActivityEventSummary, type AuditEntry, type NoChangeRun } from "@/lib/api"

/** `happened` answers "what happened?" in a few words; `{destination}` names the destination calendar. */
type ReasonCopy = { happened: string; explanation: string }

// Keep in sync with SyncReason in src/calendar_sync/domain/model.py.
const REASONS: Record<string, ReasonCopy> = {
  source_created: {
    happened: "Added to {destination}",
    explanation: "The source event had no projection in the destination calendar yet.",
  },
  projection_missing: {
    happened: "Restored in {destination}",
    explanation: "The projection was deleted from the destination calendar, so it was restored from the source.",
  },
  source_changed: {
    happened: "Updated in {destination}",
    explanation: "The source event changed, so its projection was updated to match.",
  },
  destination_drift_repaired: {
    happened: "Edit in {destination} undone",
    explanation:
      "The projection was edited directly in the destination calendar. The source is authoritative, so the edit was replaced.",
  },
  source_cancelled: {
    happened: "Removed from {destination}",
    explanation: "The source event was cancelled or deleted.",
  },
  all_day_excluded_removed: {
    happened: "Removed from {destination}: all-day event",
    explanation: "This rule syncs timed events only, so the existing all-day projection was removed.",
  },
  projection_current: {
    happened: "Already up to date",
    explanation: "The projection already matches the source event.",
  },
  outside_source_calendar: {
    happened: "Skipped: from another calendar",
    explanation: "The event does not belong to this rule's source calendar.",
  },
  managed_projection_source: {
    happened: "Skipped: a managed projection",
    explanation:
      "Projections created by Calendar Sync are never synced again. This prevents events from looping between calendars.",
  },
  recurring_unsupported: {
    happened: "Skipped: recurring event",
    explanation:
      "Earlier versions did not sync recurring events. No projection was created or changed.",
  },
  cancelled_without_projection: {
    happened: "Skipped: already cancelled",
    explanation: "The event was cancelled before a projection existed, so there was nothing to remove.",
  },
  all_day_excluded: {
    happened: "Skipped: all-day event",
    explanation: "This rule syncs timed events only. Edit the rule to include all-day events.",
  },
  mapping_inconsistent: {
    happened: "Blocked: the event mapping does not match",
    explanation:
      "The stored mapping between this event and its projection points somewhere unexpected. Nothing was written. Reconcile the rule to investigate.",
  },
  destination_identity_inconsistent: {
    happened: "Blocked: the projection in {destination} changed",
    explanation:
      "The destination event no longer matches the mapped projection. Nothing was written. Reconcile the rule to investigate.",
  },
  destination_ownership_inconsistent: {
    happened: "Blocked: not owned by this rule",
    explanation:
      "The destination event is missing this rule's ownership marker, so Calendar Sync will not change or delete it.",
  },
  source_unverifiable: {
    happened: "Blocked: the source could not be read",
    explanation:
      "The projection was edited, but the source event could not be read to repair it. The projection was left unchanged rather than risk deleting it.",
  },
  occurrence_changed: {
    happened: "One occurrence updated in {destination}",
    explanation: "One occurrence of a recurring event was moved or edited in the source, so its projection was updated.",
  },
  occurrence_cancelled: {
    happened: "One occurrence removed from {destination}",
    explanation: "One occurrence of a recurring event was cancelled in the source. The rest of the series is unchanged.",
  },
  occurrence_removed_from_series: {
    happened: "Occurrence removed from {destination}",
    explanation: "The source series no longer includes this occurrence, so its projection was removed.",
  },
  occurrence_drift_repaired: {
    happened: "Occurrence edit in {destination} undone",
    explanation:
      "One occurrence was edited or deleted directly in the destination calendar. The source is authoritative, so it was restored.",
  },
  occurrence_current: {
    happened: "Already up to date",
    explanation: "The occurrence already matches the source.",
  },
  occurrence_already_cancelled: {
    happened: "Already up to date",
    explanation: "The occurrence is cancelled in both calendars.",
  },
  occurrence_retired: {
    happened: "Cleaned up: occurrence no longer exists",
    explanation: "The occurrence no longer exists in either calendar, so its record was removed. Nothing was written.",
  },
  series_not_synchronized: {
    happened: "Skipped: series not synced",
    explanation: "The occurrence belongs to a recurring event this rule does not sync.",
  },
  destination_occurrence_missing: {
    happened: "Blocked: occurrence missing in {destination}",
    explanation:
      "The destination series has no matching occurrence, even after repairing the series. Nothing was written. Reconcile the rule to investigate.",
  },
}

const ACTION_FALLBACK: Record<string, string> = {
  create: "Added to {destination}",
  update: "Updated in {destination}",
  delete: "Removed from {destination}",
  ignore: "Skipped",
  conflict: "Blocked",
}

// Rule management entries carry no SyncReason; keep in sync with application/rules.py and removal.py.
const RULE_ACTIONS: Record<string, ReasonCopy> = {
  policy_changed: {
    happened: "Privacy setting changed",
    explanation:
      "This is a Material Rule Change. The rule needs a new preview, and existing projections are rewritten on the next run after it is enabled.",
  },
  remove_projection: {
    happened: "Removed from {destination} with the rule",
    explanation: "The administrator chose to delete this rule's projections when removing it.",
  },
  detach_projection: {
    happened: "Kept in {destination}, no longer synced",
    explanation: "The event stays in the destination calendar and is no longer updated or deleted.",
  },
  removal_conflict: {
    happened: "Blocked: left in {destination} during Rule Removal",
    explanation:
      "The event's ownership could not be verified, so it was not deleted. It stays in the destination calendar and is no longer managed.",
  },
  rule_removed: {
    happened: "Rule removed",
    explanation: "The rule and its Event Mappings were removed. Its activity history is kept.",
  },
}

export function describeEntry(entry: Pick<AuditEntry, "reason" | "action" | "detail">): ReasonCopy {
  const known = entry.reason ? REASONS[entry.reason] : RULE_ACTIONS[entry.action]
  if (known) return known
  return {
    happened: ACTION_FALLBACK[entry.action] ?? entry.action.replaceAll("_", " "),
    explanation: entry.detail,
  }
}

/** Events can be looked up only while the rule that names their calendars still exists. */
export function entryInspection(
  entry: Pick<AuditEntry, "reason" | "action" | "detail" | "source_event_id">,
  ruleExists: boolean,
): "event" | "details" | null {
  if (entry.source_event_id && ruleExists) return "event"
  return describeEntry(entry).explanation ? "details" : null
}

export const REMOVED_RULE_LOOKUP =
  "This rule was removed, so its events can no longer be looked up."

/** The service answers 410 when the entry's rule was removed, whatever the page believed. */
export function eventLookupFailure(error: unknown): string {
  if (error instanceof ApiError && error.status === 410) return REMOVED_RULE_LOOKUP
  if (error instanceof ApiError && error.status === 503) {
    return "Google is not configured, so the event cannot be looked up."
  }
  return "Google could not return this event right now. The account may need reauthorization in Settings."
}

export type HappenedIcon =
  | "added"
  | "updated"
  | "repaired"
  | "removed"
  | "kept"
  | "current"
  | "skipped"
  | "blocked"
  | "rule"
export type Happened = { text: string; icon: HappenedIcon; tone: "change" | "quiet" | "blocked" }

const REPAIRS = new Set(["projection_missing", "destination_drift_repaired", "occurrence_drift_repaired"])

/** The What happened column: a short phrase in calendar terms, with an icon that carries its meaning. */
export function whatHappened(
  entry: Pick<AuditEntry, "reason" | "action" | "detail" | "category">,
  destination: string | null,
): Happened {
  const text = describeEntry(entry).happened.replaceAll("{destination}", destination ?? "the destination")
  if (entry.category === "blocked") return { text, icon: "blocked", tone: "blocked" }
  if (entry.category === "skipped") return { text, icon: "skipped", tone: "quiet" }
  if (entry.category === "unchanged") return { text, icon: "current", tone: "quiet" }
  if (entry.action === "policy_changed" || entry.action === "rule_removed") return { text, icon: "rule", tone: "change" }
  if (entry.reason && REPAIRS.has(entry.reason)) return { text, icon: "repaired", tone: "change" }
  if (entry.action === "create") return { text, icon: "added", tone: "change" }
  if (entry.action === "delete" || entry.action === "remove_projection") return { text, icon: "removed", tone: "change" }
  if (entry.action === "detach_projection") return { text, icon: "kept", tone: "change" }
  return { text, icon: "updated", tone: "change" }
}

export const SHOW_FILTERS: { value: ActivityShow; label: string }[] = [
  { value: "", label: "Changes, skips, and blocks" },
  { value: "all", label: "All decisions" },
  { value: "changed", label: "Changes" },
  { value: "skipped", label: "Skipped" },
  { value: "blocked", label: "Blocked" },
  { value: "unchanged", label: "No change needed" },
]

/** Every run re-checks events that already match, so those checks are hidden by default. */
export function showCategories(show: ActivityShow): ActivityCategory[] | undefined {
  if (show === "") return ["changed", "skipped", "blocked"]
  if (show === "all") return undefined
  return [show]
}

export type ActivityRun = {
  key: string
  ruleId: string
  occurredAt: string
  entries: AuditEntry[]
}

/**
 * Groups newest-first entries into synchronization runs, ordered by each run's newest entry.
 * Concurrent runs of different rules interleave their entries, so groups are keyed, not adjacent.
 */
export function groupRuns(entries: AuditEntry[]): ActivityRun[] {
  const runs = new Map<string, ActivityRun>()
  for (const entry of entries) {
    // Entries recorded before run identifiers existed are grouped by rule and minute.
    const key = entry.run_id ?? `${entry.rule_id}@${entry.occurred_at.slice(0, 16)}`
    const run = runs.get(key)
    if (run) {
      run.entries.push(entry)
    } else {
      runs.set(key, { key, ruleId: entry.rule_id, occurredAt: entry.occurred_at, entries: [entry] })
    }
  }
  return [...runs.values()]
}

export type ActivityRow =
  | { kind: "entry"; entry: AuditEntry }
  | { kind: "folded"; count: number; expanded: boolean; more: boolean }

/** A run with its rows, or several consecutive runs that only found events already up to date. */
export type ActivityGroup =
  | { kind: "run"; key: string; day: string | null; run: ActivityRun; rows: ActivityRow[] }
  | { kind: "quiet"; key: string; day: string | null; runs: number; checks: number; newest: string; oldest: string }

export type ExpandedChecks = { entries: AuditEntry[]; complete: boolean }

/**
 * Lays out the table newest first and names the day above its first group. With `noChangeRuns`,
 * each run ends in one row counting its hidden no-change checks, and consecutive runs that made
 * nothing but those checks collapse into a single quiet row. An expanded run lists the checks
 * loaded for it in place and keeps its row so they can be hidden again or loaded further.
 */
export function activityRows(
  runs: ActivityRun[],
  {
    noChangeRuns,
    expanded = new Map(),
    now = new Date(),
  }: {
    noChangeRuns?: readonly NoChangeRun[]
    expanded?: ReadonlyMap<string, ExpandedChecks>
    now?: Date
  },
): ActivityGroup[] {
  const counts = new Map((noChangeRuns ?? []).map((item) => [item.run_id, item]))
  const shown = new Set(runs.map((run) => run.key))
  const ordered: ({ at: number; run: ActivityRun } | { at: number; quiet: NoChangeRun })[] = [
    ...runs.map((run) => ({
      at: Math.max(...run.entries.map((item) => item.id), counts.get(run.key)?.newest_id ?? 0),
      run,
    })),
    ...(noChangeRuns ?? []).filter((item) => !shown.has(item.run_id)).map((item) => ({ at: item.newest_id, quiet: item })),
  ].sort((a, b) => b.at - a.at)

  const groups: ActivityGroup[] = []
  let previousDay: string | null = null
  const dayOf = (value: string) => {
    const label = formatDay(value, now)
    const day = label === previousDay ? null : label
    previousDay = label
    return day
  }
  for (const item of ordered) {
    if ("quiet" in item) {
      const last = groups.at(-1)
      if (last?.kind === "quiet" && formatDay(item.quiet.occurred_at, now) === previousDay) {
        last.runs += 1
        last.checks += item.quiet.count
        last.oldest = item.quiet.occurred_at
        continue
      }
      const at = item.quiet.occurred_at
      groups.push({ kind: "quiet", key: `quiet-${item.quiet.run_id}`, day: dayOf(at), runs: 1, checks: item.quiet.count, newest: at, oldest: at })
      continue
    }
    const { run } = item
    const count = counts.get(run.key)?.count ?? 0
    const checks = expanded.get(run.key)
    const entries = checks ? [...run.entries, ...checks.entries].sort((a, b) => b.id - a.id) : run.entries
    const rows: ActivityRow[] = entries.map((entry) => ({ kind: "entry", entry }))
    if (count > 0) rows.push({ kind: "folded", count, expanded: checks !== undefined, more: checks !== undefined && !checks.complete })
    groups.push({ kind: "run", key: run.key, day: dayOf(run.occurredAt), run, rows })
  }
  return groups
}

export type EventCell =
  | { state: "loading" }
  | { state: "event"; title: string; when: string; recurring: boolean; note?: string }
  | { state: "unavailable"; label: string; note?: string }

type SummaryLookup =
  | { status: "pending" }
  | { status: "error" }
  | { status: "success"; data: ActivityEventSummary | null }

/** Calendar names of the entry's rule, or null once the rule is removed. */
export type RuleNames = { source: string; destination: string }

const REMOVED_RULE_CELL: EventCell = {
  state: "unavailable",
  label: "Event from a removed rule",
  note: "Its events can no longer be looked up",
}

/** What the Event column shows, given the live lookup of the entry's source event. */
export function eventCell(
  entry: Pick<AuditEntry, "source_event_id">,
  names: RuleNames | null,
  lookup: SummaryLookup,
): EventCell {
  if (!entry.source_event_id) {
    return {
      state: "unavailable",
      label: names ? `${names.source} → ${names.destination} rule` : "Removed rule",
      note: "Applies to the whole rule",
    }
  }
  if (!names) return REMOVED_RULE_CELL
  if (lookup.status === "pending") return { state: "loading" }
  if (lookup.status === "success" && lookup.data?.lookup === "rule_removed") return REMOVED_RULE_CELL
  const source = lookup.status === "success" ? lookup.data?.source : null
  if (!source) return { state: "unavailable", label: "Event name unavailable", note: "Google did not respond" }
  if (!source.found) {
    return { state: "unavailable", label: `Event deleted from ${names.source}`, note: "Its name is no longer available" }
  }
  const when = formatEventTime(source)
  if (source.cancelled) {
    return { state: "event", title: source.title || "Cancelled event", when, recurring: source.recurring, note: "Cancelled" }
  }
  return { state: "event", title: source.title || "(No title)", when, recurring: source.recurring }
}

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
