import type { RulePolicyPayload, TentativeEvents, UnansweredInvitations } from "@/lib/api"

// Keep in sync with TentativeEventPolicy and UnansweredInvitationPolicy in domain/model.py.
export const TENTATIVE_OPTIONS: { value: TentativeEvents; label: string }[] = [
  { value: "mark", label: "Sync, marked as tentative (recommended)" },
  { value: "sync", label: "Sync like accepted events" },
  { value: "skip", label: "Don't sync" },
]

export const UNANSWERED_OPTIONS: { value: UnansweredInvitations; label: string }[] = [
  { value: "as_tentative", label: "Sync as Maybe (recommended)" },
  { value: "wait", label: "Don't sync until I answer" },
]

/** How a Maybe event's projection is titled, matching the domain's EventProjector. */
export function tentativeTitle(privacy: RulePolicyPayload["privacy_policy"]): string {
  return privacy === "busy_only" ? "“Busy (tentative)”" : "“Maybe: ” and the event title, like “Maybe: Standup”"
}

export function tentativeHint(policy: Pick<RulePolicyPayload, "privacy_policy" | "tentative_events">): string {
  if (policy.tentative_events === "mark") return `Shown as ${tentativeTitle(policy.privacy_policy)}.`
  if (policy.tentative_events === "sync") return "Shown the same as events you accepted."
  return "Events you answered Maybe stay out of the destination."
}

export const UNANSWERED_HINT = "Declined events are never synced."

const TENTATIVE_FACTS: Record<Exclude<TentativeEvents, "mark">, string> = {
  sync: "Synced like accepted events",
  skip: "Not synced",
}


export function tentativeFact(policy: Pick<RulePolicyPayload, "privacy_policy" | "tentative_events">): string {
  if (policy.tentative_events === "mark") return `Synced as ${tentativeTitle(policy.privacy_policy)}`
  return TENTATIVE_FACTS[policy.tentative_events]
}

/** Unanswered invitations treated as Maybe follow the Maybe choice, including not being synced. */
export function unansweredFact(policy: Pick<RulePolicyPayload, "tentative_events" | "unanswered_invitations">): string {
  if (policy.unanswered_invitations === "wait") return "Not synced until answered"
  return policy.tentative_events === "skip" ? "Not synced, like events you answered Maybe" : "Synced as Maybe"
}

export function unansweredHint(policy: Pick<RulePolicyPayload, "tentative_events" | "unanswered_invitations">): string {
  if (policy.unanswered_invitations === "as_tentative" && policy.tentative_events === "skip") {
    return `Treated as Maybe, so they stay out of the destination too. ${UNANSWERED_HINT}`
  }
  return UNANSWERED_HINT
}

/** Whether invitations not answered yet are projected under this policy. */
function projectsUnanswered(policy: RulePolicyPayload): boolean {
  return policy.unanswered_invitations === "as_tentative" && policy.tentative_events !== "skip"
}

/** What a policy change does to projections of Maybe events and unanswered invitations. */
export function responseConsequences(current: RulePolicyPayload, next: RulePolicyPayload, destination: string): string[] {
  const lines: string[] = []
  const was = current.tentative_events
  const now = next.tentative_events
  if (was !== now) {
    if (now === "skip") {
      lines.push(`Events you answered Maybe will be deleted from ${destination} on the next run.`)
    } else if (was === "skip") {
      lines.push(`Events you answered Maybe will be added to ${destination} on the next run.`)
    } else if (now === "mark") {
      lines.push(`Events you answered Maybe will be marked as tentative in ${destination} on the next run.`)
    } else {
      lines.push(`Events you answered Maybe will lose their tentative mark in ${destination} on the next run.`)
    }
  }
  const before = projectsUnanswered(current)
  const after = projectsUnanswered(next)
  if (before && !after) {
    lines.push(`Invitations you haven't answered will be deleted from ${destination} on the next run.`)
  }
  if (!before && after) {
    lines.push(`Invitations you haven't answered will be added to ${destination} as Maybe events on the next run.`)
  }
  return lines
}
