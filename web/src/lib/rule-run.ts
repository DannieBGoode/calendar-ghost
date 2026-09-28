import type { RecentChange, RulePreview, RunOutcome, SyncResult } from "@/lib/api"
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

export function syncResultMessage(result: SyncResult): string {
  const changes = [
    result.created ? `${result.created} created` : null,
    result.updated ? `${result.updated} updated` : null,
    result.deleted ? `${result.deleted} deleted` : null,
  ].filter(Boolean)
  const base = changes.length
    ? `Synced: ${changes.join(", ")}.`
    : "Up to date. Nothing changed since the last run."
  return result.conflicts
    ? `${base} ${plural(result.conflicts, "conflict")} blocked; see Activity.`
    : base
}

export function reconcileResultMessage(result: SyncResult): string {
  const checked = plural(result.checked_mappings ?? 0, "projection")
  const drift = result.drift?.length ?? 0
  const base = drift
    ? `Checked ${checked}: ${plural(drift, "difference")} repaired from the source.`
    : `Checked ${checked}: every one matches its source event.`
  return result.conflicts
    ? `${base} ${plural(result.conflicts, "conflict")} blocked; see Activity.`
    : base
}

/** What enabling will write, restated at the moment of the first write. */
export function enableSummary({
  preview,
  source,
  destination,
  privacy,
}: {
  preview: Pick<RulePreview, "eligible_events" | "excluded_events"> | undefined
  source: string
  destination: string
  privacy: "busy_only" | "copy_details"
}): string {
  const events = preview ? plural(preview.eligible_events, "event") : "Events"
  const content =
    privacy === "busy_only"
      ? `as “Busy”. Titles, descriptions, and locations stay private.`
      : `with their titles, descriptions, and locations. Attendees, conferencing, and attachments are never copied.`
  const excluded =
    preview && preview.excluded_events > 0
      ? ` ${plural(preview.excluded_events, "event")} ${preview.excluded_events === 1 ? "is" : "are"} excluded by this rule.`
      : ""
  return `${events} from ${source} will appear in ${destination} ${content}${excluded}`
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

function listing(parts: string[]): string {
  if (parts.length <= 1) return parts.join("")
  return `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}`
}

/** One recent run in plain words, such as "Added 1 event and updated 2 in Family." */
export function recentChangeSummary(
  change: Pick<RecentChange, "created" | "updated" | "deleted" | "repaired" | "blocked">,
  destination: string,
): string {
  const parts = [
    change.created ? `added ${plural(change.created, "event")}` : null,
    change.updated ? `updated ${change.updated}` : null,
    change.deleted ? `removed ${change.deleted}` : null,
  ].filter((part): part is string => part !== null)
  const sentences = [
    parts.length ? `${listing(parts)} in ${destination}` : null,
    change.repaired ? `repaired ${plural(change.repaired, "event")} someone edited or deleted in ${destination}` : null,
    change.blocked
      ? `${plural(change.blocked, "change")} ${change.blocked === 1 ? "was" : "were"} blocked and ${change.blocked === 1 ? "needs" : "need"} a look`
      : null,
  ].filter((sentence): sentence is string => sentence !== null)
  if (!sentences.length) return `No changes in ${destination}.`
  return sentences.map((sentence) => `${sentence.charAt(0).toUpperCase()}${sentence.slice(1)}.`).join(" ")
}
