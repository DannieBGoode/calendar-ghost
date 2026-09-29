import { describe, expect, it } from "vitest"

import type { RunOutcome, SyncResult } from "./api"
import {
  lastRunLabel,
  previewReadyLabel,
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

  it("summarizes a reconciliation by what its sync changed and what its check found", () => {
    const checked = { ...result, checked_mappings: 12, drift: [], reconciliation_conflicts: [] }
    expect(reconcileResultMessage({ ...checked, consistent: true })).toBe(
      "Checked 12 projections: every one matches its source event.",
    )
    expect(reconcileResultMessage({ ...checked, consistent: true, updated: 2 })).toBe(
      "Synced: 2 updated. Checked 12 projections: every one matches its source event.",
    )
    expect(
      reconcileResultMessage({ ...checked, consistent: false, drift: [{ kind: "missing", detail: "" }] }),
    ).toBe(
      "Checked 12 projections: 1 still differs from its source event and was left as it is. The next sync puts back any that changed during the check.",
    )
    expect(
      reconcileResultMessage({
        ...checked,
        consistent: false,
        drift: [
          { kind: "missing", detail: "" },
          { kind: "incorrect_projection", detail: "" },
        ],
      }),
    ).toContain("2 still differ from their source events and were left as they are.")
  })

  it("never calls what the check only reported repaired", () => {
    const message = reconcileResultMessage({
      ...result,
      consistent: false,
      checked_mappings: 3,
      drift: [{ kind: "incorrect_projection", detail: "" }],
    })
    expect(message).not.toMatch(/repaired/)
  })

  it("counts the sync's blocks and the check's own conflicts together", () => {
    expect(
      reconcileResultMessage({
        ...result,
        conflicts: 1,
        consistent: false,
        checked_mappings: 4,
        drift: [],
        reconciliation_conflicts: [{ reason: "projection_unmapped", detail: "" }],
      }),
    ).toBe("Checked 4 projections: every one matches its source event. 2 conflicts blocked; see Activity.")
  })
})

describe("previewReadyLabel", () => {
  it("states what the preview found in one line", () => {
    expect(
      previewReadyLabel({ eligible_events: 73, excluded_events: 47, completed_at: "2026-09-28T11:58:00Z" }, "Work", now),
    ).toBe("Previewed 2 minutes ago: 73 events will appear in Work, 47 excluded.")
    expect(
      previewReadyLabel({ eligible_events: 1, excluded_events: 0, completed_at: "2026-09-28T11:58:00Z" }, "Work", now),
    ).toBe("Previewed 2 minutes ago: 1 event will appear in Work.")
  })

  it("still names the destination when the preview counts are not known", () => {
    expect(previewReadyLabel(null, "Work", now)).toBe("Start syncing to show events in Work.")
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

