import type { ActivityShow } from "@/lib/activity-location"
import {
  ApiError,
  type ActivityCategory,
  type AuditEntry,
  type FieldChange,
  type RecordedEvent,
  type SourceChange,
} from "@/lib/api"

/**
 * What Calendar Ghost observed (`trigger`) and what it did about it (`effect`), never who caused
 * it. `{source}` and `{destination}` name the rule's calendars. A block says what to do next.
 */
type ReasonCopy = { trigger?: string; effect: string; explanation: string; next?: string }

/** Blocks nobody can clear by hand: the daily check decides the event again and escalates. */
const RECHECKED =
  "Nothing to do now. Calendar Ghost decides this event again at the daily check, and opens an incident if it is still blocked then."

// Keep in sync with SyncReason in src/calendar_sync/domain/model.py.
const REASONS: Record<string, ReasonCopy> = {
  source_created: {
    trigger: "New in {source}",
    effect: "added to {destination}",
    explanation: "The event was new to Calendar Ghost, so it was added to {destination}.",
  },
  projection_missing: {
    trigger: "Missing from {destination}",
    effect: "put back",
    explanation:
      "The event Calendar Ghost wrote to {destination} was no longer there, so it was written again from {source}.",
  },
  source_changed: {
    trigger: "Changed in {source}",
    effect: "updated in {destination}",
    explanation: "The event changed in {source}, so {destination} was updated to match.",
  },
  destination_drift_repaired: {
    trigger: "Edited in {destination}",
    effect: "changed back to match {source}",
    explanation:
      "The event in {destination} no longer matched {source}. {source} decides what the event looks like, so the edit was replaced.",
  },
  source_cancelled: {
    trigger: "Cancelled in {source}",
    effect: "removed from {destination}",
    explanation: "The event was cancelled or deleted in {source}, so it was removed from {destination}.",
  },
  all_day_excluded_removed: {
    trigger: "All-day, which this rule leaves out",
    effect: "removed from {destination}",
    explanation: "This rule syncs timed events only, so the all-day event it had written was removed.",
  },
  declined_removed: {
    trigger: "Declined",
    effect: "removed from {destination}",
    explanation: "You declined this event in {source}, so the event Calendar Ghost had written was removed. Declined events are never synced.",
  },
  tentative_excluded_removed: {
    trigger: "Answered Maybe, which this rule leaves out",
    effect: "removed from {destination}",
    explanation: "This rule doesn't sync events you answered Maybe to, so the event it had written was removed.",
  },
  awaiting_response_removed: {
    trigger: "Not answered yet",
    effect: "removed from {destination}",
    explanation:
      "This rule waits for you to answer an invitation before syncing it, so the event it had written was removed. It is added again once you accept, or answer Maybe if this rule syncs those.",
  },
  policy_applied: {
    trigger: "Rule settings changed",
    effect: "rewritten in {destination}",
    explanation: "The rule's settings changed, so the event it had written was rewritten to match them.",
  },
  projection_current: {
    effect: "already up to date",
    explanation: "The event in {destination} already matches {source}.",
  },
  outside_source_calendar: {
    trigger: "From another calendar",
    effect: "skipped",
    explanation: "The event does not belong to {source}.",
  },
  managed_projection_source: {
    trigger: "Written by Calendar Ghost",
    effect: "skipped",
    explanation:
      "Events Calendar Ghost wrote are never synced again. This prevents events from looping between calendars.",
  },
  recurring_unsupported: {
    trigger: "Recurring event",
    effect: "skipped",
    explanation: "Earlier versions did not sync recurring events. Nothing was written.",
  },
  cancelled_without_projection: {
    trigger: "Cancelled in {source}",
    effect: "nothing to remove",
    explanation: "The event was cancelled before it was ever added to {destination}.",
  },
  all_day_excluded: {
    trigger: "All-day event",
    effect: "skipped",
    explanation: "This rule syncs timed events only. Edit the rule to include all-day events.",
  },
  declined: {
    trigger: "Declined",
    effect: "skipped",
    explanation: "You declined this event in {source}. Declined events are never synced.",
  },
  tentative_excluded: {
    trigger: "Answered Maybe",
    effect: "skipped",
    explanation: "This rule doesn't sync events you answered Maybe to. Edit the rule to sync them.",
  },
  awaiting_response: {
    trigger: "Not answered yet",
    effect: "skipped",
    explanation:
      "This rule waits for you to answer an invitation before syncing it. It is synced once you accept, or answer Maybe if this rule syncs those.",
  },
  before_sync_window: {
    trigger: "Ended before the sync window",
    effect: "skipped",
    explanation:
      "The event changed, but it ended before this rule's sync window and was never synced, so it was not added.",
  },
  mapping_inconsistent: {
    trigger: "Calendar Ghost's link to this event doesn't match",
    effect: "blocked, {destination} left unchanged",
    explanation:
      "Calendar Ghost keeps a record of which event in {destination} belongs to which event in {source}. For this event the record points somewhere unexpected, so nothing was written rather than risk changing the wrong event.",
    next: RECHECKED,
  },
  destination_identity_inconsistent: {
    trigger: "A different event is linked in {destination}",
    effect: "blocked, {destination} left unchanged",
    explanation:
      "The event in {destination} is no longer the one Calendar Ghost wrote for this event, so nothing was written rather than risk changing the wrong event.",
    next: RECHECKED,
  },
  destination_ownership_inconsistent: {
    trigger: "Not marked as written by this rule in {destination}",
    effect: "blocked, left alone",
    explanation:
      "The event in {destination} does not carry this rule's marker, so Calendar Ghost will not change or delete it.",
    next: RECHECKED,
  },
  source_unverifiable: {
    trigger: "Couldn't be read in {source}",
    effect: "blocked, {destination} left unchanged",
    explanation:
      "Its source event in {source} could not be read, so the event in {destination} was left as it is rather than risk deleting it.",
    next: "If this repeats, check in Settings that the Google account for {source} is still connected.",
  },
  occurrence_changed: {
    trigger: "Changed in {source}",
    effect: "updated in {destination}",
    explanation:
      "This occurrence was moved or edited in {source}, so it was updated in {destination}. The rest of the series is unchanged.",
  },
  occurrence_cancelled: {
    trigger: "Cancelled in {source}",
    effect: "removed from {destination}",
    explanation:
      "This occurrence was cancelled in {source}, so it was removed from {destination}. The rest of the series is unchanged.",
  },
  occurrence_removed_from_series: {
    trigger: "No longer in the series in {source}",
    effect: "removed from {destination}",
    explanation: "The series in {source} no longer includes this occurrence, so it was removed from {destination}.",
  },
  occurrence_drift_repaired: {
    trigger: "Edited or deleted in {destination}",
    effect: "put back to match {source}",
    explanation:
      "This occurrence in {destination} no longer matched {source}. {source} decides what the event looks like, so it was restored.",
  },
  occurrence_current: {
    effect: "already up to date",
    explanation: "This occurrence in {destination} already matches {source}.",
  },
  occurrence_already_cancelled: {
    effect: "already up to date",
    explanation: "This occurrence is cancelled in both calendars.",
  },
  occurrence_retired: {
    trigger: "Gone from both calendars",
    effect: "cleaned up",
    explanation: "The occurrence no longer exists in either calendar, so its record was removed. Nothing was written.",
  },
  series_not_synchronized: {
    trigger: "Its series isn't synced",
    effect: "skipped",
    explanation: "This occurrence belongs to a recurring event this rule does not sync.",
  },
  destination_occurrence_missing: {
    trigger: "Not found in the series in {destination}",
    effect: "blocked, {destination} left unchanged",
    explanation:
      "The series in {destination} has no occurrence at this time, even after Calendar Ghost checked the series itself. Nothing was written, so this occurrence may be missing or out of date in {destination}. The rest of the series is unaffected.",
    next: RECHECKED,
  },
  series_without_occurrences: {
    trigger: "Every occurrence cancelled in {source}",
    effect: "skipped",
    explanation:
      "Every occurrence of this recurring event is cancelled in {source}, or is an all-day occurrence this rule leaves out, so there is nothing to show in {destination}. It is synced again if an occurrence comes back.",
  },
  series_without_occurrences_removed: {
    trigger: "No occurrence left in {source}",
    effect: "removed from {destination}",
    explanation:
      "Every occurrence of this recurring event is cancelled in {source}, or is an all-day occurrence this rule leaves out, so the series left from an interrupted run was removed.",
  },
  projection_unmapped: {
    trigger: "Marked as written by this rule in {destination}, but not linked to an event in {source}",
    effect: "blocked, left in {destination}",
    explanation:
      "The event in {destination} carries this rule's marker, but Calendar Ghost has no record of writing it, so it will not change or delete it. Reconcile now reports it again while it is there.",
    next: "If you don't want it in {destination}, delete it there yourself.",
  },
}

