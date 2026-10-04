import { fieldLabel } from "@/lib/activity-fields"
import type { ActivityShow } from "@/lib/activity-location"
import { capitalized, named, UNNAMED, type RuleNames } from "@/lib/activity-names"
import { ACTION_FALLBACK, REASONS, RULE_ACTIONS, type ReasonCopy } from "@/lib/activity-reasons"
import { ApiError, type ActivityCategory, type AuditEntry, type RecordedEvent } from "@/lib/api"

export type { RuleNames } from "@/lib/activity-names"
export {
  CHANGE_VALUES_UNAVAILABLE,
  changeListing,
  fieldChangeLines,
  fieldLabel,
  type FieldChangeLines,
} from "@/lib/activity-fields"
export { eventCell, type EventCell, type EventScope } from "@/lib/activity-events"
export {
  activityDayGroups,
  activityRows,
  groupRuns,
  type ActivityDayGroup,
  type ActivityGroup,
  type ActivityRun,
} from "@/lib/activity-runs"
export { formatClockTime, formatDay, formatEventTime, formatRunTime } from "@/lib/activity-time"

// Decisions a source change can explain: an update, or a check that found nothing to write.
const SOURCE_CHANGE_REASONS = new Set(["source_changed", "occurrence_changed", "projection_current", "occurrence_current"])
const UNCHANGED_BY_SOURCE_CHANGE =
  "The event changed in {source}, and {destination} already matched it, so nothing was written for this entry."

function changedFields(entry: Partial<Pick<AuditEntry, "reason" | "changed_fields">>): string[] {
  if (!entry.reason || !SOURCE_CHANGE_REASONS.has(entry.reason)) return []
  return entry.changed_fields ?? []
}

const FIELD_LIST = new Intl.ListFormat("en", { style: "long", type: "conjunction" })

/** "Title and description changed in Personal": the fields in a sentence, then the calendar. */
function changedTrigger(fields: string[], names: RuleNames | null): string {
  const labels = fields.map((field, index) => (index === 0 ? fieldLabel(field) : fieldLabel(field).toLowerCase()))
  const list = FIELD_LIST.format(labels)
  return named(`${list} changed in {source}`, names)
}

type DescribedEntry = Pick<AuditEntry, "reason" | "action" | "detail"> & Partial<Pick<AuditEntry, "changed_fields">>

/** A check that found nothing to write after a source change says the change was already there. */
function unchangedAfterSourceChange(entry: DescribedEntry): ReasonCopy | undefined {
  const current = entry.reason === "projection_current" || entry.reason === "occurrence_current" ? REASONS[entry.reason] : undefined
  if (!current || !changedFields(entry).length) return undefined
  return { effect: current.effect, explanation: UNCHANGED_BY_SOURCE_CHANGE }
}

/** The copy for the entry's reason, or for its rule action, or worded from the action itself. */
function entryCopy(entry: DescribedEntry): ReasonCopy {
  const known = entry.reason ? REASONS[entry.reason] : RULE_ACTIONS[entry.action]
  return (
    known ?? {
      effect: ACTION_FALLBACK[entry.action] ?? entry.action.replaceAll("_", " "),
      explanation: entry.detail,
    }
  )
}

function namedCopy(copy: ReasonCopy, names: RuleNames | null): ReasonCopy {
  return {
    effect: named(copy.effect, names),
    explanation: named(copy.explanation, names),
    ...(copy.trigger ? { trigger: named(copy.trigger, names) } : {}),
    ...(copy.next ? { next: named(copy.next, names) } : {}),
  }
}

/** The entry's copy with the rule's calendars named. */
export function describeEntry(entry: DescribedEntry, names: RuleNames | null = null): ReasonCopy {
  return namedCopy(unchangedAfterSourceChange(entry) ?? entryCopy(entry), names)
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
  /** The sign for what it did to the destination calendar, the same wherever it is shown. */
  mark: ChangeMark
  tone: "change" | "quiet" | "blocked"
}

type HappenedEntry = Pick<AuditEntry, "reason" | "action" | "detail" | "category"> &
  Partial<Pick<AuditEntry, "event" | "repeated" | "changed_fields">>

type Outcome = Pick<Happened, "icon" | "tone">

const REPAIRS = new Set(["projection_missing", "destination_drift_repaired", "occurrence_drift_repaired"])
const MOVES = new Set(["source_changed", "occurrence_changed"])

// Decisions that wrote nothing are shown by their category, whatever the action.
const CATEGORY_OUTCOMES: Partial<Record<ActivityCategory, Outcome>> = {
  blocked: { icon: "blocked", tone: "blocked" },
  skipped: { icon: "skipped", tone: "quiet" },
  unchanged: { icon: "current", tone: "quiet" },
}

const RULE_CHANGES = new Set(["policy_changed", "rule_removed"])

const ACTION_ICONS = new Map<string, HappenedIcon>([
  ["create", "added"],
  ["delete", "removed"],
  ["remove_projection", "removed"],
  ["detach_projection", "kept"],
])

/** The icon and tone for what the entry did, most specific first. */
function outcomeOf(entry: HappenedEntry): Outcome {
  const byCategory = CATEGORY_OUTCOMES[entry.category]
  if (byCategory) return byCategory
  if (RULE_CHANGES.has(entry.action)) return { icon: "rule", tone: "change" }
  if (entry.reason && REPAIRS.has(entry.reason)) return { icon: "repaired", tone: "change" }
  return { icon: ACTION_ICONS.get(entry.action) ?? "updated", tone: "change" }
}

/** The recorded event when the entry moved it, so the trigger can say where from. */
function movedEvent(entry: HappenedEntry): RecordedEvent | null {
  if (!entry.reason || !MOVES.has(entry.reason) || !entry.event?.moved_from) return null
  return entry.event
}

function happenedTrigger(entry: HappenedEntry, copy: ReasonCopy, names: RuleNames | null): string | null {
  const event = movedEvent(entry)
  const fields = changedFields(entry)
  // A move alone says where from; any other change names its fields.
  const onlyMoved = fields.length === 0 || (fields.length === 1 && fields[0] === "time")
  if (event && onlyMoved) return movedTrigger(event, names)
  if (fields.length) return changedTrigger(fields, names)
  return copy.trigger ?? null
}

/** The What happened column: what was observed, then what Calendar Ghost did, with an icon for the outcome. */
export function whatHappened(entry: HappenedEntry, names: RuleNames | null): Happened {
  const copy = describeEntry(entry, names)
  const trigger = happenedTrigger(entry, copy, names)
  const effect = entry.repeated ? `${copy.effect} again` : copy.effect
  const { icon, tone } = outcomeOf(entry)
  return {
    text: trigger ? `${capitalized(trigger)} → ${effect}` : capitalized(effect),
    trigger: trigger ? capitalized(trigger) : null,
    effect: trigger ? effect : capitalized(effect),
    icon,
    mark: changeMark(icon, entry.action),
    tone,
  }
}

/** What an entry did to the destination calendar, read like a diff: + added, − removed, ~ changed. */
export type ChangeMark = "added" | "removed" | "changed" | "blocked" | "kept" | "current" | "skipped"

/**
 * One sign per outcome, so Activity and the Overview never show two icons for the same thing.
 * Putting back a missing event adds it again, so it is an addition; a rule's settings change in place.
 */
export function changeMark(icon: HappenedIcon, action: string): ChangeMark {
  if (icon === "added" || (icon === "repaired" && action === "create")) return "added"
  if (action === "rule_removed") return "removed"
  if (icon === "removed" || icon === "blocked" || icon === "kept" || icon === "current" || icon === "skipped") return icon
  return "changed"
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
