import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"
import { capitalized } from "@/lib/activity-names"
import { formatEventTime } from "@/lib/activity-time"
import type { FieldChange, SourceChange } from "@/lib/api"

// Keep in sync with SourceField in src/calendar_sync/domain/changes.py.
const FIELD_LABELS: Record<string, MessageKey> = {
  title: "activity.field.title",
  time: "activity.field.time",
  description: "activity.field.description",
  location: "activity.field.location",
  guests: "activity.field.guests",
  recurrence: "activity.field.recurrence",
  conferencing: "activity.field.conferencing",
  response: "activity.field.response",
}

// The same fields after the first in a sentence; the catalog decides their case, so German keeps capital nouns.
const FIELD_IN_SENTENCE: Record<string, MessageKey> = {
  title: "activity.fieldInSentence.title",
  time: "activity.fieldInSentence.time",
  description: "activity.fieldInSentence.description",
  location: "activity.fieldInSentence.location",
  guests: "activity.fieldInSentence.guests",
  recurrence: "activity.fieldInSentence.recurrence",
  conferencing: "activity.fieldInSentence.conferencing",
  response: "activity.fieldInSentence.response",
}

// Keep in sync with InvitationResponse in src/calendar_sync/domain/model.py.
const RESPONSE_LABELS: Record<string, MessageKey> = {
  accepted: "activity.response.accepted",
  tentative: "activity.response.tentative",
  declined: "activity.response.declined",
  needs_action: "activity.response.needsAction",
}

/** How Activity names a tracked source field; a field this version does not know keeps its code. */
export function fieldLabel(i18n: I18n, field: string): string {
  const key = FIELD_LABELS[field]
  return key ? i18n.t(key) : capitalized(i18n, field.replaceAll("_", " "))
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

export function fieldChangeLines(i18n: I18n, change: FieldChange): FieldChangeLines {
  const response = (value: string) => {
    const key = RESPONSE_LABELS[value]
    return key ? i18n.t(key) : value
  }
  const text = (value: string | null) =>
    value === null ? null : change.field === "response" ? response(value) : value || i18n.t("activity.changes.empty")
  const before = change.before_time ? formatEventTime(i18n, change.before_time) : text(change.before)
  const after = change.after_time ? formatEventTime(i18n, change.after_time) : text(change.after)
  return {
    field: change.field,
    label: fieldLabel(i18n, change.field),
    before,
    after,
    added: change.added,
    removed: change.removed,
    unavailable: false,
  }
}

/** Every field the change touched, in order, with values where they are still kept. */
export function changeListing(i18n: I18n, change: SourceChange): FieldChangeLines[] {
  const known = new Map(change.changes.map((item) => [item.field, fieldChangeLines(i18n, item)]))
  return change.fields.map(
    (field) =>
      known.get(field) ?? {
        field,
        label: fieldLabel(i18n, field),
        before: null,
        after: null,
        added: [],
        removed: [],
        unavailable: true,
      },
  )
}

/** A field named after the first in a sentence; a field this version does not know keeps its code. */
export function fieldInSentence(i18n: I18n, field: string): string {
  const key = FIELD_IN_SENTENCE[field]
  return key ? i18n.t(key) : field.replaceAll("_", " ")
}
