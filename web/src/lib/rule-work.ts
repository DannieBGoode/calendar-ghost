import type { RunningWork } from "@/lib/api"
import { plural } from "@/lib/rule-change"
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
 * page sent names the work instead while it waits, because Reconcile now begins with a full sync
 * that the service reports as syncing.
 */
export function ruleWork({
  pending,
  pendingSince,
  running,
  removing = false,
}: {
  pending: RuleCommand | undefined
  pendingSince?: number
  running: RunningWork | null | undefined
  removing?: boolean
}): RuleWork | null {
  const reportedStart = running ? Date.parse(running.started_at) : null
  if (running?.kind === "removal") {
    const progress =
      running.handling === "delete" && running.total !== null && running.total > 0
        ? { done: running.done, total: running.total }
        : null
    return { kind: "removal", startedAt: reportedStart, progress }
  }
  const requested = pending ? COMMAND_WORK[pending] : undefined
  if (requested) return { kind: requested, startedAt: reportedStart ?? pendingSince ?? null, progress: null }
  if (removing) return { kind: "removal", startedAt: null, progress: null }
  return running ? { kind: running.kind, startedAt: reportedStart, progress: null } : null
}

/** The command a rule's buttons treat as running, so they stay unavailable until it finishes. */
export function busyCommand(pending: RuleCommand | undefined, work: RuleWork | null): RuleCommand | undefined {
  if (pending) return pending
  return work && work.kind !== "removal" ? WORK_COMMAND[work.kind] : undefined
}

const WORK_LABELS: Record<RuleWorkKind, string> = {
  preview: "Previewing",
  sync: "Syncing",
  reconciliation: "Reconciling",
  removal: "Removing",
}

export function workLabel(kind: RuleWorkKind): string {
  return WORK_LABELS[kind]
}

/** One sentence saying what the rule is doing, in calendar language. */
export function workDescription(work: RuleWork, source: string, destination: string): string {
  switch (work.kind) {
    case "preview":
      return `Reading ${source} to show what ${destination} would get. Nothing is written yet.`
    case "sync":
      return `Applying changes from ${source} to ${destination}.`
    case "reconciliation":
      return `Checking every event this rule wrote to ${destination} against ${source}.`
    case "removal":
      return work.progress
        ? `Removing this rule: handled ${work.progress.done} of ${plural(work.progress.total, "projection")} in ${destination}.`
        : `Removing this rule from ${destination}.`
  }
}

/** Rules with work running refresh quickly; otherwise lists refresh at their usual pace. */
export function workRefreshInterval(rules: { running: RunningWork | null }[] | undefined, idleMs: number): number {
  return rules?.some((rule) => rule.running) ? WORK_REFRESH_MS : idleMs
}
