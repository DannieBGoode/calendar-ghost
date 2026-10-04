import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"

import calendarReplacementSource from "../features/calendar-replacement.tsx?raw"
import projectionChoiceSource from "../features/projection-choice.tsx?raw"
import factsSource from "../features/rule-details-facts.tsx?raw"
import pageSource from "../features/rule-details.tsx?raw"
import policyEditorSource from "../features/rule-policy-editor.tsx?raw"
import removalSource from "../features/rule-removal.tsx?raw"
import refreshSource from "./use-rule-refresh.ts?raw"
import { ApiError } from "@/lib/api"
import { removalOutcomeUnknown, ruleStateLabel } from "@/lib/rule-change"
import {
  elapsedLabel,
  removalConnectionLost,
  removalErrorMessage,
  removalProgress,
  reportedRemoval,
} from "@/lib/rule-removal"

// Rule Details spans the page and the sections and hooks it composes.
const detailsSource = [
  pageSource,
  factsSource,
  policyEditorSource,
  calendarReplacementSource,
  removalSource,
  projectionChoiceSource,
  refreshSource,
].join("\n")

const i18n = testI18n()

describe("rule removal progress", () => {
  it("counts handled projections without claiming conflicted ones were deleted", () => {
    expect(removalProgress(i18n, { handling: "delete", total: 312 }, 228, "Family")).toEqual({
      done: 84,
      label: "Handled 84 of 312 projections in Family",
    })
    expect(removalProgress(i18n, { handling: "delete", total: 1 }, 1, "Family").label).toBe(
      "Handled 0 of 1 projection in Family",
    )
  })

  it("prefers the service's own count, which also covers a reload", () => {
    expect(removalProgress(i18n, { handling: "delete", total: 10, done: 4 }, 10, "Family").done).toBe(4)
    expect(
      reportedRemoval(
        { kind: "removal", started_at: "2026-09-29T09:00:00Z", handling: "delete", total: 10, done: 4, stage: null },
        7,
      ),
    ).toEqual({ handling: "delete", total: 10, done: 4, startedAt: Date.parse("2026-09-29T09:00:00Z") })
    expect(
      reportedRemoval({ kind: "removal", started_at: "2026-09-29T09:00:00Z", handling: null, total: null, done: 0, stage: null }, 7),
    ).toMatchObject({ handling: "delete", total: 7, done: undefined })
    expect(
      reportedRemoval({ kind: "sync", started_at: "2026-09-29T09:00:00Z", handling: null, total: null, done: 0, stage: null }, 7),
    ).toBeUndefined()
  })

  it("clamps counts from a stale or newer mapping count", () => {
    expect(removalProgress(i18n, { handling: "delete", total: 5 }, 9, "Family").done).toBe(0)
    expect(removalProgress(i18n, { handling: "delete", total: 5 }, -1, "Family").done).toBe(5)
  })

  it("has no countable progress when keeping events or when nothing is mapped", () => {
    expect(removalProgress(i18n, { handling: "detach", total: 3 }, 3, "Family")).toEqual({
      done: null,
      label: "Keeping 3 events in Family as ordinary events…",
    })
    expect(removalProgress(i18n, { handling: "delete", total: 0 }, 0, "Family")).toEqual({
      done: null,
      label: "Removing the rule…",
    })
  })

  it("labels elapsed time", () => {
    expect(elapsedLabel(i18n, -5)).toBe("0 s")
    expect(elapsedLabel(i18n, 42_900)).toBe("42 s")
    expect(elapsedLabel(i18n, 125_000)).toBe("2 min 5 s")
  })

  it("labels a running removal separately from an interrupted one", () => {
    expect(ruleStateLabel(i18n, "removing")).toBe("Removing")
    expect(ruleStateLabel(i18n, "disabled")).toBe("Removal incomplete")
  })
})

describe("rule removal failures", () => {
  it("treats dropped connections and proxy timeouts as possibly still running", () => {
    expect(removalConnectionLost(new TypeError("Failed to fetch"))).toBe(true)
    expect(removalConnectionLost(new ApiError("The request could not be completed.", 504))).toBe(true)
    expect(removalConnectionLost(new ApiError("The request could not be completed.", 502))).toBe(true)
    expect(removalErrorMessage(i18n, new TypeError("Failed to fetch"))).toContain("may still be running")
  })

  it("shows the service's explanation as it is", () => {
    const detail = "Removal stopped after 3 of 10 projections."
    const interrupted = new ApiError(detail, 424, detail)
    expect(removalConnectionLost(interrupted)).toBe(false)
    expect(removalErrorMessage(i18n, interrupted)).toBe(detail)
    // An unconfigured service answers 503 with its own English detail, which is not a lost connection.
    const unconfiguredDetail = "Google OAuth is not configured."
    const unconfigured = new ApiError(unconfiguredDetail, 503, unconfiguredDetail)
    expect(removalConnectionLost(unconfigured)).toBe(false)
    expect(removalErrorMessage(i18n, unconfigured)).toBe(unconfiguredDetail)
  })

  it("translates a coded interruption with how far the removal got", () => {
    const params = { processed: 3, remaining: 7, total: 10, provider: "google", kind: "rate_limit" }
    const interrupted = new ApiError("removal stopped", 424, "removal stopped", { code: "removal_interrupted", params })
    expect(removalConnectionLost(interrupted)).toBe(false)
    expect(removalErrorMessage(i18n, interrupted)).toBe(
      "Removal stopped after 3 of 10 projections because Google Calendar reported a problem. Retry to continue.",
    )
  })
})

describe("rule removal presentation", () => {
  it("never reports a running removal as incomplete", () => {
    expect(detailsSource).toContain('const interrupted = detail.state === "disabled" && !active')
    expect(detailsSource).toContain('const displayState = removal ? "removing" : detail.state')
    expect(detailsSource).toContain("<RuleStatusBadge\n            state={displayState}")
    // A removal started before a reload is still running, not incomplete.
    expect(detailsSource).toContain("reportedRemoval(detail.running, detail.mapping_count) ?? sessionRemoval")
  })

  it("refreshes quickly while removing and keeps the page when the rule disappears", () => {
    expect(detailsSource).toContain(
      "sessionRemoval ? REMOVAL_REFRESH_MS : workRefreshInterval(query.state.data && [query.state.data], 60_000, commands.pending)",
    )
    expect(detailsSource).toContain("(rule.error && !sessionRemoval)")
    expect(detailsSource).toContain('const removed = missing && rule.data?.running?.kind === "removal"')
  })

  it("shares the running removal through the mutation cache and follows it with focus", () => {
    expect(detailsSource).toContain("mutationKey: removalMutationKey(detail.id)")
    expect(detailsSource).toContain("progress.current?.focus()")
    expect(detailsSource).toContain("aria-busy={active ? true : undefined}")
    expect(detailsSource).toContain("<progress")
  })

  it("navigates on completion only while the rule's details are still showing", () => {
    expect(detailsSource).toContain("if (isViewingRule(detail.id)) onRemoved(outcome)")
  })

  it("finishes a retry that finds the rule already removed without claiming no conflicts", () => {
    expect(detailsSource).toContain("error instanceof ApiError && error.status === 404")
    expect(detailsSource).toContain("finish(removalOutcomeUnknown(i18n, destinationName))")
    expect(removalOutcomeUnknown(i18n, "Family")).toEqual({
      attention: true,
      message:
        "The rule was removed. Any events left in Family because their ownership could not be verified are listed in Activity under Blocked.",
    })
  })
})
