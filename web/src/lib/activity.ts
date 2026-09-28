import type { ActivityCategory, AuditEntry } from "@/lib/api"

type ReasonCopy = { summary: string; explanation: string }

// Keep in sync with SyncReason in src/calendar_sync/domain/model.py.
const REASONS: Record<string, ReasonCopy> = {
  source_created: {
    summary: "Created a copy",
    explanation: "The source event had no copy in the destination calendar yet.",
  },
  projection_missing: {
    summary: "Recreated a missing copy",
    explanation: "The copy was deleted from the destination calendar, so it was restored from the source.",
  },
  source_changed: {
    summary: "Updated the copy",
    explanation: "The source event changed, so the copy was updated to match.",
  },
  destination_drift_repaired: {
    summary: "Restored an edited copy",
    explanation:
      "The copy was edited directly in the destination calendar. The source is authoritative, so the edit was replaced.",
  },
  source_cancelled: {
    summary: "Removed the copy",
    explanation: "The source event was cancelled or deleted.",
  },
  all_day_excluded_removed: {
    summary: "Removed an all-day copy",
    explanation: "This rule syncs timed events only, so the existing all-day copy was removed.",
  },
  projection_current: {
    summary: "No change needed",
    explanation: "The copy already matches the source event.",
  },
  outside_source_calendar: {
    summary: "Skipped an event from another calendar",
    explanation: "The event does not belong to this rule's source calendar.",
  },
  managed_projection_source: {
    summary: "Skipped a copy made by a sync rule",
    explanation:
      "Copies created by Calendar Sync are never synced again. This prevents events from looping between calendars.",
  },
  recurring_unsupported: {
    summary: "Skipped a recurring event",
    explanation:
      "Recurring events and changes to single occurrences are not synced yet. No copy was created or changed.",
  },
  cancelled_without_projection: {
    summary: "Skipped a cancelled event",
    explanation: "The event was cancelled before a copy existed, so there was nothing to remove.",
  },
  all_day_excluded: {
    summary: "Skipped an all-day event",
    explanation: "This rule syncs timed events only. Edit the rule to include all-day events.",
  },
  mapping_inconsistent: {
    summary: "Blocked: the event's link does not match this rule",
    explanation:
      "The stored link between this event and its copy points somewhere unexpected. Nothing was written. Reconcile the rule to investigate.",
  },
  destination_identity_inconsistent: {
    summary: "Blocked: the copy's identity changed",
    explanation:
      "The destination event no longer matches the recorded copy. Nothing was written. Reconcile the rule to investigate.",
  },
  destination_ownership_inconsistent: {
    summary: "Blocked: the copy is not owned by this rule",
    explanation:
      "The destination event is missing this rule's ownership marker, so Calendar Sync will not change or delete it.",
  },
  source_unverifiable: {
    summary: "Blocked: the source event could not be confirmed",
    explanation:
      "The copy was edited, but the source event could not be read to repair it. The copy was left unchanged rather than risk deleting it.",
  },
}

const ACTION_FALLBACK: Record<string, string> = {
  create: "Created a copy",
  update: "Updated the copy",
  delete: "Removed the copy",
  ignore: "Skipped an event",
  conflict: "Blocked a change",
}

export function describeEntry(entry: Pick<AuditEntry, "reason" | "action" | "detail">): ReasonCopy {
  const known = entry.reason ? REASONS[entry.reason] : undefined
  if (known) return known
  return {
    summary: ACTION_FALLBACK[entry.action] ?? entry.action.replaceAll("_", " "),
    explanation: entry.detail,
  }
}

export function outcomeLabel(entry: Pick<AuditEntry, "action" | "category">): string {
  if (entry.category === "blocked") return "Blocked"
  if (entry.category === "skipped") return "Skipped"
  if (entry.category === "unchanged") return "No change"
  if (entry.action === "create") return "Created"
  if (entry.action === "delete") return "Removed"
  return "Updated"
}

export const CATEGORY_FILTERS: { value: ActivityCategory | ""; label: string }[] = [
  { value: "", label: "All decisions" },
  { value: "changed", label: "Changes" },
  { value: "skipped", label: "Skipped" },
  { value: "blocked", label: "Blocked" },
  { value: "unchanged", label: "No change needed" },
]

export type ActivityRun = {
  key: string
  ruleId: string
  occurredAt: string
  entries: AuditEntry[]
}

/** Groups newest-first entries into synchronization runs, preserving order. */
export function groupRuns(entries: AuditEntry[]): ActivityRun[] {
  const runs: ActivityRun[] = []
  for (const entry of entries) {
    // Entries recorded before run identifiers existed are grouped by rule and minute.
    const key = entry.run_id ?? `${entry.rule_id}@${entry.occurred_at.slice(0, 16)}`
    const current = runs.at(-1)
    if (current?.key === key) {
      current.entries.push(entry)
    } else {
      runs.push({ key, ruleId: entry.rule_id, occurredAt: entry.occurred_at, entries: [entry] })
    }
  }
  return runs
}

export function summarizeRun(entries: AuditEntry[]): string {
  const counts = new Map<string, number>()
  for (const entry of entries) {
    const label = outcomeLabel(entry).toLowerCase()
    counts.set(label, (counts.get(label) ?? 0) + 1)
  }
  return ["created", "updated", "removed", "blocked", "skipped", "no change"]
    .filter((label) => counts.has(label))
    .map((label) => `${counts.get(label)} ${label}`)
    .join(" · ")
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

export function formatEventTime(event: {
  all_day: boolean
  starts: string | null
  ends: string | null
}): string {
  if (!event.starts || !event.ends) return ""
  const dayFormat: Intl.DateTimeFormatOptions = { weekday: "short", day: "numeric", month: "short", year: "numeric" }
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
