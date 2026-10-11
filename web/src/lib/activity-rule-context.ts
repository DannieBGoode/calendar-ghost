import type { I18n } from "@/i18n/translator"
import type { RuleNames } from "@/lib/activity"
import type { ConnectedAccount, DiscoveredCalendar, RuleSummary } from "@/lib/api"
import { ruleEndpointLabel } from "@/lib/rule-endpoint"

/** The rules, accounts, and calendars Activity uses to name the rule behind each entry. */
export type RuleContext = {
  rulesById: Map<string, RuleSummary>
  accountsById: Map<string, ConnectedAccount>
  calendarsByAccount: Map<string, DiscoveredCalendar[] | undefined>
  rulesLoaded: boolean
  i18n: I18n
}

export function ruleNames(ruleId: string, context: RuleContext): RuleNames | null {
  // Until rules load, assume a rule exists rather than hide its events.
  if (!context.rulesLoaded) {
    const { t } = context.i18n
    return { source: t("activity.names.source"), destination: t("activity.names.loadingDestination") }
  }
  const rule = context.rulesById.get(ruleId)
  if (!rule) return null
  return { source: endpointName(rule.source, context), destination: endpointName(rule.destination, context) }
}

export function endpointName(endpoint: RuleSummary["source"], context: RuleContext): string {
  return ruleEndpointLabel(
    context.i18n,
    endpoint,
    context.accountsById.get(endpoint.connected_account_id),
    context.calendarsByAccount.get(endpoint.connected_account_id),
  ).calendar
}
