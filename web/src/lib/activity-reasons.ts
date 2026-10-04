/**
 * What Calendar Ghost observed (`trigger`) and what it did about it (`effect`), never who caused
 * it. `{source}` and `{destination}` name the rule's calendars. A block says what to do next.
 */
export type ReasonCopy = { trigger?: string; effect: string; explanation: string; next?: string }

/** Blocks nobody can clear by hand: the daily check decides the event again and escalates. */
const RECHECKED =
  "Nothing to do now. Calendar Ghost decides this event again at the daily check, and opens an incident if it is still blocked then."

// Keep in sync with SyncReason in src/calendar_sync/domain/model.py.
export const REASONS: Record<string, ReasonCopy> = {
  source_created: {
    trigger: "New in {source}",
    effect: "added to {destination}",
    explanation: "The event was new to Calendar Ghost, so it was added to {destination}.",
  },
  projection_missing: {
    trigger: "Missing from {destination}",
    effect: "put back",
    explanation:
      "The event Calendar Ghost wrote to {destination} was no longer there, so it was written again from {source}.",
  },
  source_changed: {
    trigger: "Changed in {source}",
    effect: "updated in {destination}",
    explanation: "The event changed in {source}, so {destination} was updated to match.",
  },
  destination_drift_repaired: {
    trigger: "Edited in {destination}",
    effect: "changed back to match {source}",
    explanation:
      "The event in {destination} no longer matched {source}. {source} decides what the event looks like, so the edit was replaced.",
  },
  source_cancelled: {
    trigger: "Cancelled in {source}",
    effect: "removed from {destination}",
    explanation: "The event was cancelled or deleted in {source}, so it was removed from {destination}.",
  },
  all_day_excluded_removed: {
    trigger: "All-day, which this rule leaves out",
    effect: "removed from {destination}",
    explanation: "This rule syncs timed events only, so the all-day event it had written was removed.",
  },
  declined_removed: {
    trigger: "Declined",
    effect: "removed from {destination}",
    explanation: "You declined this event in {source}, so the event Calendar Ghost had written was removed. Declined events are never synced.",
  },
  tentative_excluded_removed: {
    trigger: "Answered Maybe, which this rule leaves out",
    effect: "removed from {destination}",
    explanation: "This rule doesn't sync events you answered Maybe to, so the event it had written was removed.",
  },
  awaiting_response_removed: {
    trigger: "Not answered yet",
    effect: "removed from {destination}",
    explanation:
      "This rule waits for you to answer an invitation before syncing it, so the event it had written was removed. It is added again once you accept, or answer Maybe if this rule syncs those.",
  },
  policy_applied: {
    trigger: "Rule settings changed",
    effect: "rewritten in {destination}",
    explanation: "The rule's settings changed, so the event it had written was rewritten to match them.",
  },
  projection_current: {
    effect: "already up to date",
    explanation: "The event in {destination} already matches {source}.",
  },
  outside_source_calendar: {
    trigger: "From another calendar",
    effect: "skipped",
    explanation: "The event does not belong to {source}.",
  },
  managed_projection_source: {
    trigger: "Written by Calendar Ghost",
    effect: "skipped",
    explanation:
      "Events Calendar Ghost wrote are never synced again. This prevents events from looping between calendars.",
  },
  recurring_unsupported: {
    trigger: "Recurring event",
    effect: "skipped",
    explanation: "Earlier versions did not sync recurring events. Nothing was written.",
  },
  cancelled_without_projection: {
    trigger: "Cancelled in {source}",
    effect: "nothing to remove",
    explanation: "The event was cancelled before it was ever added to {destination}.",
  },
  all_day_excluded: {
    trigger: "All-day event",
    effect: "skipped",
    explanation: "This rule syncs timed events only. Edit the rule to include all-day events.",
  },
  declined: {
    trigger: "Declined",
    effect: "skipped",
    explanation: "You declined this event in {source}. Declined events are never synced.",
  },
  tentative_excluded: {
    trigger: "Answered Maybe",
    effect: "skipped",
    explanation: "This rule doesn't sync events you answered Maybe to. Edit the rule to sync them.",
  },
  awaiting_response: {
    trigger: "Not answered yet",
    effect: "skipped",
    explanation:
      "This rule waits for you to answer an invitation before syncing it. It is synced once you accept, or answer Maybe if this rule syncs those.",
  },
  before_sync_window: {
    trigger: "Ended before the sync window",
    effect: "skipped",
    explanation:
      "The event changed, but it ended before this rule's sync window and was never synced, so it was not added.",
  },
  mapping_inconsistent: {
    trigger: "Calendar Ghost's link to this event doesn't match",
    effect: "blocked, {destination} left unchanged",
    explanation:
      "Calendar Ghost keeps a record of which event in {destination} belongs to which event in {source}. For this event the record points somewhere unexpected, so nothing was written rather than risk changing the wrong event.",
    next: RECHECKED,
  },
  destination_identity_inconsistent: {
    trigger: "A different event is linked in {destination}",
    effect: "blocked, {destination} left unchanged",
    explanation:
      "The event in {destination} is no longer the one Calendar Ghost wrote for this event, so nothing was written rather than risk changing the wrong event.",
    next: RECHECKED,
  },
  destination_ownership_inconsistent: {
    trigger: "Not marked as written by this rule in {destination}",
    effect: "blocked, left alone",
    explanation:
      "The event in {destination} does not carry this rule's marker, so Calendar Ghost will not change or delete it.",
    next: RECHECKED,
  },
  source_unverifiable: {
    trigger: "Couldn't be read in {source}",
    effect: "blocked, {destination} left unchanged",
    explanation:
      "Its source event in {source} could not be read, so the event in {destination} was left as it is rather than risk deleting it.",
    next: "If this repeats, check in Settings that the Google account for {source} is still connected.",
  },
  occurrence_changed: {
    trigger: "Changed in {source}",
    effect: "updated in {destination}",
    explanation:
      "This occurrence was moved or edited in {source}, so it was updated in {destination}. The rest of the series is unchanged.",
  },
  occurrence_cancelled: {
    trigger: "Cancelled in {source}",
    effect: "removed from {destination}",
    explanation:
      "This occurrence was cancelled in {source}, so it was removed from {destination}. The rest of the series is unchanged.",
  },
  occurrence_removed_from_series: {
    trigger: "No longer in the series in {source}",
    effect: "removed from {destination}",
    explanation: "The series in {source} no longer includes this occurrence, so it was removed from {destination}.",
  },
  occurrence_drift_repaired: {
    trigger: "Edited or deleted in {destination}",
    effect: "put back to match {source}",
    explanation:
      "This occurrence in {destination} no longer matched {source}. {source} decides what the event looks like, so it was restored.",
  },
  occurrence_current: {
    effect: "already up to date",
    explanation: "This occurrence in {destination} already matches {source}.",
  },
  occurrence_already_cancelled: {
    effect: "already up to date",
    explanation: "This occurrence is cancelled in both calendars.",
  },
  occurrence_retired: {
    trigger: "Gone from both calendars",
    effect: "cleaned up",
    explanation: "The occurrence no longer exists in either calendar, so its record was removed. Nothing was written.",
  },
  series_not_synchronized: {
    trigger: "Its series isn't synced",
    effect: "skipped",
    explanation: "This occurrence belongs to a recurring event this rule does not sync.",
  },
  destination_occurrence_missing: {
    trigger: "Not found in the series in {destination}",
    effect: "blocked, {destination} left unchanged",
    explanation:
      "The series in {destination} has no occurrence at this time, even after Calendar Ghost checked the series itself. Nothing was written, so this occurrence may be missing or out of date in {destination}. The rest of the series is unaffected.",
    next: RECHECKED,
  },
  series_without_occurrences: {
    trigger: "Every occurrence cancelled in {source}",
    effect: "skipped",
    explanation:
      "Every occurrence of this recurring event is cancelled in {source}, or is an all-day occurrence this rule leaves out, so there is nothing to show in {destination}. It is synced again if an occurrence comes back.",
  },
  series_without_occurrences_removed: {
    trigger: "No occurrence left in {source}",
    effect: "removed from {destination}",
    explanation:
      "Every occurrence of this recurring event is cancelled in {source}, or is an all-day occurrence this rule leaves out, so the series left from an interrupted run was removed.",
  },
  projection_unmapped: {
    trigger: "Marked as written by this rule in {destination}, but not linked to an event in {source}",
    effect: "blocked, left in {destination}",
    explanation:
      "The event in {destination} carries this rule's marker, but Calendar Ghost has no record of writing it, so it will not change or delete it. Reconcile now reports it again while it is there.",
    next: "If you don't want it in {destination}, delete it there yourself.",
  },
}

