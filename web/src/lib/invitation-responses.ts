import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"
import type { RulePolicyPayload, TentativeEvents, UnansweredInvitations } from "@/lib/api"

// Keep in sync with TentativeEventPolicy and UnansweredInvitationPolicy in domain/model.py.
export const TENTATIVE_OPTIONS: { value: TentativeEvents; labelKey: MessageKey }[] = [
  { value: "mark", labelKey: "rules.invitations.tentative.mark" },
  { value: "sync", labelKey: "rules.invitations.tentative.sync" },
  { value: "skip", labelKey: "rules.invitations.tentative.skip" },
]

export const UNANSWERED_OPTIONS: { value: UnansweredInvitations; labelKey: MessageKey }[] = [
  { value: "as_tentative", labelKey: "rules.invitations.unanswered.asTentative" },
  { value: "wait", labelKey: "rules.invitations.unanswered.wait" },
]

// The literal English text domain/services.py's _tentative_title writes into Google Calendar
// (busy_title defaults to "Busy" and is not configurable from this UI). Translators must not
// rewrite these: they describe what the destination event will actually say, so they are message
// parameters, not translatable text.
const BUSY_TENTATIVE_TITLE = "Busy (tentative)"
const MAYBE_PREFIX = "Maybe: "

/** How a Maybe event's projection is titled, matching the domain's EventProjector. */
export function tentativeTitle(i18n: I18n, privacy: RulePolicyPayload["privacy_policy"]): string {
  if (privacy === "busy_only") {
    return i18n.t("rules.invitations.tentativeTitle.busyOnly", { title: BUSY_TENTATIVE_TITLE })
  }
  return i18n.t("rules.invitations.tentativeTitle.copyDetails", {
    prefix: MAYBE_PREFIX,
    example: `${MAYBE_PREFIX}${i18n.t("rules.invitations.tentativeTitle.exampleTitle")}`,
  })
}

export function tentativeHint(i18n: I18n, policy: Pick<RulePolicyPayload, "privacy_policy" | "tentative_events">): string {
  if (policy.tentative_events === "mark") {
    return i18n.t("rules.invitations.tentativeHint.marked", { title: tentativeTitle(i18n, policy.privacy_policy) })
  }
  if (policy.tentative_events === "sync") return i18n.t("rules.invitations.tentativeHint.sync")
  return i18n.t("rules.invitations.tentativeHint.skip")
}

export function unansweredHint(
  i18n: I18n,
  policy: Pick<RulePolicyPayload, "tentative_events" | "unanswered_invitations">,
): string {
  if (policy.unanswered_invitations === "as_tentative" && policy.tentative_events === "skip") {
    return i18n.t("rules.invitations.unansweredHint.treatedAsMaybe")
  }
  return i18n.t("rules.invitations.unansweredHint.base")
}

const TENTATIVE_FACT_KEYS: Record<Exclude<TentativeEvents, "mark">, MessageKey> = {
  sync: "rules.invitations.tentativeFact.sync",
  skip: "rules.invitations.tentativeFact.skip",
}

export function tentativeFact(i18n: I18n, policy: Pick<RulePolicyPayload, "privacy_policy" | "tentative_events">): string {
  if (policy.tentative_events === "mark") {
    return i18n.t("rules.invitations.tentativeFact.marked", { title: tentativeTitle(i18n, policy.privacy_policy) })
  }
  return i18n.t(TENTATIVE_FACT_KEYS[policy.tentative_events])
}

/** Unanswered invitations treated as Maybe follow the Maybe choice, including not being synced. */
export function unansweredFact(
  i18n: I18n,
  policy: Pick<RulePolicyPayload, "tentative_events" | "unanswered_invitations">,
): string {
  if (policy.unanswered_invitations === "wait") return i18n.t("rules.invitations.unansweredFact.wait")
  return policy.tentative_events === "skip"
    ? i18n.t("rules.invitations.unansweredFact.skipLikeMaybe")
    : i18n.t("rules.invitations.unansweredFact.asMaybe")
}

/** Whether invitations not answered yet are projected under this policy. */
function projectsUnanswered(policy: RulePolicyPayload): boolean {
  return policy.unanswered_invitations === "as_tentative" && policy.tentative_events !== "skip"
}

/** What a policy change does to projections of Maybe events and unanswered invitations. */
export function responseConsequences(
  i18n: I18n,
  current: RulePolicyPayload,
  next: RulePolicyPayload,
  destination: string,
): string[] {
  const lines: string[] = []
  const was = current.tentative_events
  const now = next.tentative_events
  if (was !== now) {
    if (now === "skip") {
      lines.push(i18n.t("rules.invitations.consequence.maybeDeleted", { destination }))
    } else if (was === "skip") {
      lines.push(i18n.t("rules.invitations.consequence.maybeAdded", { destination }))
    } else if (now === "mark") {
      lines.push(i18n.t("rules.invitations.consequence.maybeMarked", { destination }))
    } else {
      lines.push(i18n.t("rules.invitations.consequence.maybeUnmarked", { destination }))
    }
  }
  const before = projectsUnanswered(current)
  const after = projectsUnanswered(next)
  if (before && !after) {
    lines.push(i18n.t("rules.invitations.consequence.unansweredDeleted", { destination }))
  }
  if (!before && after) {
    lines.push(i18n.t("rules.invitations.consequence.unansweredAdded", { destination }))
  }
  return lines
}
