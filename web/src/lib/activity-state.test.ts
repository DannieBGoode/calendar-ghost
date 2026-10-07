import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"

import entryDetailsSource from "../features/activity-entry-details.tsx?raw"
import tableSource from "../features/activity-table.tsx?raw"
import viewSource from "../features/activity.tsx?raw"
import historySource from "./activity-history.ts?raw"

// The Activity view, its table, its entry details, and the copy for an empty history.
const activitySource = [viewSource, tableSource, entryDetailsSource, historySource].join("\n")

describe("Activity view states", () => {
  it("keeps successful empty activity distinct from a recoverable request failure", () => {
    expect(activitySource).toContain('t("activity.empty.none.title")')
    expect(activitySource).toContain('t("activity.failure.title")')
    const { t } = testI18n()
    expect(t("activity.empty.none.title")).toBe("No activity yet")
    expect(t("activity.failure.title")).toBe("Activity is temporarily unavailable")
    expect(activitySource).toContain("activity.refetch()")
    expect(activitySource).toContain("incidents.refetch()")
  })
})

describe("Activity filters", () => {
  it("keeps the page and its filters on screen while another rule or filter loads", () => {
    expect(activitySource).toContain("placeholderData: keepPreviousData")
    expect(activitySource).toContain("aria-busy={updating}")
  })
})

describe("activity for removed rules", () => {
  it("explains why events of a removed rule cannot be looked up", () => {
    expect(activitySource).toContain("entryInspection(entry, exists)")
    expect(activitySource).toContain("REMOVED_RULE_LOOKUP")
    expect(activitySource).toContain("eventLookupFailure(i18n, event.error)")
  })
})

describe("activity date grouping", () => {
  it("keeps the date heading and all its runs in one rowgroup", () => {
    expect(activitySource).toContain("const days = activityDayGroups(groups)")
    expect(activitySource).toContain('className="activity-day"')
    expect(activitySource).toContain('scope="rowgroup"')
    expect(activitySource).not.toContain("aria-labelledby={dayId}")
  })
})
