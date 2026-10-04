import type { RuleNames } from "@/lib/activity"
import type { ConnectedAccount, DiscoveredCalendar, Incident, RuleSummary } from "@/lib/api"
import { accessRenewedSince, type IncidentRuleState } from "@/lib/incidents"
import { ruleEndpointLabel } from "@/lib/rule-endpoint"

/** The rules, accounts, and calendars Activity uses to name the rule behind each entry. */
export type RuleContext = {
  rulesById: Map<string, RuleSummary>
  accountsById: Map<string, ConnectedAccount>
  calendarsByAccount: Map<string, DiscoveredCalendar[] | undefined>
  rulesLoaded: boolean
}

// Until rules load, assume a rule exists rather than hide its events.
const LOADING_NAMES: RuleNames = { source: "the source calendar", destination: "the destination" }

export function ruleNames(ruleId: string, context: RuleContext): RuleNames | null {
  if (!context.rulesLoaded) return LOADING_NAMES
  const rule = context.rulesById.get(ruleId)
  if (!rule) return null
  return { source: endpointName(rule.source, context), destination: endpointName(rule.destination, context) }
}

export function endpointName(endpoint: RuleSummary["source"], context: RuleContext): string {
  return ruleEndpointLabel(
    endpoint,
    context.accountsById.get(endpoint.connected_account_id),
    context.calendarsByAccount.get(endpoint.connected_account_id),
  ).calendar
}

export function incidentRuleState(incident: Incident, context: RuleContext): IncidentRuleState | null {
  if (!incident.rule_id) return null
  // Until rules load, assume the rule exists but claim no renewed access.
  if (!context.rulesLoaded) return { accessRenewed: false }
  const rule = context.rulesById.get(incident.rule_id)
  if (!rule) return null
  const accounts = [rule.source, rule.destination].map((endpoint) => context.accountsById.get(endpoint.connected_account_id))
  return { accessRenewed: accessRenewedSince(incident, accounts) }
}
