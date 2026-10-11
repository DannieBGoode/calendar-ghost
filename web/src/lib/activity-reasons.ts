import type { MessageKey } from "@/i18n/types"

/**
 * What Calendar Ghost observed (`trigger`) and what it did about it (`effect`), never who caused
 * it. Messages name the rule's calendars with `{source}` and `{destination}`. A block says what
 * to do next.
 */
export type ReasonCopy = { trigger?: string; effect: string; explanation: string; next?: string }
/** The catalog messages for one reason's copy. */
export type CopyKeys = { trigger?: MessageKey; effect: MessageKey; explanation: MessageKey; next?: MessageKey }

/** Blocks nobody can clear by hand: the daily check decides the event again and escalates. */
const RECHECKED: MessageKey = "activity.reason.recheck"

// Keep in sync with SyncReason in src/calendar_sync/domain/model.py.
export const REASONS: Record<string, CopyKeys> = {
  source_created: {
    trigger: "activity.reason.sourceCreated.trigger",
    effect: "activity.reason.sourceCreated.effect",
    explanation: "activity.reason.sourceCreated.explanation",
  },
  projection_missing: {
    trigger: "activity.reason.projectionMissing.trigger",
    effect: "activity.reason.projectionMissing.effect",
    explanation: "activity.reason.projectionMissing.explanation",
  },
  source_changed: {
    trigger: "activity.reason.sourceChanged.trigger",
    effect: "activity.reason.sourceChanged.effect",
    explanation: "activity.reason.sourceChanged.explanation",
  },
  destination_drift_repaired: {
    trigger: "activity.reason.destinationDriftRepaired.trigger",
    effect: "activity.reason.destinationDriftRepaired.effect",
    explanation: "activity.reason.destinationDriftRepaired.explanation",
  },
  source_cancelled: {
    trigger: "activity.reason.sourceCancelled.trigger",
    effect: "activity.reason.sourceCancelled.effect",
    explanation: "activity.reason.sourceCancelled.explanation",
  },
  all_day_excluded_removed: {
    trigger: "activity.reason.allDayExcludedRemoved.trigger",
    effect: "activity.reason.allDayExcludedRemoved.effect",
    explanation: "activity.reason.allDayExcludedRemoved.explanation",
  },
  declined_removed: {
    trigger: "activity.reason.declinedRemoved.trigger",
    effect: "activity.reason.declinedRemoved.effect",
    explanation: "activity.reason.declinedRemoved.explanation",
  },
  tentative_excluded_removed: {
    trigger: "activity.reason.tentativeExcludedRemoved.trigger",
    effect: "activity.reason.tentativeExcludedRemoved.effect",
    explanation: "activity.reason.tentativeExcludedRemoved.explanation",
  },
  awaiting_response_removed: {
    trigger: "activity.reason.awaitingResponseRemoved.trigger",
    effect: "activity.reason.awaitingResponseRemoved.effect",
    explanation: "activity.reason.awaitingResponseRemoved.explanation",
  },
  policy_applied: {
    trigger: "activity.reason.policyApplied.trigger",
    effect: "activity.reason.policyApplied.effect",
    explanation: "activity.reason.policyApplied.explanation",
  },
  projection_current: {
    effect: "activity.reason.projectionCurrent.effect",
    explanation: "activity.reason.projectionCurrent.explanation",
  },
  outside_source_calendar: {
    trigger: "activity.reason.outsideSourceCalendar.trigger",
    effect: "activity.reason.outsideSourceCalendar.effect",
    explanation: "activity.reason.outsideSourceCalendar.explanation",
  },
  managed_projection_source: {
    trigger: "activity.reason.managedProjectionSource.trigger",
    effect: "activity.reason.managedProjectionSource.effect",
    explanation: "activity.reason.managedProjectionSource.explanation",
  },
  recurring_unsupported: {
    trigger: "activity.reason.recurringUnsupported.trigger",
    effect: "activity.reason.recurringUnsupported.effect",
    explanation: "activity.reason.recurringUnsupported.explanation",
  },
  cancelled_without_projection: {
    trigger: "activity.reason.cancelledWithoutProjection.trigger",
    effect: "activity.reason.cancelledWithoutProjection.effect",
    explanation: "activity.reason.cancelledWithoutProjection.explanation",
  },
  all_day_excluded: {
    trigger: "activity.reason.allDayExcluded.trigger",
    effect: "activity.reason.allDayExcluded.effect",
    explanation: "activity.reason.allDayExcluded.explanation",
  },
  declined: {
    trigger: "activity.reason.declined.trigger",
    effect: "activity.reason.declined.effect",
    explanation: "activity.reason.declined.explanation",
  },
  tentative_excluded: {
    trigger: "activity.reason.tentativeExcluded.trigger",
    effect: "activity.reason.tentativeExcluded.effect",
    explanation: "activity.reason.tentativeExcluded.explanation",
  },
  awaiting_response: {
    trigger: "activity.reason.awaitingResponse.trigger",
    effect: "activity.reason.awaitingResponse.effect",
    explanation: "activity.reason.awaitingResponse.explanation",
  },
  before_sync_window: {
    trigger: "activity.reason.beforeSyncWindow.trigger",
    effect: "activity.reason.beforeSyncWindow.effect",
    explanation: "activity.reason.beforeSyncWindow.explanation",
  },
  mapping_inconsistent: {
    trigger: "activity.reason.mappingInconsistent.trigger",
    effect: "activity.reason.mappingInconsistent.effect",
    explanation: "activity.reason.mappingInconsistent.explanation",
    next: RECHECKED,
  },
  destination_identity_inconsistent: {
    trigger: "activity.reason.destinationIdentityInconsistent.trigger",
    effect: "activity.reason.destinationIdentityInconsistent.effect",
    explanation: "activity.reason.destinationIdentityInconsistent.explanation",
    next: RECHECKED,
  },
  destination_ownership_inconsistent: {
    trigger: "activity.reason.destinationOwnershipInconsistent.trigger",
    effect: "activity.reason.destinationOwnershipInconsistent.effect",
    explanation: "activity.reason.destinationOwnershipInconsistent.explanation",
    next: RECHECKED,
  },
  source_unverifiable: {
    trigger: "activity.reason.sourceUnverifiable.trigger",
    effect: "activity.reason.sourceUnverifiable.effect",
    explanation: "activity.reason.sourceUnverifiable.explanation",
    next: "activity.reason.sourceUnverifiable.next",
  },
  occurrence_changed: {
    trigger: "activity.reason.occurrenceChanged.trigger",
    effect: "activity.reason.occurrenceChanged.effect",
    explanation: "activity.reason.occurrenceChanged.explanation",
  },
  occurrence_cancelled: {
    trigger: "activity.reason.occurrenceCancelled.trigger",
    effect: "activity.reason.occurrenceCancelled.effect",
    explanation: "activity.reason.occurrenceCancelled.explanation",
  },
  occurrence_removed_from_series: {
    trigger: "activity.reason.occurrenceRemovedFromSeries.trigger",
    effect: "activity.reason.occurrenceRemovedFromSeries.effect",
    explanation: "activity.reason.occurrenceRemovedFromSeries.explanation",
  },
  occurrence_drift_repaired: {
    trigger: "activity.reason.occurrenceDriftRepaired.trigger",
    effect: "activity.reason.occurrenceDriftRepaired.effect",
    explanation: "activity.reason.occurrenceDriftRepaired.explanation",
  },
  occurrence_current: {
    effect: "activity.reason.occurrenceCurrent.effect",
    explanation: "activity.reason.occurrenceCurrent.explanation",
  },
  occurrence_already_cancelled: {
    effect: "activity.reason.occurrenceAlreadyCancelled.effect",
    explanation: "activity.reason.occurrenceAlreadyCancelled.explanation",
  },
  occurrence_retired: {
    trigger: "activity.reason.occurrenceRetired.trigger",
    effect: "activity.reason.occurrenceRetired.effect",
    explanation: "activity.reason.occurrenceRetired.explanation",
  },
  series_not_synchronized: {
    trigger: "activity.reason.seriesNotSynchronized.trigger",
    effect: "activity.reason.seriesNotSynchronized.effect",
    explanation: "activity.reason.seriesNotSynchronized.explanation",
  },
  destination_occurrence_missing: {
    trigger: "activity.reason.destinationOccurrenceMissing.trigger",
    effect: "activity.reason.destinationOccurrenceMissing.effect",
    explanation: "activity.reason.destinationOccurrenceMissing.explanation",
    next: RECHECKED,
  },
  series_without_occurrences: {
    trigger: "activity.reason.seriesWithoutOccurrences.trigger",
    effect: "activity.reason.seriesWithoutOccurrences.effect",
    explanation: "activity.reason.seriesWithoutOccurrences.explanation",
  },
  series_without_occurrences_removed: {
    trigger: "activity.reason.seriesWithoutOccurrencesRemoved.trigger",
    effect: "activity.reason.seriesWithoutOccurrencesRemoved.effect",
    explanation: "activity.reason.seriesWithoutOccurrencesRemoved.explanation",
  },
  projection_unmapped: {
    trigger: "activity.reason.projectionUnmapped.trigger",
    effect: "activity.reason.projectionUnmapped.effect",
    explanation: "activity.reason.projectionUnmapped.explanation",
    next: "activity.reason.projectionUnmapped.next",
  },
  projection_unsupported: {
    trigger: "activity.reason.projectionUnsupported.trigger",
    effect: "activity.reason.projectionUnsupported.effect",
    explanation: "activity.reason.projectionUnsupported.explanation",
    next: "activity.reason.projectionUnsupported.next",
  },
}

