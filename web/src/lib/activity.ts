import { CLOCK } from "@/i18n/format"
import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"
import { fieldInSentence, fieldLabel } from "@/lib/activity-fields"
import type { ActivityShow } from "@/lib/activity-location"
import { capitalized, named, unnamed, type RuleNames } from "@/lib/activity-names"
import { ACTION_FALLBACK, REASONS, RULE_ACTIONS, type CopyKeys, type ReasonCopy } from "@/lib/activity-reasons"
import { ApiError, type ActivityCategory, type AuditEntry, type RecordedEvent } from "@/lib/api"

export type { RuleNames } from "@/lib/activity-names"
export { changeListing, fieldChangeLines, fieldLabel } from "@/lib/activity-fields"
export { eventCell, type EventCell } from "@/lib/activity-events"
export { activityDayGroups, activityRows, groupRuns, type ActivityDayGroup } from "@/lib/activity-runs"
export { formatClockTime, formatDay, formatEventTime, formatRunTime } from "@/lib/activity-time"

// Decisions a source change can explain: an update, or a check that found nothing to write.
const SOURCE_CHANGE_REASONS = new Set(["source_changed", "occurrence_changed", "projection_current", "occurrence_current"])

function changedFields(entry: Partial<Pick<AuditEntry, "reason" | "changed_fields">>): string[] {
  if (!entry.reason || !SOURCE_CHANGE_REASONS.has(entry.reason)) return []
  return entry.changed_fields ?? []
}

/** "Title and description changed in Personal": the fields in a sentence, then the calendar. */
function changedTrigger(i18n: I18n, fields: string[], names: RuleNames | null): string {
  const labels = fields.map((field, index) => (index === 0 ? fieldLabel(i18n, field) : fieldInSentence(i18n, field)))
  const { source } = names ?? unnamed(i18n)
  return i18n.t("activity.happened.fieldsChanged", { fields: i18n.format.list(labels), source })
}

type DescribedEntry = Pick<AuditEntry, "reason" | "action" | "detail"> & Partial<Pick<AuditEntry, "changed_fields">>

/** The copy this version knows for an entry: its reason, or for rule management, its action. */
function knownCopy(entry: DescribedEntry): CopyKeys | undefined {
  return entry.reason ? REASONS[entry.reason] : RULE_ACTIONS[entry.action]
}

/** A check that found nothing to write after a source change says the change was already there. */
function unchangedAfterSourceChange(entry: DescribedEntry): CopyKeys | undefined {
  const current = entry.reason === "projection_current" || entry.reason === "occurrence_current" ? REASONS[entry.reason] : undefined
  if (!current || !changedFields(entry).length) return undefined
  return { effect: current.effect, explanation: "activity.reason.unchangedBySourceChange" }
}

/**
 * Copy for an entry this version cannot describe. It never explains itself with the server's
 * recorded detail; the detail stays a diagnostic.
 */
function unknownCopy(i18n: I18n, entry: DescribedEntry, names: RuleNames | null): ReasonCopy {
  const fallback = ACTION_FALLBACK[entry.action]
  return {
    effect: fallback ? named(i18n, fallback, names) : i18n.t("activity.reason.unknown.effect"),
    explanation: entry.detail ? i18n.t("activity.reason.unknown.explanation") : "",
  }
}

function namedCopy(i18n: I18n, copy: CopyKeys, names: RuleNames | null): ReasonCopy {
  return {
    effect: named(i18n, copy.effect, names),
    explanation: named(i18n, copy.explanation, names),
    ...(copy.trigger ? { trigger: named(i18n, copy.trigger, names) } : {}),
    ...(copy.next ? { next: named(i18n, copy.next, names) } : {}),
  }
}

/** The entry's copy with the rule's calendars named. */
export function describeEntry(i18n: I18n, entry: DescribedEntry, names: RuleNames | null = null): ReasonCopy {
  const copy = unchangedAfterSourceChange(entry) ?? knownCopy(entry)
  return copy ? namedCopy(i18n, copy, names) : unknownCopy(i18n, entry, names)
}

