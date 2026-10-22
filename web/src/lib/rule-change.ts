import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"
import type { ProjectionHandling, RemovalResult, RulePolicyPayload, RuleSummary, RunOutcome } from "@/lib/api"
import { responseConsequences } from "@/lib/invitation-responses"
import { BUSY_TITLE } from "@/lib/privacy-policy"
import { providerWords } from "@/lib/providers"

export function policyChanged(current: RulePolicyPayload, next: RulePolicyPayload): boolean {
  return (
    current.privacy_policy !== next.privacy_policy ||
    current.sync_all_day_events !== next.sync_all_day_events ||
    current.tentative_events !== next.tentative_events ||
    current.unanswered_invitations !== next.unanswered_invitations ||
    current.sync_birthdays !== next.sync_birthdays
  )
}

const STATE_CONSEQUENCES: Record<string, MessageKey> = {
  enabled: "ruleDetails.change.state.enabled",
  paused: "ruleDetails.change.state.paused",
  degraded: "ruleDetails.change.state.degraded",
}

function stateConsequence(i18n: I18n, state: string): string {
  return i18n.t(STATE_CONSEQUENCES[state] ?? "ruleDetails.change.state.draft")
}

/** The kinds of event a rule includes or leaves out with one switch. */
const INCLUSIONS = [
  { field: "sync_all_day_events", removed: "ruleDetails.change.allDayRemoved", added: "ruleDetails.change.allDayAdded" },
  { field: "sync_birthdays", removed: "ruleDetails.change.birthdaysRemoved", added: "ruleDetails.change.birthdaysAdded" },
] as const satisfies { field: keyof RulePolicyPayload; removed: MessageKey; added: MessageKey }[]

function inclusionConsequences(
  i18n: I18n,
  current: RulePolicyPayload,
  next: RulePolicyPayload,
  destination: string,
): string[] {
  return INCLUSIONS.flatMap(({ field, removed, added }) =>
    current[field] === next[field] ? [] : [i18n.t(next[field] ? added : removed, { destination })],
  )
}

export function policyChangeConsequences(
  i18n: I18n,
  {
    state,
    stopCause,
    current,
    next,
    mappingCount,
    destination,
  }: {
    state: string
    stopCause?: RuleSummary["stop_cause"]
    current: RulePolicyPayload
    next: RulePolicyPayload
    mappingCount: number
    destination: string
  },
): string[] {
  const lines = [stopCause === "plan_hold" ? i18n.t("ruleDetails.change.state.held") : stateConsequence(i18n, state)]
  if (current.privacy_policy === "busy_only" && next.privacy_policy === "copy_details") {
    lines.push(
      mappingCount > 0
        ? i18n.t("ruleDetails.change.exposeExisting", { count: mappingCount, destination })
        : i18n.t("ruleDetails.change.exposeNew", { destination }),
    )
  }
  if (current.privacy_policy === "copy_details" && next.privacy_policy === "busy_only") {
    lines.push(i18n.t("ruleDetails.change.redactExisting", { count: mappingCount, destination, title: BUSY_TITLE }))
  }
  lines.push(...inclusionConsequences(i18n, current, next, destination))
  lines.push(...responseConsequences(i18n, current, next, destination))
  lines.push(i18n.t("ruleDetails.change.nothingChanges"))
  return lines
}

export function removalConsequence(
  i18n: I18n,
  handling: ProjectionHandling,
  mappingCount: number,
  destination: string,
): string {
  return handling === "delete"
    ? i18n.t("ruleDetails.projections.consequence.delete", { count: mappingCount, destination })
    : i18n.t("ruleDetails.projections.consequence.detach", { count: mappingCount, destination })
}

export type RemovalOutcome = { attention: boolean; message: string }

/** What happened to the removed rule's projections, one sentence per kind of result. */
export function removalResultSentences(i18n: I18n, result: RemovalResult, destination: string): string[] {
  const sentences: string[] = []
  if (result.deleted > 0) {
    sentences.push(i18n.t("ruleDetails.removal.outcome.deleted", { count: result.deleted, destination }))
  }
  if (result.detached > 0) {
    sentences.push(i18n.t("ruleDetails.removal.outcome.detached", { count: result.detached, destination }))
  }
  if (result.conflicts > 0) {
    sentences.push(i18n.t("ruleDetails.removal.outcome.conflicts", { count: result.conflicts, destination }))
  }
  return sentences
}

export function removalOutcome(i18n: I18n, result: RemovalResult, destination: string): RemovalOutcome {
  return {
    attention: result.conflicts > 0,
    message: [i18n.t("ruleDetails.removal.outcome.removed"), ...removalResultSentences(i18n, result, destination)].join(" "),
  }
}