const ACTION_FALLBACK: Record<string, string> = {
  create: "added to {destination}",
  update: "updated in {destination}",
  delete: "removed from {destination}",
  ignore: "skipped",
  conflict: "blocked",
}

// Rule management entries carry no SyncReason; keep in sync with application/rules.py and removal.py.
const RULE_ACTIONS: Record<string, ReasonCopy> = {
  policy_changed: {
    effect: "rule settings changed",
    explanation:
      "The rule needs a new preview, and the events it wrote are rewritten on the next run after it is enabled.",
  },
  remove_projection: {
    trigger: "Rule removed",
    effect: "removed from {destination}",
    explanation: "The administrator chose to delete the events this rule wrote when removing it.",
  },
  detach_projection: {
    trigger: "Rule removed",
    effect: "kept in {destination}, no longer synced",
    explanation: "The event stays in {destination} and is no longer updated or deleted.",
  },
  removal_conflict: {
    trigger: "Not verifiably written by this rule",
    effect: "left in {destination} during Rule Removal",
    explanation:
      "The event's ownership could not be verified, so it was not deleted. It stays in {destination} and is no longer managed.",
  },
  rule_removed: {
    effect: "rule removed",
    explanation: "The rule and its records of which events it wrote were removed. Its activity history is kept.",
  },
}