/** Events can be looked up only while the rule that names their calendars still exists. */
export function entryInspection(
  entry: Pick<AuditEntry, "reason" | "action" | "detail" | "source_event_id">,
  ruleExists: boolean,
): "event" | "details" | null {
  if (entry.source_event_id && ruleExists) return "event"
  return knownCopy(entry) || entry.detail ? "details" : null
}

export const REMOVED_RULE_LOOKUP: MessageKey = "activity.lookup.removedRule"

/** The service answers 410 when the entry's rule was removed, whatever the page believed. */
export function eventLookupFailure(i18n: I18n, error: unknown): string {
  if (error instanceof ApiError && error.status === 410) return i18n.t(REMOVED_RULE_LOOKUP)
  if (error instanceof ApiError && error.status === 503) return i18n.t("activity.lookup.notConfigured")
  return i18n.t("activity.lookup.failed")
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

function happenedTrigger(i18n: I18n, entry: HappenedEntry, copy: ReasonCopy, names: RuleNames | null): string | null {
  const event = movedEvent(entry)
  const fields = changedFields(entry)
  // A move alone says where from; any other change names its fields.
  const onlyMoved = fields.length === 0 || (fields.length === 1 && fields[0] === "time")
  if (event && onlyMoved) return movedTrigger(i18n, event, names)
  if (fields.length) return changedTrigger(i18n, fields, names)
  return copy.trigger ?? null
}

/** The What happened column: what was observed, then what Calendar Ghost did, with an icon for the outcome. */
export function whatHappened(i18n: I18n, entry: HappenedEntry, names: RuleNames | null): Happened {
  const copy = describeEntry(i18n, entry, names)
  const trigger = happenedTrigger(i18n, entry, copy, names)
  const effect = entry.repeated ? i18n.t("activity.happened.again", { effect: copy.effect }) : copy.effect
  const shownTrigger = trigger ? capitalized(i18n, trigger) : null
  const { icon, tone } = outcomeOf(entry)
  return {
    text: shownTrigger ? i18n.t("activity.happened.line", { trigger: shownTrigger, effect }) : capitalized(i18n, effect),
    trigger: shownTrigger,
    effect: shownTrigger ? effect : capitalized(i18n, effect),
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
function movedTrigger(i18n: I18n, event: RecordedEvent, names: RuleNames | null): string {
  const before = event.moved_from
  if (!before?.starts) return named(i18n, "activity.reason.sourceChanged.trigger", names)
  const { source } = names ?? unnamed(i18n)
  const day: Intl.DateTimeFormatOptions = { weekday: "short", day: "numeric", month: "short" }
  if (before.all_day) {
    return i18n.t("activity.happened.movedFrom", { when: i18n.format.date(`${before.starts}T00:00:00`, day), source })
  }
  const start = new Date(before.starts)
  const sameDay = event.starts !== null && !event.all_day && new Date(event.starts).toDateString() === start.toDateString()
  const when = sameDay ? i18n.format.time(start) : i18n.format.dateTime(start, { ...day, ...CLOCK })
  return i18n.t("activity.happened.movedFrom", { when, source })
}

export const SHOW_FILTERS: { value: ActivityShow; label: MessageKey }[] = [
  { value: "", label: "activity.filters.option.default" },
  { value: "all", label: "activity.filters.option.all" },
  { value: "changed", label: "activity.filters.option.changed" },
  { value: "skipped", label: "activity.filters.option.skipped" },
  { value: "blocked", label: "activity.filters.option.blocked" },
  { value: "unchanged", label: "activity.filters.option.unchanged" },
]

/** Every run re-checks events that already match, so those checks are hidden by default. */
export function showCategories(show: ActivityShow): ActivityCategory[] | undefined {
  if (show === "") return ["changed", "skipped", "blocked"]
  if (show === "all") return undefined
  return [show]
}
