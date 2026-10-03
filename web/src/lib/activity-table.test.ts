import { describe, expect, it } from "vitest"

import {
  activityDayGroups,
  activityRows,
  eventCell,
  formatClockTime,
  formatDay,
  formatEventTime,
  groupRuns,
  showCategories,
  SHOW_FILTERS,
} from "./activity"
import { activitySearch, activityStateFromSearch } from "./activity-location"
import type { AuditEntry, RecordedEvent } from "./api"

function entry(overrides: Partial<AuditEntry>): AuditEntry {
  return {
    id: 1,
    run_id: "run-1",
    occurred_at: "2026-09-28T15:18:46+00:00",
    rule_id: "rule-1",
    action: "ignore",
    outcome: "skipped",
    category: "unchanged",
    reason: "projection_current",
    detail: "",
    source_event_id: "source-event",
    destination_event_id: null,
    event: null,
    repeated: false,
    changed_fields: null,
    ...overrides,
  }
}

function recorded(overrides: Partial<RecordedEvent> = {}): RecordedEvent {
  return {
    title: "Dentist",
    all_day: false,
    starts: "2026-09-30T10:00:00+00:00",
    ends: "2026-09-30T11:00:00+00:00",
    recurring: false,
    cancelled: false,
    renamed_from: null,
    moved_from: null,
    ...overrides,
  }
}

describe("activity location", () => {
  it("reads the rule, filter, and open entry from the address", () => {
    expect(activityStateFromSearch("?rule=rule-1&show=blocked&entry=12")).toEqual({
      ruleId: "rule-1",
      show: "blocked",
      entryId: 12,
      query: "",
    })
  })

  it("falls back to defaults for unknown or malformed values", () => {
    expect(activityStateFromSearch("?show=everything&entry=twelve")).toEqual({
      ruleId: "",
      show: "",
      entryId: null,
      query: "",
    })
    expect(activityStateFromSearch("?entry=0").entryId).toBeNull()
  })

  it("writes only values that differ from the defaults", () => {
    expect(activitySearch({ ruleId: "", show: "", entryId: null })).toBe("")
    expect(activitySearch({ ruleId: "rule 1", show: "all", entryId: 7 })).toBe(
      "?rule=rule+1&show=all&entry=7",
    )
  })

  it("keeps a search in the address, trimmed", () => {
    expect(activityStateFromSearch("?q=%20Dentist%20").query).toBe("Dentist")
    expect(activitySearch({ ruleId: "", show: "", entryId: null, query: " team lunch " })).toBe("?q=team+lunch")
    expect(activitySearch({ ruleId: "", show: "", entryId: null, query: "  " })).toBe("")
  })
})

describe("activity filters", () => {
  it("hides no-change checks unless asked for", () => {
    expect(SHOW_FILTERS[0].value).toBe("")
    expect(showCategories("")).toEqual(["changed", "skipped", "blocked"])
    expect(showCategories("all")).toBeUndefined()
    expect(showCategories("unchanged")).toEqual(["unchanged"])
  })
})

describe("activity rows", () => {
  const now = new Date(2026, 8, 28, 20, 0)
  const at = (day: number, hour: number) => new Date(2026, 8, day, hour, 0).toISOString()
  const runs = groupRuns([
    entry({ id: 50, run_id: "run-3", occurred_at: at(28, 18), action: "create", category: "changed" }),
    entry({ id: 40, run_id: "run-2", occurred_at: at(28, 9), action: "update", category: "changed" }),
    entry({ id: 20, run_id: "run-1", occurred_at: at(27, 9), action: "create", category: "changed" }),
  ])

  it("names each day once, above its first run", () => {
    const groups = activityRows(runs, { now })

    expect(groups.map((group) => group.key)).toEqual(["run-3", "run-2", "run-1"])
    expect(groups.map((group) => group.day)).toEqual(["Today", null, "Yesterday"])
  })

  it("keeps every same-day run in the date rowgroup", () => {
    const days = activityDayGroups(activityRows(runs, { now }))

    expect(days.map((day) => day.day)).toEqual(["Today", "Yesterday"])
    expect(days.map((day) => day.runs.map((run) => run.key))).toEqual([["run-3", "run-2"], ["run-1"]])
  })
})