/** Calendar names of the entry's rule, or null once the rule is removed. */
export type RuleNames = { source: string; destination: string }

const UNNAMED: RuleNames = { source: "the source calendar", destination: "the destination calendar" }

function named(text: string, names: RuleNames | null): string {
  const { source, destination } = names ?? UNNAMED
  return text.replaceAll("{source}", source).replaceAll("{destination}", destination)
}

function capitalized(text: string): string {
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}`
}

// Keep in sync with SourceField in src/calendar_sync/domain/changes.py.
const FIELD_LABELS: Record<string, string> = {
  title: "Title",
  time: "Time",
  description: "Description",
  location: "Location",
  guests: "Guests",
  recurrence: "Repeat pattern",
  conferencing: "Video call links",
  response: "Your response",
}

// Keep in sync with InvitationResponse in src/calendar_sync/domain/model.py.
const RESPONSE_LABELS: Record<string, string> = {
  accepted: "Yes",
  tentative: "Maybe",
  declined: "No",
  needs_action: "Not answered",
}

/** How Activity names a tracked source field. */
export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? capitalized(field.replaceAll("_", " "))
}

/** One changed field as the entry panel lists it: text before and after, or what a list gained and lost. */
export type FieldChangeLines = {
  field: string
  label: string
  before: string | null
  after: string | null
  added: string[]
  removed: string[]
  /** The field changed, but its values expired or cannot be read with the current master key. */
  unavailable: boolean
}

export function fieldChangeLines(change: FieldChange): FieldChangeLines {
  const text = (value: string | null) =>
    value === null ? null : change.field === "response" ? (RESPONSE_LABELS[value] ?? value) : value || "(empty)"
  const before = change.before_time ? formatEventTime(change.before_time) : text(change.before)
  const after = change.after_time ? formatEventTime(change.after_time) : text(change.after)
  return {
    field: change.field,
    label: fieldLabel(change.field),
    before,
    after,
    added: change.added,
    removed: change.removed,
    unavailable: false,
  }
}

/** Every field the change touched, in order, with values where they are still kept. */
export function changeListing(change: SourceChange): FieldChangeLines[] {
  const known = new Map(change.changes.map((item) => [item.field, fieldChangeLines(item)]))
  return change.fields.map(
    (field) =>
      known.get(field) ?? { field, label: fieldLabel(field), before: null, after: null, added: [], removed: [], unavailable: true },
  )
}

export const CHANGE_VALUES_UNAVAILABLE =
  "Some values are no longer available. They are kept for 90 days, and cannot be read after the installation master key changes."

// Decisions a source change can explain: an update, or a check that found nothing to write.
const SOURCE_CHANGE_REASONS = new Set(["source_changed", "occurrence_changed", "projection_current", "occurrence_current"])
const UNCHANGED_BY_SOURCE_CHANGE =
  "The event changed in {source}, and {destination} already matched it, so nothing was written for this entry."

function changedFields(entry: Partial<Pick<AuditEntry, "reason" | "changed_fields">>): string[] {
  if (!entry.reason || !SOURCE_CHANGE_REASONS.has(entry.reason)) return []
  return entry.changed_fields ?? []
}

/** "Title and description changed in Personal": the fields in a sentence, then the calendar. */
function changedTrigger(fields: string[], names: RuleNames | null): string {
  const labels = fields.map((field, index) => (index === 0 ? fieldLabel(field) : fieldLabel(field).toLowerCase()))
  const list = new Intl.ListFormat("en", { style: "long", type: "conjunction" }).format(labels)
  return named(`${list} changed in {source}`, names)
}

/** The entry's copy with the rule's calendars named. */
export function describeEntry(
  entry: Pick<AuditEntry, "reason" | "action" | "detail"> & Partial<Pick<AuditEntry, "changed_fields">>,
  names: RuleNames | null = null,
): ReasonCopy {
  if (changedFields(entry).length && (entry.reason === "projection_current" || entry.reason === "occurrence_current")) {
    return { effect: named(REASONS[entry.reason].effect, names), explanation: named(UNCHANGED_BY_SOURCE_CHANGE, names) }
  }
  const known = entry.reason ? REASONS[entry.reason] : RULE_ACTIONS[entry.action]
  const copy = known ?? {
    effect: ACTION_FALLBACK[entry.action] ?? entry.action.replaceAll("_", " "),
    explanation: entry.detail,
  }
  return {
    effect: named(copy.effect, names),
    explanation: named(copy.explanation, names),
    ...(copy.trigger ? { trigger: named(copy.trigger, names) } : {}),
    ...(copy.next ? { next: named(copy.next, names) } : {}),
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
export type Happened = {
  /** The whole line, such as "Cancelled in Work → removed from Family". */
  text: string
  trigger: string | null
  effect: string
  icon: HappenedIcon
  tone: "change" | "quiet" | "blocked"
}

const REPAIRS = new Set(["projection_missing", "destination_drift_repaired", "occurrence_drift_repaired"])
const MOVES = new Set(["source_changed", "occurrence_changed"])

/** The What happened column: what was observed, then what Calendar Ghost did, with an icon for the outcome. */
export function whatHappened(
  entry: Pick<AuditEntry, "reason" | "action" | "detail" | "category"> &
    Partial<Pick<AuditEntry, "event" | "repeated" | "changed_fields">>,
  names: RuleNames | null,
): Happened {
  const copy = describeEntry(entry, names)
  const moved = entry.reason && MOVES.has(entry.reason) && entry.event?.moved_from
  const fields = changedFields(entry)
  // A move alone says where from; any other change names its fields.
  const onlyMoved = fields.length === 0 || (fields.length === 1 && fields[0] === "time")
  const trigger =
    moved && entry.event && onlyMoved
      ? movedTrigger(entry.event, names)
      : fields.length
        ? changedTrigger(fields, names)
        : (copy.trigger ?? null)
  const effect = entry.repeated ? `${copy.effect} again` : copy.effect
  const text = trigger ? `${capitalized(trigger)} → ${effect}` : capitalized(effect)
  const line = { text, trigger: trigger ? capitalized(trigger) : null, effect: trigger ? effect : capitalized(effect) }
  if (entry.category === "blocked") return { ...line, icon: "blocked", tone: "blocked" }
  if (entry.category === "skipped") return { ...line, icon: "skipped", tone: "quiet" }
  if (entry.category === "unchanged") return { ...line, icon: "current", tone: "quiet" }
  if (entry.action === "policy_changed" || entry.action === "rule_removed") return { ...line, icon: "rule", tone: "change" }
  if (entry.reason && REPAIRS.has(entry.reason)) return { ...line, icon: "repaired", tone: "change" }
  if (entry.action === "create") return { ...line, icon: "added", tone: "change" }
  if (entry.action === "delete" || entry.action === "remove_projection") return { ...line, icon: "removed", tone: "change" }
  if (entry.action === "detach_projection") return { ...line, icon: "kept", tone: "change" }
  return { ...line, icon: "updated", tone: "change" }
}

/** "Moved from 10:00 AM in Work": the earlier start, with its date only when the day changed. */
function movedTrigger(event: RecordedEvent, names: RuleNames | null): string {
  const before = event.moved_from
  if (!before?.starts) return named("Changed in {source}", names)
  const { source } = names ?? UNNAMED
  if (before.all_day) {
    const day = new Date(`${before.starts}T00:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })
    return `Moved from ${day} in ${source}`
  }
  const start = new Date(before.starts)
  const sameDay = event.starts !== null && !event.all_day && new Date(event.starts).toDateString() === start.toDateString()
  const when = sameDay
    ? start.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
    : start.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })
  return `Moved from ${when} in ${source}`
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