export const ACTION_FALLBACK: Record<string, string> = {
  create: "added to {destination}",
  update: "updated in {destination}",
  delete: "removed from {destination}",
  ignore: "skipped",
  conflict: "blocked",
}

// Rule management entries carry no SyncReason; keep in sync with application/rules.py and removal.py.
export const RULE_ACTIONS: Record<string, ReasonCopy> = {
  policy_changed: {
    effect: "rule settings changed",
    explanation:
      "The rule needs a new preview, and the events it wrote are rewritten on the next run after it is enabled.",
  },
  remove_projection: {
    trigger: "Rule removed",
    effect: "removed from {destination}",
    explanation: "The administrator chose to delete the events this rule wrote when removing it.",
  },
  detach_projection: {
    trigger: "Rule removed",
    effect: "kept in {destination}, no longer synced",
    explanation: "The event stays in {destination} and is no longer updated or deleted.",
  },
  removal_conflict: {
    trigger: "Not verifiably written by this rule",
    effect: "left in {destination} during Rule Removal",
    explanation:
      "The event's ownership could not be verified, so it was not deleted. It stays in {destination} and is no longer managed.",
  },
  rule_removed: {
    effect: "rule removed",
    explanation: "The rule and its records of which events it wrote were removed. Its activity history is kept.",
  },
}
