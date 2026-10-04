import type { I18n } from "@/i18n/translator"
import { unnamed, type RuleNames } from "@/lib/activity-names"
import { formatEventTime } from "@/lib/activity-time"
import type { AuditEntry } from "@/lib/api"

/** Which part of a recurring event an entry was about; null for single events or when unknown. */
export type EventScope = "series" | "occurrence" | null

export type EventCell =
  | { state: "event"; title: string; when: string; recurring: boolean; scope: EventScope; note?: string }
  | { state: "unavailable"; label: string; note?: string }

// Decisions about one occurrence of a series; other decisions about a recurring event are about the
// whole series. Reasons recorded for both, such as all-day removals and identity blocks, leave the
// scope unknown.
const OCCURRENCE_REASONS = new Set([
  "occurrence_changed",
  "occurrence_cancelled",
  "occurrence_removed_from_series",
  "occurrence_drift_repaired",
  "occurrence_current",
  "occurrence_already_cancelled",
  "occurrence_retired",
  "series_not_synchronized",
  "destination_occurrence_missing",
])

const EITHER_SCOPE_REASONS = new Set([
  "all_day_excluded_removed",
  "declined_removed",
  "tentative_excluded_removed",
  "awaiting_response_removed",
  "policy_applied",
  "mapping_inconsistent",
  "destination_identity_inconsistent",
  "destination_ownership_inconsistent",
  "source_unverifiable",
  "projection_unmapped",
])

function eventScope(reason: string | null | undefined, recurring: boolean): EventScope {
  if (!recurring || !reason || EITHER_SCOPE_REASONS.has(reason)) return null
  return OCCURRENCE_REASONS.has(reason) ? "occurrence" : "series"
}

/** What the Event column shows: the source event as the entry's run recorded it. */
export function eventCell(
  i18n: I18n,
  entry: Pick<AuditEntry, "source_event_id" | "event"> & Partial<Pick<AuditEntry, "reason">>,
  names: RuleNames | null,
): EventCell {
  if (!entry.source_event_id) {
    return {
      state: "unavailable",
      label: names ? i18n.t("activity.cell.ruleLabel", { source: names.source, destination: names.destination }) : i18n.t("activity.removedRule"),
      note: i18n.t("activity.cell.wholeRule"),
    }
  }
  const event = entry.event
  if (!event) {
    return { state: "unavailable", label: i18n.t("activity.cell.nameNotRecorded"), note: i18n.t("activity.cell.recordedBefore") }
  }
  const when = formatEventTime(i18n, event)
  const scope = eventScope(entry.reason, event.recurring)
  if (event.cancelled) {
    return {
      state: "event",
      title: event.title || i18n.t("activity.cell.cancelledEvent"),
      when,
      recurring: event.recurring,
      scope,
      note: i18n.t("activity.cell.cancelledIn", { source: (names ?? unnamed(i18n)).source }),
    }
  }
  return {
    state: "event",
    title: event.title || i18n.t("activity.cell.noTitle"),
    when,
    recurring: event.recurring,
    scope,
    // An empty former title is a real one: the event was untitled before.
    ...(event.renamed_from !== null
      ? { note: i18n.t("activity.cell.renamedFrom", { title: event.renamed_from || i18n.t("activity.cell.noTitle") }) }
      : {}),
  }
}
