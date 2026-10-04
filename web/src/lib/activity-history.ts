import type { I18n } from "@/i18n/translator"
import type { ActivityShow } from "@/lib/activity-location"
import type { AuditEntry } from "@/lib/api"

export type HistoryFilters = { ruleId: string; show: ActivityShow; query: string }

/** What the history says when no entry matches, depending on which filters are set. */
export function emptyHistoryCopy({ t }: I18n, { ruleId, show, query }: HistoryFilters): { title: string; body: string } {
  // The default view hides no-change checks, so an empty page there is usually good news.
  if (!ruleId && show === "" && !query) {
    return { title: t("activity.empty.quiet.title"), body: t("activity.empty.quiet.body") }
  }
  if (query) {
    return { title: t("activity.empty.search.title", { query }), body: t("activity.empty.search.body") }
  }
  if (ruleId || show !== "all") {
    return { title: t("activity.empty.filtered.title"), body: t("activity.empty.filtered.body") }
  }
  return { title: t("activity.empty.none.title"), body: t("activity.empty.none.body") }
}

/** What screen readers hear while the history updates or after a search. */
export function historyStatus(
  { t }: I18n,
  {
    updating,
    query,
    more,
    count,
  }: {
    updating: boolean
    query: string
    more: boolean
    count: number
  },
): string {
  if (updating) return t("activity.history.updating")
  if (!query) return ""
  return t(more ? "activity.history.foundMore" : "activity.history.found", { count, query })
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