/** For a removal that finished while the browser was not waiting, so its counts are unknown. */
export function removalOutcomeUnknown(i18n: I18n, destination: string): RemovalOutcome {
  return { attention: true, message: i18n.t("ruleDetails.removal.outcome.unknown", { destination }) }
}

export function removalConfirmLabel(i18n: I18n, handling: ProjectionHandling, mappingCount: number): string {
  if (mappingCount === 0) return i18n.t("ruleDetails.removal.confirm.remove")
  return handling === "delete"
    ? i18n.t("ruleDetails.removal.confirm.delete", { count: mappingCount })
    : i18n.t("ruleDetails.removal.confirm.keep", { count: mappingCount })
}

export function replacementConfirmLabel(i18n: I18n, handling: ProjectionHandling, mappingCount: number): string {
  if (mappingCount === 0) return i18n.t("ruleDetails.replacement.confirm.replace")
  return handling === "delete"
    ? i18n.t("ruleDetails.replacement.confirm.delete", { count: mappingCount })
    : i18n.t("ruleDetails.replacement.confirm.keep", { count: mappingCount })
}

const STATE_LABELS: Record<string, MessageKey> = {
  draft: "ruleDetails.state.draft",
  dry_run_validated: "ruleDetails.state.dryRunValidated",
  enabled: "ruleDetails.state.enabled",
  paused: "ruleDetails.state.paused",
  degraded: "ruleDetails.state.degraded",
  disabled: "ruleDetails.state.disabled",
  removing: "ruleDetails.state.removing",
}

/** A state this UI does not know yet shows the service's own name for it. */
export function ruleStateLabel(i18n: I18n, state: string): string {
  const key = STATE_LABELS[state]
  return key ? i18n.t(key) : state.replaceAll("_", " ")
}

const FAILURE_KINDS = ["authentication", "authorization", "rate_limit", "temporary", "permanent", "infrastructure"] as const
export type ProviderFailureKind = (typeof FAILURE_KINDS)[number]

export const isFailureKind = (kind: unknown): kind is ProviderFailureKind => FAILURE_KINDS.includes(kind as ProviderFailureKind)

const FAILURE_LABELS: Record<ProviderFailureKind, MessageKey> = {
  authentication: "ruleDetails.failure.authentication",
  authorization: "ruleDetails.failure.authorization",
  rate_limit: "ruleDetails.failure.rateLimit",
  temporary: "ruleDetails.failure.temporary",
  permanent: "ruleDetails.failure.permanent",
  infrastructure: "ruleDetails.failure.unknown",
}

/** What failed in a run, naming the provider of the calendar that failed when the server says which. */
export function failureLabel(i18n: I18n, outcome: Pick<RunOutcome, "failure_kind" | "failure_provider">): string {
  const kind = outcome.failure_kind
  return i18n.t(isFailureKind(kind) ? FAILURE_LABELS[kind] : "ruleDetails.failure.unknown", providerWords(i18n, outcome.failure_provider))
}

/** A reconciliation only reports; the sync before it made any repairs. */
function reconciliationSummary(i18n: I18n, outcome: RunOutcome): string {
  const projections = i18n.t("ruleDetails.outcome.projectionCount", { count: outcome.checked_mappings })
  const blocked = outcome.conflicts > 0 ? i18n.t("ruleDetails.outcome.conflictsBlocked", { count: outcome.conflicts }) : null
  if (outcome.drift === 0) {
    return blocked
      ? i18n.t("ruleDetails.outcome.checkedBlocked", { projections, blocked })
      : i18n.t("ruleDetails.outcome.allMatched", { count: outcome.checked_mappings })
  }
  // Projections are counted per series while differences include single occurrences, so the two
  // counts are not a ratio.
  return blocked
    ? i18n.t("ruleDetails.outcome.driftBlocked", { count: outcome.drift, projections, blocked })
    : i18n.t("ruleDetails.outcome.drift", { count: outcome.drift, projections })
}

export function runOutcomeSummary(
  i18n: I18n,
  outcome: RunOutcome | null,
  kind: "sync" | "reconciliation",
): string {
  if (outcome === null) return i18n.t("ruleDetails.outcome.notRun")
  if (!outcome.succeeded) {
    return i18n.t("ruleDetails.outcome.failed", { reason: failureLabel(i18n, outcome) })
  }
  if (kind === "reconciliation") return reconciliationSummary(i18n, outcome)
  const { created, updated, deleted, conflicts } = outcome
  return conflicts > 0
    ? i18n.t("ruleDetails.outcome.succeededWithConflicts", { created, updated, deleted, count: conflicts })
    : i18n.t("ruleDetails.outcome.succeeded", { created, updated, deleted })
}
