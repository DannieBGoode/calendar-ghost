import type { RuleDetail } from "@/lib/api"

/** The calendars a Rule Replacement would give its new draft rule. */
export type EndpointDraft = {
  sourceAccount: string
  sourceCalendar: string
  destinationAccount: string
  destinationCalendar: string
}

type RuleEndpoints = Pick<RuleDetail, "source" | "destination">

/** Only the administrator's edits are kept; an untouched field follows the rule as it loads. */
export function endpointDraft(rule: RuleEndpoints, edits: Partial<EndpointDraft>): EndpointDraft {
  return {
    sourceAccount: edits.sourceAccount ?? rule.source.connected_account_id,
    sourceCalendar: edits.sourceCalendar ?? rule.source.calendar_id,
    destinationAccount: edits.destinationAccount ?? rule.destination.connected_account_id,
    destinationCalendar: edits.destinationCalendar ?? rule.destination.calendar_id,
  }
}

/** A replacement needs both calendars chosen, different from each other, and at least one new. */
export function replacementReadiness(rule: RuleEndpoints, draft: EndpointDraft) {
  const unchanged =
    draft.sourceAccount === rule.source.connected_account_id &&
    draft.sourceCalendar === rule.source.calendar_id &&
    draft.destinationAccount === rule.destination.connected_account_id &&
    draft.destinationCalendar === rule.destination.calendar_id
  const sameEndpoint =
    draft.sourceAccount === draft.destinationAccount && draft.sourceCalendar === draft.destinationCalendar
  const canSubmit = !unchanged && !sameEndpoint && Boolean(draft.sourceCalendar && draft.destinationCalendar)
  return { sameEndpoint, canSubmit }
}
