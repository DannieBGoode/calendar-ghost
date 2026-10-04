import { describe, expect, it } from "vitest"

import { emptyHistoryCopy, entrySteps, historyStatus } from "./activity-history"
import type { AuditEntry } from "./api"

function entry(id: number): AuditEntry {
  return {
    id,
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
  }
}

describe("emptyHistoryCopy", () => {
  it("treats an empty default view as good news", () => {
    expect(emptyHistoryCopy({ ruleId: "", show: "", query: "" }).title).toBe("Nothing has changed yet")
  })

  it("names the searched title before any other filter", () => {
    const copy = emptyHistoryCopy({ ruleId: "rule-1", show: "blocked", query: "Dentist" })
    expect(copy.title).toBe("No events named “Dentist”")
    expect(copy.body).toContain("clear the search")
  })

  it("blames the rule or decision filter when no search is set", () => {
    expect(emptyHistoryCopy({ ruleId: "rule-1", show: "all", query: "" }).title).toBe("No matching activity")
    expect(emptyHistoryCopy({ ruleId: "", show: "blocked", query: "" }).title).toBe("No matching activity")
  })

  it("waits for the first run when every decision of every rule is shown", () => {
    expect(emptyHistoryCopy({ ruleId: "", show: "all", query: "" }).title).toBe("No activity yet")
  })
})

describe("historyStatus", () => {
  it("announces an update before any search result", () => {
    expect(historyStatus({ updating: true, query: "Dentist", more: false, count: 2 })).toBe("Updating activity…")
  })

  it("stays silent without a search", () => {
    expect(historyStatus({ updating: false, query: "", more: true, count: 2 })).toBe("")
  })

  it("counts search results and says when older pages may hold more", () => {
    expect(historyStatus({ updating: false, query: "Dentist", more: false, count: 1 })).toBe("1 entry found for “Dentist”.")
    expect(historyStatus({ updating: false, query: "Dentist", more: true, count: 2 })).toBe(
      "More than 2 entries found for “Dentist”.",
    )
  })
})

describe("entrySteps", () => {
  const entries = [entry(3), entry(2), entry(1)]

  it("steps to the newer and older neighbours of the selected entry", () => {
    expect(entrySteps(entries, entries[1])).toEqual({ newer: entries[0], older: entries[2] })
  })

  it("has no newer step at the top and no older step at the bottom", () => {
    expect(entrySteps(entries, entries[0])).toEqual({ newer: undefined, older: entries[1] })
    expect(entrySteps(entries, entries[2])).toEqual({ newer: entries[1], older: undefined })
  })

  it("offers no steps for an entry that is not listed or when none is selected", () => {
    expect(entrySteps(entries, entry(9))).toEqual({ newer: undefined, older: undefined })
    expect(entrySteps(entries, undefined)).toEqual({ newer: undefined, older: undefined })
  })
})
