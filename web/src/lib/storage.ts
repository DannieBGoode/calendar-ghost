import { apiErrorMessage } from "@/i18n/api-errors"
import type { I18n } from "@/i18n/translator"
import type { DatabaseUsage, LogUsage } from "@/lib/api"

export function activitySummary({ t, format }: I18n, usage: DatabaseUsage): string {
  const size = format.bytes(usage.bytes)
  const reclaimable = usage.reclaimable_bytes > 0 ? format.bytes(usage.reclaimable_bytes) : null
  if (usage.activity_entries === 0 || !usage.oldest_activity_at) {
    return reclaimable
      ? t("settings.storage.summary.emptyReclaimable", { size, reclaimable })
      : t("settings.storage.summary.empty", { size })
  }
  const count = usage.activity_entries
  const day = format.shortDay(usage.oldest_activity_at)
  return reclaimable
    ? t("settings.storage.summary.entriesReclaimable", { size, count, day, reclaimable })
    : t("settings.storage.summary.entries", { size, count, day })
}

// Clearing compacts the database even when nothing is old enough, so space left by an earlier
// clear (one answered 409 while a rule was synchronizing) can still be reclaimed.
export function canClearActivity(usage: DatabaseUsage): boolean {
  return usage.activity_entries > 0 || usage.reclaimable_bytes > 0
}

export function logSummary({ t, format }: I18n, usage: LogUsage | null): string {
  if (usage === null) return t("settings.storage.logs.off")
  if (usage.files === 0 || !usage.oldest_at || !usage.newest_at) return t("settings.storage.logs.empty")
  const sameYear = usage.oldest_at.slice(0, 4) === usage.newest_at.slice(0, 4)
  return t("settings.storage.logs.range", {
    size: format.bytes(usage.bytes),
    first: format.shortDay(usage.oldest_at, !sameYear),
    last: format.shortDay(usage.newest_at),
  })
}

export type ClearActivityConfirmation = {
  body: string
  confirmLabel: string
  pendingLabel: string
  canConfirm: boolean
}

export function clearActivityConfirmation(
  { t, format }: I18n,
  entries: number,
  days: number,
  reclaimableBytes: number,
): ClearActivityConfirmation {
  const clearing = { confirmLabel: t("settings.storage.clear.action"), pendingLabel: t("settings.storage.clear.pending") }
  if (entries > 0) {
    return { ...clearing, body: t("settings.storage.clear.body", { count: entries, days }), canConfirm: true }
  }
  if (reclaimableBytes > 0) {
    return {
      body: t("settings.storage.clear.nothingOldReclaimable", { count: days, size: format.bytes(reclaimableBytes) }),
      confirmLabel: t("settings.storage.clear.reclaim"),
      pendingLabel: t("settings.storage.clear.reclaiming"),
      canConfirm: true,
    }
  }
  return { ...clearing, body: t("settings.storage.clear.nothingOld", { count: days }), canConfirm: false }
}

/** The count failed: say why, and offer to count again. */
export function countFailedConfirmation(i18n: I18n, error: unknown): ClearActivityConfirmation {
  return {
    body: i18n.t("settings.storage.clear.countFailed", { reason: apiErrorMessage(i18n, error) }),
    confirmLabel: i18n.t("settings.storage.clear.countAgain"),
    pendingLabel: i18n.t("settings.storage.clear.countingAgain"),
    canConfirm: true,
  }
}

export function clearedActivityMessage({ t }: I18n, removed: number, reclaimableBefore: number): string {
  if (removed === 0) {
    return reclaimableBefore > 0 ? t("settings.storage.clear.reclaimed") : t("settings.storage.clear.nothingCleared")
  }
  return t("settings.storage.clear.cleared", { count: removed })
}
