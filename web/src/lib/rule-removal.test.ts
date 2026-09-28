import { describe, expect, it } from "vitest"

import detailsSource from "../features/rule-details.tsx?raw"
import { ApiError } from "@/lib/api"
import { removalOutcomeUnknown, ruleStateLabel } from "@/lib/rule-change"
import {
  elapsedLabel,
  removalConnectionLost,
  removalErrorMessage,
  removalProgress,
} from "@/lib/rule-removal"

describe("rule removal progress", () => {
  it("counts handled projections without claiming conflicted ones were deleted", () => {
    expect(removalProgress({ handling: "delete", total: 312 }, 228, "Family")).toEqual({
      done: 84,
      label: "Handled 84 of 312 projections in Family",
    })
    expect(removalProgress({ handling: "delete", total: 1 }, 1, "Family").label).toBe(
      "Handled 0 of 1 projection in Family",
    )
  })

  it("clamps counts from a stale or newer mapping count", () => {
    expect(removalProgress({ handling: "delete", total: 5 }, 9, "Family").done).toBe(0)
    expect(removalProgress({ handling: "delete", total: 5 }, -1, "Family").done).toBe(5)
  })

  it("has no countable progress when keeping events or when nothing is mapped", () => {
    expect(removalProgress({ handling: "detach", total: 3 }, 3, "Family")).toEqual({
      done: null,
      label: "Keeping 3 events in Family as ordinary events…",
    })
    expect(removalProgress({ handling: "delete", total: 0 }, 0, "Family")).toEqual({
      done: null,
      label: "Removing the rule…",
    })
  })

  it("labels elapsed time", () => {
    expect(elapsedLabel(-5)).toBe("0 s")
    expect(elapsedLabel(42_900)).toBe("42 s")
    expect(elapsedLabel(125_000)).toBe("2 min 5 s")
  })

  it("labels a running removal separately from an interrupted one", () => {
    expect(ruleStateLabel("removing")).toBe("Removing")
    expect(ruleStateLabel("disabled")).toBe("Removal incomplete")
  })
})

describe("rule removal failures", () => {
  it("treats dropped connections and proxy timeouts as possibly still running", () => {
    expect(removalConnectionLost(new TypeError("Failed to fetch"))).toBe(true)
    expect(removalConnectionLost(new ApiError("The request could not be completed.", 504))).toBe(true)
    expect(removalConnectionLost(new ApiError("The request could not be completed.", 502))).toBe(true)
    expect(removalErrorMessage(new TypeError("Failed to fetch"))).toContain("may still be running")
  })

  it("shows service explanations as they are", () => {
    const interrupted = new ApiError("removal interrupted after 3 projections", 424)
    expect(removalConnectionLost(interrupted)).toBe(false)
    expect(removalErrorMessage(interrupted)).toBe("removal interrupted after 3 projections")
    const unconfigured = new ApiError("configure Google OAuth", 503)
    expect(removalErrorMessage(unconfigured)).toBe("configure Google OAuth")
  })
})

describe("rule removal presentation", () => {
  it("never reports a running removal as incomplete", () => {
    expect(detailsSource).toContain('const interrupted = detail.state === "disabled" && !active')
    expect(detailsSource).toContain('const displayState = removal ? "removing" : detail.state')
    expect(detailsSource).toContain("<RuleStatusBadge state={displayState}")
  })

  it("refreshes quickly while removing and keeps the page when the rule disappears", () => {
    expect(detailsSource).toContain("refetchInterval: removal ? REMOVAL_REFRESH_MS : 60_000")
    expect(detailsSource).toContain("(rule.error && !removal)")
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
    expect(detailsSource).toContain("finish(removalOutcomeUnknown(destinationName))")
    expect(removalOutcomeUnknown("Family")).toEqual({
      attention: true,
      message:
        "The rule was removed. Any events left in Family because their ownership could not be verified are listed in Activity under Blocked.",
    })
  })
})
