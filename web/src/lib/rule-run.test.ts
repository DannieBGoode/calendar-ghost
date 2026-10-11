import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"

import type { ReconcileResult, RunOutcome, SyncResult } from "./api"
import {
  lastRunLabel,
  previewReadyLabel,
  recoveryExplanation,
  reconcileResultMessage,
  syncResultMessage,
} from "./rule-run"

const i18n = testI18n()

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
  failure_provider: null,
  last_succeeded_at: null,
}
const result: SyncResult = { rule_id: "r", created: 0, updated: 0, deleted: 0, ignored: 0, conflicts: 0 }
const reconciled: ReconcileResult = {
  ...result,
  consistent: true,
  checked_mappings: 0,
  drift: [],
  reconciliation_conflicts: [],
}

describe("lastRunLabel", () => {
  it("describes success, failure, and never-run rules", () => {
    expect(lastRunLabel(i18n, outcome, now)).toBe("Last synced 10 minutes ago")
    expect(lastRunLabel(i18n, { ...outcome, succeeded: false, failure_kind: "rate_limit", failure_provider: "google" }, now)).toBe(
      "Last sync failed 10 minutes ago: Google Calendar was limiting requests",
    )
    expect(lastRunLabel(i18n, null, now)).toBe("Not synced yet")
  })
})

describe("run results", () => {
  it("summarizes a sync by what changed", () => {
    expect(syncResultMessage(i18n, result)).toBe("Up to date. Nothing changed since the last run.")
    expect(syncResultMessage(i18n, { ...result, created: 2, deleted: 1 })).toBe("Synced: 2 created, 1 deleted.")
    expect(syncResultMessage(i18n, { ...result, conflicts: 1 })).toContain("1 conflict blocked")
  })

  it("summarizes a reconciliation by what its sync changed and what its check found", () => {
    const checked = { ...reconciled, checked_mappings: 12 }
    expect(reconcileResultMessage(i18n, { ...checked, consistent: true }, "Family")).toBe(
      "Checked 12 events this rule wrote to Family: every one matches its source event.",
    )
    expect(reconcileResultMessage(i18n, { ...checked, consistent: true, updated: 2 }, "Family")).toBe(
      "Synced: 2 updated. Checked 12 events this rule wrote to Family: every one matches its source event.",
    )
  })

  it("counts what still differs after the sync by kind, and never blames a change during the check", () => {
    const message = reconcileResultMessage(
      i18n,
      {
        ...reconciled,
        consistent: false,
        checked_mappings: 71,
        drift: [
          { kind: "missing", detail: "" },
          { kind: "missing", detail: "" },
          { kind: "incorrect_projection", detail: "" },
          { kind: "unexpected", detail: "" },
        ],
      },
      "IO Clone",
    )
    expect(message).toBe(
      "Checked 71 events this rule wrote to IO Clone (a recurring series counts once). " +
        "4 differences remain after the sync: 2 missing from IO Clone, 1 different from its source event, " +
        "1 still in IO Clone though its source event was cancelled or excluded. " +
        "If Reconcile now finds them again, Calendar Ghost can't settle them on its own.",
    )
    expect(message).not.toMatch(/during the check/)
  })

  it("names one remaining difference in the singular", () => {
    const message = reconcileResultMessage(
      i18n,
      { ...reconciled, consistent: false, checked_mappings: 1, drift: [{ kind: "missing", detail: "" }] },
      "Family",
    )
    expect(message).toBe(
      "Checked 1 event this rule wrote to Family (a recurring series counts once). " +
        "1 difference remains after the sync: 1 missing from Family. " +
        "If Reconcile now finds it again, Calendar Ghost can't settle it on its own.",
    )
  })

  it("describes several differences of one kind in the plural", () => {
    const drift = [
      { kind: "incorrect_projection", detail: "" },
      { kind: "incorrect_projection", detail: "" },
      { kind: "unexpected", detail: "" },
      { kind: "unexpected", detail: "" },
    ]
    expect(reconcileResultMessage(i18n, { ...reconciled, consistent: false, checked_mappings: 9, drift }, "Family")).toContain(
      "2 different from their source events, 2 still in Family though their source events were cancelled or excluded.",
    )
  })

  it("never calls what the check only reported repaired", () => {
    const message = reconcileResultMessage(
      i18n,
      {
        ...reconciled,
        consistent: false,
        checked_mappings: 3,
        drift: [{ kind: "incorrect_projection", detail: "" }],
      },
      "Family",
    )
    expect(message).not.toMatch(/repair/)
  })

  it("counts the sync's blocks and the check's own conflicts together", () => {
    expect(
      reconcileResultMessage(
        i18n,
        {
          ...reconciled,
          conflicts: 1,
          consistent: false,
          checked_mappings: 4,
          drift: [],
          reconciliation_conflicts: [{ reason: "projection_unmapped", detail: "" }],
        },
        "Family",
      ),
    ).toBe("Checked 4 events this rule wrote to Family. 2 conflicts blocked; see Activity.")
  })

  it("never says every projection matches when an event was blocked", () => {
    const checked = { ...reconciled, checked_mappings: 4 }
    const bySync = reconcileResultMessage(i18n, { ...checked, conflicts: 1, consistent: true }, "Family")
    const byCheck = reconcileResultMessage(
      i18n,
      {
        ...checked,
        consistent: false,
        reconciliation_conflicts: [{ reason: "source_unverifiable", detail: "" }],
      },
      "Family",
    )
    for (const message of [bySync, byCheck]) {
      expect(message).not.toContain("matches")
      expect(message).toContain("1 conflict blocked; see Activity.")
    }
  })
})

describe("previewReadyLabel", () => {
  it("states what the preview found in one line", () => {
    expect(
      previewReadyLabel(i18n, { eligible_events: 73, excluded_events: 47, completed_at: "2026-09-28T11:58:00Z" }, "Work", now),
    ).toBe("Previewed 2 minutes ago: 73 events will appear in Work, 47 excluded.")
    expect(
      previewReadyLabel(i18n, { eligible_events: 1, excluded_events: 0, completed_at: "2026-09-28T11:58:00Z" }, "Work", now),
    ).toBe("Previewed 2 minutes ago: 1 event will appear in Work.")
  })

  it("still names the destination when the preview counts are not known", () => {
    expect(previewReadyLabel(i18n, null, "Work", now)).toBe("Start syncing to show events in Work.")
  })
})

describe("recoveryExplanation", () => {
  it("names the cause and reassures that nothing was lost", () => {
    expect(recoveryExplanation(i18n, { ...outcome, succeeded: false, failure_kind: "rate_limit", failure_provider: "google" }, now)).toBe(
      "Google Calendar was limiting requests 10 minutes ago, so Calendar Ghost stopped this rule to be safe. Nothing was lost. Preview it to check both calendars, then start syncing again.",
    )
    expect(recoveryExplanation(i18n, { ...outcome, succeeded: false, failure_kind: "authentication", failure_provider: "outlook" }, now)).toMatch(
      /^Authorization for Outlook expired 10 minutes ago, so Calendar Ghost stopped this rule/,
    )
    expect(recoveryExplanation(i18n, null, now)).toMatch(/^Calendar Ghost stopped this rule to be safe\. Nothing was lost/)
  })
})

