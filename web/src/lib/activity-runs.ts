import { formatDay } from "@/lib/activity-time"
import type { AuditEntry } from "@/lib/api"

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

/** A run and the day heading above it, if it is the first run of its day. */
export type ActivityGroup = { key: string; day: string | null; run: ActivityRun }

/** Lays out the runs newest first and names the day above its first run. */
export function activityRows(runs: ActivityRun[], { now = new Date() }: { now?: Date } = {}): ActivityGroup[] {
  let previousDay: string | null = null
  return runs.map((run) => {
    const label = formatDay(run.occurredAt, now)
    const day = label === previousDay ? null : label
    previousDay = label
    return { key: run.key, day, run }
  })
}

export type ActivityDayGroup = { key: string; day: string; runs: ActivityRun[] }

/** Keeps each date heading with every run it labels for native table rowgroup semantics. */
export function activityDayGroups(groups: ActivityGroup[]): ActivityDayGroup[] {
  return groups.reduce<ActivityDayGroup[]>((days, group) => {
    const current = days.at(-1)
    if (group.day !== null || !current) {
      days.push({ key: group.key, day: group.day ?? "", runs: [group.run] })
    } else {
      current.runs.push(group.run)
    }
    return days
  }, [])
}
