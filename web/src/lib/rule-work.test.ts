import { describe, expect, it } from "vitest"

import type { RunningWork } from "@/lib/api"
import { busyCommand, ruleWork, workDescription, workRefreshInterval, WORK_REFRESH_MS } from "@/lib/rule-work"

const started = "2026-09-29T09:00:00Z"
const running = (overrides: Partial<RunningWork>): RunningWork => ({
  kind: "sync",
  started_at: started,
  handling: null,
  total: null,
  done: 0,
  ...overrides,
})

describe("ruleWork", () => {
  it("shows work the service reports, so a reloaded page still sees it", () => {
    expect(ruleWork({ pending: undefined, running: running({ kind: "sync" }) })).toEqual({
      kind: "sync",
      startedAt: Date.parse(started),
      progress: null,
    })
  })

  it("names a command this page sent while the service has not reported it yet", () => {
    expect(ruleWork({ pending: "preview", pendingSince: 5, running: null })).toEqual({
      kind: "preview",
      startedAt: 5,
      progress: null,
    })
  })

  it("keeps calling Reconcile now reconciling during its opening full sync", () => {
    expect(ruleWork({ pending: "reconcile", pendingSince: 5, running: running({ kind: "sync" }) })).toEqual({
      kind: "reconciliation",
      startedAt: Date.parse(started),
      progress: null,
    })
  })

  it("treats quick lifecycle commands as button states, not work", () => {
    expect(ruleWork({ pending: "enable", running: null })).toBeNull()
    expect(ruleWork({ pending: "pause", running: null })).toBeNull()
  })

  it("reports removal progress only when deleting a counted set of projections", () => {
    const deleting = running({ kind: "removal", handling: "delete", total: 40, done: 12 })
    expect(ruleWork({ pending: undefined, running: deleting })?.progress).toEqual({ done: 12, total: 40 })
    expect(ruleWork({ pending: undefined, running: { ...deleting, handling: "detach" } })?.progress).toBeNull()
    expect(ruleWork({ pending: undefined, running: { ...deleting, total: null } })?.progress).toBeNull()
    expect(ruleWork({ pending: undefined, running: null, removing: true })).toEqual({
      kind: "removal",
      startedAt: null,
      progress: null,
    })
  })
})

describe("busyCommand", () => {
  it("keeps a rule's buttons busy for work started elsewhere", () => {
    expect(busyCommand(undefined, ruleWork({ pending: undefined, running: running({ kind: "reconciliation" }) }))).toBe(
      "reconcile",
    )
    expect(busyCommand("enable", null)).toBe("enable")
    expect(busyCommand(undefined, null)).toBeUndefined()
  })
})

describe("workDescription", () => {
  it("says what each kind of work does in calendar language", () => {
    const work = (kind: RunningWork["kind"]) => ({ kind, startedAt: null, progress: null })
    expect(workDescription(work("preview"), "Family", "Work")).toBe(
      "Reading Family to show what Work would get. Nothing is written yet.",
    )
    expect(workDescription(work("sync"), "Family", "Work")).toBe("Applying changes from Family to Work.")
    expect(
      workDescription({ kind: "removal", startedAt: null, progress: { done: 3, total: 10 } }, "Family", "Work"),
    ).toBe("Removing this rule: handled 3 of 10 projections in Work.")
  })
})

describe("workRefreshInterval", () => {
  it("refreshes quickly only while some rule is working", () => {
    expect(workRefreshInterval([{ running: null }, { running: running({}) }], 60_000)).toBe(WORK_REFRESH_MS)
    expect(workRefreshInterval([{ running: null }], 60_000)).toBe(60_000)
    expect(workRefreshInterval(undefined, 60_000)).toBe(60_000)
  })
})
