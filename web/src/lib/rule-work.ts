import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"
import type { RunningWork } from "@/lib/api"
import { elapsedLabel } from "@/lib/rule-removal"
import type { RuleCommand } from "@/lib/use-rule-commands"

/** Pages refresh this often while a rule is working, so its progress and outcome appear promptly. */
export const WORK_REFRESH_MS = 2_000

export type RuleWorkKind = RunningWork["kind"]

/** What a rule is doing now, whether this page started it or the service reports it. */
export type RuleWork = {
  kind: RuleWorkKind
  /** Null only in the moment before this page learns when a removal it started began. */
  startedAt: number | null
  progress: { done: number; total: number } | null
  /** Events a sync handled while it cannot say out of how many. */
  handled?: number
  /** Reconcile now is in its opening full sync, so any count is that sync's. */
  syncing?: true
}

const COMMAND_WORK: Partial<Record<RuleCommand, RuleWorkKind>> = {
  preview: "preview",
  sync: "sync",
  reconcile: "reconciliation",
}

const WORK_COMMAND: Record<Exclude<RuleWorkKind, "removal">, RuleCommand> = {
  preview: "preview",
  sync: "sync",
  reconciliation: "reconcile",
}

/**
 * The service's report is what survives a reload and how scheduled runs show up. A command this
 * page sent names the work until the service reports it, and while it waits behind other work,
 * whose count is not its own. Reconcile now reports its full pass as its first stage.
 */
export function ruleWork({
  pending,
  pendingSince,
  running,
  removing = false,
}: {
  pending: RuleCommand | undefined
  pendingSince?: number | undefined
  running: RunningWork | null | undefined
  removing?: boolean
}): RuleWork | null {
  if (running?.kind === "removal") return removalWork(running)
  const requested = pending ? COMMAND_WORK[pending] : undefined
  if (requested) return requestedWork(requested, running, pendingSince)
  if (removing) return { kind: "removal", startedAt: null, progress: null }
  return running ? reportedWork(running) : null
}

/** A removal counts the projections it deletes; detaching them has nothing to count. */
function removalWork(running: RunningWork): RuleWork {
  const progress =
    running.handling === "delete" && running.total !== null && running.total > 0
      ? { done: running.done, total: running.total }
      : null
  return { kind: "removal", startedAt: Date.parse(running.started_at), progress }
}

function requestedWork(
  requested: RuleWorkKind,
  running: RunningWork | null | undefined,
  pendingSince: number | undefined,
): RuleWork {
  if (running?.kind === requested) return reportedWork(running)
  // Reconcile now begins with its full pass.
  const syncing = requested === "reconciliation" ? { syncing: true as const } : {}
  return { kind: requested, startedAt: pendingSince ?? null, progress: null, ...syncing }
}

function reportedWork(running: RunningWork): RuleWork {
  const work = { kind: running.kind, startedAt: Date.parse(running.started_at), ...syncProgress(running) }
  return running.stage === "sync" ? { ...work, syncing: true } : work
}

/** A sync counts the events both calendars reported once it has listed them. */
function syncProgress(running: RunningWork): Pick<RuleWork, "progress" | "handled"> {
  if (running.kind !== "sync" && running.stage !== "sync") return { progress: null }
  if (running.total !== null && running.total > 0) {
    return { progress: { done: Math.min(running.done, running.total), total: running.total } }
  }
  return running.done > 0 ? { progress: null, handled: running.done } : { progress: null }
}

/** The command a rule's buttons treat as running, so they stay unavailable until it finishes. */
export function busyCommand(pending: RuleCommand | undefined, work: RuleWork | null): RuleCommand | undefined {
  if (pending) return pending
  return work && work.kind !== "removal" ? WORK_COMMAND[work.kind] : undefined
}

const WORK_LABELS: Record<RuleWorkKind, MessageKey> = {
  preview: "ruleDetails.work.label.preview",
  sync: "ruleDetails.work.label.sync",
  reconciliation: "ruleDetails.work.label.reconciliation",
  removal: "ruleDetails.work.label.removal",
}

export function workLabel(i18n: I18n, kind: RuleWorkKind): string {
  return i18n.t(WORK_LABELS[kind])
}

/** One sentence saying what the rule is doing, in calendar language. */
export function workDescription(i18n: I18n, work: RuleWork, source: string, destination: string): string {
  switch (work.kind) {
    case "preview":
      return i18n.t("ruleDetails.work.preview", { source, destination })
    case "sync":
      return i18n.t("ruleDetails.work.sync", { source, destination })
    case "reconciliation":
      return work.syncing
        ? i18n.t("ruleDetails.work.reconciliationSyncing", { source, destination })
        : i18n.t("ruleDetails.work.reconciliation", { source, destination })
    case "removal":
      return work.progress
        ? i18n.t("ruleDetails.work.removalProgress", { done: work.progress.done, count: work.progress.total, destination })
        : i18n.t("ruleDetails.work.removal", { destination })
  }
}

/**
 * The line under the description: how far the work got, how long it has run, and that leaving is
 * safe. A removal's count is already in its description.
 */
export function workMeta(i18n: I18n, work: RuleWork, now: number): string {
  const parts: string[] = []
  if (work.kind !== "removal" && work.progress) {
    parts.push(i18n.t("ruleDetails.work.checked", { done: work.progress.done, total: work.progress.total }))
  } else if (work.kind !== "removal" && work.handled) {
    parts.push(i18n.t("ruleDetails.work.handled", { count: work.handled }))
  }
  if (work.startedAt !== null) {
    parts.push(i18n.t("ruleDetails.work.runningFor", { elapsed: elapsedLabel(i18n, now - work.startedAt) }))
  }
  parts.push(i18n.t("ruleDetails.work.keepsRunning"))
  // A visual separator between independent facts, not a word.
  return parts.join(" · ")
}

/**
 * Rules with work running refresh quickly; otherwise lists refresh at their usual pace. A command
 * this page sent counts too: the rules it last fetched predate the work, so without it the page
 * would not learn of the work's progress until its next idle refresh.
 */
export function workRefreshInterval(
  rules: { running: RunningWork | null }[] | undefined,
  idleMs: number,
  pending: Partial<Record<string, RuleCommand>> = {},
): number {
  return Object.keys(pending).length > 0 || rules?.some((rule) => rule.running) ? WORK_REFRESH_MS : idleMs
}
