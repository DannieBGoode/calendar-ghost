import { describe, expect, it, vi } from "vitest"

import { activityRows, eventCell, formatClockTime, formatDay, formatEventTime, groupRuns, showCategories, SHOW_FILTERS } from "./activity"
import { activitySearch, activityStateFromSearch } from "./activity-location"
import type { ActivityEventSummary, AuditEntry, EventSnapshot } from "./api"
import { createBatchLoader } from "./batch-loader"

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
    ...overrides,
  }
}

function snapshot(overrides: Partial<EventSnapshot> = {}): EventSnapshot {
  return {
    found: true,
    cancelled: false,
    title: "Dentist",
    all_day: false,
    starts: "2026-09-30T10:00:00+00:00",
    ends: "2026-09-30T11:00:00+00:00",
    recurring: false,
    web_link: null,
    ...overrides,
  }
}

function found(source: EventSnapshot): { status: "success"; data: ActivityEventSummary } {
  return { status: "success", data: { entry_id: 1, lookup: "found", source } }
}

describe("activity location", () => {
  it("reads the rule, filter, and open entry from the address", () => {
    expect(activityStateFromSearch("?rule=rule-1&show=blocked&entry=12")).toEqual({
      ruleId: "rule-1",
      show: "blocked",
      entryId: 12,
    })
  })

  it("falls back to defaults for unknown or malformed values", () => {
    expect(activityStateFromSearch("?show=everything&entry=twelve")).toEqual({
      ruleId: "",
      show: "",
      entryId: null,
    })
    expect(activityStateFromSearch("?entry=0").entryId).toBeNull()
  })

  it("writes only values that differ from the defaults", () => {
    expect(activitySearch({ ruleId: "", show: "", entryId: null })).toBe("")
    expect(activitySearch({ ruleId: "rule 1", show: "all", entryId: 7 })).toBe(
      "?rule=rule+1&show=all&entry=7",
    )
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
  const quiet = (run_id: string, newest_id: number, occurred_at: string, count = 2) => ({
    run_id,
    rule_id: "rule-1",
    newest_id,
    occurred_at,
    count,
  })
  const shape = (groups: ReturnType<typeof activityRows>) =>
    groups.map((group) =>
      group.kind === "quiet"
        ? `quiet ${group.runs}×${group.checks}`
        : group.rows.map((row) => (row.kind === "entry" ? row.entry.id : `+${row.count}`)).join(","),
    )

  it("names each day once, above its first group", () => {
    const groups = activityRows(runs, { now })

    expect(groups.map((group) => group.day)).toEqual(["Today", null, "Yesterday"])
  })

  it("ends a run with a count of its hidden no-change checks", () => {
    const groups = activityRows(runs, { now, noChangeRuns: [quiet("run-2", 39, at(28, 9), 3)] })

    expect(shape(groups)).toEqual(["50", "40,+3", "20"])
  })

  it("shows runs that only confirmed events were up to date, one row per stretch of such runs", () => {
    const groups = activityRows(runs, {
      now,
      noChangeRuns: [
        quiet("run-6", 70, at(28, 19)),
        quiet("run-5", 60, at(28, 18)),
        quiet("run-4", 45, at(28, 12), 5),
        quiet("run-0", 10, at(27, 8)),
      ],
    })

    expect(shape(groups)).toEqual(["quiet 2×4", "50", "quiet 1×5", "40", "20", "quiet 1×2"])
    expect(groups[0]).toMatchObject({ newest: at(28, 19), oldest: at(28, 18) })
  })

  it("lists a run's loaded no-change checks in place and offers more when some are unloaded", () => {
    const checks = [entry({ id: 39, run_id: "run-2" }), entry({ id: 41, run_id: "run-2" })]
    const groups = activityRows(runs, {
      now,
      noChangeRuns: [quiet("run-2", 41, at(28, 9), 150)],
      expanded: new Map([["run-2", { entries: checks, complete: false }]]),
    })

    expect(shape(groups)[1]).toBe("41,40,39,+150")
    const run = groups[1]
    expect(run.kind === "run" && run.rows.at(-1)).toEqual({ kind: "folded", count: 150, expanded: true, more: true })
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
    const cell = eventCell(entry({}), names, found(snapshot({ recurring: true })))

    expect(cell).toMatchObject({ state: "event", title: "Dentist", recurring: true })
    expect(cell.state === "event" && cell.when).toContain("30")
  })

  it("keeps the title of a cancelled event and says it was cancelled", () => {
    expect(eventCell(entry({}), names, found(snapshot({ cancelled: true, starts: null, ends: null })))).toMatchObject({
      state: "event",
      title: "Dentist",
      note: "Cancelled",
      when: "",
    })
    expect(eventCell(entry({}), names, found(snapshot({ cancelled: true, title: "" })))).toMatchObject({
      title: "Cancelled event",
    })
  })

  it("explains events that cannot be named in terms of their calendars", () => {
    expect(eventCell(entry({ source_event_id: null }), names, { status: "pending" })).toEqual({
      state: "unavailable",
      label: "Personal → Work rule",
      note: "Applies to the whole rule",
    })
    expect(eventCell(entry({ source_event_id: null }), null, { status: "pending" })).toMatchObject({
      label: "Removed rule",
    })
    expect(eventCell(entry({}), null, { status: "pending" })).toMatchObject({ label: "Event from a removed rule" })
    expect(eventCell(entry({}), names, { status: "pending" })).toEqual({ state: "loading" })
    expect(eventCell(entry({}), names, { status: "error" })).toMatchObject({ label: "Event name unavailable" })
    expect(eventCell(entry({}), names, found(snapshot({ found: false })))).toMatchObject({
      label: "Event deleted from Personal",
      note: "Its name is no longer available",
    })
    expect(eventCell(entry({}), names, found(snapshot({ title: "" })))).toMatchObject({ title: "(No title)" })
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

describe("batch loader", () => {
  it("combines loads from the same moment into bounded requests", async () => {
    const fetchMany = vi.fn(async (ids: number[]) => new Map(ids.map((id) => [id, id * 10])))
    const loader = createBatchLoader(fetchMany, 2)

    const values = await Promise.all([loader.load(1), loader.load(2), loader.load(3), loader.load(1)])

    expect(values).toEqual([10, 20, 30, 10])
    expect(fetchMany.mock.calls).toEqual([[[1, 2]], [[3]]])
  })

  it("answers null for keys the service omitted and rejects every load of a failed request", async () => {
    const loader = createBatchLoader(async () => new Map<number, string>(), 5)
    await expect(loader.load(4)).resolves.toBeNull()

    const failing = createBatchLoader<string>(async () => {
      throw new Error("offline")
    }, 5)
    await expect(Promise.all([failing.load(1), failing.load(2)])).rejects.toThrow("offline")
  })
})
