import { capitalized } from "@/lib/activity-names"
import { formatEventTime } from "@/lib/activity-time"
import type { FieldChange, SourceChange } from "@/lib/api"

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
