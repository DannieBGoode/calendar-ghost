import type { ActivityShow } from "@/lib/activity-location"
import type { AuditEntry } from "@/lib/api"
import { plural } from "@/lib/rule-change"

export type HistoryFilters = { ruleId: string; show: ActivityShow; query: string }

/** What the history says when no entry matches, depending on which filters are set. */
export function emptyHistoryCopy({ ruleId, show, query }: HistoryFilters): { title: string; body: string } {
  // The default view hides no-change checks, so an empty page there is usually good news.
  if (!ruleId && show === "" && !query) {
    return {
      title: "Nothing has changed yet",
      body: "No rule has added, updated, removed, skipped, or blocked an event. Checks that found everything already up to date are hidden.",
    }
  }
  if (query) {
    return {
      title: `No events named “${query}”`,
      body: "Search matches event titles as each run recorded them. Check the spelling, show all decisions, or clear the search.",
    }
  }
  if (ruleId || show !== "all") {
    return {
      title: "No matching activity",
      body: "No recorded decisions match these filters. Show all decisions, or choose a different rule.",
    }
  }
  return {
    title: "No activity yet",
    body: "Synchronization decisions will appear here after an enabled rule completes its first run.",
  }
}

/** What screen readers hear while the history updates or after a search. */
export function historyStatus({
  updating,
  query,
  more,
  count,
}: {
  updating: boolean
  query: string
  more: boolean
  count: number
}): string {
  if (updating) return "Updating activity…"
  if (!query) return ""
  return `${more ? "More than " : ""}${plural(count, "entry", "entries")} found for “${query}”.`
}

/** The entries next to the selected one; an entry that is not listed has neither. */
export function entrySteps(
  entries: AuditEntry[],
  selected: AuditEntry | undefined,
): { newer: AuditEntry | undefined; older: AuditEntry | undefined } {
  const index = selected ? entries.findIndex((item) => item.id === selected.id) : -1
  if (index < 0) return { newer: undefined, older: undefined }
  return { newer: entries[index - 1], older: entries[index + 1] }
}
