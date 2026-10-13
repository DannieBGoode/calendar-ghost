import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"

import { facetCounts, layOut, matchesFilters, offeredKinds, outcomeCounts, previewKinds, previewOutcome, type PreviewItem } from "./rule-preview"
import { outcomeText, sourceNotes, whenText } from "./rule-preview-text"

const i18n = testI18n()
const now = new Date(2025, 9, 13, 10, 0)

function item(overrides: Partial<PreviewItem> = {}): PreviewItem {
  return {
    source_event_id: "event",
    kind: "single",
    title: "Dentist",
    starts_at: new Date(2025, 9, 13, 9, 0).toISOString(),
    ends_at: new Date(2025, 9, 13, 10, 0).toISOString(),
    time_zone: null,
    starts_on: null,
    ends_before: null,
    recurrence: null,
    series_event_id: null,
    original_start: null,
    cancelled: false,
    response: "accepted",
    birthday: false,
    planned_action: "create",
    reason: "source_created",
    projection: { title: "Busy", carries_details: false, recurrence: null },
    ...overrides,
  }
}

const birthday = item({
  source_event_id: "birthday",
  title: "Mum",
  starts_at: null,
  ends_at: null,
  starts_on: "2025-10-15",
  ends_before: "2025-10-16",
  birthday: true,
  planned_action: "ignore",
  reason: "birthday",
  projection: null,
})

describe("previewOutcome", () => {
  it("reads what the destination will hold", () => {
    expect(previewOutcome(item())).toBe("add")
    expect(previewOutcome(item({ planned_action: "ignore", reason: "projection_current" }))).toBe("current")
    expect(previewOutcome(birthday)).toBe("skipped")
    expect(previewOutcome(item({ planned_action: "delete", reason: "declined_removed", projection: null }))).toBe("remove")
  })

  it("names a reason worth naming", () => {
    expect(outcomeText(i18n, item())).toBe("Add")
    expect(outcomeText(i18n, birthday)).toBe("Not synced: birthday")
    expect(outcomeText(i18n, item({ planned_action: "delete", reason: "declined_removed", projection: null }))).toBe("Remove: you declined")
  })
})

describe("filters", () => {
  it("narrow by outcome and by any chosen kind", () => {
    const declined = item({ source_event_id: "lunch", response: "declined", projection: null, planned_action: "ignore", reason: "declined" })
    expect(previewKinds(birthday)).toEqual(["allDay", "birthday"])
    expect(matchesFilters(birthday, { show: "sync", kinds: [] })).toBe(false)
    expect(matchesFilters(birthday, { show: "out", kinds: ["declined", "birthday"] })).toBe(true)
    expect(matchesFilters(declined, { show: "all", kinds: ["allDay"] })).toBe(false)
    expect([...outcomeCounts([item(), birthday, declined])]).toEqual([
      ["add", 1],
      ["skipped", 2],
    ])
  })

  it("offers only the kinds the preview has", () => {
    expect(offeredKinds([item(), birthday])).toEqual(["allDay", "birthday"])
    // A chosen kind a refresh no longer finds stays, so it can still be unpressed.
    expect(offeredKinds([item()], ["birthday"])).toEqual(["birthday"])
  })
})

describe("facetCounts", () => {
  it("counts each option beside the other choices, so the chosen Show count is the rows shown", () => {
    const items = [item(), birthday, item({ source_event_id: "standup", kind: "series", recurrence: ["RRULE:FREQ=WEEKLY"] })]

    const willSync = facetCounts(items, { show: "sync", kinds: [] })
    expect(willSync.kinds.get("birthday")).toBeUndefined()
    expect(willSync.kinds.get("recurring")).toBe(1)

    const birthdays = facetCounts(items, { show: "all", kinds: ["birthday"] })
    expect(birthdays.show).toEqual({ all: 1, sync: 0, out: 1 })
  })
})

