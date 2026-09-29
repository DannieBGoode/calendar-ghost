import type { ProjectionHandling, RemovalResult, RulePolicyPayload, RunOutcome } from "@/lib/api"

export function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralForm}`
}

export function policyChanged(current: RulePolicyPayload, next: RulePolicyPayload): boolean {
  return (
    current.privacy_policy !== next.privacy_policy ||
    current.sync_all_day_events !== next.sync_all_day_events
  )
}

function stateConsequence(state: string): string {
  if (state === "enabled") return "Synchronization pauses now. Preview the rule, then enable it again."
  if (state === "paused") return "The rule stays paused. Preview it before enabling it again."
  if (state === "degraded") {
    return "The rule stays stopped until recovery. Its recovery preview also validates the new policy."
  }
  return "The rule returns to draft. Preview it before enabling it."
}

export function policyChangeConsequences({
  state,
  current,
  next,
  mappingCount,
  destination,
}: {
  state: string
  current: RulePolicyPayload
  next: RulePolicyPayload
  mappingCount: number
  destination: string
}): string[] {
  const lines = [stateConsequence(state)]
  const existing = `${plural(mappingCount, "existing projection")} in ${destination}`
  if (current.privacy_policy === "busy_only" && next.privacy_policy === "copy_details") {
    lines.push(
      mappingCount > 0
        ? `${existing} will show event titles, descriptions, and locations after the next run, to anyone who can see ${destination}.`
        : `New projections in ${destination} will show event titles, descriptions, and locations to anyone who can see it.`,
    )
  }
  if (current.privacy_policy === "copy_details" && next.privacy_policy === "busy_only") {
    lines.push(`${existing} will be rewritten as “Busy”, removing titles, descriptions, and locations.`)
  }
  if (current.sync_all_day_events && !next.sync_all_day_events) {
    lines.push(`All-day projections in ${destination} will be deleted on the next run.`)
  }
  if (!current.sync_all_day_events && next.sync_all_day_events) {
    lines.push(`All-day source events will be added to ${destination} on the next run.`)
  }
  lines.push("Nothing changes in Google Calendar until the rule is enabled again.")
  return lines
}

export function removalConsequence(
  handling: ProjectionHandling,
  mappingCount: number,
  destination: string,
): string {
  if (handling === "delete") {
    return `${plural(mappingCount, "projection")} this rule wrote will be deleted from ${destination}. Source events are not changed. Any event whose ownership cannot be verified is left in place. This cannot be undone.`
  }
  return `${plural(mappingCount, "projection")} stay in ${destination} as ordinary events that are no longer updated or deleted. This cannot be undone.`
}

export type RemovalOutcome = { attention: boolean; message: string }

export function removalOutcome(result: RemovalResult, destination: string): RemovalOutcome {
  const parts = ["The rule was removed."]
  if (result.deleted > 0) {
    parts.push(`${plural(result.deleted, "projection")} ${result.deleted === 1 ? "was" : "were"} deleted from ${destination}.`)
  }
  if (result.detached > 0) {
    parts.push(
      `${plural(result.detached, "event")} ${result.detached === 1 ? "stays" : "stay"} in ${destination} as ${result.detached === 1 ? "a Detached Event" : "Detached Events"}.`,
    )
  }
  if (result.conflicts > 0) {
    const one = result.conflicts === 1
    parts.push(
      `${plural(result.conflicts, "event")} ${one ? "was" : "were"} left in ${destination} because ${one ? "its" : "their"} ownership could not be verified. Review ${one ? "it" : "them"} in Activity under Blocked.`,
    )
  }
  return { attention: result.conflicts > 0, message: parts.join(" ") }
}

/** For a removal that finished while the browser was not waiting, so its counts are unknown. */
export function removalOutcomeUnknown(destination: string): RemovalOutcome {
  return {
    attention: true,
    message: `The rule was removed. Any events left in ${destination} because their ownership could not be verified are listed in Activity under Blocked.`,
  }
}

export function removalConfirmLabel(handling: ProjectionHandling, mappingCount: number): string {
  if (mappingCount === 0) return "Remove rule"
  return handling === "delete"
    ? `Remove rule and delete ${plural(mappingCount, "projection")}`
    : `Remove rule and keep ${plural(mappingCount, "event")}`
}

export function replacementConfirmLabel(handling: ProjectionHandling, mappingCount: number): string {
  if (mappingCount === 0) return "Replace rule"
  return handling === "delete"
    ? `Replace rule and delete ${plural(mappingCount, "projection")}`
    : `Replace rule and keep ${plural(mappingCount, "event")}`
}

const STATE_LABELS: Record<string, string> = {
  draft: "Draft",
  dry_run_validated: "Preview passed",
  enabled: "Enabled",
  paused: "Paused",
  degraded: "Stopped",
  disabled: "Removal incomplete",
  removing: "Removing",
}

export function ruleStateLabel(state: string): string {
  return STATE_LABELS[state] ?? state.replaceAll("_", " ")
}

const FAILURE_LABELS: Record<string, string> = {
  authentication: "Google authorization expired",
  authorization: "Google calendar access was denied",
  rate_limit: "Google Calendar was limiting requests",
  temporary: "Google Calendar was temporarily unavailable",
  permanent: "Google Calendar rejected the request",
}

export function failureLabel(failureKind: string | null): string {
  return FAILURE_LABELS[failureKind ?? ""] ?? "Local synchronization failed"
}

/** A reconciliation only reports; the sync before it made any repairs. */
function reconciliationSummary(outcome: RunOutcome): string {
  const checked = plural(outcome.checked_mappings, "projection")
  const blocked = outcome.conflicts > 0 ? `${plural(outcome.conflicts, "conflict")} blocked` : null
  if (outcome.drift === 0) {
    return blocked ? `Checked ${checked}: ${blocked}` : `All ${checked} matched their sources`
  }
  const differed =
    outcome.drift === 1
      ? `1 of ${checked} differed from its source; it was not changed`
      : `${outcome.drift} of ${checked} differed from their sources; none were changed`
  return blocked ? `${differed}. ${blocked}` : differed
}

export function runOutcomeSummary(
  outcome: RunOutcome | null,
  kind: "sync" | "reconciliation",
): string {
  if (outcome === null) return "Not run yet"
  if (!outcome.succeeded) {
    return `Failed: ${failureLabel(outcome.failure_kind)}`
  }
  if (kind === "reconciliation") return reconciliationSummary(outcome)
  const counts = `${outcome.created} created, ${outcome.updated} updated, ${outcome.deleted} deleted`
  return outcome.conflicts > 0
    ? `Succeeded: ${counts}, ${plural(outcome.conflicts, "conflict")}`
    : `Succeeded: ${counts}`
}
