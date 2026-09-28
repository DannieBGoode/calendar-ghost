import { describe, expect, it } from "vitest"

import type { RunOutcome, SyncResult } from "./api"
import {
  enableSummary,
  lastRunLabel,
  recentChangeSummary,
  recoveryExplanation,
  reconcileResultMessage,
  syncResultMessage,
} from "./rule-run"

const now = Date.parse("2026-09-28T12:00:00Z")
const outcome: RunOutcome = {
  completed_at: "2026-09-28T11:50:00Z",
  succeeded: true,
  full_run: false,
  created: 0,
  updated: 0,
  deleted: 0,
  conflicts: 0,
  checked_mappings: 0,
  drift: 0,
  failure_kind: null,
}
const result: SyncResult = { rule_id: "r", created: 0, updated: 0, deleted: 0, ignored: 0, conflicts: 0 }

describe("lastRunLabel", () => {
  it("describes success, failure, and never-run rules", () => {
    expect(lastRunLabel(outcome, now)).toBe("Last synced 10 minutes ago")
    expect(lastRunLabel({ ...outcome, succeeded: false, failure_kind: "rate_limit" }, now)).toBe(
      "Last sync failed 10 minutes ago: Google Calendar was limiting requests",
    )
    expect(lastRunLabel(null, now)).toBe("Not synced yet")
  })
})

describe("run results", () => {
  it("summarizes a sync by what changed", () => {
    expect(syncResultMessage(result)).toBe("Up to date. Nothing changed since the last run.")
    expect(syncResultMessage({ ...result, created: 2, deleted: 1 })).toBe("Synced: 2 created, 1 deleted.")
    expect(syncResultMessage({ ...result, conflicts: 1 })).toContain("1 conflict blocked")
  })

  it("summarizes a reconciliation by what it checked and repaired", () => {
    expect(reconcileResultMessage({ ...result, consistent: true, checked_mappings: 12, drift: [] })).toBe(
      "Checked 12 projections: every one matches its source event.",
    )
    expect(
      reconcileResultMessage({
        ...result,
        consistent: false,
        checked_mappings: 12,
        drift: [{ kind: "missing", detail: "" }],
      }),
    ).toBe("Checked 12 projections: 1 difference repaired from the source.")
  })
})

describe("enableSummary", () => {
  it("restates the privacy consequence with preview counts", () => {
    expect(
      enableSummary({
        preview: { eligible_events: 37, excluded_events: 4 },
        source: "Family",
        destination: "Work",
        privacy: "busy_only",
      }),
    ).toBe(
      "37 events from Family will appear in Work as “Busy”. Titles, descriptions, and locations stay private. 4 events are excluded by this rule.",
    )
  })

  it("still names the consequence when the preview is no longer in memory", () => {
    expect(
      enableSummary({ preview: undefined, source: "Family", destination: "Work", privacy: "copy_details" }),
    ).toMatch(/^Events from Family will appear in Work with their titles/)
  })
})

describe("recoveryExplanation", () => {
  it("names the cause and reassures that nothing was lost", () => {
    expect(recoveryExplanation({ ...outcome, succeeded: false, failure_kind: "rate_limit" }, now)).toBe(
      "Google Calendar was limiting requests 10 minutes ago, so Calendar Sync stopped this rule to be safe. Nothing was lost. Preview it to check both calendars, then start syncing again.",
    )
    expect(recoveryExplanation(null, now)).toMatch(/^Calendar Sync stopped this rule to be safe\. Nothing was lost/)
  })
})

describe("recentChangeSummary", () => {
  const none = { created: 0, updated: 0, deleted: 0, repaired: 0, blocked: 0 }

  it("describes a run in calendar language", () => {
    expect(recentChangeSummary({ ...none, created: 1, updated: 2 }, "Family")).toBe(
      "Added 1 event and updated 2 in Family.",
    )
    expect(recentChangeSummary({ ...none, deleted: 1, repaired: 2 }, "Work")).toBe(
      "Removed 1 in Work. Repaired 2 events someone edited or deleted in Work.",
    )
  })

  it("calls out blocked changes", () => {
    expect(recentChangeSummary({ ...none, blocked: 1 }, "Work")).toBe("1 change was blocked and needs a look.")
    expect(recentChangeSummary({ ...none, created: 3, blocked: 2 }, "Work")).toBe(
      "Added 3 events in Work. 2 changes were blocked and need a look.",
    )
  })
})
