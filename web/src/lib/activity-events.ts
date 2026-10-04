import { UNNAMED, type RuleNames } from "@/lib/activity-names"
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
  entry: Pick<AuditEntry, "source_event_id" | "event"> & Partial<Pick<AuditEntry, "reason">>,
  names: RuleNames | null,
): EventCell {
  if (!entry.source_event_id) {
    return {
      state: "unavailable",
      label: names ? `${names.source} → ${names.destination} rule` : "Removed rule",
      note: "Applies to the whole rule",
    }
  }
  const event = entry.event
  if (!event) {
    return { state: "unavailable", label: "Event name not recorded", note: "Recorded before event names were kept" }
  }
  const when = formatEventTime(event)
  const scope = eventScope(entry.reason, event.recurring)
  if (event.cancelled) {
    return { state: "event", title: event.title || "Cancelled event", when, recurring: event.recurring, scope, note: `Cancelled in ${(names ?? UNNAMED).source}` }
  }
  return {
    state: "event",
    title: event.title || "(No title)",
    when,
    recurring: event.recurring,
    scope,
    // An empty former title is a real one: the event was untitled before.
    ...(event.renamed_from !== null ? { note: `Renamed from “${event.renamed_from || "(No title)"}”` } : {}),
  }
}
