import type { Messages } from "../i18n"

type EventKind = "work" | "personal" | "family"
type EventKey = keyof Messages["demo"]["events"]

/** One event in Sam's demo week. `day` 0 is Monday; times are hours, so 9.5 is 9:30. */
export interface DemoEvent {
  key: EventKey
  kind: EventKind
  day: number
  start: number
  end: number
}

export const DAY_START = 9
export const DAY_END = 17
export const DAYS = 5

export const SAM_WEEK: readonly DemoEvent[] = [
  { key: "standup", kind: "work", day: 0, start: 10, end: 11 },
  { key: "clientCall", kind: "work", day: 1, start: 14.5, end: 15.5 },
  { key: "oneOnOne", kind: "work", day: 2, start: 14, end: 15 },
  { key: "designReview", kind: "work", day: 3, start: 9.5, end: 10.5 },
  { key: "retro", kind: "work", day: 4, start: 11, end: 12 },
  { key: "dentist", kind: "personal", day: 0, start: 15, end: 16.5 },
  { key: "gym", kind: "personal", day: 1, start: 12, end: 13 },
  { key: "schoolDropOff", kind: "family", day: 2, start: 9, end: 10 },
  { key: "therapy", kind: "personal", day: 3, start: 13, end: 14.5 },
  { key: "recital", kind: "family", day: 4, start: 15.5, end: 17 },
]
