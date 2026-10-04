import { ArrowRight } from "lucide-react"

import { HappenedLine } from "@/components/activity-event"
import { RuleEndpoint } from "@/components/rule-endpoint"
import { useI18n } from "@/i18n/provider"
import { whatHappened, type RuleNames } from "@/lib/activity"
import type { RuleContext } from "@/lib/activity-rule-context"
import type { AuditEntry } from "@/lib/api"

/** Labels the Activity table, its entry details, and its incidents share. */
export function HappenedLabel({ entry, names }: { entry: AuditEntry; names: RuleNames | null }) {
  const i18n = useI18n()
  return <HappenedLine happened={whatHappened(i18n, entry, names)} />
}

export function RuleDirection({ ruleId, context }: { ruleId: string; context: RuleContext }) {
  const { t } = context.i18n
  const rule = context.rulesById.get(ruleId)
  if (!rule) return <span className="activity-removed-rule">{t("activity.removedRule")}</span>
  return (
    <span className="rule-direction activity-direction">
      <RuleEndpoint
        account={context.accountsById.get(rule.source.connected_account_id)}
        endpoint={rule.source}
        calendars={context.calendarsByAccount.get(rule.source.connected_account_id)}
        role="Source"
      />
      {/* Each endpoint names its role to screen readers, as in the rules list. */}
      <ArrowRight aria-hidden="true" />
      <RuleEndpoint
        account={context.accountsById.get(rule.destination.connected_account_id)}
        endpoint={rule.destination}
        calendars={context.calendarsByAccount.get(rule.destination.connected_account_id)}
        role="Destination"
      />
    </span>
  )
}
