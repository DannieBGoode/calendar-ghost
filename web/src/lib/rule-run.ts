import type { RulePreview, RunOutcome, SyncResult } from "@/lib/api"
import { failureLabel, plural } from "@/lib/rule-change"
import { relativeTime } from "@/lib/relative-time"

/** The one-line run status a rule row shows next to its policy. */
export function lastRunLabel(outcome: RunOutcome | null, now: number = Date.now()): string {
  if (outcome === null) return "Not synced yet"
  const when = relativeTime(outcome.completed_at, now)
  return outcome.succeeded
    ? `Last synced ${when}`
    : `Last sync failed ${when}: ${failureLabel(outcome.failure_kind)}`
}

function syncedChanges(result: SyncResult): string | null {
  const changes = [
    result.created ? `${result.created} created` : null,
    result.updated ? `${result.updated} updated` : null,
    result.deleted ? `${result.deleted} deleted` : null,
  ].filter(Boolean)
  return changes.length ? `Synced: ${changes.join(", ")}.` : null
}

function withBlocked(base: string, blocked: number): string {
  return blocked ? `${base} ${plural(blocked, "conflict")} blocked; see Activity.` : base
}

export function syncResultMessage(result: SyncResult): string {
  return withBlocked(
    syncedChanges(result) ?? "Up to date. Nothing changed since the last run.",
    result.conflicts,
  )
}

/**
 * Reconcile Now syncs first, which is where repairs happen, then checks every projection. The
 * check only reports: whatever still differs was left as it is.
 */
export function reconcileResultMessage(result: SyncResult): string {
  const checked = `Checked ${plural(result.checked_mappings ?? 0, "projection")}`
  const drift = result.drift?.length ?? 0
  const differ =
    drift === 1
      ? "1 still differs from its source event and was left as it is"
      : `${drift} still differ from their source events and were left as they are`
  const check = drift
    ? `${checked}: ${differ}. The next sync puts back any that changed during the check.`
    : `${checked}: every one matches its source event.`
  const synced = syncedChanges(result)
  const blocked = result.conflicts + (result.reconciliation_conflicts?.length ?? 0)
  return withBlocked(synced ? `${synced} ${check}` : check, blocked)
}

/** What the latest preview found, beside the Start syncing button. The policy line names the privacy. */
export function previewReadyLabel(
  preview: Pick<RulePreview, "eligible_events" | "excluded_events"> & { completed_at: string } | null | undefined,
  destination: string,
  now: number = Date.now(),
): string {
  if (!preview) return `Start syncing to show events in ${destination}.`
  const excluded = preview.excluded_events > 0 ? `, ${preview.excluded_events} excluded` : ""
  return `Previewed ${relativeTime(preview.completed_at, now)}: ${plural(preview.eligible_events, "event")} will appear in ${destination}${excluded}.`
}

export function enabledMessage(destination: string): string {
  return `Enabled. The first sync to ${destination} runs within five minutes, or choose Sync now.`
}

export function pausedMessage(destination: string): string {
  return `Paused. Existing events stay in ${destination}. Preview the rule again to resume.`
}

const RECOVERY_CAUSES: Record<string, string> = {
  rate_limit: "Google Calendar was limiting requests",
  temporary: "Google Calendar was temporarily unavailable",
  permanent: "Google Calendar rejected a request",
  authentication: "Google authorization expired",
  authorization: "Google calendar access was denied",
}

/** Why a stopped rule stopped and what restarting involves, in calendar language. */
export function recoveryExplanation(outcome: RunOutcome | null, now: number = Date.now()): string {
  const cause =
    outcome && !outcome.succeeded
      ? `${RECOVERY_CAUSES[outcome.failure_kind ?? ""] ?? "A sync could not finish"} ${relativeTime(outcome.completed_at, now)}, so Calendar Sync stopped this rule to be safe.`
      : "Calendar Sync stopped this rule to be safe."
  return `${cause} Nothing was lost. Preview it to check both calendars, then start syncing again.`
}

