import type { ReconcileResult, RulePreview, RunOutcome, SyncResult } from "@/lib/api"
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

type Drift = ReconcileResult["drift"]

/** Each kind of difference the check found, in plain words, in the order it found them. */
function driftParts(drift: Drift, destination: string): string[] {
  const counts = new Map<string, number>()
  for (const item of drift) counts.set(item.kind, (counts.get(item.kind) ?? 0) + 1)
  const describe = (kind: string, count: number): string => {
    const one = count === 1
    switch (kind) {
      case "missing":
        return `${count} missing from ${destination}`
      case "incorrect_projection":
        return one ? "1 different from its source event" : `${count} different from their source events`
      case "unexpected":
        return one
          ? `1 still in ${destination} though its source event was cancelled or excluded`
          : `${count} still in ${destination} though their source events were cancelled or excluded`
      default:
        return `${count} other`
    }
  }
  return [...counts].map(([kind, count]) => describe(kind, count))
}

/**
 * Reconcile Now syncs first, which is where fixes happen, then checks every projection without
 * changing anything. Whatever the check still finds survived a full sync, so it is a difference
 * the sync cannot settle, or a check that is wrong, rather than a change made during the check.
 */
export function reconcileResultMessage(result: ReconcileResult, destination: string): string {
  const checked = `Checked ${plural(result.checked_mappings, "event")} this rule wrote to ${destination}`
  const drift = result.drift
  const blocked = result.conflicts + result.reconciliation_conflicts.length
  // A blocked projection could not be verified, so only a check without blocks says all match.
  const check = drift.length
    ? [
        // Mappings are counted per series while differences include single occurrences.
        `${checked} (a recurring series counts once).`,
        `${drift.length === 1 ? "1 difference remains" : `${drift.length} differences remain`} after the sync: ${driftParts(drift, destination).join(", ")}.`,
        `If Reconcile now finds ${drift.length === 1 ? "it" : "them"} again, Calendar Ghost can't settle ${drift.length === 1 ? "it" : "them"} on its own.`,
      ].join(" ")
    : blocked
      ? `${checked}.`
      : `${checked}: every one matches its source event.`
  const synced = syncedChanges(result)
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
      ? `${RECOVERY_CAUSES[outcome.failure_kind ?? ""] ?? "A sync could not finish"} ${relativeTime(outcome.completed_at, now)}, so Calendar Ghost stopped this rule to be safe.`
      : "Calendar Ghost stopped this rule to be safe."
  return `${cause} Nothing was lost. Preview it to check both calendars, then start syncing again.`
}

