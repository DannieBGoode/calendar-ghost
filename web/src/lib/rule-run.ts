import type { I18n } from "@/i18n/translator"
import type { MessageKey } from "@/i18n/types"
import type { ReconcileResult, RulePreview, RunOutcome, SyncResult } from "@/lib/api"
import { failureLabel, isFailureKind, type ProviderFailureKind } from "@/lib/rule-change"

/** The one-line run status a rule row shows next to its policy. */
export function lastRunLabel(i18n: I18n, outcome: RunOutcome | null, now: number = Date.now()): string {
  if (outcome === null) return i18n.t("ruleDetails.run.notSynced")
  const when = i18n.format.relative(outcome.completed_at, now)
  return outcome.succeeded
    ? i18n.t("ruleDetails.run.lastSynced", { when })
    : i18n.t("ruleDetails.run.lastSyncFailed", { when, reason: failureLabel(i18n, outcome.failure_kind) })
}

function syncedChanges(i18n: I18n, result: SyncResult): string | null {
  const changes = [
    result.created ? i18n.t("ruleDetails.run.created", { count: result.created }) : null,
    result.updated ? i18n.t("ruleDetails.run.updated", { count: result.updated }) : null,
    result.deleted ? i18n.t("ruleDetails.run.deleted", { count: result.deleted }) : null,
  ].filter((change): change is string => change !== null)
  return changes.length ? i18n.t("ruleDetails.run.synced", { changes: i18n.format.unitList(changes) }) : null
}

function withBlocked(i18n: I18n, result: string, blocked: number): string {
  return blocked ? i18n.t("ruleDetails.run.withBlocked", { result, count: blocked }) : result
}

export function syncResultMessage(i18n: I18n, result: SyncResult): string {
  return withBlocked(i18n, syncedChanges(i18n, result) ?? i18n.t("ruleDetails.run.upToDate"), result.conflicts)
}

type Drift = ReconcileResult["drift"]

const DRIFT_KINDS: Record<string, MessageKey> = {
  missing: "ruleDetails.run.drift.missing",
  incorrect_projection: "ruleDetails.run.drift.incorrectProjection",
  unexpected: "ruleDetails.run.drift.unexpected",
}

/** Each kind of difference the check found, in plain words, in the order it found them. */
function driftParts(i18n: I18n, drift: Drift, destination: string): string[] {
  const counts = new Map<string, number>()
  for (const item of drift) counts.set(item.kind, (counts.get(item.kind) ?? 0) + 1)
  return [...counts].map(([kind, count]) => {
    const key = DRIFT_KINDS[kind]
    return key ? i18n.t(key, { count, destination }) : i18n.t("ruleDetails.run.drift.unknown", { count })
  })
}

/**
 * Reconcile Now syncs first, which is where fixes happen, then checks every projection without
 * changing anything. Whatever the check still finds survived a full sync, so it is a difference
 * the sync cannot settle, or a check that is wrong, rather than a change made during the check.
 */
export function reconcileResultMessage(i18n: I18n, result: ReconcileResult, destination: string): string {
  const checked = result.checked_mappings
  const drift = result.drift
  const blocked = result.conflicts + result.reconciliation_conflicts.length
  // A blocked projection could not be verified, so only a check without blocks says all match.
  const check = drift.length
    ? [
        // Mappings are counted per series while differences include single occurrences.
        i18n.t("ruleDetails.run.checkedSeries", { count: checked, destination }),
        i18n.t("ruleDetails.run.differencesRemain", {
          count: drift.length,
          differences: i18n.format.unitList(driftParts(i18n, drift, destination)),
        }),
        i18n.t("ruleDetails.run.settleAgain", { count: drift.length }),
      ].join(" ")
    : blocked
      ? i18n.t("ruleDetails.run.checked", { count: checked, destination })
      : i18n.t("ruleDetails.run.checkedAllMatch", { count: checked, destination })
  const synced = syncedChanges(i18n, result)
  return withBlocked(i18n, synced ? `${synced} ${check}` : check, blocked)
}

/** What the latest preview found, beside the Start syncing button. The policy line names the privacy. */
export function previewReadyLabel(
  i18n: I18n,
  preview: Pick<RulePreview, "eligible_events" | "excluded_events"> & { completed_at: string } | null | undefined,
  destination: string,
  now: number = Date.now(),
): string {
  if (!preview) return i18n.t("ruleDetails.run.previewNone", { destination })
  const when = i18n.format.relative(preview.completed_at, now)
  const count = preview.eligible_events
  return preview.excluded_events > 0
    ? i18n.t("ruleDetails.run.previewedExcluded", { when, count, destination, excluded: preview.excluded_events })
    : i18n.t("ruleDetails.run.previewed", { when, count, destination })
}

export function enabledMessage(i18n: I18n, destination: string): string {
  return i18n.t("ruleDetails.run.enabled", { destination })
}

export function pausedMessage(i18n: I18n, destination: string): string {
  return i18n.t("ruleDetails.run.paused", { destination })
}

const RECOVERY_CAUSES: Record<ProviderFailureKind, MessageKey> = {
  rate_limit: "ruleDetails.run.recovery.rateLimit",
  temporary: "ruleDetails.run.recovery.temporary",
  permanent: "ruleDetails.run.recovery.permanent",
  authentication: "ruleDetails.run.recovery.authentication",
  authorization: "ruleDetails.run.recovery.authorization",
  infrastructure: "ruleDetails.run.recovery.unknown",
}

/** Why a stopped rule stopped and what restarting involves, in calendar language. */
export function recoveryExplanation(i18n: I18n, outcome: RunOutcome | null, now: number = Date.now()): string {
  const cause =
    outcome && !outcome.succeeded
      ? i18n.t(isFailureKind(outcome.failure_kind) ? RECOVERY_CAUSES[outcome.failure_kind] : "ruleDetails.run.recovery.unknown", {
          when: i18n.format.relative(outcome.completed_at, now),
        })
      : i18n.t("ruleDetails.run.recovery.noFailure")
  return `${cause} ${i18n.t("ruleDetails.run.recovery.next")}`
}
