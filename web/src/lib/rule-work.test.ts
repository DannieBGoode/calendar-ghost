import { describe, expect, it } from "vitest"

import { testI18n } from "@/i18n/testing"

import type { RunningWork } from "@/lib/api"
import { busyCommand, ruleWork, workDescription, workMeta, workRefreshInterval, WORK_REFRESH_MS } from "@/lib/rule-work"

const i18n = testI18n()

const started = "2026-09-29T09:00:00Z"
const running = (overrides: Partial<RunningWork>): RunningWork => ({
  kind: "sync",
  started_at: started,
  handling: null,
  total: null,
  done: 0,
  stage: null,
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

  it("names Reconcile now's full pass as its first stage before the service reports it", () => {
    expect(ruleWork({ pending: "reconcile", pendingSince: 5, running: null })).toEqual({
      kind: "reconciliation",
      startedAt: 5,
      progress: null,
      syncing: true,
    })
  })

  it("never shows the count of other work a command this page sent waits behind", () => {
    const scheduled = running({ kind: "sync", total: 40, done: 4 })
    expect(ruleWork({ pending: "reconcile", pendingSince: 5, running: scheduled })).toEqual({
      kind: "reconciliation",
      startedAt: 5,
      progress: null,
      syncing: true,
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

describe("ruleWork for a sync", () => {
  it("reports how many reported events a sync has checked, out of how many", () => {
    expect(ruleWork({ pending: undefined, running: running({ total: 840, done: 412 }) })?.progress).toEqual({
      done: 412,
      total: 840,
    })
  })

  it("never reports more checked than the total", () => {
    expect(ruleWork({ pending: undefined, running: running({ total: 10, done: 12 }) })?.progress).toEqual({
      done: 10,
      total: 10,
    })
  })

  it("counts handled events alone while the total is unknown", () => {
    const work = ruleWork({ pending: undefined, running: running({ total: null, done: 5 }) })
    expect(work?.progress).toBeNull()
    expect(work?.handled).toBe(5)
    expect(ruleWork({ pending: undefined, running: running({ total: null, done: 0 }) })?.handled).toBeUndefined()
  })

  it("keeps the progress of a sync this page started", () => {
    const syncing = running({ total: 40, done: 4 })
    expect(ruleWork({ pending: "sync", pendingSince: 5, running: syncing })?.progress).toEqual({ done: 4, total: 40 })
  })

  it("shows Reconcile now's full pass with its progress, also after a reload", () => {
    const fullPass = running({ kind: "reconciliation", stage: "sync", total: 40, done: 4 })
    for (const pending of ["reconcile", undefined] as const) {
      const work = ruleWork({ pending, pendingSince: 5, running: fullPass })
      expect(work).toEqual({
        kind: "reconciliation",
        startedAt: Date.parse(started),
        progress: { done: 4, total: 40 },
        syncing: true,
      })
      expect(workDescription(i18n, work!, "Family", "Work")).toBe(
        "Syncing every event from Family to Work, then checking each one this rule wrote.",
      )
    }
    const checking = ruleWork({ pending: undefined, running: running({ kind: "reconciliation", stage: "reconciliation" }) })
    expect(checking).toEqual({ kind: "reconciliation", startedAt: Date.parse(started), progress: null })
    expect(workDescription(i18n, checking!, "Family", "Work")).toBe(
      "Checking every event this rule wrote to Work against Family.",
    )
  })
})

describe("workMeta", () => {
  const startedAt = Date.parse(started)
  const twelveMinutes = startedAt + 12 * 60_000

  it("leads with how many events a sync checked", () => {
    expect(workMeta(i18n, { kind: "sync", startedAt, progress: { done: 412, total: 840 } }, twelveMinutes)).toBe(
      "412 of 840 checked · Running for 12 min 0 s · It keeps running if you leave this page.",
    )
    expect(workMeta(i18n, { kind: "sync", startedAt, progress: null, handled: 5 }, twelveMinutes)).toBe(
      "5 handled · Running for 12 min 0 s · It keeps running if you leave this page.",
    )
  })

  it("says only how long work runs when it has no count", () => {
    expect(workMeta(i18n, { kind: "sync", startedAt, progress: null }, twelveMinutes)).toBe(
      "Running for 12 min 0 s · It keeps running if you leave this page.",
    )
    expect(workMeta(i18n, { kind: "preview", startedAt: null, progress: null }, twelveMinutes)).toBe(
      "It keeps running if you leave this page.",
    )
  })

  it("leaves a removal's count to its description", () => {
    expect(workMeta(i18n, { kind: "removal", startedAt, progress: { done: 3, total: 10 } }, twelveMinutes)).toBe(
      "Running for 12 min 0 s · It keeps running if you leave this page.",
    )
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
    expect(workDescription(i18n, work("preview"), "Family", "Work")).toBe(
      "Reading Family to show what Work would get. Nothing is written yet.",
    )
    expect(workDescription(i18n, work("sync"), "Family", "Work")).toBe("Applying changes from Family to Work.")
    expect(
      workDescription(i18n, { kind: "removal", startedAt: null, progress: { done: 3, total: 10 } }, "Family", "Work"),
    ).toBe("Removing this rule: handled 3 of 10 projections in Work.")
  })
})

describe("workRefreshInterval", () => {
  it("refreshes quickly only while some rule is working", () => {
    expect(workRefreshInterval([{ running: null }, { running: running({}) }], 60_000)).toBe(WORK_REFRESH_MS)
    expect(workRefreshInterval([{ running: null }], 60_000)).toBe(60_000)
    expect(workRefreshInterval(undefined, 60_000)).toBe(60_000)
  })

  it("refreshes quickly while a command this page sent runs, before the service reports it", () => {
    expect(workRefreshInterval([{ running: null }], 60_000, { "rule-1": "reconcile" })).toBe(WORK_REFRESH_MS)
    expect(workRefreshInterval([{ running: null }], 60_000, {})).toBe(60_000)
  })
})
