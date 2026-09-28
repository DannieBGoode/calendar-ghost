import type { ProjectionHandling, RulePolicyPayload, RunOutcome } from "@/lib/api"

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
        ? `${existing} will show event titles, descriptions, and locations after the next run.`
        : `New projections in ${destination} will show event titles, descriptions, and locations.`,
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
    return `${plural(mappingCount, "Managed Projection")} will be deleted from ${destination}. Source events are not changed. This cannot be undone.`
  }
  return `${plural(mappingCount, "projection")} stay in ${destination} as ordinary events that are no longer updated or deleted. This cannot be undone.`
}

export function removalConfirmLabel(handling: ProjectionHandling, mappingCount: number): string {
  if (mappingCount === 0) return "Remove rule"
  return handling === "delete"
    ? `Remove rule and delete ${plural(mappingCount, "projection")}`
    : `Remove rule and keep ${plural(mappingCount, "event")}`
}

const STATE_LABELS: Record<string, string> = {
  draft: "Draft",
  dry_run_validated: "Preview passed",
  enabled: "Enabled",
  paused: "Paused",
  degraded: "Stopped",
  disabled: "Removal incomplete",
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

export function runOutcomeSummary(
  outcome: RunOutcome | null,
  kind: "sync" | "reconciliation",
): string {
  if (outcome === null) return "Not run yet"
  if (!outcome.succeeded) {
    return `Failed: ${FAILURE_LABELS[outcome.failure_kind ?? ""] ?? "Local synchronization failed"}`
  }
  if (kind === "reconciliation") {
    return outcome.drift === 0
      ? `Consistent: ${plural(outcome.checked_mappings, "mapping")} checked`
      : `${plural(outcome.drift, "difference")} found in ${plural(outcome.checked_mappings, "mapping")}`
  }
  const counts = `${outcome.created} created, ${outcome.updated} updated, ${outcome.deleted} deleted`
  return outcome.conflicts > 0
    ? `Succeeded: ${counts}, ${plural(outcome.conflicts, "conflict")}`
    : `Succeeded: ${counts}`
}