describe("row times", () => {
  it("shows only the clock time, since day headers name the day", () => {
    expect(formatClockTime(new Date(2026, 8, 28, 18, 16).toISOString())).toMatch(/6:16/)
    expect(formatDay(new Date(2026, 8, 25, 9).toISOString(), new Date(2026, 8, 28))).toMatch(/25/)
  })
})

describe("event cells", () => {
  const names = { source: "Personal", destination: "Work" }

  it("names the event and when it happens", () => {
    const cell = eventCell(entry({ event: recorded({ recurring: true }) }), names)

    expect(cell).toMatchObject({ state: "event", title: "Dentist", recurring: true })
    expect(cell.state === "event" && cell.when).toContain("30")
    expect(cell.state === "event" && cell.note).toBeUndefined()
  })

  it("says whether an entry was about a whole series or one occurrence", () => {
    const weekly = recorded({ recurring: true })
    expect(eventCell(entry({ reason: "projection_current", event: weekly }), names)).toMatchObject({ scope: "series" })
    expect(eventCell(entry({ reason: "destination_occurrence_missing", event: weekly }), names)).toMatchObject({
      scope: "occurrence",
    })
    expect(eventCell(entry({ reason: "all_day_excluded_removed", event: weekly }), names)).toMatchObject({ scope: null })
    expect(eventCell(entry({ reason: "mapping_inconsistent", event: weekly }), names)).toMatchObject({ scope: null })
    expect(eventCell(entry({ reason: "source_changed", event: recorded() }), names)).toMatchObject({ scope: null })
  })

  it("names events of removed rules from what was recorded", () => {
    expect(eventCell(entry({ event: recorded() }), null)).toMatchObject({ state: "event", title: "Dentist" })
  })

  it("says when the event was renamed", () => {
    expect(eventCell(entry({ event: recorded({ title: "Dentist (moved)", renamed_from: "Dentist" }) }), names)).toMatchObject({
      title: "Dentist (moved)",
      note: "Renamed from “Dentist”",
    })
    expect(eventCell(entry({ event: recorded({ renamed_from: "" }) }), names)).toMatchObject({
      title: "Dentist",
      note: "Renamed from “(No title)”",
    })
  })

  it("keeps the title of a cancelled event and says it was cancelled", () => {
    expect(eventCell(entry({ event: recorded({ cancelled: true, starts: null, ends: null }) }), names)).toMatchObject({
      state: "event",
      title: "Dentist",
      note: "Cancelled in Personal",
      when: "",
    })
    expect(eventCell(entry({ event: recorded({ cancelled: true, title: "" }) }), names)).toMatchObject({
      title: "Cancelled event",
    })
  })

  it("explains entries that name no event", () => {
    expect(eventCell(entry({ source_event_id: null }), names)).toEqual({
      state: "unavailable",
      label: "Personal → Work rule",
      note: "Applies to the whole rule",
    })
    expect(eventCell(entry({ source_event_id: null }), null)).toMatchObject({ label: "Removed rule" })
    expect(eventCell(entry({}), names)).toMatchObject({
      state: "unavailable",
      label: "Event name not recorded",
    })
    expect(eventCell(entry({ event: recorded({ title: "" }) }), names)).toMatchObject({ title: "(No title)" })
  })
})

describe("event times", () => {
  it("names the year only for events outside the current one", () => {
    const now = new Date(2026, 8, 28)
    const thisYear = formatEventTime({ all_day: true, starts: "2026-09-30", ends: "2026-10-01" }, now)
    const nextYear = formatEventTime({ all_day: true, starts: "2027-01-04", ends: "2027-01-05" }, now)

    expect(thisYear).not.toContain("2026")
    expect(thisYear).toContain("all day")
    expect(nextYear).toContain("2027")
  })
})