describe("layOut", () => {
  it("keeps a deleted event the provider no longer dates, so its removal is shown", () => {
    const deleted = item({ source_event_id: "gone", starts_at: null, ends_at: null, cancelled: true, planned_action: "delete", reason: "source_cancelled", projection: null })

    const layout = layOut([deleted], now)

    expect(layout.undated.map((placed) => placed.item.source_event_id)).toEqual(["gone"])
    expect(layout.undated[0] && whenText(i18n, layout.undated[0], now)).toBe("Deleted")
  })

  it("dates a recurring multi-day all-day event from its next occurrence", () => {
    const retreat = item({
      source_event_id: "retreat",
      kind: "series",
      starts_at: null,
      ends_at: null,
      starts_on: "2025-09-01",
      ends_before: "2025-09-04",
      recurrence: ["RRULE:FREQ=MONTHLY"],
    })

    const [placed] = layOut([retreat], now).upcoming[0]?.items ?? []

    expect(placed && whenText(i18n, placed, now)).toBe("All day, Nov 1–Nov 3")
  })

  it("places a series that began weeks ago at its next date, not among earlier events", () => {
    const swim = item({
      source_event_id: "swim",
      kind: "series",
      title: "Swim class",
      starts_at: new Date(2025, 8, 2, 18, 0).toISOString(),
      ends_at: new Date(2025, 8, 2, 19, 0).toISOString(),
      recurrence: ["RRULE:FREQ=WEEKLY"],
    })
    const past = item({ source_event_id: "past", starts_at: new Date(2025, 8, 20, 9, 0).toISOString(), ends_at: new Date(2025, 8, 20, 10, 0).toISOString() })

    const layout = layOut([birthday, swim, item(), past], now)

    expect(layout.earlier.map((day) => day.items.map((placed) => placed.item.source_event_id))).toEqual([["past"]])
    expect(layout.upcoming.map((day) => day.items.map((placed) => placed.item.source_event_id))).toEqual([
      ["event"],
      ["swim"],
      ["birthday"],
    ])
    const placedSwim = layout.upcoming[1]?.items[0]
    expect(placedSwim && whenText(i18n, placedSwim, now)).toBe("6:00 PM–7:00 PM")
    expect(placedSwim && sourceNotes(i18n, placedSwim, now)).toEqual(["Weekly on Tuesday", "since Sep 2"])
  })

  it("names the year of a date outside the current one", () => {
    const festival = item({ source_event_id: "festival", starts_at: null, ends_at: null, starts_on: "2030-07-04", ends_before: "2030-07-07" })
    const choir = item({
      source_event_id: "choir",
      kind: "series",
      starts_at: new Date(2024, 2, 5, 18, 0).toISOString(),
      ends_at: new Date(2024, 2, 5, 19, 0).toISOString(),
      recurrence: ["RRULE:FREQ=WEEKLY"],
    })

    const { upcoming } = layOut([festival, choir], now)
    const placedChoir = upcoming[0]?.items[0]
    const placedFestival = upcoming[1]?.items[0]

    expect(placedFestival && whenText(i18n, placedFestival, now)).toBe("All day, Jul 4, 2030–Jul 6, 2030")
    expect(placedChoir && sourceNotes(i18n, placedChoir, now)).toEqual(["Weekly on Tuesday", "since Mar 5, 2024"])
  })

  it("explains a moved occurrence on the date it moved to", () => {
    const moved = item({
      kind: "occurrence",
      starts_at: new Date(2025, 9, 21, 19, 0).toISOString(),
      ends_at: new Date(2025, 9, 21, 20, 0).toISOString(),
      series_event_id: "swim",
      original_start: new Date(2025, 9, 21, 18, 0).toISOString(),
      planned_action: "update",
      reason: "occurrence_changed",
    })
    const [placed] = layOut([moved], now).upcoming[0]?.items ?? []
    expect(placed && sourceNotes(i18n, placed, now)).toEqual(["This date only: moved from 6:00 PM"])
  })
})