export const ACTION_FALLBACK: Record<string, MessageKey> = {
  create: "activity.action.create",
  update: "activity.action.update",
  delete: "activity.action.delete",
  ignore: "activity.action.ignore",
  conflict: "activity.action.conflict",
}

// Rule management entries carry no SyncReason; keep in sync with application/rules.py and removal.py.
export const RULE_ACTIONS: Record<string, CopyKeys> = {
  policy_changed: {
    effect: "activity.ruleAction.policyChanged.effect",
    explanation: "activity.ruleAction.policyChanged.explanation",
  },
  remove_projection: {
    trigger: "activity.ruleAction.removeProjection.trigger",
    effect: "activity.ruleAction.removeProjection.effect",
    explanation: "activity.ruleAction.removeProjection.explanation",
  },
  detach_projection: {
    trigger: "activity.ruleAction.detachProjection.trigger",
    effect: "activity.ruleAction.detachProjection.effect",
    explanation: "activity.ruleAction.detachProjection.explanation",
  },
  removal_conflict: {
    trigger: "activity.ruleAction.removalConflict.trigger",
    effect: "activity.ruleAction.removalConflict.effect",
    explanation: "activity.ruleAction.removalConflict.explanation",
  },
  rule_removed: {
    effect: "activity.ruleAction.ruleRemoved.effect",
    explanation: "activity.ruleAction.ruleRemoved.explanation",
  },
}
